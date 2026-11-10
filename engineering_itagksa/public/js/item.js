// Item -> Engineering tab: keep BOM / Design / Release (Related Documents) current on every refresh.
frappe.ui.form.on("Item", {
	setup(frm) {
		// Item Component dropdown only offers components of this Item's Item Group (same as Engineering Item Request).
		frm.set_query("eng_item_component", () => ({ filters: { item_group: frm.doc.item_group || "__none__" } }));
	},
	item_group(frm) {
		if (!frm.doc.eng_item_component) return;
		if (!frm.doc.item_group) return frm.set_value("eng_item_component", null);
		frappe.db.get_value("Item Component", frm.doc.eng_item_component, "item_group").then(({ message }) => {
			if (!message || message.item_group !== frm.doc.item_group) frm.set_value("eng_item_component", null);
		});
	},
	refresh(frm) {
		if (frm.is_new() || !frm.doc.name || !frm.fields_dict.eng_bom) return;
		frappe.call({
			method: "engineering_itagksa.item_links.get_item_engineering_links",
			args: { item: frm.doc.name },
			callback(r) {
				const links = r.message || {};
				["eng_bom", "eng_design", "eng_release"].forEach((f) => {
					const v = links[f] || null;
					if ((frm.doc[f] || null) !== v) {
						// Direct assignment: display-only refresh, does not mark the form dirty.
						frm.doc[f] = v;
						frm.refresh_field(f);
					}
				});
			},
		});
	},
});
