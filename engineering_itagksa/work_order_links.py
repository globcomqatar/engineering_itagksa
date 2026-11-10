"""Work Order Engineering tab -> Engineering Change: ECR / ECO for the same Work Order.

Work Order.eng_ecr / eng_eco are read-only, denormalized links kept current by doc_events on
Engineering Change Request / Engineering Change Order (create / update / submit / cancel / delete).
Chain link is the `work_order` custom field on both; an ECO without work_order falls back to its source ECR.
"""

import frappe

WO = "Work Order"
ECR = "Engineering Change Request"
ECO = "Engineering Change Order"


def _latest(doctype, filters, exclude=None):
	filters = dict(filters, docstatus=("!=", 2))
	if exclude:
		filters["name"] = ("!=", exclude)
	rows = frappe.get_all(doctype, filters=filters, fields=["name"], order_by="creation desc", limit=1)
	return rows[0].name if rows else None


def resolve_links(wo, exclude=None):
	exclude = exclude or {}
	ecr = _latest(ECR, {"work_order": wo}, exclude.get(ECR))
	eco = _latest(ECO, {"work_order": wo}, exclude.get(ECO))
	if not eco:
		ecrs = frappe.get_all(ECR, filters={"work_order": wo}, pluck="name")
		if ecrs:
			eco = _latest(ECO, {"source_ecr": ("in", ecrs)}, exclude.get(ECO))
	return {"eng_ecr": ecr, "eng_eco": eco}


def sync_work_order(wo, exclude=None):
	if not wo or not frappe.db.exists(WO, wo) or not frappe.get_meta(WO).has_field("eng_ecr"):
		return
	links = resolve_links(wo, exclude)
	current = frappe.db.get_value(WO, wo, list(links), as_dict=True) or {}
	changed = {k: v for k, v in links.items() if (current.get(k) or None) != v}
	if changed:
		frappe.db.set_value(WO, wo, changed, update_modified=False)


def _work_orders(doc):
	wos = {doc.get("work_order")}
	before = doc.get_doc_before_save() if hasattr(doc, "get_doc_before_save") else None
	if before:
		wos.add(before.get("work_order"))
	if doc.doctype == ECO and doc.get("source_ecr"):
		wos.add(frappe.db.get_value(ECR, doc.source_ecr, "work_order"))
	return {w for w in wos if w}


def on_change_doc(doc, method=None):
	exclude = {doc.doctype: doc.name} if method in ("on_trash", "on_cancel") else None
	for wo in _work_orders(doc):
		sync_work_order(wo, exclude)


def backfill():
	"""Idempotent: fill ECR / ECO on every Work Order that has one linked."""
	if not frappe.get_meta(WO).has_field("eng_ecr"):
		return
	wos = set(frappe.get_all(ECR, filters={"work_order": ("is", "set")}, pluck="work_order"))
	wos |= set(frappe.get_all(ECO, filters={"work_order": ("is", "set")}, pluck="work_order"))
	wos |= set(frappe.get_all(WO, filters=[["eng_ecr", "is", "set"]], pluck="name"))
	wos |= set(frappe.get_all(WO, filters=[["eng_eco", "is", "set"]], pluck="name"))
	for wo in wos:
		sync_work_order(wo)


def backfill_baseline():
	"""Idempotent: submitted WOs that already carry an Engineering Release get Design / BOM / Component."""
	if not frappe.get_meta(WO).has_field("eng_release_bom"):
		return
	for wo in frappe.get_all(WO, filters={"docstatus": 1, "engineering_release": ("is", "set"), "eng_release_bom": ("is", "not set")},
			fields=["name", "engineering_release", "production_item"]):
		rel = frappe.db.get_value("Engineering Release", wo.engineering_release, ["bom", "drawing_revision"], as_dict=True) or {}
		vals = {"eng_release_bom": rel.get("bom"), "eng_design": rel.get("drawing_revision")}
		if frappe.get_meta("Item").has_field("eng_item_component"):
			vals["eng_item_component"] = frappe.db.get_value("Item", wo.production_item, "eng_item_component")
		frappe.db.set_value(WO, wo.name, vals, update_modified=False)
