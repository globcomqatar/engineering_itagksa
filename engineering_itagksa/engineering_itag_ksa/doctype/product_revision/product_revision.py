# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.mapper import get_mapped_doc
from frappe.model.naming import make_autoname

from engineering_itagksa.component_series import (
	PR_SERIES,
	issue_base,
	next_revision_on_base,
	split_component_base,
)

from engineering_itagksa import engineering_refs as R
from engineering_itagksa import lifecycle as L
from engineering_itagksa.constants import (
	APPROVED,
	DRAFT,
	INACTIVE_STATES,
	OBSOLETE,
	RELEASE_READY,
	RELEASED,
	SUPERSEDED,
	UNDER_REVIEW,
)

ACTIVE_PR_STATES = (APPROVED, RELEASE_READY, RELEASED)
# v15.3.3 Revise (Owner 2026-11-10, mirrors Drawing / Material Specification Create Revision): allowed from every
# active submitted state (Approved and its downstream Release Ready / Released), never from Superseded / Obsolete /
# Cancelled. Fields copied to the new Draft (baseline + decision; ECO, status, history and readiness start empty).
REVISABLE_STATES = ACTIVE_PR_STATES
REVISE_COPY_FIELDS = ("item", "drawing_revision", "material_specification", "bom_revision_reference",
	"routing_revision_reference", "inspection_plan_revision_reference", "interchangeability_decision")
OPEN_STATES = (DRAFT, UNDER_REVIEW)
# Plain Status field (no Workflow): Save -> Draft / Under Review, Submit -> Approved, then (Update After
# Submit) Release Ready -> Released / Obsolete; Cancel -> Cancelled.
DRAFT_STATES = (DRAFT, UNDER_REVIEW)
SUBMITTED_STATES = (APPROVED, RELEASE_READY, RELEASED, SUPERSEDED, OBSOLETE)


def assert_drawing_released(drawing, item, label=None):
	"""Owner-approved draft v0.1 (2026-11-10): drawings have no Released state / docstatus / item_code any more, so
	this now means "Approved, and in the Item's drawing revises chain when that is known" (see engineering_refs).
	Name kept for existing callers; ``label`` unused."""
	R.assert_drawing_approved(drawing, item)


def assert_spec_approved(spec, item=None):
	"""Linked Material Specification must be Approved (v15.3.0: Workflow status, not submittable). It has no Item
	Code any more, so the old "same item" check is gone (``item`` kept for callers, unused)."""
	s = frappe.db.get_value("Material Specification", spec, ["workflow_state"], as_dict=True)
	if not s or s.workflow_state != APPROVED:
		frappe.throw(_("Material Specification {0} must be the active {1} specification.").format(frappe.bold(spec), APPROVED))


def assert_bom_for_item(bom, item, require_submitted=False):
	if not bom:
		return
	b = frappe.db.get_value("BOM", bom, ["item", "docstatus", "is_active"], as_dict=True)
	if not b or b.item != item:
		frappe.throw(_("BOM {0} is not for item {1}.").format(frappe.bold(bom), item))
	if require_submitted and (b.docstatus != 1 or not b.is_active):
		frappe.throw(_("BOM {0} must be submitted and active.").format(frappe.bold(bom)))


def mark_released(pr_name, release_name):
	"""v15.2.4: Engineering Release reached Released for Production -> linked Product Revision becomes Released
	(release_readiness Ready). Only an Approved / Release Ready submitted PR advances; Released is left as is
	(readiness repaired if needed); Superseded / Obsolete / Cancelled / draft are never touched. db_set (same
	transaction, no PR validate) so a missing BOM Revision Reference does not block it. Returns True if changed."""
	if not pr_name:
		return False
	pr = frappe.db.get_value("Product Revision", pr_name, ["docstatus", "workflow_state", "release_readiness"], as_dict=True)
	if not pr or pr.docstatus != 1:
		return False
	if pr.workflow_state == RELEASED:
		if pr.release_readiness != "Ready":
			frappe.db.set_value("Product Revision", pr_name, "release_readiness", "Ready", update_modified=False)
		return False
	if pr.workflow_state not in (APPROVED, RELEASE_READY):
		return False
	frappe.db.set_value("Product Revision", pr_name, {"workflow_state": RELEASED, "release_readiness": "Ready"},
		update_modified=True)
	frappe.get_doc("Product Revision", pr_name).add_comment(
		"Info", _("Released via Engineering Release {0} (Released for Production).").format(release_name))
	return True


