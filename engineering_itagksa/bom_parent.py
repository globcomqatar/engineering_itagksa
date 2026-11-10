import frappe
from frappe import _


def validate_parent_bom(doc, method=None):
	"""Light guard: a BOM may not be its own Parent BOM."""
	if doc.get("parent_bom") and doc.name and doc.parent_bom == doc.name:
		frappe.throw(_("Parent BOM cannot be the same BOM ({0}).").format(doc.name), title=_("Invalid Parent BOM"))
