// Work Order -> Engineering tab: Frappe hides empty read-only fields, which collapsed the
// Engineering Change section until an ECR / ECO is issued. Keep ECR / ECO always visible (read-only).
const ENG_WO_CHANGE_FIELDS = ["eng_ecr", "eng_eco"];

frappe.ui.form.on("Work Order", {
	onload(frm) {
		ENG_WO_CHANGE_FIELDS.forEach((f) => {
			const field = frm.get_field(f);
			if (field) field.df.get_status = () => "Read";
		});
	},
	refresh(frm) {
		ENG_WO_CHANGE_FIELDS.forEach((f) => {
			const field = frm.get_field(f);
			if (!field) return;
			field.df.get_status = () => "Read";
			frm.refresh_field(f);
			if (!frm.doc[f] && field.$wrapper) {
				field.$wrapper.find(".control-value").html(`<span class="text-muted">${__("Not issued")}</span>`);
			}
		});
	},
});
