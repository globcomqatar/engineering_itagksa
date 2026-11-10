// Master Engineering Release (v15.2.1, Desk Workflow): BOM Creator-complete finished goods only; manufacturing BOM tree pull.
const MER_METHOD = "engineering_itagksa.engineering_itag_ksa.doctype.master_engineering_release.master_engineering_release";

// v15.3.5: Frappe grids start total_colsize at 1 (row index) and refuse any field that would
// push the total past 11 (grid.js setup_visible_columns). That leaves 10 units for data columns
// (the last 1/12 is the edit-row button). All 10 Item columns are therefore columns=1 so none
// are dropped. Engineering Release is given the spare visual width in CSS; Item Name stays compact.
function ensure_mer_items_grid_style() {
	if (document.getElementById("engineering-itagksa-mer-items-grid-style")) return;
	const style = document.createElement("style");
	style.id = "engineering-itagksa-mer-items-grid-style";
	style.textContent = `
		[data-fieldname="items"] .form-grid .grid-static-col[data-fieldname="engineering_release"] {
			flex: 1 1 0 !important;
			width: 14% !important;
			max-width: 16% !important;
		}
		[data-fieldname="items"] .form-grid .grid-static-col[data-fieldname="item_name"],
		[data-fieldname="items"] .form-grid .grid-static-col[data-fieldname="level"],
		[data-fieldname="items"] .form-grid .grid-static-col[data-fieldname="row_status"] {
			flex: 0 1 0 !important;
			width: 6.5% !important;
			max-width: 7.5% !important;
		}
	`;
	document.head.appendChild(style);
}

frappe.ui.form.on("Master Engineering Release", {
	setup(frm) {
		ensure_mer_items_grid_style();
		frm.set_query("finished_good_item", () => ({
			query: `${MER_METHOD}.finished_good_query`,
			filters: { company: frm.doc.company },
		}));
		frm.set_query("bom_creator", () => ({
			filters: { item_code: frm.doc.finished_good_item, company: frm.doc.company, docstatus: 1, status: "Completed" },
		}));
		frm.set_query("top_bom", () => ({
			filters: { item: frm.doc.finished_good_item, bom_creator: frm.doc.bom_creator, docstatus: 1 },
		}));
		frm.set_query("engineering_release", "items", (doc, cdt, cdn) => ({
			filters: { item: locals[cdt][cdn].item, release_status: ["not in", ["Superseded", "Obsolete"]] },
		}));
	},

	finished_good_item(frm) {
		frm.set_value({ bom_creator: null, top_bom: null });
		if (!frm.doc.finished_good_item) return;
		frappe.db.get_list("BOM Creator", {
			filters: { item_code: frm.doc.finished_good_item, company: frm.doc.company, docstatus: 1, status: "Completed" },
			fields: ["name"], order_by: "modified desc", limit: 1,
		}).then((r) => r.length && frm.set_value("bom_creator", r[0].name));
	},

	bom_creator(frm) {
		if (!frm.doc.bom_creator) return;
		frappe.db.get_list("BOM", {
			filters: { item: frm.doc.finished_good_item, bom_creator: frm.doc.bom_creator, docstatus: 1, bom_creator_item: ["is", "not set"] },
			fields: ["name"], order_by: "creation desc", limit: 1,
		}).then((r) => r.length && frm.set_value("top_bom", r[0].name));
	},

	refresh(frm) {
		const st = frm.doc.release_status || "Draft";
		if (st === "Draft") {
			frm.add_custom_button(__("Get Items from BOM"), () => {
				if (!frm.doc.top_bom) return frappe.msgprint(__("Set Finished Good and Top BOM first."));
				frm.call({ doc: frm.doc, method: "get_items_from_bom", freeze: true }).then(() => {
					frm.dirty();
					frm.refresh_field("items");
				});
			});
			if (!frm.is_new() && (frm.doc.items || []).some((r) => !r.engineering_release)) {
				frm.add_custom_button(__("Create Draft Releases"), () => {
					frm.call({ doc: frm.doc, method: "create_draft_releases", freeze: true }).then((r) => {
						const m = r.message || {};
						frappe.show_alert({ message: __("Created {0}; skipped {1} (no Product Revision)",
							[(m.created || []).length, (m.skipped || []).length]), indicator: "green" });
						frm.reload_doc();
					});
				});
			}
		}
		// v15.2.1: Approve / Return to Draft / Release for Production come from the Desk Workflow
		// "Engineering ITAG KSA Master Engineering Release" (Actions menu, like Engineering Release); guards run server-side.
	},
});
