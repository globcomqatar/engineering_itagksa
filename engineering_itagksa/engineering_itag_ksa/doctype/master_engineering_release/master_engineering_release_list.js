frappe.listview_settings["Master Engineering Release"] = {
	add_fields: ["release_status"],
	get_indicator(doc) {
		const c = { Draft: "red", Approved: "orange", "Released for Production": "green", Superseded: "gray" };
		return [__(doc.release_status), c[doc.release_status] || "gray", "release_status,=," + doc.release_status];
	},
};
