"""v15.3.7 (Phase 1): set the hidden Engineering Drawing "Sent for Review" flag used by the delete rule on drawings
that have already been sent for review: any state other than Prepared, a review stamp, or a Version that moved the
status to Reviewed / Under Review (a drawing returned to Prepared). Idempotent."""

import json

import frappe

SENT = ("Reviewed", "Under Review")


def execute():
	if not frappe.db.table_exists("Engineering Drawing"):
		return
	if "sent_for_review" not in frappe.db.get_table_columns("Engineering Drawing"):
		return
	frappe.db.sql(
		"""update `tabEngineering Drawing` set sent_for_review=1
		where ifnull(sent_for_review, 0)=0
		and (ifnull(workflow_state, '') not in ('', 'Prepared') or submitted_for_review_on is not null)"""
	)
	prepared = frappe.get_all("Engineering Drawing", filters={"sent_for_review": 0}, pluck="name")
	for name in prepared:
		for data in frappe.get_all("Version", filters={"ref_doctype": "Engineering Drawing", "docname": name}, pluck="data"):
			try:
				changed = (json.loads(data or "{}") or {}).get("changed") or []
			except ValueError:
				continue
			if any(len(row) > 2 and row[0] == "workflow_state" and row[2] in SENT for row in changed):
				frappe.db.set_value("Engineering Drawing", name, "sent_for_review", 1, update_modified=False)
				break
