# Copyright (c) 2026, Globcom and contributors
"""Engineering dashboard data helpers (custom Number Cards and Dashboard Chart Sources)."""

import frappe
from frappe import _


def _active_items():
	return set(frappe.get_all("Item", filters={"disabled": 0}, pluck="name"))


def _items_with_drawing():
	"""Items created by a submitted Engineering Item Request that has a drawing."""
	return set(
		frappe.get_all(
			"Engineering Item Request",
			filters={"docstatus": 1, "engineering_drawing": ["is", "set"], "created_item": ["is", "set"]},
			pluck="created_item",
			distinct=True,
		)
	)


def _counts():
	if not frappe.has_permission("Item", "read"):
		return 0, 0
	items = _active_items()
	with_drawing = len(items & _items_with_drawing())
	return with_drawing, len(items) - with_drawing


@frappe.whitelist()
def get_items_with_drawing(filters=None):
	return {"value": _counts()[0], "fieldtype": "Int"}


@frappe.whitelist()
def get_items_without_drawing(filters=None):
	return {"value": _counts()[1], "fieldtype": "Int"}


def get_item_drawing_coverage():
	with_drawing, without_drawing = _counts()
	return {
		"labels": [_("With Drawing"), _("Without Drawing")],
		"datasets": [{"name": _("Items"), "values": [with_drawing, without_drawing]}],
	}


def _docstatus_breakdown(doctype):
	labels = [_("Draft"), _("Submitted"), _("Cancelled")]
	if not frappe.has_permission(doctype, "read"):
		return labels, [0, 0, 0]
	rows = frappe.get_list(
		doctype, fields=["docstatus", "count(name) as cnt"], group_by="docstatus", order_by="docstatus"
	)
	counts = {r.docstatus: r.cnt for r in rows}
	return labels, [counts.get(0, 0), counts.get(1, 0), counts.get(2, 0)]


def get_item_request_status():
	labels, values = _docstatus_breakdown("Engineering Item Request")
	return {"labels": labels, "datasets": [{"name": _("Item Requests"), "values": values}]}


def get_bom_status_summary():
	labels = [_("Active"), _("Default"), _("Inactive (Submitted)"), _("Draft"), _("Cancelled")]
	if not frappe.has_permission("BOM", "read"):
		values = [0] * 5
	else:
		count = lambda f: frappe.db.count("BOM", f)  # noqa: E731
		values = [
			count({"docstatus": 1, "is_active": 1}),
			count({"docstatus": 1, "is_default": 1}),
			count({"docstatus": 1, "is_active": 0}),
			count({"docstatus": 0}),
			count({"docstatus": 2}),
		]
	return {"labels": labels, "datasets": [{"name": _("BOMs"), "values": values}]}
