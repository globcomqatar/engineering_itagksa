"""Engineering Item Request. Submission creates one ERPNext Item."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from engineering_itagksa.engineering_itag_ksa.constants import (
	DRAWING,
	ENGINEERING_MANAGER,
	ITEM_REQUEST,
	MATERIAL_SPECIFICATION,
)
from engineering_itagksa.engineering_itag_ksa.controls import (
	assert_link,
	guard_data_import,
	remember_cancellation,
	require_role,
)

ITEM_IDENTITY_FIELDS = ("item_code", "item_name", "item_group", "stock_uom")


class EngineeringItemRequest(Document):
	def validate(self):
		guard_data_import(self)
		if frappe.flags.in_import:
			self._validate_links(require_submitted=False)
			return
		self._protect_created_item()
		self._validate_links(require_submitted=False)

	def before_submit(self):
		if frappe.flags.in_import:
			frappe.throw(_("Data Import cannot submit an Engineering Item Request or create an Item."))
		require_role(
			ENGINEERING_MANAGER, _("Only Engineering Manager can submit an Engineering Item Request.")
		)
		self._validate_links(require_submitted=True)
		if self.amended_from:
			self._assert_original_item()
			return
		if self.created_item:
			frappe.throw(_("Created Item cannot be set before the Item is created."))
		self._create_item()

	def before_cancel(self):
		remember_cancellation(self)

	def on_cancel(self):
		# The created Item stays as it was. Cancellation does not edit or cancel it.
		return

	def _validate_links(self, *, require_submitted: bool) -> None:
		assert_link(DRAWING, self.engineering_drawing, require_submitted=require_submitted)
		assert_link(
			MATERIAL_SPECIFICATION,
			self.material_specification,
			require_submitted=require_submitted,
		)

	def _protect_created_item(self) -> None:
		previous = self.get("_doc_before_save")
		if self.amended_from:
			self._assert_original_item()
			if previous and (previous.created_item or "") != (self.created_item or ""):
				frappe.throw(_("Created Item on an amendment cannot be changed."))
			return
		if previous and (previous.created_item or "") != (self.created_item or ""):
			frappe.throw(_("Created Item cannot be edited."))
		if not previous and self.created_item:
			frappe.throw(_("Created Item cannot be set by the user."))

	def _assert_original_item(self) -> None:
		original = frappe.db.get_value(
			ITEM_REQUEST,
			self.amended_from,
			["created_item", *ITEM_IDENTITY_FIELDS],
			as_dict=True,
		)
		if not original:
			frappe.throw(_("Amended From {0} was not found.").format(self.amended_from))
		if (self.created_item or "") != (original.created_item or ""):
			frappe.throw(_("An amendment keeps the original Created Item."))
		for field in ITEM_IDENTITY_FIELDS:
			if (self.get(field) or "") != (original.get(field) or ""):
				frappe.throw(_("An amendment keeps the original Item details and does not change the Item."))

	def _create_item(self) -> None:
		item_code = (self.item_code or "").strip()
		if frappe.db.exists("Item", item_code):
			frappe.throw(
				_("Item {0} already exists. Submission will not attach or change it.").format(item_code)
			)
		item = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": item_code,
				"item_name": self.item_name,
				"item_group": self.item_group,
				"stock_uom": self.stock_uom,
				"description": self.description,
			}
		)
		item.insert(ignore_permissions=True)
		self.created_item = item.name
