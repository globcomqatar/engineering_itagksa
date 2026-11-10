// B6: create button only after submit AND Item created.
// Attribute Value: Data (ERPNext Item Variant Attribute pattern) + Autocomplete
// dropdown from Item Spec Attribute Value rows for the selected attribute.
// v15.3.1: Engineering Drawing / Material Specification optional links after Maintain Stock.
frappe.ui.form.on("Engineering Item Request", {
	setup(frm) {
		// Item Component dropdown only offers components of the selected Item Group.
		frm.set_query("item_component", () => ({ filters: { item_group: frm.doc.item_group || "__none__" } }));
		// Drawing: same Item Group + Item Component, not Superseded / Obsolete.
		frm.set_query("engineering_drawing", () => {
			const filters = {
				workflow_state: ["not in", ["Superseded", "Obsolete"]],
			};
			if (frm.doc.item_group) filters.item_group = frm.doc.item_group;
			if (frm.doc.item_component) filters.item_component = frm.doc.item_component;
			return { filters };
		});
		// Material Specification: Approved only.
		frm.set_query("material_specification", () => ({ filters: { workflow_state: "Approved" } }));
		// Promote Data -> Autocomplete on this form so Desk can offer parent-scoped values
		// (same UX as ERPNext's Awesomplete on Item Attribute Value; storage stays the value string).
		const df = frappe.meta.get_docfield("Item Request Attribute", "attribute_value", frm.doc.name);
		if (df) {
			df.fieldtype = "Autocomplete";
			df.ignore_validation = 1;
		}
		frm.set_query("attribute_value", "item_request_attribute", (doc, cdt, cdn) => {
			const row = locals[cdt][cdn] || {};
			return {
				query: "engineering_itagksa.engineering_itag_ksa.doctype.engineering_item_request.engineering_item_request.get_item_spec_attribute_values",
				params: { parent: row.item_attribute || "" },
			};
		});
	},
	item_group(frm) {
		if (!frm.doc.item_component) return;
		if (!frm.doc.item_group) return frm.set_value("item_component", null);
		frappe.db.get_value("Item Component", frm.doc.item_component, "item_group").then(({ message }) => {
			if (!message || message.item_group !== frm.doc.item_group) frm.set_value("item_component", null);
		});
	},
	// Create > Engineering Drawing button removed (Owner, 2026-11-09): link an existing drawing via the Engineering Drawing field instead.
});

frappe.ui.form.on("Item Request Attribute", {
	item_attribute(frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, "attribute_value", null);
	},
});
