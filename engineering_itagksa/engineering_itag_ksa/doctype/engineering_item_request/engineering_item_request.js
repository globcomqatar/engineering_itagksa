// B6: create button only after submit AND Item created.
// Attribute Value: Data (ERPNext Item Variant Attribute pattern) + Autocomplete
// dropdown from Item Spec Attribute Value rows for the selected attribute.
// v15.3.1: Engineering Drawing / Material Specification optional links after Maintain Stock.
// v15.3.7: Attribute Value is an Autocomplete field (stored as the value string, never a Link to the child table
// Item Spec Attribute Value); picking an Item Component fills its attributes; Item Name / Description are built by
// the server on save (Component Name, attribute values, Special Details).
frappe.ui.form.on("Engineering Item Request", {
	setup(frm) {
		// Item Component dropdown only offers components of the selected Item Group.
		// v15.3.7: Item Group is optional on Item Component; components without one are offered for any group.
		frm.set_query("item_component", () => ({
			filters: [["Item Component", "item_group", "in", [frm.doc.item_group || "__none__", ""]]],
		}));
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
		// Values offered = that attribute's Item Spec Attribute Value rows (server re-checks on save).
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
			if (!message || (message.item_group && message.item_group !== frm.doc.item_group)) frm.set_value("item_component", null);
		});
	},
	item_component(frm) {
		fill_component_attributes(frm);
	},
	// Create > Engineering Drawing button removed (Owner, 2026-11-09): link an existing drawing via the Engineering Drawing field instead.
});

frappe.ui.form.on("Item Request Attribute", {
	item_attribute(frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, "attribute_value", null);
	},
});

// v15.3.7: replace the rows auto-filled from the previous component with the new component's attributes, in its
// order and with its Mandatory flags; keep values already entered for the same attribute and any rows added by hand.
function fill_component_attributes(frm) {
	const old_rows = frm.doc.item_request_attribute || [];
	const keep_value = {};
	old_rows.forEach((r) => {
		if (r.item_attribute && r.attribute_value) keep_value[r.item_attribute] = r.attribute_value;
	});
	const apply = (comp_rows) => {
		const comp_attrs = comp_rows.map((c) => c.attribute);
		const manual = old_rows.filter((r) => !r.from_component && !comp_attrs.includes(r.item_attribute));
		frm.clear_table("item_request_attribute");
		comp_rows.forEach((c) => {
			frm.add_child("item_request_attribute", {
				item_attribute: c.attribute,
				attribute_value: keep_value[c.attribute] || null,
				mandatory: c.mandatory ? 1 : 0,
				from_component: 1,
			});
		});
		manual.forEach((r) => {
			frm.add_child("item_request_attribute", {
				item_attribute: r.item_attribute,
				attribute_value: r.attribute_value,
				mandatory: 0,
				from_component: 0,
			});
		});
		frm.refresh_field("item_request_attribute");
	};
	if (!frm.doc.item_component) return apply([]);
	frappe.call({
		method: "engineering_itagksa.engineering_itag_ksa.doctype.item_component.item_component.get_component_attributes",
		args: { component: frm.doc.item_component },
		callback: (r) => apply(r.message || []),
	});
}
