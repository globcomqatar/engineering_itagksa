# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from engineering_itagksa import approval_matrix as AM
from engineering_itagksa import lifecycle as L
from engineering_itagksa.constants import APPROVED, COMPLETED, DRAFT, UNDER_REVIEW

# Plain Status field (no Workflow): Save -> Draft / Under Review, Submit -> Approved, then (Update After
# Submit) Completed; Cancel -> Cancelled.
DRAFT_STATES = (DRAFT, UNDER_REVIEW)
SUBMITTED_STATES = (APPROVED, COMPLETED)


class EngineeringChangeOrder(Document):
	"""B7: no silent Item mutation. Nothing in this controller writes to Item, BOM, Routing, Drawing or
	Material Specification. Changes are carried out by explicit new revisions / releases (their own Submit)."""

	def validate(self):
		ecr = frappe.db.get_value("Engineering Change Request", self.source_ecr, ["docstatus", "workflow_state", "item"], as_dict=True)
		if not ecr or ecr.docstatus != 1 or ecr.workflow_state != APPROVED:
			frappe.throw(_("Source ECR {0} must be Approved.").format(frappe.bold(self.source_ecr)))
		self.item = ecr.item
		L.validate_status(self, DRAFT_STATES, SUBMITTED_STATES, APPROVED)
		AM.apply(self, self.matrix_context())

	def before_submit(self):
		self.validate_controlled_changes()
		AM.apply(self, self.matrix_context(), enforce=True)

	def before_update_after_submit(self):
		L.validate_status(self, DRAFT_STATES, SUBMITTED_STATES, APPROVED)
		if L.entering(self, COMPLETED):
			self.validate_controlled_changes()
			self.completed_on = now_datetime()

	def on_cancel(self):
		L.set_cancelled(self)

	def validate_controlled_changes(self):
		if not self.controlled_changes:
			frappe.throw(_("Controlled Changes are required before ECO approval/completion."))
		for row in self.controlled_changes:
			if not row.interchangeability:
				frappe.throw(_("Row {0}: Interchangeability is required.").format(row.idx))

	def matrix_context(self):
		ecr = frappe.db.get_value("Engineering Change Request", self.source_ecr,
			["safety_impact", "customer_impact", "compliance_impact", "cost_impact"], as_dict=True) or {}
		ctx = AM.item_context(self.item)
		ctx.update(company=self.company, safety_classification=ecr.get("safety_impact"), change_risk=self.change_risk,
			is_customer_specific=ecr.get("customer_impact") not in (None, "", "None"),
			is_regulatory=ecr.get("compliance_impact") not in (None, "", "None"), cost_impact=ecr.get("cost_impact") or 0)
		return ctx
