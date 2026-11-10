"""v15.2.0 Master Engineering Release tests (v15.2.4: PR Released on ER Released for Production).

Unit (patched lookups, no fixtures): manufacturing-only BOM tree pull, BOM Creator complete-tree filter,
row status, status transitions / segregation of duties.
Integration (real records, rolled back): BOM Creator -> BOMs -> Master pull -> exclusivity.
Run:
  bench --site <site> execute engineering_itagksa.tests.test_master_engineering_release.run
"""

import unittest
from unittest.mock import patch

import frappe

from engineering_itagksa.engineering_itag_ksa.doctype.master_engineering_release import (
	master_engineering_release as M,
)

MOD = "engineering_itagksa.engineering_itag_ksa.doctype.master_engineering_release.master_engineering_release"

# BOM tree fixture: FG -> SA1 (made) -> SA2 (made); FG -> RM1 (bought); SA1 -> RM2 (bought);
# FG -> SUP1 (has BOM but supplier-sourced -> skip)
BOM_ITEM = {"BOM-FG": "FG", "BOM-SA1": "SA1", "BOM-SA2": "SA2", "BOM-SUP1": "SUP1"}
LINES = {
	"BOM-FG": [
		frappe._dict(item_code="SA1", bom_no="BOM-SA1", sourced_by_supplier=0),
		frappe._dict(item_code="RM1", bom_no="", sourced_by_supplier=0),
		frappe._dict(item_code="SUP1", bom_no="BOM-SUP1", sourced_by_supplier=1),
	],
	"BOM-SA1": [
		frappe._dict(item_code="SA2", bom_no="BOM-SA2", sourced_by_supplier=0),
		frappe._dict(item_code="RM2", bom_no=None, sourced_by_supplier=0),
	],
	"BOM-SA2": [],
}


def fake_get_value(dt, name, field=None, *a, **kw):
	if dt == "BOM" and field == "item":
		return BOM_ITEM.get(name)
	raise AssertionError(f"unexpected get_value {dt} {name} {field}")


def fake_get_all(dt, filters=None, **kw):
	if dt == "BOM Item":
		return LINES.get(filters["parent"], [])
	raise AssertionError(f"unexpected get_all {dt}")


class TestBomTree(unittest.TestCase):
	def test_manufacturing_only(self):
		with patch(f"{MOD}.frappe.db.get_value", side_effect=fake_get_value), patch(f"{MOD}.frappe.get_all", side_effect=fake_get_all):
			rows = M.get_bom_tree("BOM-FG")
		self.assertEqual([(r.item, r.level, r.parent_item, r.bom) for r in rows], [
			("FG", 0, None, "BOM-FG"),
			("SA1", 1, "FG", "BOM-SA1"),
			("SA2", 2, "SA1", "BOM-SA2"),
		])  # RM1/RM2 (bought) and SUP1 (supplier-sourced) skipped

	def test_recursion_guard(self):
		lines = {"BOM-FG": [frappe._dict(item_code="FG", bom_no="BOM-FG", sourced_by_supplier=0)]}
		with patch(f"{MOD}.frappe.db.get_value", side_effect=fake_get_value), patch(
			f"{MOD}.frappe.get_all", side_effect=lambda dt, filters=None, **k: lines.get(filters["parent"], [])
		):
			self.assertRaises(frappe.ValidationError, M.get_bom_tree, "BOM-FG")


class TestFinishedGoodFilter(unittest.TestCase):
	def doc(self, **kw):
		d = frappe.new_doc("Master Engineering Release")
		d.update({"company": "C", "finished_good_item": "FG", **kw})
		return d

	def test_blocked_without_completed_creator(self):
		with patch(f"{MOD}.completed_bom_creators", return_value=[]):
			self.assertRaises(frappe.ValidationError, self.doc().validate_finished_good)

	def test_creator_and_top_bom_auto_filled(self):
		d = self.doc()
		with patch(f"{MOD}.completed_bom_creators", return_value=[frappe._dict(name="BC-1")]), patch(
			f"{MOD}.top_bom_for_creator", return_value="BOM-FG"
		), patch(f"{MOD}.frappe.db.get_value", return_value=frappe._dict(item="FG", docstatus=1, bom_creator="BC-1")):
			d.validate_finished_good()
		self.assertEqual((d.bom_creator, d.top_bom), ("BC-1", "BOM-FG"))

	def test_top_bom_from_other_creator_blocked(self):
		d = self.doc(bom_creator="BC-1", top_bom="BOM-X")
		with patch(f"{MOD}.completed_bom_creators", return_value=[frappe._dict(name="BC-1")]), patch(
			f"{MOD}.frappe.db.get_value", return_value=frappe._dict(item="FG", docstatus=1, bom_creator="BC-OTHER")
		):
			self.assertRaises(frappe.ValidationError, d.validate_finished_good)

	def test_incomplete_creator_rejected(self):
		d = self.doc(bom_creator="BC-DRAFT")
		with patch(f"{MOD}.completed_bom_creators", return_value=[frappe._dict(name="BC-1")]):
			self.assertRaises(frappe.ValidationError, d.validate_finished_good)


