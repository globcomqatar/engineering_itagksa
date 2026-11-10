"""Fail-closed Work Order gate (B5).

Configuration surface (locked fieldname, Ahmed soft #3): Item Group custom Check
`requires_engineering_release` (default 1). Work Order submit is BLOCKED unless an Engineering Release
in `release_status = "Released for Production"` exists for the production item, when:
  * the item's Engineering category is Manufacturing / Sub-Assembly and Engineering Settings
    "Require Engineering Release for Manufacturing / Sub-Assembly" is on (default 1), regardless of group flag, or
  * the item group flag is set (1), or unset / missing (fail-closed), or the item has no group.
Only items whose group explicitly has the flag = 0 and are not manufacturing-category pass through
(service / non-engineered items).

Work Order Check ``custom_subcontracted_job`` bypasses the gate entirely when ticked (Owner rule).
"""

import frappe
from frappe import _
from frappe.utils import now_datetime

from engineering_itagksa.eng_settings import require_release_for_manufacturing
from engineering_itagksa.constants import (
	ITEM_GROUP_GATE_FIELD,
	MANUFACTURING_CATEGORIES,
	RELEASED_FOR_PRODUCTION,
)


def get_gate_inputs(item_code):
	item = frappe.db.get_value("Item", item_code, ["item_group", "eng_item_category"], as_dict=True) or {}
	flag = None
	if item.get("item_group") and frappe.get_meta("Item Group").has_field(ITEM_GROUP_GATE_FIELD):
		flag = frappe.db.get_value("Item Group", item.get("item_group"), ITEM_GROUP_GATE_FIELD)
	return item.get("item_group"), item.get("eng_item_category"), flag


def requires_release(item_group, item_category, group_flag, force_manufacturing=True, subcontracted_job=False):
	"""Pure decision function (unit-tested).

	force_manufacturing comes from Engineering Settings.require_release_for_manufacturing.
	When off, Manufacturing / Sub-Assembly items fall back to the Item Group rule below.
	subcontracted_job: Work Order ``custom_subcontracted_job`` — when True, always skip the gate.
	"""
	if subcontracted_job:
		return False
	if force_manufacturing and item_category in MANUFACTURING_CATEGORIES:
		return True
	if not item_group:
		return True
	if group_flag is None or group_flag == "":
		return True  # unset -> fail closed
	return bool(int(group_flag))


def find_release(item_code):
	rows = frappe.get_all(
		"Engineering Release",
		filters={"item": item_code, "release_status": RELEASED_FOR_PRODUCTION, "effective_datetime": ["<=", now_datetime()]},
		fields=["name", "bom", "drawing_revision"],
		order_by="effective_datetime desc, creation desc",
		limit=1,
	)
	return rows[0] if rows else None


def check_work_order(doc, method=None):
	"""Hooked on Work Order before_submit."""
	item = doc.production_item
	subcontracted = bool(int(doc.get("custom_subcontracted_job") or 0))
	if not requires_release(
		*get_gate_inputs(item),
		force_manufacturing=require_release_for_manufacturing(),
		subcontracted_job=subcontracted,
	):
		apply_release_baseline(doc)
		return
	release = find_release(item)
	if not release:
		frappe.throw(
			_("Work Order cannot be submitted: Item {0} requires an Engineering Release in state '{1}', and none exists.").format(
				frappe.bold(item), RELEASED_FOR_PRODUCTION
			),
			title=_("Engineering Release required"),
		)
	if doc.bom_no and release.bom and doc.bom_no != release.bom:
		frappe.throw(
			_("Work Order BOM {0} does not match the BOM {1} in Engineering Release {2} for Item {3}.").format(
				frappe.bold(doc.bom_no), frappe.bold(release.bom), release.name, frappe.bold(item)
			),
			title=_("Engineering Release mismatch"),
		)
	apply_release_baseline(doc, release)


def apply_release_baseline(doc, release=None):
	"""Freeze the Engineering tab baseline on the Work Order (read-only, set at submit).

	Release / Design (drawing_revision) / BOM come from the Engineering Release used by the gate;
	Item Component is a snapshot of the production Item at submit.
	"""
	if release:
		doc.engineering_release = release.name
		doc.eng_design = release.get("drawing_revision")
		doc.eng_release_bom = release.get("bom")
	if doc.get("production_item") and frappe.get_meta("Item").has_field("eng_item_component"):
		doc.eng_item_component = frappe.db.get_value("Item", doc.production_item, "eng_item_component")
