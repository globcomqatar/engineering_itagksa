"""Server-side permission, attachment, link, and import guards."""

from __future__ import annotations

import frappe
from frappe import _

from engineering_itagksa.engineering_itag_ksa.constants import (
	CANCELLABLE,
	ENGINEERING_MANAGER,
	ENGINEERING_MANAGER_MASTER,
	ENGINEERING_USER,
)


def roles_of(user: str | None = None) -> set[str]:
	return set(frappe.get_roles(user or frappe.session.user))


def require_role(role: str, message: str | None = None) -> None:
	if role not in roles_of():
		frappe.throw(message or _("This action requires the {0} role.").format(role), frappe.PermissionError)


def has_permission(doc, ptype: str, user: str, debug: bool = False):
	"""Deny only. DocPerm still has to grant the action."""
	if not doc or not getattr(doc, "doctype", None):
		return None
	roles = roles_of(user)
	if ptype == "cancel" and doc.doctype in CANCELLABLE and ENGINEERING_MANAGER_MASTER not in roles:
		return False
	if ptype == "submit" and doc.doctype in {"Engineering Drawing", "Material Specification"}:
		if "Engineering Manager" not in roles or getattr(doc, "owner", None) == user:
			return False
	if ptype == "submit" and doc.doctype == "Engineering Item Request" and ENGINEERING_MANAGER not in roles:
		return False
	if ptype == "submit" and doc.doctype == "Engineering Release" and ENGINEERING_MANAGER_MASTER not in roles:
		return False
	if (
		ptype == "import"
		and doc.doctype == "Engineering Item Request"
		and not roles.intersection({ENGINEERING_USER, ENGINEERING_MANAGER})
	):
		return False
	return None


def attachments(doctype: str, name: str) -> list[dict]:
	if not name:
		return []
	return frappe.get_all(
		"File",
		filters={"attached_to_doctype": doctype, "attached_to_name": name},
		fields=["name", "is_private"],
		ignore_permissions=True,
	)


def require_private_files(doctype: str, name: str, *, required: bool) -> None:
	rows = attachments(doctype, name)
	if required and not rows:
		frappe.throw(_("Attach a file before submission."))
	if any(not row.is_private for row in rows):
		frappe.throw(_("Attachments must use a private Frappe file."))


def assert_link(doctype: str, name: str | None, *, require_submitted: bool = False) -> None:
	if not name:
		return
	if not frappe.db.exists(doctype, name):
		frappe.throw(_("{0} {1} was not found.").format(doctype, name), frappe.DoesNotExistError)
	try:
		allowed = frappe.has_permission(doctype, "read", doc=name)
	except frappe.PermissionError:
		allowed = False
	if not allowed:
		frappe.throw(
			_("You cannot access {0} {1}.").format(doctype, name),
			frappe.PermissionError,
		)
	docstatus = int(frappe.db.get_value(doctype, name, "docstatus") or 0)
	if docstatus == 2:
		frappe.throw(_("{0} {1} is cancelled and cannot be used.").format(doctype, name))
	if require_submitted and docstatus != 1:
		frappe.throw(_("{0} {1} must be submitted.").format(doctype, name))


def guard_data_import(doc) -> None:
	"""Standard Data Import may insert a new Engineering Item Request draft and nothing else."""
	if not frappe.flags.in_import:
		return
	if not doc.is_new():
		frappe.throw(_("Data Import cannot update an existing Engineering Item Request."))
	if int(doc.docstatus or 0) != 0:
		frappe.throw(_("Data Import cannot set Document Status or submit an Engineering Item Request."))
	if doc.get("created_item"):
		frappe.throw(_("Data Import cannot set Created Item."))
	if doc.get("amended_from"):
		frappe.throw(_("Data Import cannot create or spoof an amendment."))
	for field in doc.meta.get_table_fields():
		if doc.get(field.fieldname):
			frappe.throw(_("Data Import cannot add child rows to an Engineering Item Request."))


def remember_cancellation(doc) -> None:
	require_role(ENGINEERING_MANAGER_MASTER, _("Only Engineering Manager Master can cancel."))
	reason = (doc.get("cancellation_reason") or "").strip()
	if not reason:
		frappe.throw(_("Enter a cancellation reason before cancelling."))
	doc.cancellation_reason = reason
	doc.add_comment("Comment", _("Cancellation reason: {0}").format(reason))


@frappe.whitelist()
def set_cancellation_reason(doctype: str, name: str, cancellation_reason: str):
	if doctype not in CANCELLABLE:
		frappe.throw(_("Cancellation reason is not used on {0}.").format(doctype))
	require_role(
		ENGINEERING_MANAGER_MASTER, _("Only Engineering Manager Master can record a cancellation reason.")
	)
	reason = (cancellation_reason or "").strip()
	if not reason:
		frappe.throw(_("Enter a cancellation reason."))
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("read")
	if doc.docstatus != 1:
		frappe.throw(_("Only a submitted document can be cancelled."))
	doc.db_set("cancellation_reason", reason, update_modified=False)
	return reason