class TestRowStatusAndDuties(unittest.TestCase):
	def setUp(self):
		# draft v0.1: the Item drawing-chain match is its own lookup (engineering_refs); unit rows match by default
		p = patch(f"{MOD}.drawing_matches_item", return_value=True)
		self.match = p.start()
		self.addCleanup(p.stop)

	def test_row_status(self):
		self.assertEqual(M.compute_row_status(frappe._dict(drawing=None, engineering_release="ER")), "Missing Drawing")
		self.assertEqual(M.compute_row_status(frappe._dict(drawing="D", product_revision=None, engineering_release=None)),
			"Missing Product Revision")
		self.assertEqual(M.compute_row_status(frappe._dict(drawing="D", product_revision="PR", engineering_release=None)), "Missing ER")
		with patch(f"{MOD}.frappe.db.get_value", return_value="Released for Production"):
			self.assertEqual(M.compute_row_status(frappe._dict(drawing="D", product_revision="PR", engineering_release="ER")), "Released")
		with patch(f"{MOD}.frappe.db.get_value", return_value="Draft"):
			self.assertEqual(M.compute_row_status(frappe._dict(drawing="D", product_revision="PR", engineering_release="ER")), "Linked")

	def _rows_doc(self, **row):
		d = frappe.new_doc("Master Engineering Release")
		d.append("items", {"item": "FG", "bom": "BOM-FG", "drawing": "D", "product_revision": "PR",
			"material_specification": "MS", **row})
		d.items[0].idx = 1
		return d

	@staticmethod
	def _gv(bom_ok=True, dwg_ok=True, pr_ok=True, pr_drawing="D", ms_ok=True):
		def gv(dt, name, fields=None, *a, **kw):
			if dt == "BOM":
				return frappe._dict(item="FG", docstatus=1 if bom_ok else 0)
			if dt == "Engineering Drawing":
				# draft v0.1: Drawing has no item_code / docstatus; Approved is the released state
				return "Approved" if dwg_ok else "Draft"
			if dt == "Product Revision":
				return frappe._dict(item="FG", docstatus=1, workflow_state="Released" if pr_ok else "Superseded",
					drawing_revision=pr_drawing)
			if dt == "Material Specification":
				return "Approved" if ms_ok else "Superseded"
			raise AssertionError(dt)
		return gv

	def test_ready_without_er(self):
		with patch(f"{MOD}.frappe.db.get_value", side_effect=self._gv()):
			self.assertEqual(M.row_missing(self._rows_doc().items[0]), [])
			self._rows_doc().assert_rows_ready()  # Missing ER does not block Approve/Release

	def test_drawing_of_other_item_chain_not_ready(self):
		"""draft v0.1: an Approved drawing outside the Item's drawing revises chain is not ready."""
		self.match.return_value = False
		with patch(f"{MOD}.frappe.db.get_value", side_effect=self._gv()):
			self.assertEqual(M.row_missing(self._rows_doc().items[0]), ["Approved Drawing"])
			self.assertRaises(frappe.ValidationError, self._rows_doc().assert_rows_ready)

	def test_ready_needs_submitted_bom_released_drawing_pr(self):
		for kw in ({"drawing": None}, {"product_revision": None}, {"bom": None}):
			with patch(f"{MOD}.frappe.db.get_value", side_effect=self._gv()):
				self.assertRaises(frappe.ValidationError, self._rows_doc(**kw).assert_rows_ready)
		for gv in (self._gv(bom_ok=False), self._gv(dwg_ok=False), self._gv(pr_ok=False), self._gv(pr_drawing="D-OLD")):
			with patch(f"{MOD}.frappe.db.get_value", side_effect=gv):
				self.assertTrue(M.row_missing(self._rows_doc().items[0]))
				self.assertRaises(frappe.ValidationError, self._rows_doc().assert_rows_ready)

	def test_ready_needs_approved_material_specification(self):
		with patch(f"{MOD}.frappe.db.get_value", side_effect=self._gv()):
			self.assertEqual(M.row_missing(self._rows_doc(material_specification=None).items[0]),
				["Approved Material Specification"])
			self.assertRaises(frappe.ValidationError, self._rows_doc(material_specification=None).assert_rows_ready)
		with patch(f"{MOD}.frappe.db.get_value", side_effect=self._gv(ms_ok=False)):
			self.assertEqual(M.row_missing(self._rows_doc().items[0]), ["Approved Material Specification"])
			self.assertRaises(frappe.ValidationError, self._rows_doc().assert_rows_ready)

	def test_draft_save_blocked_on_incomplete_rows(self):
		d = self._rows_doc(product_revision=None)
		d.update({"release_status": "Draft"})
		with patch.object(M.MasterEngineeringRelease, "validate_finished_good", lambda s: None), patch.object(
			M.MasterEngineeringRelease, "validate_items", lambda s: None
		), patch(f"{MOD}.frappe.db.get_value", side_effect=self._gv()):
			self.assertRaises(frappe.ValidationError, d.validate)
			d.items[0].product_revision = "PR"
			d.validate()  # complete rows save

	def test_release_drives_children_all_or_nothing(self):
		d = self._doc("Approved", approved_by="appr@x")
		calls = []
		d.release_children = lambda: calls.append(1) or (["ER-NEW"], ["ER-NEW", "ER-OLD"])
		with patch(f"{MOD}.frappe.session", frappe._dict(user="rel@x")), patch(
			f"{MOD}.frappe.get_roles", return_value=["Engineering Manager Master"]
		), patch(f"{MOD}.frappe.msgprint"), patch(f"{MOD}.frappe.db.savepoint"), patch(f"{MOD}.frappe.db.rollback") as rb:
			d.set_status("Released for Production")
			self.assertEqual((d.release_status, calls, rb.call_count), ("Released for Production", [1], 0))
			# a failing child aborts: Master stays Approved, savepoint rolled back
			d2 = self._doc("Approved", approved_by="appr@x")
			def _fail():
				raise frappe.ValidationError("child failed")
			d2.release_children = _fail
			self.assertRaises(frappe.ValidationError, d2.set_status, "Released for Production")
			self.assertEqual((d2.release_status, d2.released_by, rb.call_count), ("Approved", None, 1))

	def _doc(self, status, owner="creator@x", approved_by=None):
		d = frappe.new_doc("Master Engineering Release")
		d.update({"release_status": status, "owner": owner, "approved_by": approved_by})
		d.save = lambda *a, **k: d
		d.assert_rows_ready = lambda *a: None
		return d

	def test_creator_cannot_approve(self):
		d = self._doc("Draft")
		with patch(f"{MOD}.frappe.session", frappe._dict(user="creator@x")), patch(
			f"{MOD}.frappe.get_roles", return_value=["Engineering Manager"]
		):
			self.assertRaises(frappe.ValidationError, d.set_status, "Approved")

	def test_approver_cannot_release_and_role_required(self):
		d = self._doc("Approved", approved_by="appr@x")
		with patch(f"{MOD}.frappe.session", frappe._dict(user="appr@x")), patch(
			f"{MOD}.frappe.get_roles", return_value=["Engineering Manager Master"]
		):
			self.assertRaises(frappe.ValidationError, d.set_status, "Released for Production")
		with patch(f"{MOD}.frappe.session", frappe._dict(user="rel@x")), patch(
			f"{MOD}.frappe.get_roles", return_value=["Engineering Manager"]
		):
			self.assertRaises(frappe.PermissionError, d.set_status, "Released for Production")
		with patch(f"{MOD}.frappe.session", frappe._dict(user="rel@x")), patch(
			f"{MOD}.frappe.get_roles", return_value=["Engineering Manager Master"]
		), patch(f"{MOD}.frappe.get_all", return_value=[]), patch(f"{MOD}.frappe.msgprint"):
			d.release_children = lambda: ([], [])
			d.set_status("Released for Production")
		self.assertEqual((d.release_status, d.released_by), ("Released for Production", "rel@x"))

	def test_illegal_transition(self):
		d = self._doc("Draft")
		with patch(f"{MOD}.frappe.session", frappe._dict(user="x@x")), patch(
			f"{MOD}.frappe.get_roles", return_value=["Engineering Manager Master"]
		):
			self.assertRaises(frappe.ValidationError, d.set_status, "Released for Production")


