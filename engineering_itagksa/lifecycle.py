"""Shared server-side lifecycle helpers: plain Status field rules, revision rules, one-active supersede.

No Workflow is used: documents move with standard ERPNext Save / Submit / Cancel from Desk.
"""

import re

import frappe
from frappe import _
from frappe.utils import get_datetime, nowdate

from engineering_itagksa.constants import CANCELLED, DRAFT

def validate_status(doc, draft_states, submitted_states, submit_state, field="workflow_state", keep_on_submit=()):
	"""Plain Status (Select) field, no Workflow.

	* Save (draft): status must be a pre-submit value (blank -> Draft).
	* Submit (standard ERPNext Submit): status becomes ``submit_state`` (or stays, if in ``keep_on_submit``).
	* Update After Submit: status must be a post-submit value.
	Cancel sets "Cancelled" (see ``set_cancelled``).
	"""
	val = doc.get(field) or None
	action = getattr(doc, "_action", None)
	if action == "submit":
		if val not in keep_on_submit:
			doc.set(field, submit_state)
		return
	if doc.docstatus == 0:
		if not val:
			doc.set(field, DRAFT)
		elif val not in draft_states:
			frappe.throw(
				_("{0} cannot be {1} on a draft. Use one of: {2}; Submit sets {3}.").format(
					doc.meta.get_label(field), frappe.bold(val), ", ".join(draft_states), submit_state
				)
			)
	elif doc.docstatus == 1 and val not in submitted_states:
		frappe.throw(
			_("{0} of a submitted document must be one of: {1}.").format(
				doc.meta.get_label(field), ", ".join(submitted_states)
			)
		)


def set_cancelled(doc, field="workflow_state"):
	"""on_cancel: standard ERPNext Cancel marks the status Cancelled."""
	doc.db_set(field, CANCELLED, update_modified=False)


REVISION_RE = re.compile(r"^[A-Z0-9][A-Z0-9.]{0,9}$")


def get_transition(doc, field="workflow_state"):
	"""Return (old_state, new_state) for this save. New docs start from Draft."""
	before = doc.get_doc_before_save() if not doc.is_new() else None
	old = before.get(field) if before else None
	new = doc.get(field) or DRAFT
	return (old or DRAFT), new


def entering(doc, state, field="workflow_state"):
	old, new = get_transition(doc, field)
	return new == state and old != state


def normalize_revision(doc, fieldname):
	val = (doc.get(fieldname) or "").strip().upper()
	if not REVISION_RE.match(val):
		frappe.throw(
			_("{0} must be 1-10 characters: letters A-Z, digits and dots, starting with a letter or digit.").format(
				doc.meta.get_label(fieldname)
			)
		)
	if doc.is_new():
		doc.set(fieldname, val)


def validate_amendment_keeps_revision(doc, item_field, rev_field):
	"""A2: Frappe Amend is only allowed to correct a cancelled doc at the SAME revision."""
	if not doc.get("amended_from"):
		return
	src = frappe.db.get_value(doc.doctype, doc.amended_from, [item_field, rev_field], as_dict=True)
	if src and (src.get(item_field) != doc.get(item_field) or (src.get(rev_field) or "").upper() != (doc.get(rev_field) or "").upper()):
		frappe.throw(
			_("Amend may only correct the same item and revision. Create a new document for a new revision.")
		)


def get_active(doctype, item_field, item, active_states, state_field="workflow_state", exclude=None, docstatus=1):
	filters = {item_field: item, state_field: ["in", list(active_states)]}
	if docstatus is not None:
		filters["docstatus"] = docstatus
	if exclude:
		filters["name"] = ["!=", exclude]
	return frappe.get_all(doctype, filters=filters, fields=["name", "creation"], order_by="creation asc")


def guard_not_older_than_active(doc, actives):
	"""Refuse activating an older revision over a newer active one."""
	for a in actives:
		if a.creation and doc.creation and get_datetime(a.creation) > get_datetime(doc.creation):
			frappe.throw(
				_("{0} {1} is active and newer than this document. An older revision cannot supersede it.").format(
					doc.doctype, a.name
				)
			)


def supersede(doc, actives, new_state, state_field="workflow_state", link_field=None, date_field=None):
	"""Mark prior active docs superseded IN THE SAME DB TRANSACTION as the caller (db_set, no commit)."""
	for a in actives:
		values = {state_field: new_state}
		if link_field:
			values[link_field] = doc.name
		if date_field:
			values[date_field] = nowdate()
		frappe.db.set_value(doc.doctype, a.name, values, update_modified=True)
		frappe.get_doc(doc.doctype, a.name).add_comment(
			"Info", _("Superseded by {0} {1}").format(doc.doctype, doc.name)
		)
