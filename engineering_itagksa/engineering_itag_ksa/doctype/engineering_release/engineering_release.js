// v15.3.4 (Owner 2026-11-10): single parent Material Specification link (Approved only) in Baseline
// after Drawing Revision, replacing the Specifications table on the form (the child DocType is kept).
// Picking an Item fills Product Revision (MER resolve_product_revision) and from that PR the Drawing,
// BOM, Routing, Inspection Plan and Material Specification. Changing the Product Revision refreshes
// those fields from the new PR (not fetch_if_empty).
const ER_METHOD = "engineering_itagksa.engineering_itag_ksa.doctype.engineering_release.engineering_release";
const ER_FROM_ITEM = ["product_revision", "drawing_revision", "bom", "routing", "inspection_plan", "material_specification"];
const ER_FROM_PR = ["drawing_revision", "bom", "routing", "inspection_plan", "material_specification"];
const ER_LOCKED = ["Released for Production", "Superseded", "Obsolete"];

function er_locked(frm) {
	return ER_LOCKED.includes(frm.doc.release_status);
}

frappe.ui.form.on("Engineering Release", {
	setup(frm) {
		frm.set_query("product_revision", () => ({ filters: { item: frm.doc.item, docstatus: 1 } }));
		frm.set_query("bom", () => ({ filters: { item: frm.doc.item, docstatus: 1, is_active: 1 } }));
		frm.set_query("material_specification", () => ({ filters: { workflow_state: "Approved" } }));
	},
	item(frm) {
		if (er_locked(frm)) return;
		const clear = () => frm.set_value(Object.fromEntries(ER_FROM_ITEM.map((f) => [f, null])));
		if (!frm.doc.item) {
			clear();
			return;
		}
		const item = frm.doc.item;
		frappe.call({ method: `${ER_METHOD}.get_item_release_defaults`, args: { item } }).then((r) => {
			if (frm.doc.item !== item) return;
			const d = r.message || {};
			frm.set_value(Object.fromEntries(ER_FROM_ITEM.map((f) => [f, d[f] || null])));
		});
	},
	product_revision(frm) {
		if (er_locked(frm)) return;
		if (!frm.doc.product_revision) {
			frm.set_value(Object.fromEntries(ER_FROM_PR.map((f) => [f, null])));
			return;
		}
		const pr = frm.doc.product_revision;
		frappe.call({
			method: `${ER_METHOD}.get_product_revision_release_defaults`,
			args: { product_revision: pr },
		}).then((r) => {
			if (frm.doc.product_revision !== pr) return;
			const d = r.message || {};
			frm.set_value(Object.fromEntries(ER_FROM_PR.map((f) => [f, d[f] || null])));
		});
	},
});
