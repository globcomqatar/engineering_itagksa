# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class ItemComponent(Document):
	def validate(self):
		self.part_code_prefix = (self.part_code_prefix or "").strip().upper()
		self.component_name = (self.component_name or "").strip()
		if self.part_code_prefix.endswith("-#####") or "#" in self.part_code_prefix or "-" in self.part_code_prefix:
			frappe.throw(_("Part Code Prefix must be the prefix only, e.g. 500 (not 500-#####)."))
		dup = frappe.db.get_value("Item Component", {"part_code_prefix": self.part_code_prefix, "name": ("!=", self.name)})
		if dup:
			frappe.throw(_("Part Code Prefix {0} is already used by {1}.").format(frappe.bold(self.part_code_prefix), dup))

	def on_update(self):
		ensure_item_naming_rule(self)

	def after_rename(self, old, new, merge=False):
		# part_code_prefix is the autoname field, so a prefix change is a rename.
		# Item links follow the rename; point the naming-rule condition at the new
		# name too, then retarget/recreate the rule for the new prefix.
		if merge:
			return
		frappe.db.sql(
			"""update `tabDocument Naming Rule Condition`
			set value=%s
			where parenttype='Document Naming Rule' and field=%s and `condition`='=' and value=%s""",
			(new, ITEM_NAMING_FIELD, old),
		)
		self.part_code_prefix = new
		ensure_item_naming_rule(self)


ITEM_NAMING_FIELD = "eng_item_component"
# Item codes from an Item Request are <Part Code Prefix>-NNNNNNN: seven digits, first number 1000501
# (1000501, 1000502, ... past 1000599 to 1000600). Digits are fixed at 7 (Engineering Settings
# item_naming_prefix_digits is kept in sync / pinned to 7).
ITEM_NAMING_DIGITS = 7
ITEM_NAMING_PRIORITY = 10
# Document Naming Rule uses (counter + 1) for the next name, so 1000500 -> first Item 1000501.
ITEM_NAMING_COUNTER_START = 1000500


def _naming_digits():
	"""Always 7 for component Item naming (Owner decision v15.3.5)."""
	return ITEM_NAMING_DIGITS


def _rules_for_component(component):
	"""Document Naming Rules on Item whose condition is eng_item_component = component."""
	parents = frappe.get_all(
		"Document Naming Rule Condition",
		filters={
			"parenttype": "Document Naming Rule",
			"field": ITEM_NAMING_FIELD,
			"condition": "=",
			"value": component,
		},
		pluck="parent",
	)
	if not parents:
		return []
	return frappe.get_all(
		"Document Naming Rule",
		filters={"name": ("in", parents), "document_type": "Item"},
		fields=["name", "prefix", "prefix_digits", "counter", "disabled"],
		order_by="creation desc",
	)


def _highest_existing_item_number(prefix):
	"""Highest 7-digit suffix already used by an Item named {prefix}NNNNNNN, or 0.

	5-digit legacy names such as 500-50001 are ignored so they cannot pull the
	new counter backwards or collide with 500-1000501.
	"""
	import re

	highest = 0
	pat = re.compile(rf"^{re.escape(prefix)}\d{{{ITEM_NAMING_DIGITS}}}$")
	for name in frappe.get_all("Item", filters={"name": ["like", f"{prefix}%"]}, pluck="name"):
		if pat.match(name):
			highest = max(highest, int(name[len(prefix):]))
	return highest


def _items_exist_for_prefix(prefix):
	"""Any Item whose name starts with this naming-rule prefix (legacy 5-digit or new 7-digit)."""
	return bool(frappe.db.exists("Item", {"name": ["like", f"{prefix}%"]}))


def _sync_rule_floor(rule):
	"""Pin prefix_digits to 7; raise the counter to at least 1000500 and above any existing
	7-digit Item of this prefix. Never lower a higher counter."""
	updates = {}
	if cint(rule.prefix_digits) != ITEM_NAMING_DIGITS:
		updates["prefix_digits"] = ITEM_NAMING_DIGITS
	floor = max(ITEM_NAMING_COUNTER_START, _highest_existing_item_number(rule.prefix or ""))
	if cint(rule.counter) < floor:
		updates["counter"] = floor
	if updates:
		frappe.db.set_value("Document Naming Rule", rule.name, updates)
		rule.update(updates)
	return rule


def ensure_item_naming_rule(component_doc):
	"""Create / sync the Item Document Naming Rule for an Item Component.

	Shape: Item, prefix "<part_code_prefix>-", 7 digits, priority 10,
	condition eng_item_component = <component name>, counter floor 1000500
	(first issued code is <prefix>-1000501, then -1000502, …, -1000600, …).

	Idempotent: an enabled matching rule is kept, its digits pinned to 7, and its
	counter raised to 1000500 (or the highest existing 7-digit Item of that
	prefix) only when below that floor (never lowered). Existing Item names are
	not renamed. Staging migrate calls ensure_all_item_naming_rules() so
	already-installed 5-digit / 50000 rules switch to the new shape.
	"""
	prefix_code = (component_doc.part_code_prefix or "").strip().upper()
	if not prefix_code:
		return
	prefix = f"{prefix_code}-"
	component = component_doc.name

	rules = _rules_for_component(component)
	enabled = [r for r in rules if not r.disabled]

	for r in enabled:
		if r.prefix == prefix:
			_sync_rule_floor(r)
			return

	if enabled:
		# Prefix changed. Retarget only a rule that has never issued an Item;
		# otherwise disable and recreate so already-issued names keep their prefix.
		r = enabled[0]
		if cint(r.counter) <= ITEM_NAMING_COUNTER_START and not _items_exist_for_prefix(r.prefix):
			frappe.db.set_value(
				"Document Naming Rule",
				r.name,
				{"prefix": prefix, "prefix_digits": _naming_digits(), "counter": ITEM_NAMING_COUNTER_START},
			)
			return
		for old in enabled:
			frappe.db.set_value("Document Naming Rule", old.name, "disabled", 1)
	else:
		# Re-enable a previously disabled rule with the same prefix instead of duplicating.
		for r in rules:
			if r.prefix == prefix:
				frappe.db.set_value("Document Naming Rule", r.name, "disabled", 0)
				r.disabled = 0
				_sync_rule_floor(r)
				return

	# Avoid two enabled Item rules issuing the same series (counters are per rule).
	clash = frappe.db.get_value(
		"Document Naming Rule", {"document_type": "Item", "prefix": prefix, "disabled": 0}
	)
	if clash:
		frappe.msgprint(
			_("Item naming rule {0} already uses prefix {1}; no new rule created for component {2}.").format(
				clash, frappe.bold(prefix), component
			),
			alert=True,
		)
		return

	rule = frappe.get_doc(
		{
			"doctype": "Document Naming Rule",
			"document_type": "Item",
			"prefix": prefix,
			"prefix_digits": _naming_digits(),
			"counter": ITEM_NAMING_COUNTER_START,
			"priority": ITEM_NAMING_PRIORITY,
			"conditions": [{"field": ITEM_NAMING_FIELD, "condition": "=", "value": component}],
		}
	)
	rule.insert(ignore_permissions=True)


def ensure_all_item_naming_rules():
	"""after_migrate: switch every Item Component naming rule to the v15.3.5 shape. Idempotent."""
	if not frappe.db.exists("DocType", "Item Component"):
		return
	for row in frappe.get_all("Item Component", fields=["name", "part_code_prefix"]):
		ensure_item_naming_rule(row)
