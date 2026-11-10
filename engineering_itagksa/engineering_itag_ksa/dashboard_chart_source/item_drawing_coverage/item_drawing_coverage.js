frappe.provide("frappe.dashboards.chart_sources");

frappe.dashboards.chart_sources["Item Drawing Coverage"] = {
	method: "engineering_itagksa.engineering_itag_ksa.dashboard_chart_source.item_drawing_coverage.item_drawing_coverage.get",
	filters: [],
};
