// v15.3.7: Engineering keeps each component's Attributes and Allowed Drawing Types here.
frappe.ui.form.on("Item Component", {
	setup(frm) {
		frm.set_query("drawing_type", "allowed_drawing_types", () => ({ filters: { enabled: 1 } }));
	},
});