def item_component_code(item):
	"""Item Component (part code prefix) used in the Product Revision number."""
	if not item:
		return None
	return frappe.db.get_value("Item", item, "eng_item_component")


def latest_new_format_pr(item, exclude=None):
	"""The most recently created new-format Product Revision of ``item``, if any (any docstatus)."""
	filters = {"item": item}
	if exclude:
		filters["name"] = ["!=", exclude]
	for n in frappe.get_all("Product Revision", filters=filters, pluck="name", order_by="creation desc"):
		if split_component_base(n)[0]:
			return n
	return None


def get_next_revision(item, exclude=None, previous_revision=None):
	"""v15.3.5: the revision a new Product Revision of ``item`` gets.

	0 for the Item's first new-format Product Revision (or when every existing PR of the Item is still
	the legacy PR-{item}-{letter} name). When the Item already has a new-format PR, or ``previous_revision``
	is a recognised {component}-5NNNN-{n} name, the next digit on that base (0 -> 1 -> 2; cancelled names
	stay taken). Legacy PR-{item}-A sources do not keep a base: the new document gets a fresh number and
	starts at 0 (Previous Revision is kept).
	"""
	source = previous_revision or latest_new_format_pr(item, exclude=exclude)
	if source and split_component_base(source)[0]:
		return next_revision_on_base(source, first="0")
	return "0"


def open_revision_of(pr_name, exclude=None):
	"""The Draft / Under Review Product Revision that revises ``pr_name`` (previous_revision), if any."""
	filters = {"previous_revision": pr_name, "docstatus": 0, "workflow_state": ["in", list(OPEN_STATES)]}
	if exclude:
		filters["name"] = ["!=", exclude]
	return frappe.db.get_value("Product Revision", filters, ["name", "workflow_state"], as_dict=True)


