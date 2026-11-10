"""Optional master load: Item Component list from "Part Number - Master list.xlsx" (item_component_data).

Not run automatically. Same logic as the retired 15.1.20 patch ``seed_item_components``; idempotent by prefix.
Uses standard Item Group (created under the root Item Group if missing) as the parent of each component.

  bench --site <site> execute engineering_itagksa.setup.seed_item_components.run
"""

import frappe

from engineering_itagksa.item_component_data import COMPONENTS

ITEM_GROUPS = ("Raw Material", "Ball Valve-IS", "Miscellaneous", "Kelly Valve", "Gate Valve", "Wellhead Items")


def run():
	root = frappe.db.get_value("Item Group", {"is_group": 1, "parent_item_group": ("in", ("", None))}) or "All Item Groups"
	for group in dict.fromkeys(ITEM_GROUPS + tuple(g for g, _, _ in COMPONENTS)):
		if not frappe.db.exists("Item Group", group):
			doc = frappe.get_doc({"doctype": "Item Group", "item_group_name": group,
				"parent_item_group": root, "is_group": 0})
			doc.flags.ignore_permissions = True
			doc.insert()
	for group, component, prefix in COMPONENTS:
		if frappe.db.exists("Item Component", prefix):
			doc = frappe.get_doc("Item Component", prefix)
			if doc.component_name == component and doc.item_group == group:
				continue
			doc.component_name, doc.item_group = component, group
			doc.flags.ignore_permissions = True
			doc.save()
		else:
			doc = frappe.get_doc({"doctype": "Item Component", "part_code_prefix": prefix,
				"component_name": component, "item_group": group})
			doc.flags.ignore_permissions = True
			doc.insert()
	frappe.db.commit()
	print(f"Item Components: {len(COMPONENTS)} rows checked")
