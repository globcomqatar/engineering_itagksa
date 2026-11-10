"""v15.3.4 Engineering Release unit tests: parent Material Specification link (no form table), auto-fill
from Item / Product Revision refresh, MS mandatory at Approve, PR-to-ER and MER-to-ER carry-over.
End-to-end checks are in smoke_lifecycle.run_product_revision_v01.
"""

import unittest
from unittest.mock import patch

import frappe

from engineering_itagksa.engineering_itag_ksa.doctype.engineering_release import engineering_release as ERM
from engineering_itagksa.engineering_itag_ksa.doctype.product_revision import product_revision as PRM

ERMOD = "engineering_itagksa.engineering_itag_ksa.doctype.engineering_release.engineering_release"


class TestEngineeringReleaseFormV1534(unittest.TestCase):
	def test_parent_link_and_child_doctype_kept(self):
		meta = frappe.get_meta("Engineering Release")
		self.assertTrue(meta.has_field("material_specification"))
		self.assertEqual(meta.get_field("material_specification").options, "Material Specification")
		self.assertFalse(meta.get_field("material_specification").reqd)
		order = [f.fieldname for f in meta.fields
			if f.fieldname in ("drawing_revision", "material_specification", "bom")]
		self.assertEqual(order, ["drawing_revision", "material_specification", "bom"])
		self.assertFalse(meta.has_field("specifications"))
		self.assertFalse(meta.has_field("spec_section"))
		self.assertTrue(frappe.db.exists("DocType", "Engineering Release Specification"))


class TestEngineeringReleaseDefaultsV1534(unittest.TestCase):
	def test_defaults_from_product_revision(self):
		pr = frappe._dict(
			item="IT-1", drawing_revision="DWG-1", bom_revision_reference="BOM-1",
			routing_revision_reference="RT-1", inspection_plan_revision_reference="QI-1",
			material_specification="MS-OLD",
		)
		with patch(f"{ERMOD}.frappe.db.get_value", return_value=pr), patch(
			f"{ERMOD}.frappe.has_permission", return_value=True
		), patch(f"{ERMOD}.current_approved", return_value="MS-NEW"):
			d = ERM.defaults_from_product_revision("PR-IT-1-A")
		self.assertEqual(
			(d.drawing_revision, d.bom, d.routing, d.inspection_plan, d.material_specification),
			("DWG-1", "BOM-1", "RT-1", "QI-1", "MS-NEW"),
		)

	def test_defaults_ms_falls_back_to_eir_when_pr_has_none(self):
		pr = frappe._dict(
			item="IT-1", drawing_revision="DWG-1", bom_revision_reference="BOM-1",
			routing_revision_reference=None, inspection_plan_revision_reference=None,
			material_specification=None,
		)
		with patch(f"{ERMOD}.frappe.db.get_value", return_value=pr), patch(
			f"{ERMOD}.frappe.has_permission", return_value=True
		), patch(f"{ERMOD}.R.item_engineering_defaults",
				return_value=frappe._dict(material_specification="MS-EIR")):
			d = ERM.defaults_from_product_revision("PR-IT-1-A")
		self.assertEqual(d.material_specification, "MS-EIR")
		self.assertEqual(d.drawing_revision, "DWG-1")

	def test_item_auto_fill_uses_mer_resolve(self):
		resolved = frappe._dict(
			drawing_revision="DWG-1", bom="BOM-1", routing=None, inspection_plan=None,
			material_specification="MS-1",
		)
		mer = "engineering_itagksa.engineering_itag_ksa.doctype.master_engineering_release.master_engineering_release"
		with patch(f"{mer}.resolve_drawing", return_value="DWG-1"), patch(
			f"{mer}.resolve_product_revision", return_value="PR-IT-1-A"
		) as resolve_pr, patch(f"{ERMOD}.defaults_from_product_revision", return_value=resolved):
			d = ERM.item_release_defaults("IT-1", check_perm=False)
			resolve_pr.assert_called_once_with("IT-1", "DWG-1")
		self.assertEqual(d.product_revision, "PR-IT-1-A")
		self.assertEqual(d.drawing_revision, "DWG-1")
		self.assertEqual(d.material_specification, "MS-1")


class TestEngineeringReleaseCarryOverV1534(unittest.TestCase):
	def test_pr_to_er_sets_parent_link(self):
		target = frappe.get_doc({"doctype": "Engineering Release"})
		PRM._map_material_specification(frappe._dict(material_specification="MS-1"), target)
		self.assertEqual(target.material_specification, "MS-1")

	def test_validate_baseline_requires_ms(self):
		doc = frappe.get_doc({"doctype": "Engineering Release", "item": "IT-1", "product_revision": "PR-1",
			"drawing_revision": "DWG-1", "bom": "BOM-1"})
		with patch.object(ERM, "assert_drawing_released"), patch.object(ERM, "assert_bom_for_item"), patch(
			f"{ERMOD}.frappe.db.get_value",
			return_value=frappe._dict(docstatus=1, workflow_state="Approved"),
		):
			with self.assertRaises(frappe.ValidationError) as ctx:
				doc.validate_baseline()
		self.assertIn("Material Specification", str(ctx.exception))

	def test_checksum_uses_parent_link(self):
		doc = frappe.get_doc({"doctype": "Engineering Release", "item": "IT-1", "product_revision": "PR-1",
			"drawing_revision": "DWG-1", "bom": "BOM-1", "routing": None, "inspection_plan": None,
			"material_specification": "MS-1", "effective_datetime": "2026-11-10 10:00:00"})
		with patch(f"{ERMOD}.frappe.db.get_value", return_value="abc"):
			a = doc.compute_checksum()
		doc.material_specification = "MS-2"
		with patch(f"{ERMOD}.frappe.db.get_value", return_value="abc"):
			b = doc.compute_checksum()
		self.assertNotEqual(a, b)
