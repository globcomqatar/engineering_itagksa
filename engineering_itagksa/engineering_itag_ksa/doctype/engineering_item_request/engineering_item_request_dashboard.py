def get_data():
	return {
		"fieldname": "engineering_item_request",
		"internal_links": {
			"Item": "created_item",
			"Engineering Drawing": "engineering_drawing",
			"Material Specification": "material_specification",
		},
		"transactions": [
			{"label": "Item", "items": ["Item"]},
			{"label": "Engineering", "items": ["Engineering Drawing", "Material Specification"]},
		],
	}
