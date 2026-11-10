from frappe import _


def get_data():
	"""Standard Connections: the Master Engineering Release this release belongs to (v15.2.0)."""
	return {
		"fieldname": "engineering_release",
		"internal_links": {"Master Engineering Release": "master_engineering_release"},
		"transactions": [{"label": _("Engineering"), "items": ["Master Engineering Release"]}],
		"disable_create_buttons": ["Master Engineering Release"],
	}
