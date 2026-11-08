frappe.provide("engineering_itagksa");

engineering_itagksa.ask_reason = function (title) {
	return new Promise((resolve, reject) => {
		const dialog = new frappe.ui.Dialog({
			title,
			fields: [
				{
					fieldname: "reason",
					fieldtype: "Small Text",
					label: __("Reason"),
					reqd: 1,
				},
			],
			primary_action(values) {
				dialog._confirmed = true;
				dialog.hide();
				resolve((values.reason || "").trim());
			},
		});
		dialog.onhide = () => {
			if (!dialog._confirmed) {
				reject();
			}
		};
		dialog.show();
	}).catch(() => {
		frappe.validated = false;
	});
};

engineering_itagksa.prompt_cancellation = function (frm) {
	frappe.validated = false;
	return engineering_itagksa.ask_reason(__("Cancellation Reason")).then((reason) => {
		if (!reason) {
			frappe.validated = false;
			return;
		}
		return frappe
			.call({
				method: "engineering_itagksa.engineering_itag_ksa.controls.set_cancellation_reason",
				args: {
					doctype: frm.doctype,
					name: frm.doc.name,
					cancellation_reason: reason,
				},
			})
			.then(() => {
				frappe.validated = true;
			});
	});
};

for (const doctype of [
	"Engineering Drawing",
	"Material Specification",
	"Engineering Item Request",
	"Engineering Release",
]) {
	frappe.ui.form.on(doctype, {
		before_cancel(frm) {
			return engineering_itagksa.prompt_cancellation(frm);
		},
	});
}

frappe.ui.form.on("Engineering Release", {
	before_workflow_action(frm) {
		if (frm.selected_workflow_action !== "Return to Draft") {
			return;
		}
		return engineering_itagksa.ask_reason(__("Return Reason")).then((reason) => {
			if (!reason) {
				frappe.validated = false;
				return;
			}
			return frappe
				.call({
					method:
						"engineering_itagksa.engineering_itag_ksa.doctype.engineering_release.engineering_release.set_return_reason",
					args: { name: frm.doc.name, return_reason: reason },
				})
				.then(() => frm.reload_doc());
		});
	},
});
