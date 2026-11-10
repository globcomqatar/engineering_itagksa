"""v15.3.6 unit tests (patched lookups where possible): Drawing starts at revision 0,
removed field descriptions, Engineering workspace shortcut, auto-fill without Item/BOM
read permission, and Revise moving a superseded Material Specification forward.
"""

import json
import unittest
from pathlib import Path
from unittest.mock import patch

import frappe

from engineering_itagksa import engineering_refs as R
from engineering_itagksa.engineering_itag_ksa.doctype.product_revision import product_revision as PRM

PR_MOD = "engineering_itagksa.engineering_itag_ksa.doctype.product_revision.product_revision"
REF_MOD = "engineering_itagksa.engineering_refs"
APP = Path(__file__).resolve().parents[1]


class TestFieldDescriptionsRemovedV1536(unittest.TestCase):
	def test_descriptions_removed_from_json(self):
		cases = [
			("doctype/engineering_drawing/engineering_drawing.json", "revision"),
			("doctype/product_revision/product_revision.json", "revision_number"),
			("doctype/product_revision/product_revision.json", "workflow_state"),
			("doctype/engineering_release/engineering_release.json", "release_status"),
		]
		for rel, fieldname in cases:
			meta = json.loads((APP / "engineering_itag_ksa" / rel).read_text())
			field = next(f for f in meta["fields"] if f["fieldname"] == fieldname)
			self.assertFalse(field.get("description"), f"{rel} {fieldname}")


class TestWorkspaceShortcutV1536(unittest.TestCase):
	def test_mer_shortcut_follows_engineering_release(self):
		ws = json.loads((APP / "engineering_itag_ksa/workspace/engineering/engineering.json").read_text())
		labels = [s["label"] for s in ws["shortcuts"]]
		self.assertIn("Master Engineering Release", labels)
		self.assertEqual(
			labels[labels.index("Engineering Release") + 1],
			"Master Engineering Release",
		)
		content = json.loads(ws["content"])
		names = [b["data"]["shortcut_name"] for b in content if b.get("type") == "shortcut"]
		self.assertEqual(
			names[names.index("Engineering Release") + 1],
			"Master Engineering Release",
		)


class TestAutofillPermissionsV1536(unittest.TestCase):
	def test_engineering_user_without_item_read_gets_names(self):
		eir = frappe._dict(name="EIR-1", engineering_drawing="500-50001-0", material_specification="MSBV-00001-0")

		def perms(dt, ptype="read", *a, **kw):
			if dt in ("Item", "BOM", "Engineering Item Request"):
				return False
			if dt in ("Product Revision", "Engineering Release") and ptype in ("read", "create"):
				return True
			return False

		with patch(f"{REF_MOD}.frappe.db.exists", return_value=True), patch(
			f"{REF_MOD}.frappe.has_permission", side_effect=perms
		), patch(f"{REF_MOD}.creating_item_request", return_value=eir), patch(
			f"{REF_MOD}.current_approved", side_effect=lambda dt, name: name
		), patch(f"{REF_MOD}.item_bom", return_value="BOM-FG"), patch(
			f"{REF_MOD}._readable", side_effect=lambda dt, name, check_perm: name
		), patch(f"{REF_MOD}.frappe.get_meta") as meta:
			meta.return_value.has_field.return_value = False
			d = R.item_engineering_defaults("500-1000501")
		self.assertEqual(d.drawing, "500-50001-0")
		self.assertEqual(d.material_specification, "MSBV-00001-0")
		self.assertEqual(d.bom, "BOM-FG")

	def test_user_without_pr_or_er_access_gets_nothing(self):
		with patch(f"{REF_MOD}.frappe.db.exists", return_value=True), patch(
			f"{REF_MOD}.frappe.has_permission", return_value=False
		), patch(f"{REF_MOD}.creating_item_request") as eir:
			d = R.item_engineering_defaults("500-1000501")
			eir.assert_not_called()
		self.assertEqual((d.drawing, d.material_specification, d.bom), (None, None, None))


class TestReviseMovesMaterialSpecificationV1536(unittest.TestCase):
	def test_superseded_ms_is_moved_forward(self):
		src = frappe._dict(
			name="500-50002-0", item="IT-1", docstatus=1, workflow_state="Approved",
			superseding_revision=None, drawing_revision="500-50001-0",
			material_specification="MSBV-00001-0", bom_revision_reference="BOM-1",
			routing_revision_reference=None, inspection_plan_revision_reference=None,
			interchangeability_decision="Interchangeable",
		)
		src.check_permission = lambda *a: None
		src.get = lambda k, default=None: src[k] if k in src else default

		class _Draft:
			def __init__(self):
				self.values = {}
			def set(self, f, v):
				self.values[f] = v
				setattr(self, f, v)
			def as_dict(self):
				return frappe._dict(self.values)

		draft = _Draft()
		with patch(f"{PR_MOD}.frappe.get_doc", return_value=src), patch(
			f"{PR_MOD}.frappe.has_permission", return_value=True
		), patch(f"{PR_MOD}.open_revision_of", return_value=None), patch(
			f"{PR_MOD}.get_next_revision", return_value="1"
		), patch(f"{PR_MOD}.frappe.new_doc", return_value=draft), patch(
			f"{PR_MOD}.R.current_approved", return_value="MSBV-00001-1"
		) as fwd:
			out = PRM.create_revision("500-50002-0")
		fwd.assert_called_once_with(R.SPEC, "MSBV-00001-0")
		self.assertEqual(out.get("material_specification"), "MSBV-00001-1")


def run():
	suite = unittest.defaultTestLoader.loadTestsFromModule(frappe.get_module(__name__))
	return unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful()
