"""B10 least privilege: Customer Controlled drawings are visible only to privileged roles.
Nasser must review DocPerm before any production enable."""

import frappe

PRIVILEGED = {"Engineering Manager", "System Manager"}
CUSTOMER_CONTROLLED = "Customer Controlled"


def _privileged(user):
	user = user or frappe.session.user
	return user == "Administrator" or bool(PRIVILEGED & set(frappe.get_roles(user)))


def drawing_query_conditions(user=None, doctype=None):
	if _privileged(user):
		return ""
	return "(ifnull(`tabEngineering Drawing`.`security_classification`, '') != 'Customer Controlled')"


def drawing_has_permission(doc, ptype=None, user=None, debug=False):
	if doc.get("security_classification") == CUSTOMER_CONTROLLED and not _privileged(user):
		return False
	return None