class ProductRevision(Document):
	def before_naming(self):
		# revision is assigned by the system before autoname so the name carries it (as Engineering Drawing)
		self.assign_revision()
		self.flags.revision_assigned = True
		L.normalize_revision(self, "revision_number")

	def autoname(self):
		"""v15.3.5: {component}-5NNNN-{revision}, e.g. 500-50001-0. Revisions keep the canonical base.
		Existing PR-{item}-{letter} names are not changed. Amend uses the standard {{amended_from}}-N suffix.
		Numbers are shared with Engineering Drawing so the two DocTypes never get the same name string."""
		if self.amended_from:
			self.name = make_autoname(self.amended_from + "-.#", doc=self)
			return
		source = self.previous_revision or (latest_new_format_pr(self.item) if not self.amended_from else None)
		base = split_component_base(source)[0] if source else None
		if not base:
			component = item_component_code(self.item)
			if not component:
				frappe.throw(
					_("Item {0} has no Item Component; it is required for the Product Revision number.").format(
						frappe.bold(self.item or "-")
					)
				)
			base = issue_base(component, PR_SERIES)
		self.name = f"{base}-{self.revision_number}"
		if frappe.db.exists("Product Revision", self.name):
			frappe.throw(
				_("Product Revision {0} already exists.").format(frappe.bold(self.name)),
				frappe.DuplicateEntryError,
			)

	def assign_revision(self):
		"""v15.3.5: Revision is never typed: 0 for a new number, then 1, 2, … on the same base.
		A value sent by Desk / import / API on a new document is replaced. Amend keeps the cancelled
		document's revision (A2 rule). After insert the field is locked (set_only_once)."""
		if not self.is_new():
			return
		if self.amended_from:
			src = frappe.db.get_value("Product Revision", self.amended_from, "revision_number")
			if src:
				self.revision_number = src
			return
		self.revision_number = get_next_revision(self.item, previous_revision=self.previous_revision)

	def before_validate(self):
		# Runs before the mandatory check (Drawing Revision is required). Draft v0.1: new documents (Desk, import,
		# API) get the Item's Drawing / Material Specification / BOM when those fields are empty; values already
		# entered are never overwritten.
		if self.is_new() and self.docstatus == 0 and self.item:
			self.fill_item_engineering_defaults()

	def fill_item_engineering_defaults(self):
		empty = [f for f in ("drawing_revision", "material_specification", "bom_revision_reference") if not self.get(f)]
		if not empty:
			return
		d = R.item_engineering_defaults(self.item)
		for f, v in (("drawing_revision", d.drawing), ("material_specification", d.material_specification),
				("bom_revision_reference", d.bom)):
			if f in empty and v:
				self.set(f, v)

	def validate(self):
		if self.is_new() and not self.flags.revision_assigned:
			# validate() also runs for a doc whose name was set by the caller (no before_naming); assign once
			self.assign_revision()
			self.flags.revision_assigned = True
		L.normalize_revision(self, "revision_number")
		L.validate_amendment_keeps_revision(self, "item", "revision_number")
		# Approved state is enforced at submit / Release Ready; on save only the Item's drawing chain is checked.
		R.assert_drawing_matches_item(self.drawing_revision, self.item)
		assert_bom_for_item(self.bom_revision_reference, self.item)
		L.validate_status(self, DRAFT_STATES, SUBMITTED_STATES, APPROVED)
		if self.is_new() and not self.previous_revision:
			active = L.get_active("Product Revision", "item", self.item, ACTIVE_PR_STATES)
			self.previous_revision = active[-1].name if active else None
		if self.is_new():
			self.validate_previous_revision()

	def validate_previous_revision(self):
		"""v15.3.3 Revise: the revised Product Revision must be of the same Item, and only one open (Draft / Under
		Review) revision of it may exist at a time (as Drawing). Checked when the new revision is created, so
		existing drafts are never blocked on later saves."""
		if not self.previous_revision:
			return
		prev_item = frappe.db.get_value("Product Revision", self.previous_revision, "item")
		if prev_item != self.item:
			frappe.throw(_("Previous Revision {0} is for Item {1}; a revision must keep the same Item ({2}).").format(
				self.previous_revision, prev_item or "-", self.item))
		other = open_revision_of(self.previous_revision, exclude=self.name)
		if other:
			frappe.throw(_("{0} is already being revised by {1} ({2}). Finish or cancel that revision first.").format(
				frappe.bold(self.previous_revision), frappe.bold(other.name), other.workflow_state))

	def before_submit(self):
		assert_drawing_released(self.drawing_revision, self.item)
		if not self.material_specification:
			frappe.throw(_("An Approved Material Specification is required before submit."))
		assert_spec_approved(self.material_specification, self.item)
		L.guard_not_older_than_active(self, self._other_active())

	def on_submit(self):
		others = self._other_active()
		if others and not self.previous_revision:
			self.db_set("previous_revision", others[-1].name)
		L.supersede(self, others, SUPERSEDED, link_field="superseding_revision")
		self.db_set("release_readiness", "Not Ready")

	def before_update_after_submit(self):
		L.validate_status(self, DRAFT_STATES, SUBMITTED_STATES, APPROVED)
		old, new = L.get_transition(self)
		if new == RELEASE_READY and old != RELEASE_READY:
			if not self.bom_revision_reference:
				frappe.throw(_("Link a BOM before marking Release Ready."))
			assert_bom_for_item(self.bom_revision_reference, self.item, require_submitted=True)
			assert_drawing_released(self.drawing_revision, self.item)
		self.release_readiness = "Ready" if new in (RELEASE_READY, RELEASED) else "Not Ready"

	def on_cancel(self):
		L.set_cancelled(self)

	def _other_active(self):
		return L.get_active("Product Revision", "item", self.item, ACTIVE_PR_STATES, exclude=self.name)


