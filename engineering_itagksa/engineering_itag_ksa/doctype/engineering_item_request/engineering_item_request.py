# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import set_naming_from_document_naming_rule

ITEM_MAP = (
	"item_name", "item_group", "stock_uom", "is_stock_item", "description",
	"eng_item_category",
)
# EIR field -> Item field (different fieldnames).
ITEM_FIELD_MAP = {"item_component": "eng_item_component"}
# EIR field -> optional site Custom Field on Item (not an app fixture); set only when Item has the field.
ITEM_OPTIONAL_FIELD_MAP = {"eng_item_type": "custom_product_type"}


def _set_optional_item_fields(item, src_doc, only_if_value=False):
	"""Copy EIR values into optional Item fields (e.g. custom_product_type) when the site has them."""
	meta = frappe.get_meta("Item")
	for src, dst in ITEM_OPTIONAL_FIELD_MAP.items():
		if not meta.has_field(dst):
			continue
		value = src_doc.get(src)
		if only_if_value and not value:
			continue
		item.set(dst, value)


class EngineeringItemRequest(Document):
	def _validate_selects(self):
		# v15.3.5: Purchase was removed from Item Category. Existing documents that already
		# have Purchase must remain readable and savable; a new or changed value of Purchase is refused.
		# Core Select validation would otherwise reject the stored value after the option is dropped.
		saved = self.eng_item_category
		legacy = False
		if saved == "Purchase":
			before = None if self.is_new() else self.get_doc_before_save()
			if self.is_new() or not before or before.eng_item_category != "Purchase":
				frappe.throw(_("Item Category cannot be Purchase."))
			legacy = True
			self.eng_item_category = "Manufacturing"
		try:
			super()._validate_selects()
		finally:
			if legacy:
				self.eng_item_category = saved

	def validate(self):
		if not self.created_item:
			self.created_item = self._linked_item_from_amendment()
		self._validate_item_category()
		self._validate_item_component()
		self._validate_item_attributes()
		self._validate_engineering_refs()

	def _validate_item_category(self):
		"""Purchase is no longer offered. Keep a historically stored Purchase value; reject a new one."""
		if self.eng_item_category != "Purchase":
			return
		before = None if self.is_new() else self.get_doc_before_save()
		if self.is_new() or not before or before.eng_item_category != "Purchase":
			frappe.throw(_("Item Category cannot be Purchase."))

	def before_update_after_submit(self):
		self._validate_engineering_refs()

	def _validate_item_component(self):
		"""Item Component must belong to the selected Item Group."""
		if not self.item_component:
			return
		group = frappe.db.get_value("Item Component", self.item_component, "item_group")
		if group != self.item_group:
			frappe.throw(_("Item Component {0} does not belong to Item Group {1}.").format(
				frappe.bold(self.item_component), frappe.bold(self.item_group)))

	def _validate_item_attributes(self):
		"""Each row's value must belong to the selected Item Attribute; no attribute twice.

		Mirrors ERPNext Item.validate_attributes: attribute_value is the display string on
		Item Spec Attribute Value (istable), not a Link name.
		"""
		seen = set()
		for row in self.get("item_request_attribute") or []:
			if row.item_attribute in seen:
				frappe.throw(_("Row {0}: Item Attribute {1} is listed more than once.").format(row.idx, frappe.bold(row.item_attribute)))
			seen.add(row.item_attribute)
			value = (row.attribute_value or "").strip()
			if not value:
				continue
			row.attribute_value = value
			if not frappe.db.exists(
				"Item Spec Attribute Value",
				{"attribute_value": value, "parent": row.item_attribute, "parenttype": "Item Spec Attribute"},
			):
				frappe.throw(_("Row {0}: value {1} is not in the list for Item Attribute {2}.").format(
					row.idx, frappe.bold(value), frappe.bold(row.item_attribute)))

	def _validate_engineering_refs(self):
		"""Engineering Drawing / Material Specification link checks (save and update-after-submit)."""
		before = self.get_doc_before_save() if not self.is_new() else None
		self._validate_linked_drawing(before)
		self._validate_linked_material_specification(before)

	def _validate_linked_drawing(self, before):
		if not self.engineering_drawing:
			return
		row = frappe.db.get_value(
			"Engineering Drawing",
			self.engineering_drawing,
			["item_group", "item_component", "workflow_state"],
			as_dict=True,
		)
		if not row:
			frappe.throw(_("Engineering Drawing {0} does not exist.").format(frappe.bold(self.engineering_drawing)))
		state = row.workflow_state or ""
		already = bool(before and before.engineering_drawing == self.engineering_drawing)
		if state == "Obsolete":
			frappe.throw(_("Engineering Drawing {0} is Obsolete and cannot be linked.").format(
				frappe.bold(self.engineering_drawing)))
		if state == "Superseded":
			if not already:
				frappe.throw(_("Cannot link a Superseded Engineering Drawing. Pick an active drawing."))
			frappe.msgprint(
				_("Linked Engineering Drawing {0} is Superseded.").format(frappe.bold(self.engineering_drawing)),
				indicator="orange",
				alert=True,
			)
		if self.item_group and row.item_group and row.item_group != self.item_group:
			frappe.throw(_("Engineering Drawing {0} belongs to Item Group {1}, not {2}.").format(
				frappe.bold(self.engineering_drawing), frappe.bold(row.item_group), frappe.bold(self.item_group)))
		if self.item_component and row.item_component and row.item_component != self.item_component:
			frappe.throw(_("Engineering Drawing {0} belongs to Item Component {1}, not {2}.").format(
				frappe.bold(self.engineering_drawing), frappe.bold(row.item_component), frappe.bold(self.item_component)))

	def _validate_linked_material_specification(self, before):
		if not self.material_specification:
			return
		state = frappe.db.get_value("Material Specification", self.material_specification, "workflow_state")
		if state is None and not frappe.db.exists("Material Specification", self.material_specification):
			frappe.throw(_("Material Specification {0} does not exist.").format(frappe.bold(self.material_specification)))
		state = state or ""
		already = bool(before and before.material_specification == self.material_specification)
		if state == "Obsolete":
			frappe.throw(_("Material Specification {0} is Obsolete and cannot be linked.").format(
				frappe.bold(self.material_specification)))
		if state == "Superseded":
			if not already:
				frappe.throw(_("Cannot link a Superseded Material Specification. Pick an Approved specification."))
			frappe.msgprint(
				_("Linked Material Specification {0} is Superseded.").format(frappe.bold(self.material_specification)),
				indicator="orange",
				alert=True,
			)
			return
		if state != "Approved":
			frappe.throw(_("Material Specification {0} must be Approved (current status: {1}).").format(
				frappe.bold(self.material_specification), frappe.bold(state or "-")))

	def _linked_item_from_amendment(self):
		"""Walk the amended_from chain and return an Item already created for it, if any."""
		src, seen = self.amended_from, set()
		while src and src not in seen:
			seen.add(src)
			created, src = frappe.db.get_value("Engineering Item Request", src, ["created_item", "amended_from"]) or (None, None)
			if created and frappe.db.exists("Item", created):
				return created
		return None

	def on_submit(self):
		# Idempotent: if an Item is already linked (incl. via the amended original), never create another.
		linked = self.created_item or self._linked_item_from_amendment()
		if linked and frappe.db.exists("Item", linked):
			self.db_set("created_item", linked)
			self._sync_item_attributes(linked)
			return
		item = frappe.new_doc("Item")
		for f in ITEM_MAP:
			item.set(f, self.get(f))
		for src, dst in ITEM_FIELD_MAP.items():
			item.set(dst, self.get(src))
		_set_optional_item_fields(item, self)
		item.description = self.description or self.item_name
		item.set("eng_item_attributes", self._item_attribute_rows())
		# Item naming = Document Naming Rule driven by Item Component (eng_item_component).
		set_naming_from_document_naming_rule(item)
		name = item.name
		if not name:
			frappe.throw(
				_("Configure a Document Naming Rule on Item for Item Component {0} (or Item Group {1}).").format(
					frappe.bold(self.item_component or "-"), frappe.bold(self.item_group)
				)
			)
		item.item_code = name
		# Mapping is the controlled purpose of this submit; submitter already passed submit permission here.
		item.flags.ignore_permissions = True
		item.insert(set_name=name)
		self.db_set("created_item", item.name)
		self.add_comment("Info", _("Created Item {0}").format(item.name))

	def _item_attribute_rows(self):
		"""Request rows -> Engineering Item Attribute rows (value string, same as ERPNext variants)."""
		rows = []
		for row in self.get("item_request_attribute") or []:
			rows.append({"item_attribute": row.item_attribute, "attribute_value": row.attribute_value})
		return rows

	def _sync_item_attributes(self, item_code):
		"""Existing Item (amend path): replace its Item Attributes rows with this request's rows;
		also sync Item Component and custom_product_type (from eng_item_type) when set."""
		item = frappe.get_doc("Item", item_code)
		item.set("eng_item_attributes", self._item_attribute_rows())
		if self.item_component:
			item.set("eng_item_component", self.item_component)
		_set_optional_item_fields(item, self, only_if_value=True)
		item.flags.ignore_permissions = True
		item.save()

	def on_cancel(self):
		# Never delete or mutate the created Item; it stays as master data.
		pass


