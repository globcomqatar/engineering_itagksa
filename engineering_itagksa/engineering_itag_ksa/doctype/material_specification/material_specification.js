// Material Specification (v15.3.0): not submittable; Status moves with the "Engineering ITAG KSA Material Specification"
// Workflow buttons. No Item Code; name MSBV-NNNNN-<revision>; Revision is set by the server.
frappe.ui.form.on("Material Specification", {
	refresh(frm) {
		// Create Revision: Approved, not superseded specifications only. The server re-checks status and blocks a
		// second open (Draft / Under Review) revision of the same specification.
		if (frm.is_new() || frm.doc.workflow_state !== "Approved" || frm.doc.superseded_by) return;
		if (!frappe.model.can_create("Material Specification")) return;
		frm.add_custom_button(__("Create Revision"), () => {
			frappe.call({
				method: "engineering_itagksa.engineering_itag_ksa.doctype.material_specification.material_specification.create_revision",
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
	},
});
