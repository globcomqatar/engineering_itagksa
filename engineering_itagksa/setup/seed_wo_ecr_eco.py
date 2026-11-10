"""LOCAL demo/test: start a Work Order -> ECR auto-raised -> (ECR approved) -> ECO auto-raised (v0.1.12).

LOCAL BENCH ONLY (local dev site). Run:
  bench --site <site> execute engineering_itagksa.setup.seed_wo_ecr_eco.run

The Work Order is started the real ERPNext way: a submitted Stock Entry "Material Transfer for Manufacture"
(erpnext make_stock_entry), which makes WorkOrder.update_status set status "In Process" -> on_change hook
raises the draft ECR. Raw materials are topped up with a demo Material Receipt only if Stores is short.
No Workflow is used (v15.1.31): the ECR is set Under Review and then submitted the standard ERPNext way
(Submit sets Approved); its on_submit hook raises the draft ECO. Re-running is safe: no duplicate transfer, ECR or ECO is created.
"""

import frappe
from frappe.utils import flt

from engineering_itagksa.setup.seed_demo import FG_ITEM

DEMO_WO = "MFG-WO-2026-00001"
ECR = "Engineering Change Request"
ECO = "Engineering Change Order"


def _find_wo():
	if frappe.db.exists("Work Order", {"name": DEMO_WO, "docstatus": 1}):
		return DEMO_WO
	wo = frappe.db.get_value("Work Order", {"production_item": FG_ITEM, "docstatus": 1,
		"status": ["in", ["Not Started", "In Process"]]}, "name", order_by="creation asc")
	if not wo:
		frappe.throw(f"No submitted Not Started / In Process Work Order for {FG_ITEM}; run seed_engineering_release first.")
	return wo


def _top_up_raw_materials(wo):
	rows = []
	for r in wo.required_items:
		need = flt(r.required_qty) - flt(r.transferred_qty)
		wh = r.source_warehouse or wo.source_warehouse
		have = flt(frappe.db.get_value("Bin", {"item_code": r.item_code, "warehouse": wh}, "actual_qty"))
		if need > 0 and have < need:
			rate = flt(frappe.db.get_value("Item", r.item_code, "valuation_rate")) or 100
			rows.append({"item_code": r.item_code, "qty": need - have, "t_warehouse": wh, "basic_rate": rate,
				"allow_zero_valuation_rate": 0})
	if not rows:
		return None
	se = frappe.get_doc({"doctype": "Stock Entry", "stock_entry_type": "Material Receipt", "purpose": "Material Receipt",
		"company": wo.company, "remarks": f"Demo raw material receipt to start {wo.name}", "items": rows})
	se.insert()
	se.submit()
	return se.name


def _start_work_order(wo_name):
	"""Real ERPNext start: Material Transfer for Manufacture. Skipped if already In Process / transferred."""
	from erpnext.manufacturing.doctype.work_order.work_order import make_stock_entry

	wo = frappe.get_doc("Work Order", wo_name)
	if wo.status != "Not Started":
		return None, None
	receipt = _top_up_raw_materials(wo)
	se = frappe.get_doc(make_stock_entry(wo.name, "Material Transfer for Manufacture", flt(wo.qty)))
	se.insert()
	se.submit()
	return receipt, se.name


def _review(doctype, name):
	"""Draft -> Under Review (plain Status field, normal Save)."""
	d = frappe.get_doc(doctype, name)
	d.workflow_state = "Under Review"
	d.save()
	return d


def _submit(doctype, name):
	"""Standard ERPNext Submit (controller sets Status Approved; on_submit hooks fire)."""
	d = frappe.get_doc(doctype, name)
	d.submit()
	return d


