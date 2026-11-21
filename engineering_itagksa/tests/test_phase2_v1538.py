"""v15.3.8 Phase 2 tests (DB, rolled back after each test).

1. BOM: no Workflow (BOM workflow dropped from 15.3.8, Owner 21-Nov-2026).
2. Material Specification Category: plain Select label, not part of the number.
3. Engineering Drawing Sheet print format: watermark by Status, "Uncontrolled when printed".
4. Drawing Mark-ups: server stamp, private files, controlled file untouched, frozen once Approved.
5. Bulk Engineering Item Request upload (Data Import): approved roles, drafts only, Submit After Import refused.
6. Disabled Drawing Types kept but not selectable.
7. ECR / ECO unchanged (no Workflow).
Run: bench --site <site> run-tests --module engineering_itagksa.tests.test_phase2_v1538
"""

import os
from unittest.mock import patch

import frappe
from frappe.model.workflow import apply_workflow

from engineering_itagksa import install as I
from engineering_itagksa import item_request_import as IRI
from engineering_itagksa.engineering_itag_ksa.doctype.item_component import item_component as IC
from engineering_itagksa.tests.test_phase1_v1537 import COMP, EM, EM2, EU, GROUP, Phase1Base, _as

NO_ROLE_USER = "zz.p2.norole@example.com"
_FILES = []


def _pfile(name, content, private=1):
	f = frappe.get_doc({"doctype": "File", "file_name": name, "is_private": private, "content": content}).insert(
		ignore_permissions=True
	)
	_FILES.append(f.get_full_path())
	return f.file_url


class Phase2Base(Phase1Base):
	def setUp(self):
		super().setUp()
		if not frappe.db.exists("User", NO_ROLE_USER):
			u = frappe.get_doc({"doctype": "User", "email": NO_ROLE_USER, "first_name": "zz p2 norole",
				"send_welcome_email": 0, "user_type": "System User"}).insert(ignore_permissions=True)
			u.add_roles("Manufacturing User")

	def tearDown(self):
		super().tearDown()
		for path in _FILES:
			if os.path.exists(path):
				os.remove(path)
		_FILES.clear()
		frappe.clear_cache(doctype="Material Specification")


class Test1_BOMStandard(Phase2Base):
	def test_bom_has_no_workflow(self):
		self.assertFalse(frappe.get_meta("BOM").get_workflow())
		self.assertFalse(frappe.db.exists("Workflow", "Engineering ITAG KSA BOM"))
		self.assertFalse(hasattr(I, "BOM_WORKFLOW_NAME"))

class Test2_MaterialSpecificationCategory(Phase2Base):
	def test_field(self):
		df = frappe.get_meta("Material Specification").get_field("category")
		self.assertEqual((df.fieldtype, df.label, df.reqd), ("Select", "Category", 0))
		self.assertFalse((df.options or "").strip())  # empty list, ITAG fills it in Customize Form
		self.assertNotIn("category", frappe.get_meta("Material Specification").autoname or "")

	def test_category_not_in_number(self):
		from frappe.custom.doctype.property_setter.property_setter import make_property_setter

		make_property_setter("Material Specification", "category", "options", "\nForged\nCast", "Text", validate_fields_for_doctype=False)
		frappe.clear_cache(doctype="Material Specification")
		ms = frappe.get_doc({"doctype": "Material Specification", "specification_name": "ZZ P2 MS", "category": "Cast",
			"description": "ZZ P2"}).insert()
		self.assertEqual(ms.category, "Cast")
		self.assertTrue(ms.name.startswith("MSBV-"))
		self.assertNotIn("Cast", ms.name)
		ms2 = frappe.get_doc({"doctype": "Material Specification", "specification_name": "ZZ P2 MS2", "category": "Wrong"})
		self.assertRaises(frappe.ValidationError, ms2.insert)


