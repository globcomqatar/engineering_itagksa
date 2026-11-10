"""v15.3.6 Engineering Drawing autoname tests (patched lookups, no fixtures).

A first issue is {component}-5NNNN-0 (no DWG- prefix). A revision of a recognised base
keeps the canonical base and only changes the digit (500-50001-0 -> 500-50001-1). An
unrecognised source gets a fresh number and starts at 0. The 9,999 cap runs only for
new numbers. The end-to-end same-base / unchanged series path is in smoke_lifecycle.run_drawing.
"""

import unittest
from unittest.mock import patch

import frappe

from engineering_itagksa.engineering_itag_ksa.doctype.engineering_drawing import engineering_drawing as D

MOD = "engineering_itagksa.engineering_itag_ksa.doctype.engineering_drawing.engineering_drawing"
CS = "engineering_itagksa.component_series"


def _doc(**kw):
	d = frappe.get_doc({"doctype": "Engineering Drawing", "item_component": "500", "drawing_name": "x", **kw})
	d.set("__islocal", 1)
	return d


class TestDrawingAutonameV1535(unittest.TestCase):
	def test_split_name(self):
		self.assertEqual(D.split_name("500-50001-0"), ("500-50001", "0"))
		self.assertEqual(D.split_name("500-50001-1"), ("500-50001", "1"))
		self.assertEqual(D.split_name("500-50001-0-1"), ("500-50001", "0"))
		self.assertEqual(D.split_name("NOT-A-BASE"), (None, None))
		self.assertEqual(D.split_name(None), (None, None))

	def test_revision_of_new_format_keeps_base(self):
		doc = _doc(revises="500-50001-0")
		with patch(f"{MOD}.frappe.db.get_value", return_value="0"), patch(
			f"{CS}.names_for_base", return_value=["500-50001-0"]
		):
			doc.assign_revision()
		self.assertEqual(doc.revision, "1")
		with patch(f"{MOD}.issue_base") as iss, patch(f"{MOD}.frappe.db.exists", return_value=False):
			doc.autoname()
			iss.assert_not_called()
		self.assertEqual(doc.name, "500-50001-1")

	def test_unrecognised_source_gets_fresh_number_and_0(self):
		doc = _doc(revises="NOT-A-BASE")
		with patch(f"{MOD}.frappe.db.get_value", return_value="X"):
			doc.assign_revision()
		self.assertEqual(doc.revision, "0")
		with patch(f"{MOD}.issue_base", return_value="500-50007") as iss, patch(
			f"{MOD}.frappe.db.exists", return_value=False
		):
			doc.autoname()
			iss.assert_called_once_with("500", D.SERIES_PREFIX)
		self.assertEqual(doc.name, "500-50007-0")

	def test_duplicate_name_refused(self):
		doc = _doc(revises="500-50001-1")
		doc.revision = "2"
		with patch(f"{MOD}.issue_base") as iss, patch(f"{MOD}.frappe.db.exists", return_value=True):
			self.assertRaises(frappe.DuplicateEntryError, doc.autoname)
			iss.assert_not_called()
		self.assertEqual(doc.name, "500-50001-2")

	def test_cap_only_for_new_numbers(self):
		rev = _doc(revises="500-50001-1", revision="2")
		with patch(f"{MOD}.issue_base") as iss, patch(f"{MOD}.frappe.db.exists", return_value=False):
			rev.autoname()
			iss.assert_not_called()
		self.assertEqual(rev.name, "500-50001-2")
		fresh = _doc()
		fresh.revision = "0"
		with patch(f"{MOD}.issue_base", side_effect=frappe.ValidationError("cap")):
			self.assertRaises(frappe.ValidationError, fresh.autoname)


def run():
	suite = unittest.defaultTestLoader.loadTestsFromModule(frappe.get_module(__name__))
	return unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful()
