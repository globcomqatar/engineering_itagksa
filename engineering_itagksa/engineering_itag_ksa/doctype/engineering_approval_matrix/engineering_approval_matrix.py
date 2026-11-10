# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate


class EngineeringApprovalMatrix(Document):
	"""Resolver rule only (B1). Holds no status; see engineering_itagksa.approval_matrix.resolve."""

	def validate(self):
		if self.effective_from and self.effective_to and getdate(self.effective_to) < getdate(self.effective_from):
			frappe.throw(_("Effective To cannot be before Effective From."))
		seqs = [d.sequence for d in self.required_disciplines if d.sequence]
		if len(seqs) != len(set(seqs)):
			frappe.throw(_("Discipline sequence numbers must be unique."))
