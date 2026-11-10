"""Engineering Settings helpers (Single DocType `Engineering Settings`)."""

import frappe

from engineering_itagksa.engineering_itag_ksa.doctype.engineering_settings.engineering_settings import (
	default_company,
	item_naming_digits,
	require_release_for_manufacturing,
)

__all__ = ["default_company", "item_naming_digits", "require_release_for_manufacturing", "apply_default_company"]


def apply_default_company(doc, method=None):
	"""Fill `company` on new Engineering docs from Engineering Settings when blank."""
	if doc.meta.has_field("company") and not doc.get("company"):
		company = default_company()
		if company:
			doc.company = company


def ensure_settings_defaults():
	"""Seed the Single with defaults once; pin item_naming_prefix_digits to 7 (v15.3.5)."""
	from frappe.utils import cint

	from engineering_itagksa.engineering_itag_ksa.doctype.item_component.item_component import ITEM_NAMING_DIGITS

	settings = frappe.get_single("Engineering Settings")
	changed = False
	if cint(settings.item_naming_prefix_digits) != ITEM_NAMING_DIGITS:
		settings.item_naming_prefix_digits = ITEM_NAMING_DIGITS
		changed = True
	if settings.require_release_for_manufacturing in (None, ""):
		settings.require_release_for_manufacturing = 1
		changed = True
	if not settings.default_company:
		settings.default_company = frappe.defaults.get_global_default("company")
		changed = True
	# First save of an empty Single, or a digits pin / missing default.
	if changed or not frappe.db.get_single_value("Engineering Settings", "item_naming_prefix_digits"):
		settings.flags.ignore_permissions = True
		settings.save()
