# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt

import hashlib
import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from engineering_itagksa import approval_matrix as AM
from engineering_itagksa import lifecycle as L
from engineering_itagksa.constants import (
	APPROVED,
	DRAFT,
	INACTIVE_STATES,
	OBSOLETE,
	RELEASED_FOR_PRODUCTION,
	SUPERSEDED,
)
from engineering_itagksa import engineering_refs as R
from engineering_itagksa.engineering_refs import SPEC, current_approved
from engineering_itagksa.engineering_itag_ksa.doctype.product_revision.product_revision import (
	assert_bom_for_item,
	assert_drawing_released,
	assert_spec_approved,
	mark_released,
)

# v15.3.4: fields filled from the Product Revision (Drawing must be the PR's drawing).
RELEASE_FROM_PR = ("drawing_revision", "bom", "routing", "inspection_plan", "material_specification")

FIELD = "release_status"
LOCKED_STATES = (RELEASED_FOR_PRODUCTION, SUPERSEDED, OBSOLETE)
# Release Status is driven by the "Engineering ITAG KSA Engineering Release" Workflow (install.py, the app's only coded
# Workflow): Submit for Review / Return to Draft / Approve / Release for Production / Mark Obsolete. The controller
# never rewrites the status on save (only blank -> Draft for a new record); it validates the move the Workflow made.
# Superseded is set only by the system (on_update supersede when a newer release goes Released for Production).
# Once locked the status may only move forward.
LOCKED_NEXT = {
	RELEASED_FOR_PRODUCTION: (RELEASED_FOR_PRODUCTION, SUPERSEDED, OBSOLETE),
	SUPERSEDED: (SUPERSEDED, OBSOLETE),
	OBSOLETE: (OBSOLETE,),
}
# fields that may still change once a release is locked (status / system-owned or acknowledgement)
MUTABLE_WHEN_LOCKED = {"release_status", "superseded_by_release", "master_engineering_release", "release_distribution", "modified", "modified_by"}


