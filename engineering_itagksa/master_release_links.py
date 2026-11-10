"""v15.2.0 Master Engineering Release: extra Connections cards on standard ERPNext dashboards (no core patch)."""

from frappe import _


def bom_dashboard(data):
	"""BOM Connections: Masters whose Top BOM is this BOM."""
	data.setdefault("non_standard_fieldnames", {})["Master Engineering Release"] = "top_bom"
	data.setdefault("transactions", []).append({"label": _("Engineering"), "items": ["Master Engineering Release"]})
	data.setdefault("disable_create_buttons", []).append("Master Engineering Release")
	return data
