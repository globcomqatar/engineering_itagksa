from frappe import _


def get_data():
	"""Standard Connections: ERs back-linked by `master_engineering_release`; BOM / Drawing / Product Revision
	and Material Specification from the Items table (internal links)."""
	return {
		"fieldname": "master_engineering_release",
		"internal_links": {
			"BOM": ["items", "bom"],
			"Engineering Drawing": ["items", "drawing"],
			"Product Revision": ["items", "product_revision"],
			"Material Specification": ["items", "material_specification"],
			"BOM Creator": "bom_creator",
		},
		"transactions": [
			{"label": _("Engineering"), "items": ["Engineering Release", "Engineering Drawing", "Product Revision", "Material Specification"]},
			{"label": _("Manufacturing"), "items": ["BOM", "BOM Creator"]},
		],
		"disable_create_buttons": ["Engineering Release", "Engineering Drawing", "Product Revision", "Material Specification", "BOM", "BOM Creator"],
	}