class Test3_DrawingPrintFormat(Phase2Base):
	def test_standard_default_format(self):
		pf = frappe.get_doc("Print Format", "Engineering Drawing Sheet")
		self.assertEqual((pf.standard, pf.doc_type, pf.module, pf.print_format_type), ("Yes", "Engineering Drawing", "Engineering ITAG KSA", "Jinja"))
		self.assertEqual(frappe.get_meta("Engineering Drawing").default_print_format, "Engineering Drawing Sheet")

	def test_watermark_by_state(self):
		d = self.drawing().insert()
		expected = {"Prepared": "PREPARED", "Reviewed": "REVIEWED", "Approved": None, "Superseded": "SUPERSEDED", "Obsolete": "OBSOLETE"}
		for state, mark in expected.items():
			doc = frappe.get_doc("Engineering Drawing", d.name)
			doc.workflow_state = state
			html = frappe.get_print("Engineering Drawing", d.name, "Engineering Drawing Sheet", doc=doc, no_letterhead=1)
			self.assertIn("Uncontrolled when printed", html, state)
			self.assertIn(d.name, html)
			if mark:
				self.assertIn(f'data-watermark="{mark}"', html, state)
			else:
				self.assertNotIn("data-watermark", html, state)


class Test4_Markups(Phase2Base):
	def test_stamp_and_private(self):
		d = _as(EU, lambda: self.drawing(external_file_link="https://dms.example.local/p2.pdf").insert())
		url = _pfile("zz-p2-markup-1.txt", b"markup one")
		doc = frappe.get_doc("Engineering Drawing", d.name)
		doc.append("markups", {"markup_file": url, "note": "check bore", "added_by": "Administrator", "added_on": "2020-01-01 00:00:00"})
		_as(EU, doc.save)
		doc.reload()
		row = doc.markups[0]
		self.assertEqual(row.added_by, EU)
		self.assertTrue(row.added_on and str(row.added_on) > "2026")
		stamp = (row.added_by, row.added_on)
		# another user edits the note: stamp kept
		doc.markups[0].note = "check bore and face"
		doc.markups[0].added_by = EM
		_as(EM, doc.save)
		doc.reload()
		self.assertEqual((doc.markups[0].added_by, doc.markups[0].added_on), stamp)
		self.assertEqual(doc.markups[0].note, "check bore and face")
		# public file refused
		pub = _pfile("zz-p2-markup-pub.txt", b"public", private=0)
		doc.append("markups", {"markup_file": pub})
		self.assertRaises(frappe.ValidationError, doc.save)

	def test_controlled_file_untouched(self):
		dwg = _pfile("zz-p2-drawing.txt", b"controlled drawing")
		d = self.drawing(drawing_file=dwg).insert()
		before = (d.drawing_file, d.file_checksum_sha256)
		self.assertTrue(before[1])
		d.append("markups", {"markup_file": _pfile("zz-p2-markup-2.txt", b"markup two"), "note": "n"})
		d.save()
		d.reload()
		self.assertEqual((d.drawing_file, d.file_checksum_sha256), before)
		self.assertNotEqual(d.markups[0].markup_file, d.drawing_file)

	def test_markups_on_review_allowed_frozen_when_approved(self):
		d = _as(EU, lambda: self.drawing(external_file_link="https://dms.example.local/p2b.pdf").insert())
		_as(EU, lambda: apply_workflow(frappe.get_doc("Engineering Drawing", d.name), "Submit for Review"))
		doc = frappe.get_doc("Engineering Drawing", d.name)
		doc.append("markups", {"markup_file": _pfile("zz-p2-markup-3.txt", b"m3"), "note": "review note"})
		_as(EM, doc.save)
		_as(EM2, lambda: apply_workflow(frappe.get_doc("Engineering Drawing", d.name), "Approve"))
		doc = frappe.get_doc("Engineering Drawing", d.name)
		self.assertEqual((doc.workflow_state, len(doc.markups)), ("Approved", 1))
		doc.append("markups", {"markup_file": _pfile("zz-p2-markup-4.txt", b"m4")})
		self.assertRaises(frappe.ValidationError, doc.save)
		doc = frappe.get_doc("Engineering Drawing", d.name)
		doc.markups[0].note = "changed"
		self.assertRaises(frappe.ValidationError, doc.save)
		doc = frappe.get_doc("Engineering Drawing", d.name)
		doc.markups = []
		self.assertRaises(frappe.ValidationError, doc.save)
		# an unchanged save of the locked drawing still works (form values as strings)
		doc = frappe.get_doc("Engineering Drawing", d.name)
		for r in doc.markups:
			r.added_on = str(r.added_on)
		doc.save()
		# Mark Obsolete keeps the Mark-ups
		_as(EM, lambda: apply_workflow(frappe.get_doc("Engineering Drawing", d.name), "Mark Obsolete"))
		self.assertEqual(frappe.db.count("Engineering Drawing Markup", {"parent": d.name}), 1)

	def test_markup_file_required(self):
		d = self.drawing().insert()
		d.append("markups", {"note": "no file"})
		self.assertRaises(frappe.ValidationError, d.save)