PRM = "engineering_itagksa.engineering_itag_ksa.doctype.product_revision.product_revision"


class TestPrReleasedOnRfp(unittest.TestCase):
	"""v15.2.4: ER Released for Production -> linked Product Revision Released / Ready (mark_released)."""

	def _run(self, state, docstatus=1, readiness="Not Ready"):
		from engineering_itagksa.engineering_itag_ksa.doctype.product_revision import product_revision as PR

		row = frappe._dict(docstatus=docstatus, workflow_state=state, release_readiness=readiness)
		with patch(f"{PRM}.frappe.db.get_value", return_value=row), patch(f"{PRM}.frappe.db.set_value") as sv, patch(
			f"{PRM}.frappe.get_doc"):
			changed = PR.mark_released("PR-X", "ER-X")
		return changed, sv

	def test_approved_and_release_ready_advance(self):
		for state in ("Approved", "Release Ready"):
			changed, sv = self._run(state)
			self.assertTrue(changed)
			sv.assert_called_once_with("Product Revision", "PR-X", {"workflow_state": "Released",
				"release_readiness": "Ready"}, update_modified=True)

	def test_inactive_and_draft_untouched(self):
		for state in ("Superseded", "Obsolete", "Cancelled"):
			changed, sv = self._run(state)
			self.assertFalse(changed)
			sv.assert_not_called()
		changed, sv = self._run("Approved", docstatus=0)
		self.assertFalse(changed)
		sv.assert_not_called()

	def test_already_released_idempotent(self):
		changed, sv = self._run("Released", readiness="Ready")
		self.assertFalse(changed)
		sv.assert_not_called()
		changed, sv = self._run("Released")  # readiness repaired only
		self.assertFalse(changed)
		sv.assert_called_once_with("Product Revision", "PR-X", "release_readiness", "Ready", update_modified=False)


