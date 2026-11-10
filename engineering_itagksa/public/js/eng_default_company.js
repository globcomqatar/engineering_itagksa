// Default Company from Engineering Settings on new Engineering documents.
["Engineering Release", "Engineering Change Order", "Engineering Approval Matrix"].forEach((dt) => {
	frappe.ui.form.on(dt, {
		onload(frm) {
			if (!frm.is_new() || frm.doc.company) return;
			frappe.db.get_single_value("Engineering Settings", "default_company").then((company) => {
				if (company && frm.is_new() && !frm.doc.company) frm.set_value("company", company);
			});
		},
	});
});