CSV_HEADER = "Item Group,Item Component,Stock UOM,Item Category,Item Attribute (Attributes),Attribute Value (Attributes)"


def _csv(rows, extra_header=""):
	head = CSV_HEADER + (("," + extra_header) if extra_header else "")
	return ("\n".join([head] + rows) + "\n").encode()


class Test5_ItemRequestImport(Phase2Base):
	def setUp(self):
		super().setUp()
		self._logs = set(frappe.get_all("Data Import Log", pluck="name"))

	def tearDown(self):
		super().tearDown()
		# Data Import Log is a MyISAM table (not rolled back): remove the rows written by this test
		for name in set(frappe.get_all("Data Import Log", pluck="name")) - self._logs:
			frappe.db.delete("Data Import Log", {"name": name})

	def row(self, size="2in", extra=None):
		r = f"{GROUP},{COMP},Nos,Manufacturing,ZZ P1 Size,{size}"
		return r + (("," + extra) if extra is not None else "")

	def _import(self, user, content, submit_after_import=0):
		url = _pfile(f"zz-p2-import-{frappe.generate_hash(length=6)}.csv", content)
		di = frappe.get_doc({"doctype": "Data Import", "reference_doctype": "Engineering Item Request",
			"import_type": "Insert New Records", "import_file": url, "submit_after_import": submit_after_import})
		_as(user, di.insert)
		from frappe.core.doctype.data_import.data_import import start_import

		# the importer commits / rolls back per row; keep the test inside one transaction
		with patch.object(frappe.db, "commit"), patch.object(frappe.db, "rollback"):
			_as(user, lambda: start_import(di.name))
		return di

	def test_meta(self):
		meta = frappe.get_meta("Engineering Item Request")
		self.assertEqual(meta.allow_import, 1)
		for user in (EU, EM2):
			self.assertTrue(frappe.has_permission("Engineering Item Request", "import", user=user))
			self.assertTrue(frappe.has_permission("Data Import", "create", user=user))
		self.assertTrue(frappe.has_permission("Engineering Item Request", "submit", user=EM2))  # managers bulk submit
		self.assertFalse(frappe.has_permission("Engineering Item Request", "submit", user=EU))
		self.assertFalse(frappe.has_permission("Engineering Item Request", "import", user=NO_ROLE_USER))

	def test_engineering_user_imports_drafts(self):
		before = set(frappe.get_all("Engineering Item Request", pluck="name"))
		self._import(EU, _csv([self.row("2in"), self.row("4in")]))
		new = frappe.get_all("Engineering Item Request", filters={"name": ["not in", list(before) or [""]]},
			fields=["name", "docstatus", "owner", "item_name"])
		self.assertEqual(len(new), 2)
		self.assertTrue(all(r.docstatus == 0 and r.owner == EU and r.item_name == "ZZ Gate Valve" for r in new))
		vals = sorted(frappe.get_all("Item Request Attribute", filters={"parent": ["in", [r.name for r in new]],
			"item_attribute": "ZZ P1 Size"}, pluck="attribute_value"))
		self.assertEqual(vals, ["2in", "4in"])
		# a manager submits them afterwards (standard bulk Submit uses doc.submit)
		_as(EM2, lambda: [frappe.get_doc("Engineering Item Request", r.name).submit() for r in new])
		self.assertEqual({frappe.db.get_value("Engineering Item Request", r.name, "docstatus") for r in new}, {1})

	def test_attribute_value_checked(self):
		before = frappe.db.count("Engineering Item Request")
		self._import(EU, _csv([self.row("99in")]))
		self.assertEqual(frappe.db.count("Engineering Item Request"), before)

	def test_submitted_row_refused(self):
		before = frappe.db.count("Engineering Item Request")
		self._import(EM2, _csv([self.row("2in", "1")], extra_header="Document Status"))
		self.assertEqual(frappe.db.count("Engineering Item Request"), before)
		self.assertEqual(frappe.db.count("Engineering Item Request", {"docstatus": 1, "owner": EM2}), 0)

	def test_submit_after_import_refused(self):
		url = _pfile("zz-p2-import-sai.csv", _csv([self.row()]))
		di = frappe.get_doc({"doctype": "Data Import", "reference_doctype": "Engineering Item Request",
			"import_type": "Insert New Records", "import_file": url, "submit_after_import": 1})
		self.assertRaises(frappe.ValidationError, lambda: _as(EM2, di.insert))
		# other DocTypes keep the standard behaviour
		IRI.validate_data_import(frappe._dict(reference_doctype="ToDo", submit_after_import=1))

	def test_console_import_cannot_submit(self):
		"""bench data-import / import_file(submit_after_import=True) skips the Data Import record: the Item Request
		hook still refuses the Submit."""
		from frappe.core.doctype.data_import.importer import Importer

		url = _pfile("zz-p2-import-console.csv", _csv([self.row()]))
		# same as data_import.import_file(..., submit_after_import=True): an unsaved Data Import (no validate hook)
		di = frappe.new_doc("Data Import")
		di.name = "zz-p2-console-import"
		di.submit_after_import = 1
		di.import_type = "Insert New Records"
		di.payload_count = 1
		with patch.object(frappe.db, "commit"), patch.object(frappe.db, "rollback"):
			Importer(doctype="Engineering Item Request", file_path=url, data_import=di).import_data()
		self.assertEqual(frappe.db.count("Engineering Item Request", {"docstatus": 1, "item_component": COMP}), 0)
		log = frappe.get_all("Data Import Log", filters={"data_import": di.name}, fields=["success", "exception"])
		self.assertEqual(len(log), 1)
		self.assertFalse(log[0].success)
		self.assertIn("imported as drafts", log[0].exception)
		self.assertFalse(frappe.flags.in_import)

	def test_role_block(self):
		self.assertRaises(frappe.PermissionError, lambda: _as(NO_ROLE_USER, lambda: IRI.validate_data_import(
			frappe._dict(reference_doctype="Engineering Item Request", submit_after_import=0))))
		frappe.flags.in_import = True
		try:
			self.assertRaises(frappe.PermissionError, lambda: _as(NO_ROLE_USER, lambda: IRI.before_insert(frappe._dict(docstatus=0))))
			_as(EU, lambda: IRI.before_insert(frappe._dict(docstatus=0)))
		finally:
			frappe.flags.in_import = False

	def test_desk_submit_unaffected(self):
		eir = self.eir(item_request_attribute=[{"item_attribute": "ZZ P1 Size", "attribute_value": "2in"}]).insert()
		eir.submit()
		self.assertEqual(eir.docstatus, 1)


