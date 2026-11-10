"""v15.3.5 naming and Item Category unit tests (patched lookups where possible).

Item codes <component>-1000501 (7 digits, per-component, continues past 1000599);
Engineering Drawing {component}-5NNNN-{n} starting at 0; Material Specification
MSBV-NNNNN-{n} starting at 0, revising MS-BV-00001-0 to MSBV-00001-1; Product Revision
{component}-5NNNN-{n} starting at 0, sharing the 5XXXX space with Drawing so names do
not collide; Purchase removed from Engineering Item Request Item Category (legacy values
kept); Master Engineering Release Item grid shows all 10 columns at width 1.
"""

import json
import unittest
from pathlib import Path
from unittest.mock import patch

import frappe

from engineering_itagksa.component_series import (
	DRAWING_SERIES,
	PR_SERIES,
	next_revision_on_base,
	split_component_base,
)
from engineering_itagksa.engineering_itag_ksa.doctype.engineering_drawing import engineering_drawing as D
from engineering_itagksa.engineering_itag_ksa.doctype.engineering_item_request import (
	engineering_item_request as EIR,
)
from engineering_itagksa.engineering_itag_ksa.doctype.item_component.item_component import (
	ITEM_NAMING_COUNTER_START,
	ITEM_NAMING_DIGITS,
)
from engineering_itagksa.engineering_itag_ksa.doctype.material_specification import (
	material_specification as MS,
)
from engineering_itagksa.engineering_itag_ksa.doctype.product_revision import product_revision as PR

DRAW_MOD = "engineering_itagksa.engineering_itag_ksa.doctype.engineering_drawing.engineering_drawing"
MS_MOD = "engineering_itagksa.engineering_itag_ksa.doctype.material_specification.material_specification"
PR_MOD = "engineering_itagksa.engineering_itag_ksa.doctype.product_revision.product_revision"
CS_MOD = "engineering_itagksa.component_series"
APP = Path(__file__).resolve().parents[1]


def _dwg(**kw):
	d = frappe.get_doc({"doctype": "Engineering Drawing", "item_component": "500", "drawing_name": "x", **kw})
	d.set("__islocal", 1)
	return d


def _ms(**kw):
	d = frappe.get_doc({"doctype": "Material Specification", "description": "x", **kw})
	d.set("__islocal", 1)
	return d


def _pr(**kw):
	d = frappe.get_doc({"doctype": "Product Revision", "item": "500-1000501", **kw})
	d.set("__islocal", 1)
	return d


class TestItemNamingV1535(unittest.TestCase):
	def test_seven_digits_starting_at_1000501(self):
		self.assertEqual(ITEM_NAMING_DIGITS, 7)
		self.assertEqual(ITEM_NAMING_COUNTER_START, 1000500)  # next issued name is …-1000501

	def test_rule_floor_and_passing_1000599(self):
		from engineering_itagksa.engineering_itag_ksa.doctype.item_component import item_component as IC

		rule = frappe._dict(name="R", prefix="500-", prefix_digits=5, counter=50005)
		with patch.object(IC, "_highest_existing_item_number", return_value=0), patch.object(
			IC.frappe.db, "set_value"
		) as setv:
			IC._sync_rule_floor(rule)
		self.assertEqual(rule.prefix_digits, 7)
		self.assertEqual(rule.counter, 1000500)
		setv.assert_called()

		# An already-high 7-digit counter (past 1000599) is not lowered.
		high = frappe._dict(name="R", prefix="500-", prefix_digits=7, counter=1000600)
		with patch.object(IC, "_highest_existing_item_number", return_value=1000599), patch.object(
			IC.frappe.db, "set_value"
		) as setv:
			IC._sync_rule_floor(high)
		self.assertEqual(high.counter, 1000600)
		setv.assert_not_called()

		# Existing 7-digit Item 500-1000700 raises the floor to that number.
		exist = frappe._dict(name="R", prefix="500-", prefix_digits=7, counter=1000500)
		with patch.object(IC, "_highest_existing_item_number", return_value=1000700), patch.object(
			IC.frappe.db, "set_value"
		) as setv:
			IC._sync_rule_floor(exist)
		self.assertEqual(exist.counter, 1000700)


