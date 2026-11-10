frappe.provide("frappe.dashboards.chart_sources");

frappe.dashboards.chart_sources["BOM Status Summary"] = {
	method: "engineering_itagksa.engineering_itag_ksa.dashboard_chart_source.bom_status_summary.bom_status_summary.get",
	filters: [],
};