class TestIntegration(unittest.TestCase):
	"""Real BOM Creator tree on the local site; everything rolled back."""

	def setUp(self):
		frappe.db.savepoint("mer_test")

	def tearDown(self):
		frappe.db.rollback(save_point="mer_test")

	def _item(self, code, stock=1, purchase=0):
		if frappe.db.exists("Item", code):
			return code
		group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
		frappe.get_doc({"doctype": "Item", "item_code": code, "item_name": code, "item_group": group,
			"stock_uom": "Nos", "is_stock_item": stock, "is_purchase_item": purchase}).insert(ignore_permissions=True)
		return code

	def test_bom_creator_tree_pull(self):
		company = frappe.db.get_value("Company", {}, "name")
		fg, sa, rm = self._item("_MER-FG"), self._item("_MER-SA"), self._item("_MER-RM", purchase=1)
		bc = frappe.new_doc("BOM Creator")
		bc.update({"name": "_MER-BC", "item_code": fg, "qty": 1, "company": company, "rm_cost_as_per": "Valuation Rate",
			"currency": frappe.db.get_value("Company", company, "default_currency"), "conversion_rate": 1})
		bc.append("items", {"item_code": sa, "fg_item": fg, "qty": 1, "uom": "Nos", "stock_uom": "Nos", "conversion_factor": 1,
			"is_expandable": 1})
		bc.insert(ignore_permissions=True)
		sa_row = bc.items[0]
		bc.append("items", {"item_code": rm, "fg_item": sa, "qty": 2, "uom": "Nos", "stock_uom": "Nos", "conversion_factor": 1,
			"fg_reference_id": sa_row.name, "parent_row_no": sa_row.idx})
		bc.append("items", {"item_code": rm, "fg_item": fg, "qty": 1, "uom": "Nos", "stock_uom": "Nos", "conversion_factor": 1,
			"fg_reference_id": bc.name})
		bc.save(ignore_permissions=True)
		with patch("frappe.enqueue"):
			bc.submit()
		self.assertNotIn(fg, [c.item_code for c in M.completed_bom_creators(fg)])  # submitted, BOMs not yet built
		bc.reload()
		bc.create_boms()
		bc.reload()
		bc.set_status(save=True)
		self.assertEqual(bc.status, "Completed")
		self.assertIn(bc.name, [c.name for c in M.completed_bom_creators(fg, company)])
		names = [r[0] for r in M.finished_good_query("Item", "_MER-", "name", 0, 20, {"company": company})]
		self.assertIn(fg, names)
		self.assertNotIn(sa, names)  # sub-assembly is not a BOM Creator finished good

		for u in ("creator@example.com", "approver@example.com"):
			if not frappe.db.exists("User", u):
				frappe.get_doc({"doctype": "User", "email": u, "first_name": u.split("@")[0],
					"send_welcome_email": 0}).insert(ignore_permissions=True)
		m = frappe.new_doc("Master Engineering Release")
		m.update({"company": company, "finished_good_item": fg})
		m.validate_finished_good()
		self.assertEqual(m.bom_creator, bc.name)
		# Gap 1: sub-levels have no Drawing / Product Revision -> Get Items and save are blocked
		self.assertRaises(frappe.ValidationError, m.get_items_from_bom)
		self.assertEqual([(r.item, r.level, r.parent_item) for r in m.items], [(fg, 0, None), (sa, 1, fg)])  # RM skipped
		self.assertTrue(all(r.row_status == "Missing Drawing" for r in m.items))
		self.assertRaises(frappe.ValidationError, m.insert, ignore_permissions=True)
		m.set("items", [])
		m.insert(ignore_permissions=True)  # header-only Draft is allowed
		self.assertTrue(m.name.startswith("MER-"))
		self.assertEqual(m.release_status, "Draft")
		m.release_status = "Released for Production"
		self.assertRaises(frappe.ValidationError, m.save)  # status only via buttons

	def _demo_master(self):
		fg = "MER-DEMO-FG"
		if not frappe.db.exists("Product Revision", "PR-MER-DEMO-FG-A"):
			self.skipTest("MER demo data not present (setup.seed_master_demo.run)")
		for u in ("creator@example.com", "approver@example.com"):
			if not frappe.db.exists("User", u):
				frappe.get_doc({"doctype": "User", "email": u, "first_name": u.split("@")[0],
					"send_welcome_email": 0}).insert(ignore_permissions=True)
		m = frappe.new_doc("Master Engineering Release")
		m.update({"company": frappe.db.get_value("BOM", {"item": fg, "docstatus": 1}, "company"), "finished_good_item": fg})
		m.get_items_from_bom()
		m.insert(ignore_permissions=True)
		# simulate SoD: someone else created and approved it; Administrator (Engineering Manager Master) releases
		frappe.db.set_value("Master Engineering Release", m.name, {"owner": "creator@example.com",
			"release_status": "Approved", "approved_by": "approver@example.com"}, update_modified=False)
		m.reload()
		return m

	def test_release_drives_every_child_er_to_rfp(self):
		m = self._demo_master()
		self.assertEqual(len(m.items), 4)
		self.assertTrue(all(not M.row_missing(r) for r in m.items))
		# one row already has a Draft ER (Create Draft Releases preview); the rest get created on release
		m.release_status = "Draft"
		frappe.db.set_value("Master Engineering Release", m.name, "release_status", "Draft", update_modified=False)
		m.reload()
		m._create_missing_releases()
		pre = m.items[0].engineering_release
		m.items[1].engineering_release = m.items[2].engineering_release = m.items[3].engineering_release = None
		m.save(ignore_permissions=True)
		frappe.db.set_value("Master Engineering Release", m.name, {"release_status": "Approved",
			"approved_by": "approver@example.com"}, update_modified=False)
		m.reload()
		# v15.2.4: PRs start Approved / Not Ready (demo seeds them Released); RfP must advance them
		prs = {r.product_revision for r in m.items}
		for pr in prs:
			frappe.db.set_value("Product Revision", pr, {"workflow_state": "Approved", "release_readiness": "Not Ready"},
				update_modified=False)
		with patch(f"{MOD}.frappe.msgprint"):
			m.set_status("Released for Production")
		m.reload()
		self.assertEqual(m.release_status, "Released for Production")
		self.assertEqual(m.items[0].engineering_release, pre)
		for pr in prs:
			self.assertEqual(frappe.db.get_value("Product Revision", pr, ["workflow_state", "release_readiness"]),
				("Released", "Ready"))
		for r in m.items:
			er = frappe.get_doc("Engineering Release", r.engineering_release)
			self.assertEqual((er.release_status, er.master_engineering_release), ("Released for Production", m.name))
			self.assertTrue(er.release_checksum)
			self.assertEqual(r.row_status, "Released")
			notes = frappe.get_all("Comment", filters={"reference_doctype": "Engineering Release",
				"reference_name": er.name, "comment_type": "Info"}, pluck="content")
			self.assertTrue(any(m.name in n and "approver@example.com" in n for n in notes))

	def test_release_all_or_nothing(self):
		# demo ERs already released by an earlier (real) Master stay out of the comparison
		pre_rfp = set(frappe.get_all("Engineering Release", filters={"item": ("like", "MER-DEMO-%"),
			"release_status": "Released for Production"}, pluck="name"))
		m = self._demo_master()
		from engineering_itagksa.engineering_itag_ksa.doctype.engineering_release import engineering_release as ERM
		orig = ERM.EngineeringRelease.validate
		def boom(self):
			if self.item == "MER-DEMO-SUB-DOOR" and self.release_status == "Released for Production":
				raise frappe.ValidationError("forced child failure")  # msgprint is patched, so no frappe.throw
			return orig(self)
		with patch.object(ERM.EngineeringRelease, "validate", boom), patch(f"{MOD}.frappe.msgprint"):
			self.assertRaises(frappe.ValidationError, m.set_status, "Released for Production")
		self.assertEqual(frappe.db.get_value("Master Engineering Release", m.name, "release_status"), "Approved")
		self.assertFalse(frappe.get_all("Engineering Release", filters={"master_engineering_release": m.name}))
		self.assertFalse(set(frappe.get_all("Engineering Release", filters={"item": ("like", "MER-DEMO-%"),
			"release_status": "Released for Production"}, pluck="name")) - pre_rfp)

	def test_er_workflow_bypass_only_via_master(self):
		"""Outside a Master release the Desk Workflow transition check still applies to Engineering Release."""
		m = self._demo_master()
		frappe.db.set_value("Master Engineering Release", m.name, "release_status", "Draft", update_modified=False)
		m.reload()
		m._create_missing_releases()
		er = frappe.get_doc("Engineering Release", m.items[0].engineering_release)
		er.release_status = "Released for Production"
		self.assertRaises(frappe.ValidationError, er.save)  # Draft -> RFP is not a Workflow transition
		er.reload()
		er.release_status = "Released for Production"
		er.flags.via_master_release = m.name  # Master is Draft, not Approved -> no bypass
		self.assertRaises(frappe.ValidationError, er.save)

	def test_workflow_release_via_apply_workflow(self):
		"""Desk Workflow 'Release for Production' runs the same SoD guards and drives every child ER to RFP."""
		from frappe.model.workflow import apply_workflow

		m = self._demo_master()
		frappe.db.set_value("Master Engineering Release", m.name, "approved_by", "Administrator", update_modified=False)
		# releaser == approver -> blocked by the controller even though the Workflow allows the role
		# (msgprint not patched here: frappe.throw raises through msgprint)
		self.assertRaises(frappe.ValidationError, apply_workflow, m.as_dict(), "Release for Production")
		self.assertEqual(frappe.db.get_value("Master Engineering Release", m.name, "release_status"), "Approved")
		frappe.db.set_value("Master Engineering Release", m.name, "approved_by", "approver@example.com", update_modified=False)
		with patch(f"{MOD}.frappe.msgprint"):
			apply_workflow(frappe.get_doc("Master Engineering Release", m.name).as_dict(), "Release for Production")
		m.reload()
		self.assertEqual((m.release_status, m.released_by), ("Released for Production", "Administrator"))
		for r in m.items:
			self.assertEqual(frappe.db.get_value("Engineering Release", r.engineering_release, "release_status"),
				"Released for Production")

	def test_workflow_return_to_draft(self):
		from frappe.model.workflow import apply_workflow

		m = self._demo_master()
		apply_workflow(m.as_dict(), "Return to Draft")
		m.reload()
		self.assertEqual((m.release_status, m.approved_by), ("Draft", None))

	def test_resolve_link_exclusive_on_demo_item(self):
		"""Existing demo item (Approved drawing / PR / ER): resolve, back-link, exclusivity, ER delete block."""
		item = "DEMO-FG-VALVE-001"
		bom = frappe.db.get_value("BOM", {"item": item, "docstatus": 1}, "name")
		if not bom or not M.resolve_drawing(item):
			self.skipTest("demo data not present")
		company = frappe.db.get_value("BOM", bom, "company")

		def make():
			m = frappe.new_doc("Master Engineering Release")
			m.update({"company": company, "finished_good_item": item, "top_bom": bom})
			with patch.object(M.MasterEngineeringRelease, "validate_finished_good", lambda self: None):
				m.get_items_from_bom()
				m.insert(ignore_permissions=True)
			return m

		with patch.object(M.MasterEngineeringRelease, "validate_finished_good", lambda self: None):
			m1 = make()
			row = m1.items[0]
			self.assertEqual(row.drawing, M.resolve_drawing(item))
			self.assertTrue(row.product_revision and row.engineering_release)
			self.assertIn(row.row_status, ("Linked", "Released"))
			er = row.engineering_release
			self.assertEqual(frappe.db.get_value("Engineering Release", er, "master_engineering_release"), m1.name)
			# second active Master: pull leaves the ER free-only (none) and linking it by hand is blocked
			m2 = make()
			self.assertNotEqual(m2.items[0].engineering_release, er)
			m2.items[0].engineering_release = er
			self.assertRaises(frappe.ValidationError, m2.save)
			# linked ER cannot be deleted
			self.assertRaises(frappe.ValidationError, frappe.delete_doc, "Engineering Release", er, ignore_permissions=True)
			# Connections: Drawing card lists the Master via the Items table
			from engineering_itagksa.connections import get_open_count
			cards = get_open_count("Engineering Drawing", row.drawing)["count"]["internal_links_found"]
			mer = [c for c in cards if c["doctype"] == "Master Engineering Release"][0]
			self.assertIn(m1.name, mer["names"])
			# draft delete clears the back-link
			frappe.delete_doc("Master Engineering Release", m1.name, ignore_permissions=True)
			self.assertFalse(frappe.db.get_value("Engineering Release", er, "master_engineering_release"))


