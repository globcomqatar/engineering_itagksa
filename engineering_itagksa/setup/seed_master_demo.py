"""Master Engineering Release demo data (LOCAL BENCH ONLY, local dev site).

Seeds an active Product Revision (on the Item's Approved drawing, BOM referenced) for every manufacturing item of the
MER-DEMO cabinet tree, then re-pulls Items on the demo Draft Masters so they satisfy the row-readiness rule
(submitted BOM + Approved Drawing + Product Revision on every row).

Run:
  bench --site <site> execute engineering_itagksa.setup.seed_master_demo.run
Re-running is safe (existing Product Revisions reused, only advanced).
"""

import frappe

from engineering_itagksa.constants import APPROVED, RELEASE_READY, RELEASED, UNDER_REVIEW
from engineering_itagksa.engineering_itag_ksa.doctype.master_engineering_release import (
	master_engineering_release as M,
)
from engineering_itagksa.setup.seed_engineering_release import _ms_action, _set, _state, _submit, ensure_demo_submitter

FG = "MER-DEMO-FG"


def ensure_spec(item):
	"""v15.3.0: Material Specification has no Item Code; one per demo item, found by its seed description."""
	desc = f"{item} material specification (Master demo seed)."
	name = frappe.db.get_value("Material Specification", {"description": desc, "workflow_state": APPROVED}, "name") or \
		frappe.db.get_value("Material Specification", {"description": desc, "workflow_state": ["in", ["Draft", UNDER_REVIEW]]}, "name")
	if not name:
		name = frappe.get_doc({
			"doctype": "Material Specification", "description": desc,
			"applicable_standards": "ISO 9001", "material_requirements": "Per drawing",
			"testing_requirements": "Visual and dimensional inspection",
		}).insert().name
	if _state("Material Specification", name) == "Draft":
		_ms_action(name, "Submit for Review", ensure_demo_submitter())
	if _state("Material Specification", name) == UNDER_REVIEW:
		_ms_action(name, "Approve")
	return name


def ensure_pr(item, drawing, bom):
	name = frappe.db.get_value(
		"Product Revision", {"item": item, "docstatus": ["!=", 2]}, "name", order_by="creation desc",
	)
	if not name:
		spec = ensure_spec(item)
		name = frappe.get_doc({
			"doctype": "Product Revision", "item": item, "drawing_revision": drawing,
			"bom_revision_reference": bom, "interchangeability_decision": "Interchangeable",
			"material_specification": spec,
		}).insert().name
	if _state("Product Revision", name) in (None, "", "Draft"):
		_set("Product Revision", name, UNDER_REVIEW)
	if _state("Product Revision", name) == UNDER_REVIEW:
		_submit("Product Revision", name)
	if _state("Product Revision", name) == APPROVED:
		_set("Product Revision", name, RELEASE_READY)
	if _state("Product Revision", name) == RELEASE_READY:
		# v15.3.3: Released is system-only in the Product Revision Workflow (set by ER / MER Released for
		# Production via mark_released, a direct DB write); the demo seed writes it the same way.
		frappe.db.set_value("Product Revision", name, {"workflow_state": RELEASED, "release_readiness": "Ready"})
	return name


def run():
	top = frappe.db.get_value("BOM", {"item": FG, "docstatus": 1, "is_default": 1}, "name") or frappe.db.get_value(
		"BOM", {"item": FG, "docstatus": 1}, "name")
	prs = {}
	for n in M.get_bom_tree(top):
		drawing = M.resolve_drawing(n.item)
		if not drawing:
			frappe.throw(f"{n.item} has no Approved drawing (Engineering Item Request drawing or Item Design)")
		prs[n.item] = ensure_pr(n.item, drawing, n.bom)
	masters = {}
	for name in frappe.get_all("Master Engineering Release", filters={"finished_good_item": FG, "release_status": "Draft"},
			pluck="name", order_by="name"):
		m = frappe.get_doc("Master Engineering Release", name)
		m.get_items_from_bom()
		m.save()
		masters[name] = [(r.item, r.product_revision, r.row_status) for r in m.items]
	frappe.db.commit()
	return {"product_revisions": prs, "masters": masters}