class Test6_DisabledDrawingTypes(Phase2Base):
	def setUp(self):
		super().setUp()
		frappe.get_doc({"doctype": "Engineering Drawing Type", "drawing_type_name": "ZZ P2 Disabled", "enabled": 0}).insert()
		self.comp.append("allowed_drawing_types", {"drawing_type": "ZZ P2 Disabled"})
		self.comp.save()

	def test_query_hides_disabled(self):
		rows = [r[0] for r in IC.drawing_type_query("Engineering Drawing Type", "", "name", 0, 20, {"item_component": COMP})]
		self.assertEqual(rows, ["Welding", "Forging"])
		rows = [r[0] for r in IC.drawing_type_query("Engineering Drawing Type", "", "name", 0, 50, {"item_component": ""})]
		self.assertNotIn("ZZ P2 Disabled", rows)

	def test_disabled_not_selectable_but_kept(self):
		self.assertRaises(frappe.ValidationError, self.drawing(drawing_type="ZZ P2 Disabled").insert)
		# existing drawing keeps its type when the type is disabled later
		frappe.db.set_value("Engineering Drawing Type", "ZZ P2 Disabled", "enabled", 1)
		d = self.drawing(drawing_type="ZZ P2 Disabled").insert()
		frappe.db.set_value("Engineering Drawing Type", "ZZ P2 Disabled", "enabled", 0)
		d.reload()
		d.description = "still saves"
		d.save()
		I.ensure_drawing_types()
		self.assertTrue(frappe.db.exists("Engineering Drawing Type", "ZZ P2 Disabled"))
		self.assertEqual(frappe.db.get_value("Engineering Drawing Type", "ZZ P2 Disabled", "enabled"), 0)


class Test7_ECR_ECO_Unchanged(Phase2Base):
	def test_no_workflow(self):
		for dt in ("Engineering Change Request", "Engineering Change Order"):
			self.assertFalse(frappe.get_meta(dt).get_workflow(), dt)
