# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt
"""Master Engineering Release (v15.2.0, Owner CLEAR 2026-11-04).

One document approves and releases a whole manufacturing BOM family (finished good + manufactured
children). Each child item keeps its own Engineering Release; the Work Order gate is unchanged.

v15.2.1 (Owner CLEAR 2026-11-04): Status (``release_status``) is driven by the Desk Workflow
"Engineering ITAG KSA Master Engineering Release" (install.ensure_master_release_workflow, editable on Desk like the Engineering
Release Workflow) -- Approve / Return to Draft / Release for Production. Email alerts are Desk Notifications
(install.ensure_master_release_notifications). Every Workflow move still runs the controller guards below
(``_apply_transition``), and ``set_status`` remains as a server API with the same guards:
	Draft -> Approved -> Released for Production; Approved -> Draft (same main path as Engineering Release).
	Superseded is system-only (a newer Master for the same finished good is Released for Production).
Segregation of duties: creator != approver != releaser; Release only by Engineering Manager Master.

Row readiness (Owner CLEAR 2026-11-04): every manufacturing row needs a submitted BOM, an Approved Drawing and an
active Product Revision (on that drawing) BEFORE the Master can be saved -- checked on Get Items from BOM, on every
Draft save, and again on Approve / Release for Production. An Engineering Release is not required up front.
On Released for Production every child Engineering Release (auto-created where missing, plus already linked ones)
is driven to Released for Production through the ER controller, stamped with the Master releaser and a Master
reference -- all-or-nothing: if any child fails, nothing (children or Master status) is committed.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from engineering_itagksa.engineering_refs import DRAWING, SPEC, current_approved, drawing_matches_item, item_drawing

from engineering_itagksa.constants import (
	APPROVED,
	INACTIVE_STATES,
	RELEASED_FOR_PRODUCTION,
	ROLE_ENG_MANAGER,
	ROLE_ENG_MANAGER_MASTER,
)

DOCTYPE = "Master Engineering Release"
CHILD_DOCTYPE = "Master Engineering Release Item"

M_DRAFT, M_APPROVED, M_RELEASED = "Draft", "Approved", RELEASED_FOR_PRODUCTION
M_SUPERSEDED = "Superseded"
# a Master in one of these holds its child Engineering Releases exclusively
ACTIVE_STATES = (M_DRAFT, M_APPROVED, M_RELEASED)
# (from, to) -> roles allowed
TRANSITIONS = {
	(M_DRAFT, M_APPROVED): (ROLE_ENG_MANAGER, ROLE_ENG_MANAGER_MASTER),
	(M_APPROVED, M_DRAFT): (ROLE_ENG_MANAGER, ROLE_ENG_MANAGER_MASTER),
	(M_APPROVED, M_RELEASED): (ROLE_ENG_MANAGER_MASTER,),
}
# fields that may still change outside Draft (status / system-owned)
MUTABLE_WHEN_LOCKED = {
	"release_status", "superseded_by_master", "supersedes_master", "approved_by", "approved_on",
	"released_by", "released_on", "effective_datetime", "notes", "modified", "modified_by",
}
ROW_SYSTEM_FIELDS = {"row_status", "engineering_release"}
# Engineering Release coded Workflow path to Released for Production (install.RELEASE_TRANSITIONS)
ER_PATH = ("Draft", "Under Review", "Approved", RELEASED_FOR_PRODUCTION)


# ---------------------------------------------------------------------------
# BOM Creator / BOM tree helpers (pure reads, unit-tested)
# ---------------------------------------------------------------------------
def completed_bom_creators(item=None, company=None):
	"""BOM Creators that are submitted and Completed (ERPNext sets Completed only once every expandable
	row has its BOM created and the top BOM exists = complete multi-level tree)."""
	filters = {"docstatus": 1, "status": "Completed"}
	if item:
		filters["item_code"] = item
	if company:
		filters["company"] = company
	return frappe.get_all("BOM Creator", filters=filters, fields=["name", "item_code", "company"], order_by="modified desc")


def top_bom_for_creator(bom_creator, item):
	"""The finished-good BOM a BOM Creator produced (the one with no BOM Creator Item row reference)."""
	boms = frappe.get_all("BOM", filters={"bom_creator": bom_creator, "item": item, "docstatus": 1},
		fields=["name", "bom_creator_item"], order_by="creation desc")
	for b in boms:
		if not b.bom_creator_item:
			return b.name
	return boms[0].name if boms else None


def get_bom_tree(top_bom, max_depth=20):
	"""Manufacturing-only tree: level 0 = the finished good; a child line is kept only when it is made in-house
	(has its own BOM and is not supplier-sourced). Bought / non-manufactured lines are skipped.
	Each (item, bom) appears once (first occurrence); cycles are guarded."""
	fg = frappe.db.get_value("BOM", top_bom, "item")
	rows = [frappe._dict(item=fg, level=0, parent_item=None, bom=top_bom)]
	seen = {(fg, top_bom)}

	def walk(bom, parent_item, level, path):
		if level > max_depth:
			frappe.throw(_("BOM tree deeper than {0} levels under {1}.").format(max_depth, top_bom))
		lines = frappe.get_all(
			"BOM Item", filters={"parent": bom, "parenttype": "BOM"},
			fields=["item_code", "bom_no", "sourced_by_supplier"], order_by="idx asc",
		)
		for ln in lines:
			if not ln.bom_no or ln.sourced_by_supplier:
				continue  # bought / supplier-sourced / non-manufactured
			if ln.bom_no in path:
				frappe.throw(_("BOM recursion: {0} appears inside its own tree.").format(ln.bom_no))
			key = (ln.item_code, ln.bom_no)
			if key in seen:
				continue
			seen.add(key)
			rows.append(frappe._dict(item=ln.item_code, level=level, parent_item=parent_item, bom=ln.bom_no))
			walk(ln.bom_no, ln.item_code, level + 1, path | {ln.bom_no})

	walk(top_bom, fg, 1, {top_bom})
	return rows


def resolve_drawing(item):
	"""Current Approved Engineering Drawing of the item (draft v0.1, 2026-11-10): the Item's drawing from the
	Engineering Item Request that created it (fallback Item.eng_design), moved forward along superseded_by to the
	Approved revision. Drawing has no Item Code / Released state / docstatus since v15.3.0."""
	d = item_drawing(item)
	return current_approved(DRAWING, d) if d else None


def resolve_product_revision(item, drawing=None):
	"""Current active (submitted, not superseded/obsolete/cancelled) Product Revision; prefer the one on `drawing`."""
	prs = frappe.get_all(
		"Product Revision",
		filters={"item": item, "docstatus": 1, "workflow_state": ("not in", list(INACTIVE_STATES))},
		fields=["name", "drawing_revision"], order_by="creation desc",
	)
	for pr in prs:
		if drawing and pr.drawing_revision == drawing:
			return pr.name
	return prs[0].name if prs else None


def resolve_material_specification(pr):
	"""The Product Revision's Material Specification, moved forward to the current Approved revision."""
	if not pr:
		return None
	ms = frappe.db.get_value("Product Revision", pr, "material_specification")
	if not ms:
		return None
	return current_approved(SPEC, ms) or ms


