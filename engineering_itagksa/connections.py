"""Connections tab data for Engineering Item Request / Engineering Drawing / Product Revision.

Item Request uses its own outbound engineering_drawing / material_specification links;
BOM and Engineering Release still match on the created Item. Engineering Drawing counts BOMs
through the Items created by Engineering Item Requests that reference the drawing (or a
revision in the same chain). Product Revision also lists its Material Specification.
"""

import frappe

GROUPS = {
	"Engineering Item Request": [
		("Engineering Drawing", "@engineering_drawing"),
		("Material Specification", "@material_specification"),
		("BOM", "item"),
		("Engineering Release", "item"),
	],
	"Engineering Drawing": [
		("Product Revision", "drawing_revision"),
		("Engineering Release", "drawing_revision"),
		("Master Engineering Release", "items.drawing"),
		("BOM", "eir_item"),
	],
	# Product Revision: outbound links (own fields) + inbound (Release / next revision)
	"Product Revision": [
		("Engineering Drawing", "@drawing_revision"),
		("Material Specification", "@material_specification"),
		("BOM", "@bom_revision_reference"),
		("Routing", "@routing_revision_reference"),
		("Quality Inspection Template", "@inspection_plan_revision_reference"),
		("Engineering Change Order", "@applicable_eco"),
		("Engineering Release", "product_revision"),
		("Master Engineering Release", "items.product_revision"),
		("Product Revision", "previous_revision"),
	],
}



def _boms_for_drawing(drawing):
	"""Submitted (non-cancelled) BOM names for Items created from EIRs that reference this drawing."""
	from engineering_itagksa.engineering_refs import items_for_drawing
	names = []
	for item in items_for_drawing(drawing):
		names.extend(frappe.get_all("BOM", filters={"item": item, "docstatus": ("!=", 2)}, pluck="name"))
	return names


# "table.field" = match on a child-table field of a parent DocType (v15.2.0 Master Engineering Release Items)
CHILD_TABLES = {"Master Engineering Release": "Master Engineering Release Item"}


def _child_parents(dt, field, value):
	child_field = field.split(".", 1)[1]
	return sorted(set(frappe.get_all(CHILD_TABLES[dt], filters={child_field: value, "parenttype": dt}, pluck="parent")))


@frappe.whitelist()
def get_connections(doctype, name):
	if doctype not in GROUPS:
		frappe.throw("Not supported")
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("read")
	item = doc.get("created_item") if doctype == "Engineering Item Request" else (doc.get("item") if doctype == "Product Revision" else doc.get("item_code"))
	out = []
	for dt, field in GROUPS[doctype]:
		if field.startswith("@"):
			# outbound link stored on this document
			value = doc.get(field[1:])
			row = {"doctype": dt, "field": "name", "value": value, "count": 1 if value else 0, "allowed": bool(frappe.has_permission(dt, "read"))}
			out.append(row)
			continue
		if field == "eir_item":
			row = {"doctype": dt, "field": "item", "value": name, "count": 0, "allowed": bool(frappe.has_permission(dt, "read"))}
			if row["allowed"]:
				row["count"] = len(_boms_for_drawing(name))
			out.append(row)
			continue
		if doctype == "Product Revision" or field == "drawing_revision" or "." in field:
			value = name
		else:
			value = item
		row = {"doctype": dt, "field": field, "value": value, "count": 0, "allowed": bool(frappe.has_permission(dt, "read"))}
		if value and row["allowed"]:
			if "." in field:
				row["count"] = len(_child_parents(dt, field, value))
			else:
				row["count"] = frappe.db.count(dt, {field: value, "docstatus": ("!=", 2)})
		out.append(row)
	return {"item": item, "groups": out}


LABELS = {
	"Engineering Item Request": [
		("Engineering", ["Engineering Drawing", "Material Specification", "Engineering Release"]),
		("Manufacturing", ["BOM"]),
	],
	"Engineering Drawing": [
		("Engineering", ["Product Revision", "Engineering Release", "Master Engineering Release"]),
		("Manufacturing", ["BOM"]),
	],
	"Product Revision": [
		("Engineering", ["Engineering Drawing", "Material Specification", "Engineering Change Order", "Engineering Release", "Master Engineering Release", "Product Revision"]),
		("Manufacturing", ["BOM", "Routing"]),
		("Quality", ["Quality Inspection Template"]),
	],
}


def dashboard_data(doctype):
	"""Standard Frappe dashboard dict; counts come from get_open_count below (item/outbound matching)."""
	return {
		"fieldname": "name",
		"method": "engineering_itagksa.connections.get_open_count",
		"transactions": [{"label": l, "items": i} for l, i in LABELS[doctype]],
	}


@frappe.whitelist()
def get_open_count(doctype, name, items=None):
	"""Same response shape as frappe.desk.notifications.get_open_count; every row is an
	internal link with explicit names so the standard card click filters `name in (...)`."""
	if doctype not in GROUPS:
		frappe.throw("Not supported")
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("read")
	item = doc.get("created_item") if doctype == "Engineering Item Request" else (doc.get("item") if doctype == "Product Revision" else doc.get("item_code"))
	found = []
	for dt, field in GROUPS[doctype]:
		if not frappe.has_permission(dt, "read"):
			continue
		if field.startswith("@"):
			v = doc.get(field[1:])
			names = [v] if v and frappe.db.exists(dt, v) else []
		elif field == "eir_item":
			names = _boms_for_drawing(name) if frappe.has_permission("BOM", "read") else []
		else:
			value = name if (doctype == "Product Revision" or field == "drawing_revision" or "." in field) else item
			if "." in field:
				names = _child_parents(dt, field, value)
				found.append({"doctype": dt, "count": len(names), "open_count": 0, "names": names})
				continue
			names = frappe.get_all(dt, filters={field: value, "docstatus": ("!=", 2)}, pluck="name", limit=500) if value else []
		found.append({"doctype": dt, "count": len(names), "open_count": 0, "names": names})
	return {"count": {"external_links_found": [], "internal_links_found": found}}