def run():
	wo_name = _find_wo()
	before = {"ecr": frappe.db.count(ECR, {"work_order": wo_name}), "eco": frappe.db.count(ECO, {"work_order": wo_name})}
	receipt, transfer = _start_work_order(wo_name)
	status = frappe.db.get_value("Work Order", wo_name, "status")
	assert status == "In Process", f"Work Order {wo_name} status is {status}, expected In Process"

	ecr = frappe.db.get_value(ECR, {"work_order": wo_name}, "name")
	assert ecr, "ECR was not raised on Work Order start"
	if frappe.db.get_value(ECR, ecr, "workflow_state") in (None, "", "Draft"):
		_review(ECR, ecr)
	if frappe.db.get_value(ECR, ecr, "workflow_state") == "Under Review":
		_submit(ECR, ecr)  # on_submit hook raises the ECO

	eco = frappe.db.get_value(ECO, {"source_ecr": ecr}, "name")
	assert eco, "ECO was not raised on ECR approval"
	e = frappe.db.get_value(ECO, eco, ["source_ecr", "work_order", "item", "workflow_state", "docstatus"], as_dict=True)
	r = frappe.db.get_value(ECR, ecr, ["work_order", "item", "affected_bom", "workflow_state", "docstatus"], as_dict=True)
	assert e.source_ecr == ecr, "ECO.source_ecr mismatch"
	assert r.work_order == wo_name, "ECR.work_order mismatch"
	assert e.work_order == wo_name, "ECO.work_order mismatch"
	n_ecr, n_eco = frappe.db.count(ECR, {"work_order": wo_name}), frappe.db.count(ECO, {"work_order": wo_name})
	assert n_ecr == 1 and n_eco == 1, f"duplicates: ECR={n_ecr} ECO={n_eco}"
	frappe.db.commit()

	print(f"Work Order : {wo_name} status={status}")
	print(f"Start      : material receipt={receipt or '-'} transfer={transfer or '- (already started)'}")
	print(f"ECR        : {ecr} item={r.item} bom={r.affected_bom} state={r.workflow_state} docstatus={r.docstatus}")
	print(f"ECO        : {eco} source_ecr={e.source_ecr} work_order={e.work_order} state={e.workflow_state} docstatus={e.docstatus}")
	print(f"Counts before run ECR={before['ecr']} ECO={before['eco']} -> after ECR={n_ecr} ECO={n_eco}")
	print("CHAIN OK")
	return {"work_order": wo_name, "ecr": ecr, "eco": eco, "transfer": transfer}


# --- v0.1.14: ECR approval -> Job Card On Hold -------------------------------------------------------
# Run: bench --site <site> execute engineering_itagksa.setup.seed_wo_ecr_eco.demo_hold_job_card
DEMO_OPERATION = "DEMO-ECR-HOLD-OP"
DEMO_WORKSTATION = "DEMO-ECR-HOLD-WS"


def _ensure_demo_job_card(wo_name):
	"""LOCAL demo only: the demo WO/BOM has no operations, so create a minimal Operation + Workstation and
	one draft Job Card against the WO (WO itself is not modified). Reuses an open draft JC if present."""
	existing = frappe.db.get_value("Job Card", {"work_order": wo_name, "docstatus": 0,
		"status": ["!=", "On Hold"]}, "name", order_by="creation asc")
	if existing:
		return existing, False
	if not frappe.db.exists("Workstation", DEMO_WORKSTATION):
		frappe.get_doc({"doctype": "Workstation", "workstation_name": DEMO_WORKSTATION}).insert(ignore_permissions=True)
	if not frappe.db.exists("Operation", DEMO_OPERATION):
		frappe.get_doc({"doctype": "Operation", "name": DEMO_OPERATION, "workstation": DEMO_WORKSTATION}).insert(
			ignore_permissions=True)
	wo = frappe.get_doc("Work Order", wo_name)
	jc = frappe.get_doc({
		"doctype": "Job Card",
		"work_order": wo.name,
		"production_item": wo.production_item,
		"bom_no": wo.bom_no,
		"company": wo.company,
		"operation": DEMO_OPERATION,
		"workstation": DEMO_WORKSTATION,
		"wip_warehouse": wo.wip_warehouse,
		"for_quantity": flt(wo.qty),
		"posting_date": frappe.utils.nowdate(),
		"remarks": "LOCAL demo Job Card for ECR approval -> On Hold",
	})
	jc.insert(ignore_permissions=True)
	return jc.name, True


def demo_hold_job_card():
	"""Ensure WO -> ECR (Approved) -> ECO chain via run(), ensure an open Job Card, then fire the real ECR
	on_submit handler (hold Job Cards + idempotent ECO) and assert the Job Card is On Hold."""
	from engineering_itagksa.work_order_change import on_ecr_submit

	chain = run()
	wo_name, ecr = chain["work_order"], chain["ecr"]
	jc_name, created = _ensure_demo_job_card(wo_name)
	before = frappe.db.get_value("Job Card", jc_name, "status")
	ecr_doc = frappe.get_doc(ECR, ecr)
	assert ecr_doc.workflow_state == "Approved", f"ECR {ecr} not Approved"
	on_ecr_submit(ecr_doc)  # same function the hook calls on ECR approval
	after = frappe.db.get_value("Job Card", jc_name, ["status", "docstatus"], as_dict=True)
	assert after.status == "On Hold" and after.docstatus == 0, f"Job Card {jc_name} status={after.status}"
	# idempotent re-fire: no error, still one ECO, JC stays On Hold
	on_ecr_submit(ecr_doc)
	assert frappe.db.count(ECO, {"source_ecr": ecr}) == 1
	assert frappe.db.get_value("Job Card", jc_name, "status") == "On Hold"
	frappe.db.commit()
	print(f"Job Card   : {jc_name} ({'created' if created else 'existing'}) {before} -> {after.status} docstatus={after.docstatus}")
	print("HOLD OK")
	return {**chain, "job_card": jc_name, "before": before, "after": after.status}


