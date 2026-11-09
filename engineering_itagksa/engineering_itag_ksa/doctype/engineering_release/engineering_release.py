"""Engineering Release. Desk workflow from Draft to Approved to Released for Production."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from engineering_itagksa.engineering_itag_ksa.constants import (
	DRAWING,
	ENGINEERING_MANAGER,
	ENGINEERING_MANAGER_MASTER,
	MATERIAL_SPECIFICATION,
	RELEASE_CONTENT_FIELDS,
)
from engineering_itagksa.engineering_itag_ksa.controls import (
	assert_link,
	remember_cancellation,
	require_role,
)
from engineering_itagksa.engineering_itag_ksa.release_rules import release_key, sequences_match


class EngineeringRelease(Document):
	def validate(self):
		self._validate_selected_links(final=False)
		previous = self.get("_doc_before_save")
		if previous:
			self._reject_direct_state_change(previous)
			self._lock_engineering_fields(previous)
			self._apply_return(previous)
			self._apply_approval(previous)
		elif self.workflow_state not in (None, "", "Draft"):
			frappe.throw(_("A new Engineering Release starts in Draft."))

	def before_submit(self):
		previous = self.get("_doc_before_save")
		if (
			not previous
			or previous.workflow_state != "Approved"
			or self.workflow_state != "Released for Production"
		):
			frappe.throw(
				_("Release for Production is the only transition that submits an Engineering Release.")
			)
		require_role(
			ENGINEERING_MANAGER_MASTER,
			_("Only Engineering Manager Master can release an Engineering Release for production."),
		)
		approver = previous.approved_by
		user = frappe.session.user
		if not approver:
			frappe.throw(_("Approve the Engineering Release before releasing it."))
		if user in {self.owner, approver}:
			frappe.throw(_("Creator, approver, and releaser must be three different users."))
		self.approved_by = approver
		self.released_by = user
		self._validate_selected_links(final=True)
		self._claim_release_slot()

	def before_cancel(self):
		remember_cancellation(self)
		self.active_release_key = None

	def on_cancel(self):
		# Linked Drawing, Material Specification, BOM, and Item stay at their own status.
		key = release_key(self.item, self.bom) if self.item and self.bom else None
		if key and frappe.db.exists("Engineering Release Slot", key):
			frappe.delete_doc("Engineering Release Slot", key, ignore_permissions=True, force=True)

	def _reject_direct_state_change(self, previous) -> None:
		old = previous.workflow_state or "Draft"
		new = self.workflow_state or "Draft"
		if old == new:
			return
		from frappe.model.workflow import get_transitions

		allowed = {row.next_state for row in get_transitions(previous)}
		if new not in allowed:
			frappe.throw(_("Workflow State cannot be changed directly from {0} to {1}.").format(old, new))

	def _lock_engineering_fields(self, previous) -> None:
		old = previous.workflow_state or "Draft"
		new = self.workflow_state or "Draft"
		if old == "Draft" and new == "Draft":
			return
		for field in RELEASE_CONTENT_FIELDS:
			if (self.get(field) or None) != (previous.get(field) or None):
				frappe.throw(_("Engineering fields are locked while {0}.").format(old))
		if (
			old == "Approved"
			and new == "Approved"
			and (self.approved_by or None) != (previous.approved_by or None)
		):
			frappe.throw(_("Approved By cannot be edited."))

	def _apply_return(self, previous) -> None:
		if previous.workflow_state != "Approved" or self.workflow_state != "Draft":
			return
		require_role(
			ENGINEERING_MANAGER_MASTER,
			_("Only Engineering Manager Master can return an Approved Engineering Release to Draft."),
		)
		reason = (previous.return_reason or "").strip()
		if not reason:
			frappe.throw(_("Enter a return reason before returning this Engineering Release to Draft."))
		self.return_reason = None
		self.approved_by = None
		self.released_by = None
		self.add_comment("Comment", _("Returned to Draft: {0}").format(reason))

	def _apply_approval(self, previous) -> None:
		if previous.workflow_state != "Draft" or self.workflow_state != "Approved":
			return
		require_role(ENGINEERING_MANAGER, _("Only Engineering Manager can approve an Engineering Release."))
		if frappe.session.user == self.owner:
			frappe.throw(_("The approver must be a different user from the creator."))
		self.approved_by = frappe.session.user
		self.released_by = None
		self._validate_selected_links(final=True)

	def _validate_selected_links(self, *, final: bool) -> None:
		assert_link("Item", self.item)
		assert_link(DRAWING, self.engineering_drawing, require_submitted=final)
		assert_link(MATERIAL_SPECIFICATION, self.material_specification, require_submitted=final)
		assert_link("BOM", self.bom, require_submitted=final)
		assert_link("Routing", self.routing)
		if self.routing and frappe.db.get_value("Routing", self.routing, "disabled"):
			frappe.throw(_("Routing {0} is disabled.").format(self.routing))
		assert_link("Quality Inspection Template", self.inspection_plan)
		if final:
			for field, label in (
				("engineering_drawing", _("Drawing")),
				("material_specification", _("Material Specification")),
				("bom", _("BOM")),
			):
				if not self.get(field):
					frappe.throw(_("{0} is required before approval and production release.").format(label))
		if self.bom:
			self._validate_bom(final=final)
		elif self.routing and final:
			frappe.throw(_("Select a BOM before selecting a Routing for approval or production release."))

	def _validate_bom(self, *, final: bool) -> None:
		bom = frappe.get_doc("BOM", self.bom)
		if bom.item != self.item:
			frappe.throw(_("BOM {0} is for Item {1}, not {2}.").format(bom.name, bom.item, self.item))
		if final and not bom.is_active:
			frappe.throw(_("BOM {0} must be active.").format(bom.name))
		uses_operations = bool(bom.with_operations) or any(row.operation for row in bom.operations)
		if final and uses_operations and not self.routing:
			frappe.throw(_("Routing is required because BOM {0} uses operations.").format(bom.name))
		if self.routing:
			routing = frappe.get_doc("Routing", self.routing)
			if not sequences_match(bom.operations, routing.operations):
				frappe.throw(
					_(
						"Routing {0} must match the operation and sequence of BOM {1}. Times and workstations are not compared."
					).format(routing.name, bom.name)
				)

	def _claim_release_slot(self) -> None:
		key = release_key(self.item, self.bom)
		frappe.db.sql("select name from `tabEngineering Release Slot` where name=%s for update", key)
		if frappe.db.exists("Engineering Release Slot", key):
			holder = frappe.db.get_value("Engineering Release Slot", key, "engineering_release")
			frappe.throw(
				_(
					"An uncancelled Released for Production Engineering Release already exists for this Item and BOM: {0}. Cancel it before releasing a replacement."
				).format(holder)
			)
		try:
			frappe.get_doc(
				{
					"doctype": "Engineering Release Slot",
					"name": key,
					"engineering_release": self.name,
					"item": self.item,
					"bom": self.bom,
				}
			).insert(ignore_permissions=True)
		except frappe.DuplicateEntryError:
			frappe.throw(
				_(
					"An uncancelled Released for Production Engineering Release already exists for this Item and BOM."
				)
			)
		self.active_release_key = key


@frappe.whitelist()
def set_return_reason(name: str, return_reason: str):
	require_role(
		ENGINEERING_MANAGER_MASTER,
		_("Only Engineering Manager Master can record a return reason."),
	)
	reason = (return_reason or "").strip()
	if not reason:
		frappe.throw(_("Enter a return reason."))
	doc = frappe.get_doc("Engineering Release", name)
	doc.check_permission("read")
	if doc.docstatus != 0 or doc.workflow_state != "Approved":
		frappe.throw(_("Return to Draft is available only while the Engineering Release is Approved."))
	doc.db_set("return_reason", reason, update_modified=False)
	return reason
