# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

# Component Item naming is fixed at 7 digits (…-1000501). This setting is kept at 7
# for compatibility; ensure_item_naming_rule does not read a free value anymore.
DEFAULT_ITEM_NAMING_DIGITS = 7


class EngineeringSettings(Document):
	def validate(self):
		digits = cint(self.item_naming_prefix_digits)
		if digits != DEFAULT_ITEM_NAMING_DIGITS:
			# Pin quietly to the fixed component Item naming width.
			self.item_naming_prefix_digits = DEFAULT_ITEM_NAMING_DIGITS
			frappe.msgprint(
				_("Item Naming Prefix Digits is fixed at {0} for Item Component codes (<prefix>-1000501, then 1000502, …).").format(
					DEFAULT_ITEM_NAMING_DIGITS
				),
				indicator="blue",
				alert=True,
			)


def require_release_for_manufacturing():
	"""Engineering Settings flag; defaults to 1 (fail-closed) when never saved."""
	val = frappe.db.get_single_value("Engineering Settings", "require_release_for_manufacturing")
	if val is None or val == "":
		return True
	return bool(cint(val))


def item_naming_digits():
	"""Always 7: component Item codes are <prefix>-1000501 (Owner decision v15.3.5)."""
	return DEFAULT_ITEM_NAMING_DIGITS


def default_company():
	return frappe.db.get_single_value("Engineering Settings", "default_company")
