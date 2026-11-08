"""Roles, workflow, and read access required by the confirmed Engineering ITAG KSA process."""

from __future__ import annotations

import frappe
from frappe.permissions import add_permission, update_permission_property

from engineering_itagksa.engineering_itag_ksa.constants import (
	ENGINEERING_MANAGER,
	ENGINEERING_MANAGER_MASTER,
	ENGINEERING_USER,
	ROLES,
)

READ_DOCTYPES = (
	"Item",
	"Item Group",
	"UOM",
	"BOM",
	"Routing",
	"Quality Inspection Template",
)
WORKFLOW_NAME = "Engineering Release"
WORKSPACE_NAME = "Engineering ITAG KSA"


def after_install():
	ensure_process_setup()


def after_migrate():
	ensure_process_setup()


def ensure_process_setup():
	ensure_roles()
	ensure_workflow_metadata()
	ensure_workflow()
	ensure_read_access()
	ensure_data_import_access()
	restrict_workspace()
	frappe.clear_cache()


def ensure_roles():
	for role in ROLES:
		if frappe.db.exists("Role", role):
			continue
		frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(
			ignore_permissions=True
		)


def ensure_workflow_metadata():
	for state, style in (
		("Draft", "Primary"),
		("Approved", "Warning"),
		("Released for Production", "Success"),
		("Cancelled", "Danger"),
	):
		if frappe.db.exists("Workflow State", state):
			continue
		frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": state, "style": style}).insert(
			ignore_permissions=True
		)
	for action in ("Approve", "Release for Production", "Return to Draft"):
		if frappe.db.exists("Workflow Action Master", action):
			continue
		frappe.get_doc({"doctype": "Workflow Action Master", "workflow_action_name": action}).insert(
			ignore_permissions=True
		)


def ensure_workflow():
	states = [
		{"state": "Draft", "doc_status": "0", "allow_edit": ENGINEERING_USER, "send_email": 0},
		{"state": "Approved", "doc_status": "0", "allow_edit": "", "send_email": 0},
		{"state": "Released for Production", "doc_status": "1", "allow_edit": "", "send_email": 0},
		{"state": "Cancelled", "doc_status": "2", "allow_edit": "", "send_email": 0},
	]
	transitions = [
		{
			"state": "Draft",
			"action": "Approve",
			"next_state": "Approved",
			"allowed": ENGINEERING_MANAGER,
			"allow_self_approval": 0,
			"send_email_to_creator": 0,
		},
		{
			"state": "Approved",
			"action": "Release for Production",
			"next_state": "Released for Production",
			"allowed": ENGINEERING_MANAGER_MASTER,
			"allow_self_approval": 0,
			"send_email_to_creator": 0,
		},
		{
			"state": "Approved",
			"action": "Return to Draft",
			"next_state": "Draft",
			"allowed": ENGINEERING_MANAGER_MASTER,
			"allow_self_approval": 1,
			"condition": "doc.return_reason",
			"send_email_to_creator": 0,
		},
	]
	if frappe.db.exists("Workflow", WORKFLOW_NAME):
		workflow = frappe.get_doc("Workflow", WORKFLOW_NAME)
	else:
		workflow = frappe.new_doc("Workflow")
		workflow.workflow_name = WORKFLOW_NAME
	workflow.document_type = "Engineering Release"
	workflow.is_active = 1
	workflow.override_status = 1
	workflow.send_email_alert = 0
	workflow.workflow_state_field = "workflow_state"
	workflow.set("states", [])
	workflow.set("transitions", [])
	for row in states:
		workflow.append("states", row)
	for row in transitions:
		workflow.append("transitions", row)
	workflow.save(ignore_permissions=True)


def ensure_read_access():
	"""Grant read on the ERPNext documents this process selects.

	Frappe's add_permission copies existing DocPerm rows into Custom DocPerm
	before adding a role, so standard permissions are kept. No create, write,
	submit, or cancel right is added on those DocTypes, and Item has no new fields.
	"""
	for doctype in READ_DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			frappe.throw(f"Required DocType {doctype} is not installed.")
		for role in ROLES:
			_ensure_permission(doctype, role, "read")


def ensure_data_import_access():
	for role in (ENGINEERING_USER, ENGINEERING_MANAGER):
		_ensure_permission("Data Import", role, "read")
		_ensure_permission("Data Import", role, "create")
		_ensure_permission("Data Import", role, "write")


def restrict_workspace():
	if not frappe.db.exists("Workspace", WORKSPACE_NAME):
		return
	workspace = frappe.get_doc("Workspace", WORKSPACE_NAME)
	current = {row.role for row in workspace.roles}
	changed = False
	for role in ROLES:
		if role not in current:
			workspace.append("roles", {"role": role})
			changed = True
	if changed:
		workspace.save(ignore_permissions=True)


def _ensure_permission(doctype: str, role: str, ptype: str):
	name = frappe.db.get_value(
		"Custom DocPerm",
		{"parent": doctype, "role": role, "permlevel": 0, "if_owner": 0},
		"name",
	)
	if not name:
		add_permission(doctype, role, permlevel=0, ptype=ptype)
		return
	if not frappe.db.get_value("Custom DocPerm", name, ptype):
		update_permission_property(doctype, role, 0, ptype, 1, validate=False)
