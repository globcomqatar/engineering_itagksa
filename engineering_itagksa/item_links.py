"""Item Engineering tab: Related Documents (BOM / Design / Release) for the same Item.

Item.eng_bom / eng_design / eng_release are read-only, denormalized links. They are kept current two ways:
- doc_events on BOM, Engineering Drawing, Engineering Release and Engineering Item Request re-sync the Item
  on create/submit/update/cancel/delete;
- public/js/item.js re-reads them on Item form refresh (get_item_engineering_links).
"Design" (v15.3.6) = the Engineering Drawing on the Engineering Item Request that created the Item, moved
forward to the current Approved revision (fallback Item.eng_design). "Release" = Engineering Release (field item).
"""

import frappe

from engineering_itagksa.constants import COMPLETED, INACTIVE_STATES, RELEASED_FOR_PRODUCTION

ITEM_FIELDS = ("eng_bom", "eng_design", "eng_release")
SOURCES = {
	"BOM": ("item", "eng_bom"),
	"Engineering Drawing": ("item_code", "eng_design"),
	"Engineering Release": ("item", "eng_release"),
}


def _first(getter, doctype, filter_sets, exclude=None):
	for filters in filter_sets:
		filters = dict(filters)
		if exclude:
			filters["name"] = ("!=", exclude)
		rows = getter(doctype, filters=filters, fields=["name"], order_by="modified desc", limit_page_length=1)
		if rows:
			return rows[0].name
	return None


def resolve_links(item, getter=None, exclude=None):
	"""Best current BOM / Drawing / Release for an Item. getter=frappe.get_all (sync) or frappe.get_list (client)."""
	getter = getter or frappe.get_all
	exclude = exclude or {}
	bom = _first(getter, "BOM", [
		{"item": item, "docstatus": 1, "is_active": 1, "is_default": 1},
		{"item": item, "docstatus": 1, "is_active": 1},
		{"item": item, "docstatus": ("!=", 2)},
	], exclude.get("BOM"))
	# v15.3.6: Design comes from the creating EIR's drawing, moved forward to the current Approved revision.
	from engineering_itagksa.engineering_refs import DRAWING, current_approved, item_drawing
	linked = item_drawing(item)
	design = (current_approved(DRAWING, linked) or linked) if linked else None
	if design and exclude.get("Engineering Drawing") == design:
		design = None
	release = _first(getter, "Engineering Release", [
		{"item": item, "release_status": ("in", (RELEASED_FOR_PRODUCTION, COMPLETED))},
		{"item": item, "release_status": ("not in", INACTIVE_STATES)},
		{"item": item},
	], exclude.get("Engineering Release"))
	return {"eng_bom": bom, "eng_design": design, "eng_release": release}


def sync_item(item, exclude=None):
	if not item or not frappe.db.exists("Item", item):
		return
	if not frappe.get_meta("Item").has_field("eng_bom"):
		return
	links = resolve_links(item, exclude=exclude)
	current = frappe.db.get_value("Item", item, list(ITEM_FIELDS), as_dict=True) or {}
	changed = {f: v for f, v in links.items() if (current.get(f) or None) != v}
	if changed:
		frappe.db.set_value("Item", item, changed, update_modified=False)


def on_source_change(doc, method=None):
	"""doc_event for BOM / Engineering Drawing / Engineering Release / Engineering Item Request."""
	items = set()
	if doc.doctype == "Engineering Item Request":
		items.add(doc.get("created_item"))
		before = doc.get_doc_before_save() if hasattr(doc, "get_doc_before_save") else None
		if before and before.get("created_item"):
			items.add(before.get("created_item"))
	elif doc.doctype == "Engineering Drawing":
		from engineering_itagksa.engineering_refs import items_for_drawing
		items.update(items_for_drawing(doc.name))
		if doc.get("revises"):
			items.update(items_for_drawing(doc.get("revises")))
	else:
		item_field, _ = SOURCES[doc.doctype]
		if not doc.meta.has_field(item_field):
			return
		items.add(doc.get(item_field))
		before = doc.get_doc_before_save() if hasattr(doc, "get_doc_before_save") else None
		if before and before.get(item_field):
			items.add(before.get(item_field))
	exclude = {doc.doctype: doc.name} if method == "on_trash" else None
	for item in filter(None, items):
		sync_item(item, exclude=exclude)


@frappe.whitelist()
def get_item_engineering_links(item):
	"""Client refresh for Item form; respects the caller's read permissions."""
	frappe.has_permission("Item", "read", doc=item, throw=True)
	return resolve_links(item, getter=frappe.get_list)