@frappe.whitelist()
def create_revision(source_name):
	"""v15.3.6 Revise (mirrors Engineering Drawing / Material Specification Create Revision):
	returns an unsaved Draft Product Revision of the same Item that revises ``source_name`` (Previous Revision),
	with the baseline fields and Interchangeability Decision copied and the next revision digit shown (the server
	re-assigns it on save). A copied Material Specification that has been superseded is moved forward to the
	current Approved revision. Only from an active submitted revision (Approved / Release Ready / Released) that
	is not superseded, and only when no other open revision of it exists. Approving the new revision supersedes
	it (on_submit)."""
	src = frappe.get_doc("Product Revision", source_name)
	src.check_permission("read")
	frappe.has_permission("Product Revision", "create", throw=True)
	if src.docstatus != 1 or src.workflow_state not in REVISABLE_STATES or src.superseding_revision:
		frappe.throw(_("Revise is only available on an Approved, Release Ready or Released Product Revision that is "
			"not superseded ({0} is {1}).").format(frappe.bold(source_name), src.workflow_state))
	other = open_revision_of(src.name)
	if other:
		frappe.throw(_("{0} is already being revised by {1} ({2}). Open that draft instead of creating another.").format(
			frappe.bold(src.name), frappe.bold(other.name), other.workflow_state))
	new = frappe.new_doc("Product Revision")
	for f in REVISE_COPY_FIELDS:
		new.set(f, src.get(f))
	if new.material_specification:
		new.set("material_specification", R.current_approved(R.SPEC, new.material_specification) or new.material_specification)
	new.previous_revision = src.name
	new.revision_number = get_next_revision(src.item, previous_revision=src.name)  # shown on the draft; re-assigned on save
	new.set("workflow_state", DRAFT)
	return new.as_dict()


@frappe.whitelist()
def make_engineering_release(source_name, target_doc=None):
	src = frappe.get_doc("Product Revision", source_name)
	src.check_permission("read")
	if src.docstatus != 1 or src.workflow_state in INACTIVE_STATES:
		frappe.throw(_("Engineering Release can be created only from a submitted, active Product Revision."))
	return get_mapped_doc(
		"Product Revision",
		source_name,
		{
			"Product Revision": {
				"doctype": "Engineering Release",
				"field_map": {
					"name": "product_revision",
					"drawing_revision": "drawing_revision",
					"material_specification": "material_specification",
					"bom_revision_reference": "bom",
					"routing_revision_reference": "routing",
					"inspection_plan_revision_reference": "inspection_plan",
					"applicable_eco": "applicable_eco",
				},
				"field_no_map": ["workflow_state"],
			},
		},
		target_doc,
		_map_material_specification,
	)


def _map_material_specification(source, target):
	"""v15.3.4: the Product Revision's Material Specification is copied onto the Engineering Release
	parent link (the Specifications table is no longer on the ER form; the child DocType is kept)."""
	spec = source.get("material_specification")
	if spec:
		target.material_specification = spec


@frappe.whitelist()
def get_next_revision_for_item(item):
	"""Form preview of the revision digit the server will assign on save (0, 1, 2, …)."""
	frappe.has_permission("Product Revision", "create", throw=True)
	return get_next_revision(item)


@frappe.whitelist()
def get_item_engineering_defaults(item):
	"""Auto-fill source for the Product Revision form (Item change): the Item's Drawing and Material Specification
	from the Engineering Item Request that created it (Drawing falls back to Item.eng_design), and its BOM
	(default BOM, else Item.eng_bom, else latest active submitted BOM). Returns names and codes only. The
	caller must be able to create or read Product Revision or Engineering Release; Item/BOM read is not required."""
	d = R.item_engineering_defaults(item)
	return {"drawing_revision": d.drawing, "material_specification": d.material_specification,
		"bom_revision_reference": d.bom, "item_request": d.item_request}