def demo_no_job_card():
	"""Behaviour check: hold logic on a WO with no Job Cards is a no-op (no error)."""
	from engineering_itagksa.work_order_change import hold_job_cards_for_ecr

	doc = frappe._dict(name="(no-jc check)", work_order="__NO_SUCH_WO__")
	res = hold_job_cards_for_ecr(doc)
	assert not res["held"] and not res["failed"]
	print(f"No Job Card: {res} -> no-op OK")
	return res


# --- v0.1.15: ECR approval -> JC On Hold + WO Stopped; ECO approval -> JC Work In Progress + WO re-opened -----
# Run: bench --site <site> execute engineering_itagksa.setup.seed_wo_ecr_eco.demo_stop_resume


def _prepare_eco_for_approval(eco_name, ecr_name):
	"""LOCAL demo only: fill the engineering-owned Controlled Changes on the auto-raised draft ECO."""
	eco = frappe.get_doc(ECO, eco_name)
	if not eco.controlled_changes:
		eco.append("controlled_changes", {"change_type": "Other",
			"change_description": f"LOCAL demo controlled change for {ecr_name}",
			"interchangeability": "Interchangeable", "stock_disposition": "Not Applicable"})
	eco.change_risk = eco.change_risk or "Low"
	eco.save()
	return eco


def demo_stop_resume():
	from engineering_itagksa.work_order_change import on_ecr_submit, release_work_order_for_eco

	wo_name = _find_wo()
	if frappe.db.get_value("Work Order", wo_name, "status") == "Stopped":
		frappe.throw(f"{wo_name} is Stopped; approve its ECO (or Re-open) before re-running the demo.")
	held = demo_hold_job_card()  # run() chain + Job Card + on_ecr_submit (now also stops the WO)
	ecr, eco, jc = held["ecr"], held["eco"], held["job_card"]
	s1 = {"wo": frappe.db.get_value("Work Order", wo_name, "status"),
		"jc": frappe.db.get_value("Job Card", jc, "status")}
	assert s1["wo"] == "Stopped", f"WO {wo_name} expected Stopped, got {s1['wo']}"
	assert s1["jc"] == "On Hold"
	on_ecr_submit(frappe.get_doc(ECR, ecr))  # idempotent re-fire
	assert frappe.db.get_value("Work Order", wo_name, "status") == "Stopped"
	print(f"ECR approve: WO {wo_name} -> {s1['wo']}, JC {jc} -> {s1['jc']}")

	state = frappe.db.get_value(ECO, eco, "workflow_state")
	if state in (None, "", "Draft"):
		_prepare_eco_for_approval(eco, ecr)
		_review(ECO, eco)
	if frappe.db.get_value(ECO, eco, "workflow_state") == "Under Review":
		_submit(ECO, eco)  # ECO on_submit hook -> on_eco_submit
	else:
		# ECO already approved on an earlier run: fire the same handler (idempotent)
		release_work_order_for_eco(eco)
	e = frappe.db.get_value(ECO, eco, ["workflow_state", "docstatus"], as_dict=True)
	s2 = {"wo": frappe.db.get_value("Work Order", wo_name, "status"),
		"jc": frappe.db.get_value("Job Card", jc, "status")}
	assert e.workflow_state == "Approved" and e.docstatus == 1, f"ECO {eco} {e}"
	assert s2["wo"] != "Stopped", f"WO {wo_name} still Stopped"
	assert s2["jc"] == "Work In Progress", f"JC {jc} {s2['jc']}"
	again = release_work_order_for_eco(eco)  # idempotent: nothing more to do
	assert not again["resumed"] and not again["failed"]
	frappe.db.commit()
	print(f"ECO approve: {eco} state={e.workflow_state} docstatus={e.docstatus}; WO {wo_name} -> {s2['wo']}, JC {jc} -> {s2['jc']}")
	print("STOP/RESUME OK")
	return {"work_order": wo_name, "ecr": ecr, "eco": eco, "job_card": jc, "after_ecr": s1, "after_eco": s2}
