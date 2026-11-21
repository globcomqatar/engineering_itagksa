"""v15.3.8 (Phase 2): bulk Engineering Item Request upload through the standard Data Import.

Owner decision: the approved roles upload, managers review and submit in bulk from the list view. Records are always
imported as drafts. This is the only custom code for the feature:
- Data Import for Engineering Item Request: only the approved roles may use it; "Submit After Import" is refused.
- Engineering Item Request during an import: a row may not be created submitted (Document Status column) and an
  import may not submit or cancel an Item Request.
Attribute values are checked by the Item Request's own validation, as for a record saved on Desk.
"""

import frappe
from frappe import _

from engineering_itagksa import constants as C

DOCTYPE = "Engineering Item Request"
IMPORT_ROLES = (C.ROLE_ENG_MANAGER, C.ROLE_ENG_USER, "System Manager")


def _check_import_role():
	if frappe.session.user == "Administrator":
		return
	if not set(IMPORT_ROLES) & set(frappe.get_roles()):
		frappe.throw(
			_("Only {0} can import Engineering Item Requests.").format(", ".join(IMPORT_ROLES)),
			frappe.PermissionError,
		)


def validate_data_import(doc, method=None):
	"""Data Import validate."""
	if doc.reference_doctype != DOCTYPE:
		return
	_check_import_role()
	if doc.submit_after_import:
		frappe.throw(
			_("Engineering Item Requests are imported as drafts. Untick Submit After Import; a manager submits them from the list."),
			title=_("Drafts only"),
		)


def before_insert(doc, method=None):
	"""Engineering Item Request before_insert."""
	if not frappe.flags.in_import:
		return
	_check_import_role()
	if doc.docstatus != 0:
		frappe.throw(_("Engineering Item Requests are imported as drafts. Remove the Document Status value."), title=_("Drafts only"))


def block_status_change_on_import(doc, method=None):
	"""Engineering Item Request before_submit / before_cancel."""
	if frappe.flags.in_import:
		frappe.throw(_("Engineering Item Requests are imported as drafts. A manager submits them from the list."), title=_("Drafts only"))
