"""Material Specification. Submittable technical document with no Item and no Revision."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from engineering_itagksa.engineering_itag_ksa.constants import ENGINEERING_MANAGER, MS_CONTENT_FIELDS
from engineering_itagksa.engineering_itag_ksa.controls import (
	remember_cancellation,
	require_private_files,
	require_role,
)


class MaterialSpecification(Document):
	def before_submit(self):
		require_role(
			ENGINEERING_MANAGER,
			_("Only Engineering Manager can submit a Material Specification."),
		)
		if self.owner == frappe.session.user:
			frappe.throw(_("The Engineering Manager who submits must be a different user from the creator."))
		if not any((self.get(field) or "").strip() for field in MS_CONTENT_FIELDS):
			frappe.throw(
				_("Enter material specification content before submission. The attachment is optional.")
			)
		require_private_files(self.doctype, self.name, required=False)

	def before_cancel(self):
		remember_cancellation(self)
