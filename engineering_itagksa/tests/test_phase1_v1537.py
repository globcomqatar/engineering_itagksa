"""v15.3.7 Phase 1 tests (DB, rolled back after each test).

A. Engineering Drawing Type master + per-component Allowed Drawing Types (query + server check).
B. Item Component Attributes -> Item Request attribute rows (order, Mandatory), allowed values, mandatory at submit.
C. Item Name / Description built from Component Name, attribute values and Special Details.
D. Drawing number without a file; file or link required from Reviewed on.
E. Delete only a Prepared drawing never sent for review.
F. Drawing / Material Specification states Prepared / Reviewed; Product Revision keeps Draft / Under Review.
Run: bench --site <site> run-tests --module engineering_itagksa.tests.test_phase1_v1537
"""

import unittest

import frappe
from frappe.model.workflow import apply_workflow

from engineering_itagksa import install as I
from engineering_itagksa.engineering_itag_ksa.doctype.engineering_item_request import engineering_item_request as EIR
from engineering_itagksa.engineering_itag_ksa.doctype.item_component import item_component as IC

GROUP = "ZZ P1 Group"
COMP = "Z71"
COMP2 = "Z72"
USERS = {
	"zz.p1.user@example.com": ("Engineering User",),
	"zz.p1.mgr@example.com": ("Engineering Manager", "Engineering User"),
	"zz.p1.mgr2@example.com": ("Engineering Manager",),
}
EU, EM, EM2 = list(USERS)


def _as(user, fn):
	prev = frappe.session.user
	frappe.set_user(user)
	try:
		return fn()
	finally:
		frappe.set_user(prev)


def _attr(name, values):
	if frappe.db.exists("Item Spec Attribute", name):
		return frappe.get_doc("Item Spec Attribute", name)
	return frappe.get_doc({"doctype": "Item Spec Attribute", "attribute_name": name,
		"item_spec_attribute_values": [{"attribute_value": v} for v in values]}).insert()