class EngineeringRelease(Document):
	def validate_workflow(self):
		"""Desk Workflow transition check. Skipped only when a Master Engineering Release that holds this ER is being
		Released for Production (Master.release_children): the Master's role + segregation-of-duties guards stand in
		for the per-transition roles, every other ER rule in validate() still runs, and the move is commented."""
		m = self.flags.via_master_release
		if m and self.master_engineering_release == m and frappe.db.get_value(
			"Master Engineering Release", m, "release_status") == APPROVED:
			return
		return super().validate_workflow()

	def before_validate(self):
		# v15.3.4: new documents (Desk, import, API, MER) get empty baseline fields filled from the
		# Product Revision / Item; values already entered are never overwritten.
		if self.is_new() and self.item:
			self.fill_item_release_defaults()

	def fill_item_release_defaults(self):
		if not self.product_revision:
			d = item_release_defaults(self.item, check_perm=False)
			if d.product_revision:
				self.product_revision = d.product_revision
		else:
			d = defaults_from_product_revision(self.product_revision, check_perm=False)
		for f in RELEASE_FROM_PR:
			if not self.get(f) and d.get(f):
				self.set(f, d.get(f))

	def validate(self):
		if not self.get(FIELD):
			self.set(FIELD, DRAFT)
		old, new = L.get_transition(self, FIELD)
		if new == SUPERSEDED and old != SUPERSEDED:
			frappe.throw(_("Superseded is set automatically when a newer release goes Released for Production."))
		self.enforce_lock(old)
		self.validate_consistency()
		self.stamp_checklist()
		if old in LOCKED_STATES and not self.is_new():
			self.flags.entering_rfp = False
			return  # locked record: no re-stamping
		AM.apply(self, self.matrix_context(), enforce=(new == APPROVED and old != APPROVED))
		self.flags.entering_rfp = new == RELEASED_FOR_PRODUCTION and old != RELEASED_FOR_PRODUCTION
		if new == APPROVED and old != APPROVED:
			self.validate_baseline()
		if self.flags.entering_rfp:
			self.validate_baseline()
			if not self.release_checklist or any(not r.is_complete for r in self.release_checklist):
				frappe.throw(_("All Release Checklist items must be complete (at least one) before Released for Production."))
			prior = L.get_active("Engineering Release", "item", self.item, [RELEASED_FOR_PRODUCTION], state_field=FIELD,
				exclude=self.name, docstatus=None)
			self.superseded_release = prior[-1].name if prior else None
			self.release_checksum = self.compute_checksum()

	def enforce_lock(self, old_state):
		if old_state not in LOCKED_STATES or self.is_new():
			return
		allowed = LOCKED_NEXT[old_state]
		if self.get(FIELD) not in allowed:
			frappe.throw(_("Release Status cannot change from {0} to {1}; allowed: {2}.").format(
				old_state, self.get(FIELD) or "-", ", ".join(allowed)))
		before = self.get_doc_before_save()
		for df in self.meta.fields:
			if df.fieldname in MUTABLE_WHEN_LOCKED or df.fieldtype in ("Section Break", "Column Break", "Tab Break"):
				continue
			if df.fieldtype == "Table":
				a = [r.as_dict(no_default_fields=True) for r in before.get(df.fieldname)]
				b = [r.as_dict(no_default_fields=True) for r in self.get(df.fieldname)]
				if json.dumps(a, default=str, sort_keys=True) != json.dumps(b, default=str, sort_keys=True):
					frappe.throw(_("{0} is locked once a release is {1}.").format(df.label, old_state))
			elif (before.get(df.fieldname) or None) != (self.get(df.fieldname) or None):
				frappe.throw(_("{0} is locked once a release is {1}.").format(df.label, old_state))

	def validate_consistency(self):
		pr = frappe.db.get_value("Product Revision", self.product_revision, ["item", "drawing_revision"], as_dict=True)
		if not pr or pr.item != self.item:
			frappe.throw(_("Product Revision {0} is not for item {1}.").format(self.product_revision, self.item))
		if self.drawing_revision != pr.drawing_revision:
			frappe.throw(_("Drawing Revision must be the drawing of Product Revision {0} ({1}).").format(
				self.product_revision, pr.drawing_revision))
		assert_bom_for_item(self.bom, self.item)

	def validate_baseline(self):
		pr = frappe.db.get_value("Product Revision", self.product_revision, ["docstatus", "workflow_state"], as_dict=True)
		if pr.docstatus != 1 or pr.workflow_state in INACTIVE_STATES:
			frappe.throw(_("Product Revision {0} must be submitted and active.").format(self.product_revision))
		# draft v0.1: Approved drawing in the Item's drawing revises chain (no Released state / item_code since v15.3.0)
		assert_drawing_released(self.drawing_revision, self.item)
		assert_bom_for_item(self.bom, self.item, require_submitted=True)
		# v15.3.4: single parent Material Specification link is mandatory at Approve / Released for Production
		if not self.material_specification:
			frappe.throw(_("An Approved Material Specification is required to Approve or Release for Production."))
		assert_spec_approved(self.material_specification, self.item)

	def stamp_checklist(self):
		before = {r.name: r for r in (self.get_doc_before_save() or frappe._dict()).get("release_checklist") or []}
		for r in self.release_checklist:
			prev = before.get(r.name)
			if not r.is_complete:
				r.verified_by = r.verified_on = None
			elif prev and prev.is_complete:
				r.verified_by, r.verified_on = prev.verified_by, prev.verified_on
			else:
				r.verified_by, r.verified_on = frappe.session.user, now_datetime()

	def matrix_context(self):
		ctx = AM.item_context(self.item)
		cost = 0
		if self.applicable_eco:
			ecr = frappe.db.get_value("Engineering Change Order", self.applicable_eco, "source_ecr")
			cost = frappe.db.get_value("Engineering Change Request", ecr, "cost_impact") if ecr else 0
		ctx.update(company=self.company, is_customer_specific=bool(self.customer or self.release_classification == "Customer-Specific"),
			is_regulatory=False, cost_impact=cost or 0)
		return ctx

	def compute_checksum(self):
		drawing_hash = frappe.db.get_value("Engineering Drawing", self.drawing_revision, "file_checksum_sha256")
		payload = {
			"item": self.item, "product_revision": self.product_revision, "drawing_revision": self.drawing_revision,
			"drawing_sha256": drawing_hash, "bom": self.bom, "routing": self.routing, "inspection_plan": self.inspection_plan,
			"material_specification": self.material_specification,
			"effective_datetime": str(self.effective_datetime),
		}
		return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

	def on_update(self):
		if not self.flags.entering_rfp:
			return
		prior = L.get_active("Engineering Release", "item", self.item, [RELEASED_FOR_PRODUCTION], state_field=FIELD,
			exclude=self.name, docstatus=None)
		L.supersede(self, prior, SUPERSEDED, state_field=FIELD, link_field="superseded_by_release")
		mark_released(self.product_revision, self.name)  # v15.2.4: PR -> Released / Ready
		self.notify_distribution()

	def notify_distribution(self):
		"""In-app System Notification only. Email/Print are handled by humans / standard Notification (B9, POL-EML)."""
		for row in self.release_distribution:
			if row.method != "System Notification" or row.sent_on:
				continue
			frappe.get_doc({
				"doctype": "Notification Log", "for_user": row.recipient, "type": "Alert",
				"document_type": self.doctype, "document_name": self.name,
				"subject": _("Engineering Release {0} Released for Production ({1})").format(self.name, self.item),
			}).insert(ignore_permissions=True)
			row.db_set("sent_on", now_datetime())

