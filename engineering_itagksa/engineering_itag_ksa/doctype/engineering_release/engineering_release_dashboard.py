def get_data():
	return {
		"fieldname": "engineering_release",
		"internal_links": {
			"Item": "item",
			"Engineering Drawing": "engineering_drawing",
			"Material Specification": "material_specification",
			"BOM": "bom",
			"Routing": "routing",
			"Quality Inspection Template": "inspection_plan",
		},
		"transactions": [
			{"label": "Item", "items": ["Item"]},
			{"label": "Engineering", "items": ["Engineering Drawing", "Material Specification"]},
			{"label": "Manufacturing", "items": ["BOM", "Routing", "Quality Inspection Template"]},
		],
	}