class Phase1Base(unittest.TestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		if not frappe.db.exists("Item Group", "All Item Groups"):
			frappe.get_doc({"doctype": "Item Group", "item_group_name": "All Item Groups", "is_group": 1}).insert()
		if not frappe.db.exists("Item Group", GROUP):
			frappe.get_doc({"doctype": "Item Group", "item_group_name": GROUP, "parent_item_group": "All Item Groups"}).insert()
		if not frappe.db.exists("UOM", "Nos"):
			frappe.get_doc({"doctype": "UOM", "uom_name": "Nos"}).insert()
		I.ensure_drawing_types()
		_attr("ZZ P1 Size", ["2in", "4in"])
		_attr("ZZ P1 Class", ["150", "300"])
		_attr("ZZ P1 Extra", ["X1"])
		self.comp = frappe.get_doc({"doctype": "Item Component", "part_code_prefix": COMP, "component_name": "ZZ Gate Valve",
			"item_group": GROUP,
			"attributes": [{"attribute": "ZZ P1 Size", "mandatory": 1}, {"attribute": "ZZ P1 Class", "mandatory": 0}],
			"allowed_drawing_types": [{"drawing_type": "Welding"}, {"drawing_type": "Forging"}]}).insert()
		self.comp2 = frappe.get_doc({"doctype": "Item Component", "part_code_prefix": COMP2, "component_name": "ZZ Bonnet",
			"item_group": GROUP, "attributes": [{"attribute": "ZZ P1 Extra", "mandatory": 1}]}).insert()
		for email, roles in USERS.items():
			if not frappe.db.exists("User", email):
				u = frappe.get_doc({"doctype": "User", "email": email, "first_name": email.split("@")[0],
					"send_welcome_email": 0, "user_type": "System User"}).insert(ignore_permissions=True)
				u.add_roles(*roles)

	def tearDown(self):
		frappe.db.rollback()
		frappe.set_user("Administrator")
		frappe.clear_messages()

	def drawing(self, **kw):
		d = {"doctype": "Engineering Drawing", "item_component": COMP, "drawing_type": "Welding", "description": "P1 drawing"}
		d.update(kw)
		return frappe.get_doc(d)

	def eir(self, **kw):
		d = {"doctype": "Engineering Item Request", "item_group": GROUP, "item_component": COMP, "stock_uom": "Nos",
			"eng_item_category": "Manufacturing"}
		d.update(kw)
		return frappe.get_doc(d)


class TestA_DrawingTypes(Phase1Base):
	def test_seeded_types(self):
		for t in I.DEFAULT_DRAWING_TYPES:
			self.assertEqual(frappe.db.get_value("Engineering Drawing Type", t, "enabled"), 1)
		I.ensure_drawing_types()  # idempotent
		self.assertEqual(frappe.db.count("Engineering Drawing Type", {"name": ["in", list(I.DEFAULT_DRAWING_TYPES)]}), 6)

	def test_drawing_type_is_link(self):
		df = frappe.get_meta("Engineering Drawing").get_field("drawing_type")
		self.assertEqual((df.fieldtype, df.options, df.reqd), ("Link", "Engineering Drawing Type", 1))

	def test_query_uses_component_allowed_types(self):
		q = lambda comp, txt="": [r[0] for r in IC.drawing_type_query("Engineering Drawing Type", txt, "name", 0, 20,  # noqa: E731
			{"item_component": comp})]
		self.assertEqual(q(COMP), ["Welding", "Forging"])
		self.assertEqual(q(COMP, "forg"), ["Forging"])
		all_enabled = q(COMP2)
		self.assertTrue(set(I.DEFAULT_DRAWING_TYPES) <= set(all_enabled))
		frappe.db.set_value("Engineering Drawing Type", "Coating", "enabled", 0)
		self.assertNotIn("Coating", q(COMP2))

	def test_server_enforces_allowed_types(self):
		self.assertRaises(frappe.ValidationError, self.drawing(drawing_type="Manufacturing").insert)
		self.assertTrue(self.drawing(drawing_type="Forging").insert().name.startswith(f"{COMP}-5"))
		frappe.db.set_value("Engineering Drawing Type", "Coating", "enabled", 0)
		self.assertRaises(frappe.ValidationError, self.drawing(item_component=COMP2, drawing_type="Coating").insert)
		self.assertTrue(self.drawing(item_component=COMP2, drawing_type="Cladding").insert().name)

	def test_unchanged_legacy_type_still_saves(self):
		d = self.drawing().insert()
		if not frappe.db.exists("Engineering Drawing Type", "General Arrangement"):
			frappe.get_doc({"doctype": "Engineering Drawing Type", "drawing_type_name": "General Arrangement", "enabled": 0}).insert()
		frappe.db.set_value("Engineering Drawing", d.name, "drawing_type", "General Arrangement")
		d = frappe.get_doc("Engineering Drawing", d.name)
		d.change_description = "edit keeps legacy type"
		d.save()
		self.assertEqual(d.drawing_type, "General Arrangement")

	def test_duplicate_rows_on_component_refused(self):
		self.comp.append("allowed_drawing_types", {"drawing_type": "Welding"})
		self.assertRaises(frappe.ValidationError, self.comp.save)

	def test_drawing_type_permissions(self):
		self.assertTrue(frappe.has_permission("Engineering Drawing Type", "create", user=EM))
		self.assertTrue(frappe.has_permission("Engineering Drawing Type", "delete", user=EM))
		self.assertFalse(frappe.has_permission("Engineering Drawing Type", "create", user=EU))
		self.assertTrue(frappe.has_permission("Engineering Drawing Type", "read", user=EU))


class TestB_Attributes(Phase1Base):
	def test_component_attributes_api(self):
		rows = IC.get_component_attributes(COMP)
		self.assertEqual([(r.attribute, r.mandatory) for r in rows], [("ZZ P1 Size", 1), ("ZZ P1 Class", 0)])

	def test_autofill_order_and_flags(self):
		e = self.eir(item_request_attribute=[{"item_attribute": "ZZ P1 Class", "attribute_value": "300"},
			{"item_attribute": "ZZ P1 Extra", "attribute_value": "X1"}]).insert()
		got = [(r.item_attribute, r.attribute_value, r.mandatory, r.from_component) for r in e.item_request_attribute]
		self.assertEqual(got, [("ZZ P1 Size", None, 1, 1), ("ZZ P1 Class", "300", 0, 1), ("ZZ P1 Extra", "X1", 0, 0)])

	def test_component_change_replaces_auto_rows(self):
		e = self.eir(item_request_attribute=[{"item_attribute": "ZZ P1 Size", "attribute_value": "2in"}]).insert()
		e.item_component = COMP2
		e.save()
		self.assertEqual([r.item_attribute for r in e.item_request_attribute], ["ZZ P1 Extra"])

	def test_value_must_be_allowed(self):
		e = self.eir(item_request_attribute=[{"item_attribute": "ZZ P1 Size", "attribute_value": "3in"}])
		self.assertRaises(frappe.ValidationError, e.insert)

	def test_value_dropdown_source(self):
		self.assertEqual(EIR.get_item_spec_attribute_values(parent="ZZ P1 Size"), ["2in", "4in"])
		self.assertEqual(EIR.get_item_spec_attribute_values(parent="ZZ P1 Size", txt="4"), ["4in"])
		df = frappe.get_meta("Item Request Attribute").get_field("attribute_value")
		self.assertEqual(df.fieldtype, "Autocomplete")

	def test_mandatory_before_submit_and_item_rows(self):
		e = self.eir().insert()  # optional + mandatory empty: draft saves
		self.assertRaises(frappe.ValidationError, e.submit)
		e = frappe.get_doc("Engineering Item Request", e.name)
		e.item_request_attribute[0].attribute_value = "4in"
		e.save()
		e.submit()
		self.assertTrue(e.created_item)
		rows = frappe.get_all("Engineering Item Attribute", filters={"parent": e.created_item}, fields=["item_attribute", "attribute_value"])
		self.assertEqual([(r.item_attribute, r.attribute_value) for r in rows], [("ZZ P1 Size", "4in")])

	def test_manual_row_needs_value(self):
		e = self.eir(item_component=None, special_details="x", item_request_attribute=[{"item_attribute": "ZZ P1 Extra"}])
		self.assertRaises(frappe.ValidationError, e.insert)


class TestC_NameDescription(Phase1Base):
	def test_built_name_and_description(self):
		e = self.eir(special_details="  NACE   MR0175 ", item_name="typed is ignored", item_request_attribute=[
			{"item_attribute": "ZZ P1 Class", "attribute_value": "300"}, {"item_attribute": "ZZ P1 Size", "attribute_value": "4in"}]).insert()
		self.assertEqual(e.item_name, "ZZ Gate Valve")  # Owner 2026-11-21: short Component Name only
		self.assertEqual(e.description, "ZZ Gate Valve, 4in, 300, NACE MR0175")
		meta = frappe.get_meta("Engineering Item Request")
		self.assertTrue(meta.get_field("item_name").read_only and meta.get_field("description").read_only)
		self.assertEqual(meta.get_field("special_details").fieldtype, "Small Text")
		e.submit()
		item = frappe.db.get_value("Item", e.created_item, ["item_name", "description"], as_dict=True)
		self.assertEqual((item.item_name, item.description), (e.item_name, e.description))

	def test_long_description_not_truncated(self):
		long = "L" * 200
		e = self.eir(special_details=long, item_request_attribute=[{"item_attribute": "ZZ P1 Size", "attribute_value": "2in"},
			{"item_attribute": "ZZ P1 Extra", "attribute_value": "X1"}]).insert()
		self.assertEqual(e.item_name, "ZZ Gate Valve")
		self.assertEqual(e.description, f"ZZ Gate Valve, 2in, X1, {long}")  # manual row after component rows

	def test_component_item_group_optional(self):
		self.assertFalse(frappe.get_meta("Item Component").get_field("item_group").reqd)
		c = frappe.get_doc({"doctype": "Item Component", "part_code_prefix": "Z73", "component_name": "ZZ No Group"}).insert()
		e = self.eir(item_component=c.name, special_details="x").insert()
		self.assertEqual(e.item_name, "ZZ No Group")
		d = self.drawing(item_component=c.name, drawing_type="Manufacturing").insert()
		self.assertTrue(d.name.startswith("Z73-50001-"))

	def test_sequence_restarts_per_component(self):
		a = self.drawing().insert()
		b = self.drawing(item_component=COMP2, drawing_type="Manufacturing").insert()
		self.assertEqual((a.name, b.name), (f"{COMP}-50001-0", f"{COMP2}-50001-0"))
		self.assertEqual(self.drawing().insert().name, f"{COMP}-50002-0")

	def test_drawing_name_removed(self):
		meta = frappe.get_meta("Engineering Drawing")
		self.assertFalse(meta.has_field("drawing_name"))
		self.assertTrue(meta.get_field("description").reqd)
		self.assertNotIn("drawing_name", meta.search_fields or "")
		self.assertNotEqual(meta.title_field, "drawing_name")


class TestD_DrawingWithoutFile(Phase1Base):
	def test_number_without_file_and_file_needed_for_review(self):
		d = _as(EU, lambda: self.drawing().insert())
		self.assertEqual((d.workflow_state, d.revision), ("Prepared", "0"))
		self.assertTrue(d.name.startswith(f"{COMP}-5"))
		self.assertRaises(frappe.ValidationError, lambda: _as(EU, lambda: apply_workflow(frappe.get_doc("Engineering Drawing", d.name), "Submit for Review")))
		d = frappe.get_doc("Engineering Drawing", d.name)
		d.external_file_link = "https://dms.example.local/p1.pdf"
		d.save()
		_as(EU, lambda: apply_workflow(frappe.get_doc("Engineering Drawing", d.name), "Submit for Review"))
		self.assertEqual(frappe.db.get_value("Engineering Drawing", d.name, "workflow_state"), "Reviewed")
		_as(EM, lambda: apply_workflow(frappe.get_doc("Engineering Drawing", d.name), "Approve"))
		self.assertEqual(frappe.db.get_value("Engineering Drawing", d.name, "workflow_state"), "Approved")

	def test_description_required(self):
		self.assertRaises(frappe.ValidationError, self.drawing(description=None).insert)


class TestE_DeleteDraft(Phase1Base):
	def test_permissions(self):
		self.assertTrue(frappe.has_permission("Engineering Drawing", "delete", user=EU))
		self.assertTrue(frappe.has_permission("Engineering Drawing", "delete", user=EM))

	def test_delete_prepared_never_reviewed(self):
		d = _as(EU, lambda: self.drawing().insert())
		_as(EU, lambda: frappe.delete_doc("Engineering Drawing", d.name))
		self.assertFalse(frappe.db.exists("Engineering Drawing", d.name))
		nxt = self.drawing().insert()
		self.assertNotEqual(nxt.name, d.name)  # number consumed, not reissued

	def test_delete_refused_after_review(self):
		d = self.drawing(external_file_link="https://dms.example.local/p1.pdf").insert()
		_as(EU, lambda: apply_workflow(frappe.get_doc("Engineering Drawing", d.name), "Submit for Review"))
		self.assertRaises(frappe.ValidationError, lambda: frappe.delete_doc("Engineering Drawing", d.name))
		_as(EM, lambda: apply_workflow(frappe.get_doc("Engineering Drawing", d.name), "Return to Prepared"))
		self.assertEqual(frappe.db.get_value("Engineering Drawing", d.name, "workflow_state"), "Prepared")
		self.assertFalse(frappe.db.get_value("Engineering Drawing", d.name, "submitted_for_review_on"))
		self.assertEqual(frappe.db.get_value("Engineering Drawing", d.name, "sent_for_review"), 1)
		self.assertRaises(frappe.ValidationError, lambda: _as(EU, lambda: frappe.delete_doc("Engineering Drawing", d.name)))
		_as(EU, lambda: apply_workflow(frappe.get_doc("Engineering Drawing", d.name), "Submit for Review"))
		_as(EM, lambda: apply_workflow(frappe.get_doc("Engineering Drawing", d.name), "Approve"))
		self.assertRaises(frappe.ValidationError, lambda: frappe.delete_doc("Engineering Drawing", d.name))

	def test_delete_blocked_when_linked(self):
		d = self.drawing().insert()
		self.eir(engineering_drawing=d.name, item_request_attribute=[{"item_attribute": "ZZ P1 Size", "attribute_value": "2in"}]).insert()
		self.assertRaises(frappe.LinkExistsError, lambda: frappe.delete_doc("Engineering Drawing", d.name))


class TestF_States(Phase1Base):
	def test_select_options_and_workflows(self):
		for dt, wf in (("Engineering Drawing", I.DRAWING_WORKFLOW_NAME), ("Material Specification", I.MS_WORKFLOW_NAME)):
			df = frappe.get_meta(dt).get_field("workflow_state")
			self.assertEqual(df.options.split("\n"), ["Prepared", "Reviewed", "Approved", "Superseded", "Obsolete"])
			self.assertEqual(df.default, "Prepared")
			w = frappe.get_doc("Workflow", wf)
			self.assertEqual([s.state for s in w.states], ["Prepared", "Reviewed", "Approved", "Superseded", "Obsolete"])
			self.assertIn(("Reviewed", "Return to Prepared", "Prepared"), {(t.state, t.action, t.next_state) for t in w.transitions})
		pr = frappe.get_doc("Workflow", I.PR_WORKFLOW_NAME)
		self.assertEqual([s.state for s in pr.states][:2], ["Draft", "Under Review"])

	def test_material_specification_flow(self):
		ms = _as(EU, lambda: frappe.get_doc({"doctype": "Material Specification", "description": "ZZ P1 MS"}).insert())
		self.assertEqual(ms.workflow_state, "Prepared")
		_as(EU, lambda: apply_workflow(frappe.get_doc("Material Specification", ms.name), "Submit for Review"))
		self.assertEqual(frappe.db.get_value("Material Specification", ms.name, "workflow_state"), "Reviewed")
		_as(EM, lambda: apply_workflow(frappe.get_doc("Material Specification", ms.name), "Approve"))
		self.assertEqual(frappe.db.get_value("Material Specification", ms.name, "workflow_state"), "Approved")

	def test_sent_for_review_backfill_patch(self):
		from engineering_itagksa.patches.v15_3_7 import backfill_drawing_sent_for_review as P

		d = self.drawing(external_file_link="https://dms.example.local/p1.pdf").insert()
		_as(EU, lambda: apply_workflow(frappe.get_doc("Engineering Drawing", d.name), "Submit for Review"))
		frappe.db.set_value("Engineering Drawing", d.name, "sent_for_review", 0)
		fresh = self.drawing().insert()
		P.execute()
		self.assertEqual(frappe.db.get_value("Engineering Drawing", d.name, "sent_for_review"), 1)
		self.assertEqual(frappe.db.get_value("Engineering Drawing", fresh.name, "sent_for_review"), 0)

	def test_rename_patch_idempotent(self):
		from engineering_itagksa.patches.v15_3_7 import rename_drawing_ms_states as P

		d = self.drawing().insert()
		frappe.db.set_value("Engineering Drawing", d.name, "workflow_state", "Draft")
		P.execute()
		P.execute()
		self.assertEqual(frappe.db.get_value("Engineering Drawing", d.name, "workflow_state"), "Prepared")

	def test_revision_supersede_still_works(self):
		from engineering_itagksa.engineering_itag_ksa.doctype.engineering_drawing.engineering_drawing import create_revision

		a = self.drawing(external_file_link="https://dms.example.local/a.pdf").insert()
		_as(EU, lambda: apply_workflow(frappe.get_doc("Engineering Drawing", a.name), "Submit for Review"))
		_as(EM, lambda: apply_workflow(frappe.get_doc("Engineering Drawing", a.name), "Approve"))
		rev = create_revision(a.name)
		self.assertEqual((rev["workflow_state"], rev["description"], rev["drawing_type"]), ("Prepared", "P1 drawing", "Welding"))
		b = _as(EU, lambda: frappe.get_doc(dict(rev, external_file_link="https://dms.example.local/b.pdf")).insert())
		self.assertEqual(b.name, a.name.rsplit("-", 1)[0] + "-1")
		_as(EU, lambda: apply_workflow(frappe.get_doc("Engineering Drawing", b.name), "Submit for Review"))
		_as(EM2, lambda: apply_workflow(frappe.get_doc("Engineering Drawing", b.name), "Approve"))
		self.assertEqual(frappe.db.get_value("Engineering Drawing", a.name, ["workflow_state", "superseded_by"]), ("Superseded", b.name))
