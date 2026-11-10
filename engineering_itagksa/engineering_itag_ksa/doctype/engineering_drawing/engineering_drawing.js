// v15.3.0: Drawing is not submittable; Status moves with the "Engineering ITAG KSA Engineering Drawing" Workflow buttons.
// No Item Code on the Drawing, so the Create > Product Revision / BOM buttons are gone until those DocTypes are
// revised for the new Drawing model (separate pass). A4: attestation is server-stamped.
frappe.ui.form.on("Engineering Drawing", {
	setup(frm) {
		frm.set_query("item_component", () => (frm.doc.item_group ? { filters: { item_group: frm.doc.item_group } } : {}));
		frm.set_query("revises", () => ({
			filters: { item_component: frm.doc.item_component || "", name: ["!=", frm.doc.name || ""] },
		}));
	},
	refresh(frm) {
		// Create Revision: Approved, not superseded drawings only. The server re-checks status and blocks a second
		// open (Draft / Under Review) revision of the same drawing.
		if (frm.is_new() || frm.doc.workflow_state !== "Approved" || frm.doc.superseded_by) return;
		if (!frappe.model.can_create("Engineering Drawing")) return;
		frm.add_custom_button(__("Create Revision"), () => {
			frappe.call({
				method: "engineering_itagksa.engineering_itag_ksa.doctype.engineering_drawing.engineering_drawing.create_revision",
				args: { source_name: frm.doc.name },
				freeze: true,
				callback(r) {
					if (!r.message) return;
					const doc = frappe.model.sync(r.message)[0];
					frappe.set_route("Form", doc.doctype, doc.name);
					frappe.show_alert({
						message: __("New revision draft of {0}. Check the revision and attach the new drawing file.", [frm.doc.name]),
						indicator: "blue",
					});
				},
			});
		});
	},
	item_group(frm) {
		if (!frm.doc.item_component || !frm.doc.item_group) return;
		frappe.db.get_value("Item Component", frm.doc.item_component, "item_group").then(({ message }) => {
			if (message && message.item_group && message.item_group !== frm.doc.item_group) frm.set_value("item_component", null);
		});
	},
	drawing_file(frm) {
		// server computes SHA-256 on save; clear the stale value so the form never shows a wrong hash
		frm.set_value("file_checksum_sha256", "");
	},
});
