"""v15.3.7 (Phase 1): Engineering Drawing Type master + required Description on Engineering Drawing.

* Seed the default drawing types and create the old Select values still used by a drawing (disabled), so every
  Engineering Drawing.drawing_type is a valid link.
* Fill the new required Description of existing drawings from the removed Drawing Name (column still in the
  table after the field is dropped), else Change Description, else the Item Component name. Idempotent.
"""

import frappe


def execute():
	if not frappe.db.table_exists("Engineering Drawing"):
		return
	frappe.reload_doc("engineering_itag_ksa", "doctype", "engineering_drawing_type")
	from engineering_itagksa.install import ensure_drawing_types

	ensure_drawing_types()

	columns = set(frappe.db.get_table_columns("Engineering Drawing"))
	if "description" not in columns:
		return
	sources = [c for c in ("drawing_name", "change_description") if c in columns]
	rows = frappe.db.sql(
		"select name, item_component{0} from `tabEngineering Drawing` where ifnull(description, '') = ''".format(
			"".join(f", {c}" for c in sources)
		),
		as_dict=True,
	)
	for row in rows:
		text = next((row.get(c) for c in sources if (row.get(c) or "").strip()), None)
		if not text and row.item_component:
			text = frappe.db.get_value("Item Component", row.item_component, "component_name")
		frappe.db.set_value("Engineering Drawing", row.name, "description", text or row.name, update_modified=False)
