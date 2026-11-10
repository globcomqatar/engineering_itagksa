"""Engineering Approval Matrix resolver (B1). Resolver ONLY: it never holds or sets status.

It finds the matching rule for a context, stamps the rule name + requirements for audit, and can
BLOCK an approval (ECO Submit / Engineering Release set to Approved) when the acting user lacks a mandatory
required role. No Workflow is involved.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

SCOPE_SELECTS = ("company", "item_category", "safety_classification", "change_risk")


def _yes_no(val):
	return "Yes" if val else "No"


def _item_group_matches(rule_group, item_group):
	if not rule_group:
		return True
	if not item_group:
		return False
	if rule_group == item_group:
		return True
	r = frappe.db.get_value("Item Group", rule_group, ["lft", "rgt"], as_dict=True)
	i = frappe.db.get_value("Item Group", item_group, ["lft", "rgt"], as_dict=True)
	return bool(r and i and r.lft <= i.lft and i.rgt <= r.rgt)


def resolve(doctype, context):
	"""Return the matched Engineering Approval Matrix doc (lowest priority wins) or None."""
	on_date = getdate(context.get("date") or nowdate())
	rules = frappe.get_all(
		"Engineering Approval Matrix",
		filters={"is_active": 1},
		fields=["*"],
		order_by="priority asc, rule_name asc",
	)
	for r in rules:
		if r.applies_to and r.applies_to != doctype:
			continue
		if r.effective_from and getdate(r.effective_from) > on_date:
			continue
		if r.effective_to and getdate(r.effective_to) < on_date:
			continue
		if any(r.get(f) and r.get(f) != context.get(f) for f in SCOPE_SELECTS):
			continue
		if not _item_group_matches(r.product_family, context.get("item_group")):
			continue
		if r.is_customer_specific and r.is_customer_specific != _yes_no(context.get("is_customer_specific")):
			continue
		if r.is_regulatory and r.is_regulatory != _yes_no(context.get("is_regulatory")):
			continue
		if flt(r.cost_impact_threshold) > 0 and flt(context.get("cost_impact")) < flt(r.cost_impact_threshold):
			continue
		return frappe.get_doc("Engineering Approval Matrix", r.name)
	return None


def describe(rule):
	if not rule:
		return _("No matching Approval Matrix rule; standard role permissions apply.")
	lines = []
	for d in sorted(rule.required_disciplines, key=lambda x: x.sequence or 0):
		lines.append(f"{d.sequence or '-'}. {d.discipline}: {d.required_role}{'' if d.is_mandatory else ' (optional)'}")
	if rule.requires_cost_review:
		lines.append(_("Cost review required"))
	if rule.requires_customer_review:
		lines.append(_("Customer review required"))
	return "\n".join(lines) or _("Rule {0} has no disciplines").format(rule.name)


def apply(doc, context, enforce=False):
	"""Stamp matched rule on doc; when enforce=True block if the acting user lacks a mandatory role."""
	rule = resolve(doc.doctype, context)
	doc.approval_rule = rule.name if rule else None
	doc.approval_requirements = describe(rule)
	if not (enforce and rule):
		return rule
	roles = set(frappe.get_roles())
	missing = [d.required_role for d in rule.required_disciplines if d.is_mandatory and d.required_role not in roles]
	if missing:
		frappe.throw(
			_("Approval Matrix rule {0} requires role(s) {1} for this approval.").format(
				frappe.bold(rule.name), ", ".join(sorted(set(missing)))
			),
			title=_("Approval Matrix"),
		)
	return rule


def item_context(item):
	if not item:
		return {}
	vals = frappe.db.get_value("Item", item, ["item_group", "eng_item_category"], as_dict=True) or {}
	return {"item_group": vals.get("item_group"), "item_category": vals.get("eng_item_category")}
