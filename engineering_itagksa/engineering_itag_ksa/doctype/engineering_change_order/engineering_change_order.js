frappe.ui.form.on("Engineering Change Order", {
	setup(frm) {
		frm.set_query("source_ecr", () => ({ filters: { docstatus: 1, workflow_state: "Approved" } }));
	},
});