class TestDrawingNamingV1535(unittest.TestCase):
	def test_split_name_old_and_new(self):
		self.assertEqual(D.split_name("500-50001-0"), ("500-50001", "0"))
		self.assertEqual(D.split_name("500-50001-1"), ("500-50001", "1"))
		self.assertEqual(D.split_name("500-50001-10"), ("500-50001", "10"))
		self.assertEqual(D.split_name("500-50001-0-1"), ("500-50001", "0"))
		self.assertEqual(D.split_name("500-50001-10-2"), ("500-50001", "10"))

	def test_split_name_unexpected_does_not_raise(self):
		for name in (None, "", "not-a-name", "500", "500-12", "FG-VALVE-0", object()):
			self.assertEqual(D.split_name(name), (None, None))
			self.assertEqual(split_component_base(name), (None, None))

	def test_first_issue_is_500_50001_0(self):
		doc = _dwg()
		doc.assign_revision()
		self.assertEqual(doc.revision, "0")
		with patch(f"{DRAW_MOD}.issue_base", return_value="500-50001") as iss, patch(
			f"{DRAW_MOD}.frappe.db.exists", return_value=False
		):
			doc.autoname()
			iss.assert_called_once_with("500", D.SERIES_PREFIX)
		self.assertEqual(doc.name, "500-50001-0")

	def test_revision_keeps_base_and_bumps_digit(self):
		doc = _dwg(revises="500-50001-1")
		with patch(f"{DRAW_MOD}.frappe.db.get_value", return_value="1"), patch(
			f"{CS_MOD}.names_for_base", return_value=["500-50001-1"]
		):
			doc.assign_revision()
		self.assertEqual(doc.revision, "2")
		with patch(f"{DRAW_MOD}.issue_base") as iss, patch(f"{DRAW_MOD}.frappe.db.exists", return_value=False):
			doc.autoname()
			iss.assert_not_called()
		self.assertEqual(doc.name, "500-50001-2")

	def test_unrecognised_source_gets_fresh_number_and_0(self):
		doc = _dwg(revises="NOT-A-BASE")
		with patch(f"{DRAW_MOD}.frappe.db.get_value", return_value="X"):
			doc.assign_revision()
		self.assertEqual(doc.revision, "0")
		with patch(f"{DRAW_MOD}.issue_base", return_value="500-50007") as iss, patch(
			f"{DRAW_MOD}.frappe.db.exists", return_value=False
		):
			doc.autoname()
			iss.assert_called_once()
		self.assertEqual(doc.name, "500-50007-0")

	def test_series_prefix_unchanged_so_existing_counter_continues(self):
		self.assertEqual(D.SERIES_PREFIX, DRAWING_SERIES)
		self.assertEqual(DRAWING_SERIES, "DWG-{0}-5")


class TestMaterialSpecificationNamingV1535(unittest.TestCase):
	def test_split_name_old_and_new(self):
		self.assertEqual(MS.split_name("MS-BV-00001-0"), ("MSBV-00001", 0))
		self.assertEqual(MS.split_name("MSBV-00001-1"), ("MSBV-00001", 1))
		self.assertEqual(MS.split_name("TS-OLD-0"), (None, None))

	def test_revision_of_old_ms_bv_uses_msbv_prefix_and_next_digit(self):
		doc = _ms(revises="MS-BV-00001-0")
		with patch(f"{MS_MOD}.frappe.db.exists", return_value=True), patch(
			f"{MS_MOD}.chain_names", return_value={"MS-BV-00001-0"}
		):
			doc.assign_revision()
		self.assertEqual(doc.revision, "1")
		with patch(f"{MS_MOD}.make_autoname") as mak, patch(f"{MS_MOD}.frappe.db.exists", return_value=False), patch(
			f"{MS_MOD}.next_revision", return_value=("MSBV-00001", "1")
		):
			# autoname reads next_revision again for the base
			doc.revision = "1"
			doc.autoname()
			mak.assert_not_called()
		self.assertEqual(doc.name, "MSBV-00001-1")

	def test_first_issue_uses_existing_series_key(self):
		doc = _ms()
		doc.assign_revision()
		self.assertEqual(doc.revision, "0")
		with patch(f"{MS_MOD}.make_autoname", return_value="MS-BV-00001") as mak, patch(
			f"{MS_MOD}.frappe.db.get_value", return_value=0
		), patch(f"{MS_MOD}.frappe.db.exists", return_value=False):
			doc.autoname()
			mak.assert_called_once_with(MS.SERIES, doc=doc)
		self.assertEqual(doc.name, "MSBV-00001-0")
		self.assertEqual(MS.SERIES_KEY, "MS-BV-")