@frappe.whitelist()
def get_item_spec_attribute_values(parent=None, attribute_value="", txt=None, **kwargs):
	"""Auto-completions for Item Request Attribute.attribute_value.

	Mirrors erpnext.stock.doctype.item.item.get_item_attribute: read child values by parent
	attribute name; never Link-search the istable DocType.
	"""
	parent = parent or kwargs.get("parent")
	if not (
		frappe.has_permission("Item Spec Attribute", "read")
		or frappe.has_permission("Engineering Item Request", "read")
	):
		frappe.throw(_("No Permission"))
	if not parent:
		return []
	term = (attribute_value or txt or "").strip()
	filters = {"parent": parent, "parenttype": "Item Spec Attribute"}
	if term:
		filters["attribute_value"] = ("like", f"%{term}%")
	return frappe.get_all(
		"Item Spec Attribute Value",
		filters=filters,
		pluck="attribute_value",
		order_by="idx asc",
		limit_page_length=50,
	)


@frappe.whitelist()
def make_engineering_drawing(source_name):
	"""Prefill a new Engineering Drawing from a submitted Item Request (no Item Code).

	Sets ``source_item_request`` so Drawing.after_insert can write the new drawing
	back onto the request's ``engineering_drawing`` field.
	"""
	src = frappe.get_doc("Engineering Item Request", source_name)
	src.check_permission("read")
	if src.docstatus != 1 or not src.created_item:
		frappe.throw(_("Engineering Drawing can be created only after the Item Request is submitted and the Item exists."))
	if not src.item_component:
		frappe.throw(_("Set Item Component on the Item Request before creating an Engineering Drawing."))
	doc = frappe.new_doc("Engineering Drawing")
	doc.item_group = src.item_group
	doc.item_component = src.item_component
	doc.drawing_name = src.item_name
	doc.source_item_request = src.name
	return doc


@frappe.whitelist()
def link_drawing_to_item_request(item_request, drawing):
	"""Write Drawing back to a submitted Item Request (allow_on_submit). Used by tests / recovery."""
	eir = frappe.get_doc("Engineering Item Request", item_request)
	eir.check_permission("write")
	if not frappe.db.exists("Engineering Drawing", drawing):
		frappe.throw(_("Engineering Drawing {0} does not exist.").format(frappe.bold(drawing)))
	frappe.db.set_value("Engineering Item Request", item_request, "engineering_drawing", drawing)
	return drawing
