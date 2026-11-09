"""Integration coverage for the confirmed Engineering ITAG KSA process.

These tests run inside a Frappe site. They are builder self-tests, not
independent QA.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import random_string
from frappe.utils.file_manager import save_file

from engineering_itagksa.engineering_itag_ksa.constants import (
	ENGINEERING_MANAGER,
	ENGINEERING_MANAGER_MASTER,
	ENGINEERING_USER,
)
from engineering_itagksa.install import ensure_process_setup


class TestConfirmedProcess(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		ensure_process_setup()
		cls.user = cls._user("euser", [ENGINEERING_USER])
		cls.manager = cls._user("emanager", [ENGINEERING_MANAGER])
		cls.master = cls._user("emaster", [ENGINEERING_MANAGER_MASTER])
		cls.combined = cls._user(
			"ecombined",
			[ENGINEERING_USER, ENGINEERING_MANAGER, ENGINEERING_MANAGER_MASTER],
		)
		cls.outsider = cls._user("eoutsider", [])

	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.flags.in_import = False

	@classmethod
	def _user(cls, prefix, roles):
		email = f"{prefix}.{random_string(6)}@example.com"
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": prefix,
				"send_welcome_email": 0,
				"user_type": "System User",
			}
		).insert(ignore_permissions=True)
		if roles:
			user.add_roles(*roles)
		return user.name

	def test_drawing_submission_file_and_segregation(self):
		drawing = self._drawing(self.user)
		self._as(self.user)
		self._raises(drawing.submit)
		self._as(self.manager)
		owned = self._drawing(self.manager)
		self._raises(owned.submit)
		self._as(self.manager)
		self._raises(drawing.reload().submit)
		self._attach(drawing, private=0)
		self._raises(drawing.reload().submit)
		frappe.db.delete("File", {"attached_to_doctype": drawing.doctype, "attached_to_name": drawing.name})
		self._attach(drawing, private=1)
		self._as(self.manager)
		drawing.reload().submit()
		self.assertEqual(drawing.docstatus, 1)

	def test_material_specification_content_and_optional_file(self):
		spec = self._specification(self.user, standards="")
		self._as(self.manager)
		self._raises(spec.submit)
		spec.reload()
		spec.standards = "ASTM body"
		spec.save()
		spec.reload()
		spec.submit()
		self.assertEqual(spec.docstatus, 1)
		with_file = self._specification(self.user, standards="ISO body")
		self._attach(with_file, private=0)
		self._as(self.manager)
		self._raises(with_file.reload().submit)

	def test_only_master_can_cancel_and_reason_is_required(self):
		drawing = self._submitted_drawing()
		self._as(self.manager)
		self._raises(drawing.reload().cancel)
		self._as(self.master)
		self._raises(drawing.reload().cancel)
		frappe.db.set_value(
			drawing.doctype, drawing.name, "cancellation_reason", "Withdrawn", update_modified=False
		)
		drawing.reload().cancel()
		self.assertEqual(drawing.docstatus, 2)
		comment = frappe.db.get_value(
			"Comment", {"reference_name": drawing.name, "comment_type": "Comment"}, "content"
		)
		self.assertIn("Withdrawn", comment or "")

	def test_item_request_creates_one_item_and_amendment_keeps_it(self):
		drawing = self._submitted_drawing()
		spec = self._submitted_specification()
		self._as(self.user)
		request = self._request(drawing=drawing.name, spec=spec.name)
		request.insert()
		self._raises(request.submit)
		self._as(self.manager)
		own_request = self._request()
		own_request.insert()
		own_request.submit()
		self.assertTrue(own_request.created_item)
		item_name = frappe.db.get_value("Item", own_request.created_item, "item_name")
		self.assertEqual(item_name, own_request.item_name)
		self._as(self.master)
		frappe.db.set_value(
			own_request.doctype, own_request.name, "cancellation_reason", "Replace", update_modified=False
		)
		own_request.reload().cancel()
		self.assertEqual(frappe.db.get_value("Item", own_request.created_item, "item_name"), item_name)
		amended = frappe.copy_doc(own_request)
		amended.amended_from = own_request.name
		amended.name = None
		amended.docstatus = 0
		amended.naming_series = "EIR-.#####"
		amended.cancellation_reason = None
		amended.description = "Amended text"
		self._as(self.manager)
		amended.insert()
		amended.submit()
		self.assertEqual(amended.created_item, own_request.created_item)
		self.assertNotEqual(
			frappe.db.get_value("Item", own_request.created_item, "description") or "",
			"Amended text",
		)
		self.assertEqual(frappe.db.count("Item", {"item_code": own_request.item_code}), 1)

	def test_item_request_rejects_bad_links_and_forged_created_item(self):
		draft_drawing = self._drawing(self.user)
		self._as(self.manager)
		request = self._request(drawing=draft_drawing.name)
		request.insert()
		self._raises(request.submit)
		cancelled = self._submitted_drawing()
		self._cancel(cancelled)
		self._as(self.manager)
		request = self._request(drawing=cancelled.name)
		self._raises(request.insert)
		request = self._request()
		request.insert()
		request.created_item = request.item_code
		self._raises(request.save)

	def test_data_import_is_new_drafts_only(self):
		self._as(self.outsider)
		data_import = frappe.new_doc("Data Import")
		data_import.reference_doctype = "Engineering Item Request"
		data_import.import_type = "Insert New Records"
		self._raises(data_import.validate_doctype)
		self._as(self.user)
		other = frappe.new_doc("Data Import")
		other.reference_doctype = "ToDo"
		other.import_type = "Insert New Records"
		self._raises(other.validate_doctype)
		self.assertFalse(frappe.get_meta("Engineering Item Request").get_table_fields())
		frappe.flags.in_import = True
		try:
			request = self._request()
			request.docstatus = 1
			self._raises(request.insert)
			request = self._request()
			request.created_item = "FORGED"
			self._raises(request.insert)
			request = self._request()
			request.amended_from = "EIR-00001"
			self._raises(request.insert)
			request = self._request()
			request.insert()
			self._raises(request.submit)
			self._raises(request.save)
		finally:
			frappe.flags.in_import = False
		self.assertFalse(frappe.db.exists("Item", request.item_code))

	def test_release_workflow_segregation_uniqueness_and_cancel(self):
		item = self._item()
		other_item = self._item()
		drawing = self._submitted_drawing()
		spec = self._submitted_specification()
		bom = self._bom(item, operations=True)
		other_bom = self._bom(item, operations=False, raw_suffix="B")
		routing = self._routing(time_in_mins=15, workstation="Release Bench")
		self._as(self.user)
		release = self._release(item, drawing.name, spec.name, bom, routing)
		release.insert()
		release.workflow_state = "Approved"
		self._raises(release.save)
		self._as(self.combined)
		owned = self._release(
			other_item, drawing.name, spec.name, self._bom(other_item, operations=False), None
		)
		owned.insert()
		owned.workflow_state = "Approved"
		self._raises(owned.save)
		self._as(self.manager)
		release.reload()
		release.workflow_state = "Approved"
		release.save()
		self.assertEqual(release.approved_by, self.manager)
		release.engineering_drawing = None
		self._raises(release.save)
		self._as(self.manager)
		release.reload()
		release.workflow_state = "Released for Production"
		self._raises(release.submit)
		self._as(self.master)
		release.reload()
		release.workflow_state = "Released for Production"
		release.submit()
		self.assertEqual(release.docstatus, 1)
		self.assertEqual(release.released_by, self.master)
		self.assertNotEqual(release.owner, release.approved_by)
		self.assertNotEqual(release.released_by, release.approved_by)
		duplicate = self._release(item, drawing.name, spec.name, bom, routing)
		self._as(self.user)
		duplicate.insert()
		self._approve(duplicate)
		self._as(self.master)
		duplicate.reload()
		duplicate.workflow_state = "Released for Production"
		self._raises(duplicate.submit)
		different = self._release(item, drawing.name, spec.name, other_bom, None)
		self._as(self.user)
		different.insert()
		self._approve(different)
		self._as(self.master)
		different.reload()
		different.workflow_state = "Released for Production"
		different.submit()
		self.assertEqual(different.docstatus, 1)
		self._cancel(release)
		self.assertEqual(frappe.db.get_value("Engineering Drawing", drawing.name, "docstatus"), 1)
		self.assertEqual(frappe.db.get_value("BOM", bom, "docstatus"), 1)
		self.assertEqual(frappe.db.get_value("Item", item, "disabled"), 0)
		replacement = self._release(item, drawing.name, spec.name, bom, routing)
		self._as(self.user)
		replacement.insert()
		self._approve(replacement)
		self._as(self.master)
		replacement.reload()
		replacement.workflow_state = "Released for Production"
		replacement.submit()
		self.assertEqual(replacement.docstatus, 1)

	def test_release_package_rules_and_return(self):
		item = self._item()
		drawing = self._submitted_drawing()
		spec = self._submitted_specification()
		bom = self._bom(item, operations=True)
		routing = self._routing(time_in_mins=5, workstation="Other Bench", operation="Other")
		self._as(self.user)
		draft = self._release(item, None, None, None, None)
		draft.insert()
		self.assertEqual(draft.workflow_state, "Draft")
		draft.engineering_drawing = drawing.name
		draft.material_specification = spec.name
		draft.bom = bom
		draft.routing = routing
		self._raises(draft.save)
		draft.reload()
		draft.engineering_drawing = drawing.name
		draft.material_specification = spec.name
		draft.bom = bom
		matching = self._routing(time_in_mins=40, workstation="Release Bench")
		draft.routing = matching
		draft.save()
		self._approve(draft)
		from engineering_itagksa.engineering_itag_ksa.doctype.engineering_release.engineering_release import (
			set_return_reason,
		)

		self._as(self.master)
		set_return_reason(draft.name, "Correct the routing note")
		draft.reload()
		draft.workflow_state = "Draft"
		draft.save()
		self.assertFalse(draft.approved_by)
		comment = frappe.db.get_value("Comment", {"reference_name": draft.name}, "content")
		self.assertIn("Correct the routing note", comment or "")
		self._approve(draft)
		self._as(self.master)
		draft.reload()
		draft.workflow_state = "Released for Production"
		draft.submit()
		self.assertEqual(draft.released_by, self.master)

	def _approve(self, doc):
		self._as(self.manager)
		doc.reload()
		doc.workflow_state = "Approved"
		doc.save()

	def _cancel(self, doc):
		self._as(self.master)
		frappe.db.set_value(
			doc.doctype, doc.name, "cancellation_reason", "Superseded by a new release", update_modified=False
		)
		doc.reload()
		doc.cancel()

	def _raises(self, fn):
		with self.assertRaises(Exception):
			fn()

	def _as(self, user):
		frappe.set_user(user)

	def _drawing(self, owner):
		self._as(owner)
		doc = frappe.new_doc("Engineering Drawing")
		doc.drawing_title = f"Body {random_string(5)}"
		doc.drawing_type = "General arrangement"
		doc.security_classification = "Internal"
		doc.insert()
		return doc

	def _attach(self, doc, *, private):
		self._as("Administrator")
		save_file(f"{doc.name}.txt", b"drawing", doc.doctype, doc.name, is_private=private)

	def _submitted_drawing(self):
		doc = self._drawing(self.user)
		self._attach(doc, private=1)
		self._as(self.manager)
		doc.reload().submit()
		return doc

	def _specification(self, owner, standards="ASTM A216"):
		self._as(owner)
		doc = frappe.new_doc("Material Specification")
		doc.specification_title = f"Body material {random_string(5)}"
		doc.standards = standards
		doc.insert()
		return doc

	def _submitted_specification(self):
		doc = self._specification(self.user)
		self._as(self.manager)
		doc.reload().submit()
		return doc

	def _request(self, drawing=None, spec=None):
		doc = frappe.new_doc("Engineering Item Request")
		doc.item_code = f"ITAG-{random_string(8)}"
		doc.item_name = doc.item_code
		doc.item_group = self._item_group()
		doc.stock_uom = self._uom()
		doc.item_category = "Manufacturing"
		doc.engineering_drawing = drawing
		doc.material_specification = spec
		return doc

	def _release(self, item, drawing, spec, bom, routing):
		doc = frappe.new_doc("Engineering Release")
		doc.item = item
		doc.engineering_drawing = drawing
		doc.material_specification = spec
		doc.bom = bom
		doc.routing = routing
		return doc

	def _item(self):
		self._as("Administrator")
		code = f"FG-{random_string(8)}"
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": code,
				"item_name": code,
				"item_group": self._item_group(),
				"stock_uom": self._uom(),
				"is_stock_item": 1,
			}
		).insert(ignore_permissions=True)
		return code

	def _uom(self):
		if not frappe.db.exists("UOM", "Nos"):
			frappe.get_doc({"doctype": "UOM", "uom_name": "Nos"}).insert(ignore_permissions=True)
		return "Nos"

	def _item_group(self):
		root = "All Item Groups"
		if not frappe.db.exists("Item Group", root):
			frappe.get_doc({"doctype": "Item Group", "item_group_name": root, "is_group": 1}).insert(
				ignore_permissions=True
			)
		name = "Engineering ITAG Test"
		if not frappe.db.exists("Item Group", name):
			frappe.get_doc(
				{
					"doctype": "Item Group",
					"item_group_name": name,
					"parent_item_group": root,
					"is_group": 0,
				}
			).insert(ignore_permissions=True)
		return name

	def _company(self):
		existing = frappe.db.get_value("Company", {}, "name")
		if existing:
			return existing
		if not frappe.db.exists("Warehouse Type", "Transit"):
			frappe.get_doc({"doctype": "Warehouse Type", "name": "Transit"}).insert(ignore_permissions=True)
		doc = frappe.get_doc(
			{
				"doctype": "Company",
				"company_name": "ITAG KSA Test",
				"abbr": "IKT",
				"default_currency": "SAR",
				"country": "Saudi Arabia",
			}
		).insert(ignore_permissions=True)
		return doc.name

	def _operation(self, name="Cut"):
		if not frappe.db.exists("Operation", name):
			frappe.get_doc({"doctype": "Operation", "name": name, "description": name}).insert(
				ignore_permissions=True
			)
		return name

	def _workstation(self, name):
		if frappe.db.exists("Workstation", name):
			return name
		frappe.get_doc({"doctype": "Workstation", "workstation_name": name, "production_capacity": 1}).insert(
			ignore_permissions=True
		)
		return name

	def _bom(self, item, *, operations, raw_suffix=""):
		self._as("Administrator")
		raw = self._item() if raw_suffix == "" else self._item()
		payload = {
			"doctype": "BOM",
			"item": item,
			"company": self._company(),
			"quantity": 1,
			"is_active": 1,
			"is_default": 0,
			"with_operations": 1 if operations else 0,
			"items": [{"item_code": raw, "qty": 1, "uom": self._uom(), "rate": 1}],
		}
		if operations:
			workstation = self._workstation("Release Bench")
			payload["operations"] = [
				{
					"operation": self._operation("Cut"),
					"workstation": workstation,
					"time_in_mins": 10,
					"sequence_id": 1,
					"description": "Cut",
				}
			]
		bom = frappe.get_doc(payload).insert(ignore_permissions=True)
		bom.submit()
		return bom.name

	def _routing(self, *, time_in_mins, workstation, operation="Cut"):
		self._as("Administrator")
		name = f"RT-{random_string(6)}"
		doc = frappe.get_doc(
			{
				"doctype": "Routing",
				"routing_name": name,
				"operations": [
					{
						"operation": self._operation(operation),
						"workstation": self._workstation(workstation),
						"time_in_mins": time_in_mins,
						"sequence_id": 1,
					}
				],
			}
		).insert(ignore_permissions=True)
		return doc.name