def defaults_from_product_revision(product_revision, check_perm=True):
	"""Drawing, BOM, Routing, Inspection Plan and Material Specification from ``product_revision``.
	MS is the PR's Material Specification moved forward to the current Approved revision, or the Item's
	EIR Material Specification when the PR has none."""
	out = frappe._dict({f: None for f in RELEASE_FROM_PR})
	if not product_revision:
		return out
	pr = frappe.db.get_value(
		"Product Revision",
		product_revision,
		[
			"item", "drawing_revision", "bom_revision_reference", "routing_revision_reference",
			"inspection_plan_revision_reference", "material_specification",
		],
		as_dict=True,
	)
	if not pr:
		return out
	if check_perm and not frappe.has_permission("Product Revision", "read", product_revision):
		return out
	out.drawing_revision = pr.drawing_revision
	out.bom = pr.bom_revision_reference
	out.routing = pr.routing_revision_reference
	out.inspection_plan = pr.inspection_plan_revision_reference
	spec = pr.material_specification
	if spec:
		spec = current_approved(SPEC, spec) or spec
	if not spec and pr.item:
		spec = R.item_engineering_defaults(pr.item, check_perm=check_perm).material_specification
	out.material_specification = spec
	return out


def item_release_defaults(item, check_perm=True):
	"""Product Revision (MER resolve_product_revision) plus baseline fields from that PR for ``item``."""
	from engineering_itagksa.engineering_itag_ksa.doctype.master_engineering_release.master_engineering_release import (
		resolve_drawing,
		resolve_product_revision,
	)

	out = frappe._dict(product_revision=None, **{f: None for f in RELEASE_FROM_PR})
	if not item:
		return out
	drawing = resolve_drawing(item)
	pr = resolve_product_revision(item, drawing)
	out.product_revision = pr
	if pr:
		out.update(defaults_from_product_revision(pr, check_perm=check_perm))
	else:
		out.material_specification = R.item_engineering_defaults(item, check_perm=check_perm).material_specification
	return out


@frappe.whitelist()
def get_item_release_defaults(item):
	"""Auto-fill source for the Engineering Release form (Item change)."""
	frappe.has_permission("Engineering Release", "create", throw=True)
	return item_release_defaults(item)


@frappe.whitelist()
def get_product_revision_release_defaults(product_revision):
	"""Refresh Drawing, BOM, Routing, Inspection Plan and Material Specification from a Product Revision change."""
	frappe.has_permission("Engineering Release", "create", throw=True)
	return defaults_from_product_revision(product_revision)

