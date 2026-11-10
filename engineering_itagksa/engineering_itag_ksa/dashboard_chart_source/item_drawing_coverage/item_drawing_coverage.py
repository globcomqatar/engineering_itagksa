# Copyright (c) 2026, Globcom and contributors
import frappe
from frappe.utils.dashboard import cache_source

from engineering_itagksa.dashboard_utils import get_item_drawing_coverage


@frappe.whitelist()
@cache_source
def get(
	chart_name=None,
	chart=None,
	no_cache=None,
	filters=None,
	from_date=None,
	to_date=None,
	timespan=None,
	time_interval=None,
	heatmap_year=None,
):
	return get_item_drawing_coverage()