class TestWorkflowSetup(unittest.TestCase):
	"""v15.2.1: Desk Workflow + email Notifications exist on the site (created by install.setup on migrate)."""

	def test_workflow_present(self):
		from engineering_itagksa import install

		name = install.MASTER_WORKFLOW_NAME
		self.assertTrue(frappe.db.exists("Workflow", name))
		wf = frappe.get_doc("Workflow", name)
		self.assertEqual((wf.document_type, wf.workflow_state_field, wf.is_active),
			("Master Engineering Release", "release_status", 1))
		self.assertEqual(frappe.get_meta("Master Engineering Release").get_workflow(), name)
		moves = {(t.state, t.action, t.next_state) for t in wf.transitions}
		self.assertTrue({("Draft", "Approve", "Approved"), ("Approved", "Return to Draft", "Draft"),
			("Approved", "Release for Production", "Released for Production")} <= moves)
		rfp_roles = {t.allowed for t in wf.transitions if t.next_state == "Released for Production"}
		self.assertEqual(rfp_roles, {"Engineering Manager Master"})
		# every Workflow move is also a controller transition (guards always apply)
		for t in wf.transitions:
			if (t.state, t.next_state) in M.TRANSITIONS:
				self.assertIn(t.allowed, M.TRANSITIONS[(t.state, t.next_state)])

	def test_notifications_present(self):
		from engineering_itagksa import install

		for n in install.MASTER_NOTIFICATIONS:
			d = frappe.get_doc("Notification", n["name"])
			self.assertEqual((d.document_type, d.event, d.value_changed, d.channel),
				("Master Engineering Release", "Value Change", "release_status", "Email"))
			self.assertTrue(d.recipients)


def run():
	suite = unittest.TestSuite()
	for cls in (TestBomTree, TestFinishedGoodFilter, TestRowStatusAndDuties, TestPrReleasedOnRfp, TestWorkflowSetup,
			TestIntegration):
		suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(cls))
	res = unittest.TextTestRunner(verbosity=2).run(suite)
	frappe.db.rollback()
	return {"run": res.testsRun, "failures": len(res.failures), "errors": len(res.errors)}