class TestProductRevisionNamingV1535(unittest.TestCase):
	def test_first_revision_is_0_and_name_has_no_pr_prefix(self):
		doc = _pr()
		with patch(f"{PR_MOD}.get_next_revision", return_value="0"):
			doc.assign_revision()
		self.assertEqual(doc.revision_number, "0")
		with patch(f"{PR_MOD}.latest_new_format_pr", return_value=None), patch(
			f"{PR_MOD}.item_component_code", return_value="500"
		), patch(f"{PR_MOD}.issue_base", return_value="500-50001") as iss, patch(
			f"{PR_MOD}.frappe.db.exists", return_value=False
		):
			doc.autoname()
			iss.assert_called_once_with("500", PR_SERIES)
		self.assertEqual(doc.name, "500-50001-0")

	def test_revision_keeps_base(self):
		doc = _pr(previous_revision="500-50001-0")
		with patch(f"{PR_MOD}.get_next_revision", return_value="1") as gnr:
			doc.assign_revision()
			gnr.assert_called()
		self.assertEqual(doc.revision_number, "1")
		# autoname uses the previous_revision base and must not issue a new number
		doc.revision_number = "1"
		with patch(f"{PR_MOD}.issue_base") as iss, patch(f"{PR_MOD}.frappe.db.exists", return_value=False):
			doc.autoname()
			iss.assert_not_called()
		self.assertEqual(doc.name, "500-50001-1")

	def test_unrecognised_previous_revision_gets_fresh_number_at_0(self):
		self.assertEqual(split_component_base("NOT-A-BASE"), (None, None))
		doc = _pr(previous_revision="NOT-A-BASE")
		with patch(f"{PR_MOD}.get_next_revision", return_value="0"):
			doc.assign_revision()
		self.assertEqual(doc.revision_number, "0")
		with patch(f"{PR_MOD}.item_component_code", return_value="500"), patch(
			f"{PR_MOD}.issue_base", return_value="500-50002"
		), patch(f"{PR_MOD}.frappe.db.exists", return_value=False):
			doc.autoname()
		self.assertEqual(doc.name, "500-50002-0")

	def test_amend_name_shares_base_and_revision(self):
		self.assertEqual(split_component_base("500-50001-0-1"), ("500-50001", "0"))
		with patch(f"{CS_MOD}.names_for_base", return_value=["500-50001-0", "500-50001-0-1"]):
			self.assertEqual(next_revision_on_base("500-50001-0", first="0"), "1")

	def test_amend_keeps_revision(self):
		doc = _pr(revision_number="Q", amended_from="500-50001-0")
		with patch(f"{PR_MOD}.frappe.db.get_value", return_value="0"):
			doc.assign_revision()
		self.assertEqual(doc.revision_number, "0")

	def test_shared_series_key_is_separate_from_drawing(self):
		self.assertEqual(PR_SERIES, "PR-{0}-5")
		self.assertNotEqual(PR_SERIES, DRAWING_SERIES)


class TestPurchaseRemovedFromEIR(unittest.TestCase):
	def test_purchase_not_offered_on_item_request(self):
		meta = json.loads(
			(APP / "engineering_itag_ksa/doctype/engineering_item_request/engineering_item_request.json").read_text()
		)
		opts = next(f["options"] for f in meta["fields"] if f["fieldname"] == "eng_item_category")
		self.assertNotIn("Purchase", opts.split("\n"))
		self.assertEqual(opts.split("\n"), ["Manufacturing", "Raw Material", "Sub-Assembly"])

	def test_new_purchase_is_refused(self):
		doc = frappe.get_doc({
			"doctype": "Engineering Item Request", "item_name": "x", "item_group": "G",
			"stock_uom": "Nos", "eng_item_category": "Purchase",
		})
		doc.set("__islocal", 1)
		self.assertRaises(frappe.ValidationError, doc._validate_item_category)


class TestMasterReleaseItemGridV1535(unittest.TestCase):
	def test_all_ten_columns_visible_at_width_one(self):
		meta = json.loads(
			(APP / "engineering_itag_ksa/doctype/master_engineering_release_item/master_engineering_release_item.json").read_text()
		)
		wanted = [
			"item", "item_name", "level", "parent_item", "bom",
			"engineering_release", "drawing", "product_revision", "material_specification", "row_status",
		]
		fields = {f["fieldname"]: f for f in meta["fields"]}
		for fn in wanted:
			self.assertTrue(fields[fn].get("in_list_view"), fn)
			self.assertEqual(fields[fn].get("columns"), 1, fn)
		self.assertEqual([fn for fn in meta["field_order"] if fn in wanted], wanted)


def run():
	suite = unittest.defaultTestLoader.loadTestsFromModule(frappe.get_module(__name__))
	return unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful()
