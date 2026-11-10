"""v15.3.5 Product Revision unit tests (patched lookups, no fixtures): system-assigned revision digits
(0, 1, 2 per Item number base, amend keeps the digit), Interchangeable default, and the Product Revision
Workflow definition being the Engineering Drawing one plus the listed submittable adaptations. Naming
({component}-5NNNN-{n}) is covered in test_naming_v1535. The end-to-end flow is in
smoke_lifecycle.run_product_revision_v153.
"""

import unittest
from unittest.mock import patch

import frappe

from engineering_itagksa import install as I
from engineering_itagksa.engineering_itag_ksa.doctype.product_revision import product_revision as PRM

MOD = "engineering_itagksa.engineering_itag_ksa.doctype.product_revision.product_revision"


def _next(existing, item="IT-1", taken_names=()):
	with patch(f"{MOD}.frappe.get_all", return_value=list(existing)), patch(
		f"{MOD}.frappe.db.exists", side_effect=lambda dt, name=None: name in taken_names
	):
		return PRM.get_next_revision(item)


class TestProductRevisionDigits(unittest.TestCase):
	def test_first_is_0(self):
		# no existing new-format PR of the item
		with patch(f"{MOD}.latest_new_format_pr", return_value=None):
			self.assertEqual(PRM.get_next_revision("IT-1"), "0")

	def test_new_doc_ignores_typed_value(self):
		doc = frappe.get_doc({"doctype": "Product Revision", "item": "IT-1", "revision_number": "Q"})
		doc.set("__islocal", 1)  # as Document.insert() does
		with patch(f"{MOD}.get_next_revision", return_value="1"):
			doc.assign_revision()
		self.assertEqual(doc.revision_number, "1")

	def test_amend_keeps_revision(self):
		doc = frappe.get_doc({"doctype": "Product Revision", "item": "IT-1", "revision_number": "Q",
			"amended_from": "500-50001-0"})
		doc.set("__islocal", 1)
		with patch(f"{MOD}.frappe.db.get_value", return_value="0"):
			doc.assign_revision()
		self.assertEqual(doc.revision_number, "0")

	def test_field_locks_and_default(self):
		meta = frappe.get_meta("Product Revision")
		rev, idf = meta.get_field("revision_number"), meta.get_field("interchangeability_decision")
		self.assertTrue(rev.read_only and rev.set_only_once)
		self.assertEqual(idf.default, "Interchangeable")
		self.assertIn("Interchangeable", idf.options.split("\n"))
		doc = frappe.new_doc("Product Revision")
		self.assertEqual(doc.interchangeability_decision, "Interchangeable")


class TestProductRevisionRevise(unittest.TestCase):
	def test_revisable_states_and_copied_fields(self):
		self.assertEqual(set(PRM.REVISABLE_STATES), {"Approved", "Release Ready", "Released"})
		self.assertEqual(PRM.REVISE_COPY_FIELDS, ("item", "drawing_revision", "material_specification",
			"bom_revision_reference", "routing_revision_reference", "inspection_plan_revision_reference",
			"interchangeability_decision"))
		meta = frappe.get_meta("Product Revision")
		for f in PRM.REVISE_COPY_FIELDS + ("previous_revision",):
			self.assertTrue(meta.has_field(f), f)

	def _src(self, **kw):
		d = frappe._dict(name="PR-IT-1-A", item="IT-1", docstatus=1, workflow_state="Approved", superseding_revision=None)
		d.update(kw)
		d.check_permission = lambda *a: None
		d.get = lambda k, default=None: d[k] if k in d else default
		return d

	def test_revise_refused_outside_active_states(self):
		for kw in ({"workflow_state": "Superseded"}, {"workflow_state": "Obsolete"}, {"docstatus": 2,
				"workflow_state": "Cancelled"}, {"docstatus": 0, "workflow_state": "Draft"},
				{"superseding_revision": "PR-IT-1-B"}):
			with patch(f"{MOD}.frappe.get_doc", return_value=self._src(**kw)), patch(
				f"{MOD}.frappe.has_permission", return_value=True):
				self.assertRaises(frappe.ValidationError, PRM.create_revision, "PR-IT-1-A")

	def test_second_open_revision_refused(self):
		with patch(f"{MOD}.frappe.get_doc", return_value=self._src()), patch(
			f"{MOD}.frappe.has_permission", return_value=True), patch(
			f"{MOD}.open_revision_of", return_value=frappe._dict(name="PR-IT-1-B", workflow_state="Draft")):
			self.assertRaises(frappe.ValidationError, PRM.create_revision, "PR-IT-1-A")


class TestProductRevisionWorkflowDefinition(unittest.TestCase):
	def test_copy_of_drawing_plus_adaptations(self):
		self.assertEqual(I.PR_WORKFLOW_FIELD, I.DRAWING_WORKFLOW_FIELD)
		self.assertEqual(I.PR_TRANSITIONS[: len(I.DRAWING_TRANSITIONS)], I.DRAWING_TRANSITIONS)
		self.assertEqual([t[:3] for t in I.PR_TRANSITIONS[len(I.DRAWING_TRANSITIONS):]], [
			("Approved", "Mark Release Ready", "Release Ready"),
			("Release Ready", "Mark Obsolete", "Obsolete"),
			("Released", "Mark Obsolete", "Obsolete"),
		])
		dw = {s[0]: (s[2], s[3]) for s in I.DRAWING_STATES}
		pr = {s[0]: (s[2], s[3]) for s in I.PR_STATES}
		for state, edit_style in dw.items():
			self.assertEqual(pr[state], edit_style)  # same allow_edit role and style
		self.assertEqual({s[0]: s[1] for s in I.PR_STATES}, {"Draft": 0, "Under Review": 0, "Approved": 1,
			"Superseded": 1, "Obsolete": 1, "Release Ready": 1, "Released": 1, "Cancelled": 2})
		self.assertFalse([t for t in I.PR_TRANSITIONS if t[2] in ("Superseded", "Released", "Cancelled")])

	def test_installed_workflow(self):
		if not frappe.db.exists("Workflow", I.PR_WORKFLOW_NAME):
			self.skipTest("Product Revision Workflow not installed (run bench migrate)")
		wf = frappe.get_doc("Workflow", I.PR_WORKFLOW_NAME)
		self.assertEqual((wf.document_type, wf.workflow_state_field, wf.is_active, wf.send_email_alert),
			("Product Revision", "workflow_state", 1, 0))
		self.assertEqual(len(wf.transitions), sum(len(t[3]) for t in I.PR_TRANSITIONS))


def run():
	suite = unittest.defaultTestLoader.loadTestsFromModule(frappe.get_module(__name__))
	return unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful()