def other_active_master(er, exclude=None):
	"""Name of another active Master that already holds this Engineering Release, else None."""
	m = frappe.db.get_value("Engineering Release", er, "master_engineering_release")
	if not m or m == exclude:
		m = None
	else:
		if frappe.db.get_value(DOCTYPE, m, "release_status") not in ACTIVE_STATES:
			m = None
	if m:
		return m
	# also catch rows on other active Masters not yet back-linked
	rows = frappe.get_all(CHILD_DOCTYPE, filters={"engineering_release": er, "parenttype": DOCTYPE}, pluck="parent")
	for p in rows:
		if p != exclude and frappe.db.get_value(DOCTYPE, p, "release_status") in ACTIVE_STATES:
			return p
	return None


def resolve_engineering_release(item, bom, master=None):
	"""Latest non-retired Engineering Release for the item that is free (not on another active Master);
	prefer one on the same BOM."""
	ers = frappe.get_all(
		"Engineering Release",
		filters={"item": item, "release_status": ("not in", list(INACTIVE_STATES))},
		fields=["name", "bom"], order_by="creation desc",
	)
	free = [e for e in ers if not other_active_master(e.name, exclude=master)]
	for e in free:
		if e.bom == bom:
			return e.name
	return free[0].name if free else None


def row_missing(row):
	"""What a Master row lacks: submitted BOM of the item, Approved Drawing of the item, active Product Revision of
	the item on that drawing. Returns a list of labels (empty = ready)."""
	missing = []
	b = frappe.db.get_value("BOM", row.bom, ["item", "docstatus"], as_dict=True) if row.bom else None
	if not b or b.item != row.item or b.docstatus != 1:
		missing.append(_("submitted BOM"))
	state = frappe.db.get_value(DRAWING, row.drawing, "workflow_state") if row.drawing else None
	if state != APPROVED or not drawing_matches_item(row.drawing, row.item):
		missing.append(_("Approved Drawing"))
	pr = frappe.db.get_value("Product Revision", row.get("product_revision"), ["item", "docstatus", "workflow_state",
		"drawing_revision"], as_dict=True) if row.get("product_revision") else None
	if not pr or pr.item != row.item or pr.docstatus != 1 or pr.workflow_state in INACTIVE_STATES:
		missing.append(_("Product Revision"))
	elif row.drawing and pr.drawing_revision != row.drawing:
		missing.append(_("Product Revision on drawing {0} (it is on {1})").format(row.drawing, pr.drawing_revision))
	ms = row.get("material_specification")
	state = frappe.db.get_value(SPEC, ms, "workflow_state") if ms else None
	if not ms or state != APPROVED:
		missing.append(_("Approved Material Specification"))
	return missing


