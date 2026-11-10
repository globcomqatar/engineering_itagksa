# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ItemSpecAttribute(Document):
	def validate(self):
		seen = set()
		for row in self.item_spec_attribute_values:
			row.attribute_value = (row.attribute_value or "").strip()
			key = row.attribute_value.lower()
			if key in seen:
				frappe.throw(_("Row {0}: value {1} is listed more than once.").format(row.idx, frappe.bold(row.attribute_value)))
			seen.add(key)
			# Stable child row names (EIR stores the value string, not this name).
			if not row.name or not frappe.db.exists("Item Spec Attribute Value", row.name):
				row.name = f"{self.name}-{row.attribute_value}"[:140]
