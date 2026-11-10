// B6: Engineering Release button only after this Product Revision is submitted (and active).
// Draft v0.1 (Owner approved 2026-11-10): Drawing Revision lists Approved drawings (Drawing has no Item Code and no
// Released state since v15.3.0); picking an Item fills Drawing Revision, Material Specification and BOM from the
// Engineering Item Request that created the Item and the Item's BOM.
// v15.3.5: Revision Number is assigned by the server (0, 1, 2 ... on the Item's number base, locked after save);
// the form shows a preview when the Item is picked. The name is {component}-5NNNN-{revision} (no PR- prefix). Status moves with the "Engineering ITAG KSA Product Revision" Workflow (copy of Drawing's).
const PR_METHOD = "engineering_itagksa.engineering_itag_ksa.doctype.product_revision.product_revision";

frappe.ui.form.on("Product Revision", {
	setup(frm) {
		frm.set_query("drawing_revision", () => ({ filters: { workflow_state: "Approved" } }));
		frm.set_query("bom_revision_reference", () => ({ filters: { item: frm.doc.item } }));
		frm.set_query("material_specification", () => ({ filters: { workflow_state: "Approved" } }));
	},
	refresh(frm) {
		// v15.3.3 Revise (as Drawing's Create Revision): active submitted revision (Approved / Release Ready /
		// Released), not superseded, user may create Product Revisions. The server re-checks status and blocks a
		// second open (Draft / Under Review) revision of the same Product Revision.
		const revisable = ["Approved", "Release Ready", "Released"];
		if (frm.doc.docstatus === 1 && revisable.includes(frm.doc.workflow_state) && !frm.doc.superseding_revision
			&& frappe.model.can_create("Product Revision")) {
			frm.add_custom_button(__("Revise"), () => {
				frappe.call({
					method: `${PR_METHOD}.create_revision`,
					args: { source_name: frm.doc.name },
					freeze: true,
					callback(r) {
						if (!r.message) return;
						const doc = frappe.model.sync(r.message)[0];
						frappe.set_route("Form", doc.doctype, doc.name);
						frappe.show_alert({ message: __("New revision draft of {0}.", [frm.doc.name]), indicator: "blue" });
					},
				});
			});
		}
		const inactive = ["Superseded", "Obsolete", "Cancelled", "Rejected"];
		if (frm.doc.docstatus === 1 && !inactive.includes(frm.doc.workflow_state)) {
			frm.add_custom_button(__("Engineering Release"), () =>
				frappe.model.open_mapped_doc({ method: `${PR_METHOD}.make_engineering_release`, frm }),
				__("Create"));
		}
	},
	item(frm) {
		if (frm.doc.docstatus !== 0) return;
		const fields = ["drawing_revision", "material_specification", "bom_revision_reference"];
		const clear = () => frm.set_value(Object.fromEntries(fields.map((f) => [f, null])));
		if (!frm.doc.item) {
			clear();
			return;
		}
		const item = frm.doc.item;
		if (frm.is_new()) {
			frappe.call({ method: `${PR_METHOD}.get_next_revision_for_item`, args: { item } }).then((r) => {
				if (frm.doc.item === item && r.message) frm.set_value("revision_number", r.message);
			});
		}
		frappe.call({ method: `${PR_METHOD}.get_item_engineering_defaults`, args: { item } }).then((r) => {
			if (frm.doc.item !== item) return; // Item changed again meanwhile
			const d = r.message || {};
			frm.set_value(Object.fromEntries(fields.map((f) => [f, d[f] || null])));
		});
	},
});
