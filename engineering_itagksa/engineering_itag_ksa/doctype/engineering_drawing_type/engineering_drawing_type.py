# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class EngineeringDrawingType(Document):
	def validate(self):
		self.drawing_type_name = (self.drawing_type_name or "").strip()
