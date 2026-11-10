# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from engineering_itagksa import lifecycle as L
from engineering_itagksa.constants import APPROVED, DRAFT, REJECTED, UNDER_REVIEW

# Plain Status field (no Workflow): Save -> Draft / Under Review / Rejected; Submit -> Approved (a draft set
# to Rejected stays Rejected when submitted); Cancel -> Cancelled.
DRAFT_STATES = (DRAFT, UNDER_REVIEW, REJECTED)
SUBMITTED_STATES = (APPROVED, REJECTED)


class EngineeringChangeRequest(Document):
	"""ECR is a request record only: it never modifies Item or any linked document (B7)."""

	def validate(self):
		L.validate_status(self, DRAFT_STATES, SUBMITTED_STATES, APPROVED, keep_on_submit=(REJECTED,))

	def before_update_after_submit(self):
		# the decision (Approved / Rejected) is fixed once submitted
		before = self.get_doc_before_save()
		L.validate_status(self, DRAFT_STATES, (before.workflow_state,) if before else SUBMITTED_STATES, APPROVED)

	def on_cancel(self):
		L.set_cancelled(self)