def assert_rows_complete(rows, action=None):
	"""Throw listing every row/item that lacks submitted BOM / Approved Drawing / Product Revision."""
	bad = []
	for r in rows:
		missing = row_missing(r)
		if missing:
			bad.append(_("Row {0} {1}: missing {2}").format(r.idx, frappe.bold(r.item), ", ".join(missing)))
	if bad:
		frappe.throw(
			_("Every manufacturing item in the BOM tree must already have its own submitted BOM, Approved Drawing and "
				"Product Revision before {0}.").format(action or _("the Master is saved"))
			+ "<br><br>" + "<br>".join(bad),
			title=_("BOM tree not ready"),
		)


def compute_row_status(row):
	if not row.drawing:
		return "Missing Drawing"
	if not row.get("product_revision"):
		return "Missing Product Revision"
	if not row.engineering_release:
		return "Missing ER"
	if frappe.db.get_value("Engineering Release", row.engineering_release, "release_status") == RELEASED_FOR_PRODUCTION:
		return "Released"
	return "Linked"


# ---------------------------------------------------------------------------
class MasterEngineeringRelease(Document):
	def validate(self):
		before = self.get_doc_before_save() if not self.is_new() else None
		old = (before.release_status if before else None) or M_DRAFT
		if not self.release_status or self.is_new():
			self.release_status = M_DRAFT if not self.flags.status_change else self.release_status
		if before and self.release_status != old and not self.flags.status_change:
			# Desk Workflow action (apply_workflow): same role / segregation-of-duties guards as set_status
			self._workflow_transition(old, self.release_status)
		elif not before and self.release_status != M_DRAFT:
			frappe.throw(_("A new Master always starts as Draft."))
		if before and old != M_DRAFT:
			self.enforce_lock(before, old)
		if old == M_DRAFT or self.is_new():
			self.validate_finished_good()
		self.validate_items()
		if self.items and self.release_status == M_DRAFT and not self.flags.status_change:
			# Gap 1: a Master cannot be saved (created or edited as Draft) with incomplete rows
			assert_rows_complete(self.items)

	# -- header ---------------------------------------------------------------
	def validate_finished_good(self):
		creators = completed_bom_creators(self.finished_good_item, self.company)
		if not creators:
			frappe.throw(_("Finished Good {0} has no Completed BOM Creator for {1}. Build the full tree in BOM Creator first.").format(
				frappe.bold(self.finished_good_item), self.company))
		names = [c.name for c in creators]
		if not self.bom_creator:
			self.bom_creator = names[0]
		elif self.bom_creator not in names:
			frappe.throw(_("BOM Creator {0} must be Completed and for {1}.").format(self.bom_creator, self.finished_good_item))
		if not self.top_bom:
			self.top_bom = top_bom_for_creator(self.bom_creator, self.finished_good_item)
		b = frappe.db.get_value("BOM", self.top_bom, ["item", "docstatus", "bom_creator"], as_dict=True) if self.top_bom else None
		if not b or b.item != self.finished_good_item or b.docstatus != 1:
			frappe.throw(_("Top BOM must be a submitted BOM of {0}.").format(self.finished_good_item))
		if b.bom_creator != self.bom_creator:
			frappe.throw(_("Top BOM {0} was not created by BOM Creator {1}.").format(self.top_bom, self.bom_creator))

	def enforce_lock(self, before, old):
		for df in self.meta.fields:
			if df.fieldname in MUTABLE_WHEN_LOCKED or df.fieldtype in ("Section Break", "Column Break", "Tab Break"):
				continue
			if df.fieldtype == "Table":
				strip = lambda rows: [{k: v for k, v in r.as_dict(no_default_fields=True).items() if k not in ROW_SYSTEM_FIELDS}
					for r in rows]
				if frappe.as_json(strip(before.get(df.fieldname))) != frappe.as_json(strip(self.get(df.fieldname))):
					frappe.throw(_("{0} is locked once the Master is {1}. Return to Draft first.").format(df.label, old))
			elif (before.get(df.fieldname) or None) != (self.get(df.fieldname) or None):
				frappe.throw(_("{0} is locked once the Master is {1}.").format(df.label, old))

	# -- rows -----------------------------------------------------------------
	def validate_items(self):
		seen = {}
		for row in self.items:
			if row.bom:
				bi = frappe.db.get_value("BOM", row.bom, "item")
				if bi != row.item:
					frappe.throw(_("Row {0}: BOM {1} is not for item {2}.").format(row.idx, row.bom, row.item))
			if row.engineering_release:
				er_item = frappe.db.get_value("Engineering Release", row.engineering_release, "item")
				if er_item != row.item:
					frappe.throw(_("Row {0}: Engineering Release {1} is not for item {2}.").format(
						row.idx, row.engineering_release, row.item))
				if row.engineering_release in seen:
					frappe.throw(_("Engineering Release {0} is on rows {1} and {2}.").format(
						row.engineering_release, seen[row.engineering_release], row.idx))
				seen[row.engineering_release] = row.idx
				if self.release_status in ACTIVE_STATES:
					other = other_active_master(row.engineering_release, exclude=self.name)
					if other:
						frappe.throw(_("Row {0}: Engineering Release {1} already belongs to active Master {2}.").format(
							row.idx, row.engineering_release, other))
			row.row_status = compute_row_status(row)

	def assert_rows_ready(self, action=None):
		if not self.items:
			frappe.throw(_("Get Items from BOM first."))
		# Approve / Release need submitted BOM + Approved Drawing + Product Revision per row; an Engineering Release
		# is NOT required (missing ones are auto-created on Released for Production).
		assert_rows_complete(self.items, action)

	# -- back-links / delete ----------------------------------------------------
	def on_update(self):
		self.sync_release_links()
		if self.flags.entering_released:
			self.supersede_prior()

	def sync_release_links(self):
		keep = self.release_status in ACTIVE_STATES
		current = {r.engineering_release for r in self.items if r.engineering_release} if keep else set()
		linked = set(frappe.get_all("Engineering Release", filters={"master_engineering_release": self.name}, pluck="name"))
		for er in linked - current:
			frappe.db.set_value("Engineering Release", er, "master_engineering_release", None, update_modified=False)
		for er in current - linked:
			frappe.db.set_value("Engineering Release", er, "master_engineering_release", self.name, update_modified=False)

	def supersede_prior(self):
		prior = frappe.get_all(DOCTYPE, filters={
			"finished_good_item": self.finished_good_item, "company": self.company,
			"release_status": M_RELEASED, "name": ("!=", self.name)}, pluck="name", order_by="creation asc")
		for p in prior:
			frappe.db.set_value(DOCTYPE, p, {"release_status": M_SUPERSEDED, "superseded_by_master": self.name})
			frappe.get_doc(DOCTYPE, p).add_comment("Info", _("Superseded by {0}").format(self.name))
		if prior and not self.supersedes_master:
			self.db_set("supersedes_master", prior[-1], update_modified=False)

	def on_trash(self):
		if self.release_status != M_DRAFT:
			frappe.throw(_("Only a Draft Master can be deleted; {0} is {1}. ").format(self.name, self.release_status))
		for er in frappe.get_all("Engineering Release", filters={"master_engineering_release": self.name}, pluck="name"):
			frappe.db.set_value("Engineering Release", er, "master_engineering_release", None, update_modified=False)

	# -- form actions -----------------------------------------------------------
	@frappe.whitelist()
	def get_items_from_bom(self):
		"""Fill Items from the manufacturing-only BOM tree of Top BOM; resolve Drawing, Product Revision, Material
		Specification and a free Engineering Release per row (Draft Masters only)."""
		self.check_permission("write")
		if self.release_status not in (None, "", M_DRAFT):
			frappe.throw(_("Items can be pulled only on a Draft Master."))
		self.validate_finished_good()
		self.set("items", [])
		for n in get_bom_tree(self.top_bom):
			drawing = resolve_drawing(n.item)
			pr = resolve_product_revision(n.item, drawing)
			ms = resolve_material_specification(pr)
			row = self.append("items", {
				"item": n.item, "level": n.level, "parent_item": n.parent_item, "bom": n.bom,
				"drawing": drawing, "product_revision": pr, "material_specification": ms,
				"engineering_release": resolve_engineering_release(n.item, n.bom, master=None if self.is_new() else self.name),
			})
			row.row_status = compute_row_status(row)
		# Gap 1: every sub-level must already have its own submitted BOM, Approved Drawing and Product Revision
		assert_rows_complete(self.items, _("Get Items from BOM"))
		return self

	@frappe.whitelist()
	def create_draft_releases(self):
		"""Create a Draft Engineering Release (linked to this Master) for every row without one.
		Rows with no Product Revision are skipped (a Release needs its baseline)."""
		self.check_permission("write")
		if self.is_new() or self.release_status != M_DRAFT:
			frappe.throw(_("Save the Master as Draft first."))
		created, skipped = self._create_missing_releases()
		self.save()
		return {"created": created, "skipped": skipped}

	def _create_missing_releases(self, strict=False):
		"""Insert a Draft Engineering Release (back-linked to this Master) for every row without one.
		strict=True (Release for Production): a row without Product Revision throws instead of being skipped."""
		created, skipped = [], []
		for row in self.items:
			if row.engineering_release:
				continue
			if not row.product_revision:
				if strict:
					frappe.throw(_("Row {0} ({1}) has no Product Revision; cannot create its Engineering Release.").format(
						row.idx, row.item))
				skipped.append(row.item)
				continue
			pr = frappe.db.get_value(
				"Product Revision", row.product_revision,
				["drawing_revision", "material_specification"], as_dict=True,
			)
			ms = None
			if pr and pr.material_specification:
				ms = current_approved(SPEC, pr.material_specification) or pr.material_specification
			er = frappe.get_doc({
				"doctype": "Engineering Release", "item": row.item, "product_revision": row.product_revision,
				"drawing_revision": pr.drawing_revision if pr else None,
				"material_specification": ms,
				"bom": row.bom, "company": self.company,
				"effective_datetime": self.effective_datetime or now_datetime(),
				"release_classification": "Customer-Specific" if self.customer else "Standard",
				"customer": self.customer, "project": self.project, "master_engineering_release": self.name,
			}).insert(ignore_permissions=strict)
			row.engineering_release = er.name
			created.append(er.name)
		return created, skipped

	def release_children(self):
		"""Drive every child Engineering Release to Released for Production (Master release). Missing ones are created
		first. Each ER walks its coded path (Draft -> Under Review -> Approved -> Released for Production) through
		the ER controller (baseline, checklist, Approval Matrix, checksum, supersede all run); only the Desk Workflow
		role-per-transition check is replaced by the Master's own role + segregation-of-duties guards, and that is
		recorded on each ER. Raises on the first failure (caller rolls back)."""
		created, _skipped = self._create_missing_releases(strict=True)
		ref = _("via Master Engineering Release {0} (approved by {1}, released by {2})").format(
			self.name, self.approved_by, self.released_by)
		advanced = []
		for row in self.items:
			er = frappe.get_doc("Engineering Release", row.engineering_release)
			cur = er.release_status or "Draft"
			if cur == RELEASED_FOR_PRODUCTION:
				continue
			if cur not in ER_PATH:
				frappe.throw(_("Row {0} ({1}): Engineering Release {2} is {3} and cannot be Released for Production. "
					"Get Items from BOM again.").format(row.idx, row.item, er.name, cur))
			if er.master_engineering_release and er.master_engineering_release != self.name:
				frappe.throw(_("Engineering Release {0} belongs to Master {1}.").format(er.name, er.master_engineering_release))
			# Release Checklist: the Master release attests BOM / Approved Drawing / Product Revision for the row
			attest = _("Master {0}: BOM, Approved Drawing, Product Revision verified").format(self.name)
			if not any(c.checklist_item == attest for c in er.release_checklist):
				er.append("release_checklist", {"checklist_item": attest, "is_complete": 1})
			for c in er.release_checklist:
				c.is_complete = 1
			er.master_engineering_release = self.name
			if not er.effective_datetime:
				er.effective_datetime = self.effective_datetime
			for state in ER_PATH[ER_PATH.index(cur) + 1:]:
				er.release_status = state
				er.flags.via_master_release = self.name
				er.flags.ignore_permissions = True
				er.save()
				er.add_comment("Workflow", state)
			er.add_comment("Info", _("Released for Production {0}.").format(ref))
			row.row_status = compute_row_status(row)
			advanced.append(er.name)
		return created, advanced

	def _apply_transition(self, old, status):
		"""Role + segregation-of-duties guards and stamps for one status move (shared by the Desk Workflow and
		set_status). Does not save and does not release children."""
		roles = TRANSITIONS.get((old, status))
		if not roles:
			frappe.throw(_("Status cannot move from {0} to {1}.").format(old, status))
		user = frappe.session.user
		if not set(roles) & set(frappe.get_roles(user)):
			frappe.throw(_("{0} -> {1} needs role: {2}.").format(old, status, " / ".join(roles)), frappe.PermissionError)
		if status == M_APPROVED:
			if user == self.owner:
				frappe.throw(_("The creator of a Master cannot Approve it."))
			self.assert_rows_ready(_("Approve"))
			self.approved_by, self.approved_on = user, now_datetime()
		elif status == M_DRAFT:
			self.approved_by = self.approved_on = None
		elif status == M_RELEASED:
			if user in (self.owner, self.approved_by):
				frappe.throw(_("The Releaser must differ from the creator and the Approver."))
			self.assert_rows_ready(_("Release for Production"))
			if not self.effective_datetime:
				self.effective_datetime = now_datetime()
			self.released_by, self.released_on = user, now_datetime()
			self.flags.entering_released = old == M_APPROVED

	def _release_children_atomic(self, old, then=None):
		"""all-or-nothing: children + Master status commit together or not at all (``then`` = the Master save when
		called from set_status; from the Workflow the Master save is already in progress)."""
		frappe.db.savepoint("mer_release")
		try:
			created, advanced = self.release_children()
			if then:
				then()
		except Exception:
			frappe.db.rollback(save_point="mer_release")
			self.release_status, self.released_by, self.released_on = old, None, None
			raise
		frappe.msgprint(_("Engineering Releases Released for Production: {0}{1}").format(
			", ".join(advanced) or "-", _(" (created: {0})").format(", ".join(created)) if created else ""), alert=True)
		return created, advanced

	def _workflow_transition(self, old, status):
		"""Called from validate when the Desk Workflow changed release_status (Approve / Return to Draft /
		Release for Production)."""
		self._apply_transition(old, status)
		if status == M_RELEASED:
			self._release_children_atomic(old)

	@frappe.whitelist()
	def set_status(self, status):
		"""Server API (the form uses the Desk Workflow): role + segregation-of-duties guards, then save."""
		old = self.release_status or M_DRAFT
		self._apply_transition(old, status)
		if status == M_RELEASED:
			def _save():
				self.release_status = status
				self.flags.status_change = True
				self.save()
			self._release_children_atomic(old, then=_save)
			return self
		self.release_status = status
		self.flags.status_change = True
		self.save()
		return self


# ---------------------------------------------------------------------------
@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def finished_good_query(doctype, txt, searchfield, start, page_len, filters):
	"""Item link query: only Items with a Completed BOM Creator (full sub-level BOM tree created)."""
	company = (filters or {}).get("company")
	cond = "and bc.company = %(company)s" if company else ""
	return frappe.db.sql(
		f"""select distinct i.name, i.item_name from `tabItem` i
		join `tabBOM Creator` bc on bc.item_code = i.name and bc.docstatus = 1 and bc.status = 'Completed' {cond}
		where i.disabled = 0 and (i.name like %(txt)s or i.item_name like %(txt)s)
		order by i.name limit %(start)s, %(page_len)s""",
		{"txt": f"%{txt}%", "company": company, "start": start, "page_len": page_len},
	)


def block_er_delete(doc, method=None):
	"""Engineering Release on_trash: block delete only when linked to a Master (standalone ERs unchanged)."""
	if doc.get("master_engineering_release") and frappe.db.exists(DOCTYPE, doc.master_engineering_release):
		frappe.throw(_("Engineering Release {0} belongs to Master {1} and cannot be deleted.").format(
			doc.name, doc.master_engineering_release))
