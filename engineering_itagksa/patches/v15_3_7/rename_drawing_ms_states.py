"""v15.3.7 (Phase 1): Engineering Drawing and Material Specification states Draft -> Prepared and
Under Review -> Reviewed. Data only, idempotent. The Workflows are rewritten by after_migrate (install.setup)."""

import frappe

RENAMES = (("Draft", "Prepared"), ("Under Review", "Reviewed"))


def execute():
	for doctype in ("Engineering Drawing", "Material Specification"):
		if not frappe.db.table_exists(doctype):
			continue
		for old, new in RENAMES:
			frappe.db.sql(
				f"update `tab{doctype}` set workflow_state=%s where workflow_state=%s", (new, old)
			)
