"""Work Order start -> Engineering Change Request -> Engineering Change Order chain (v0.1.12).

Reuses the existing Engineering Change Request / Engineering Change Order DocTypes; linkage is via the
fixture Custom Fields `work_order` on both (module Engineering ITAG KSA). No core edits.

Chain:
  1. Work Order status transitions TO "In Process" (ERPNext start: submitted Material Transfer for
     Manufacture -> WorkOrder.update_status -> db_set("status") -> on_change) => one draft ECR is raised
     (item = production_item, work_order, affected_bom = bom_no). Idempotent per Work Order.
  2. The ECO controller (B7 governance) refuses an ECO whose source ECR is not submitted + Approved, so
     the ECO is raised automatically when that WO-linked ECR is Approved by standard Submit
     (ECR on_submit). One draft ECO per ECR (idempotent). Nothing is auto-submitted / auto-approved.
  3. (v0.1.14) On that same ECR approval, the source Work Order's open Job Card(s) are put "On Hold"
     (Work Order itself has no hold state). Only draft (docstatus 0) Job Cards not already On Hold are
     touched; a running time log is closed the ERPNext "Pause Job" way (make_time_log status On Hold).
     JobCard.set_status keeps "On Hold" while docstatus == 0. Nothing is submitted/cancelled. No Job
     Cards => no-op; ECO is still raised. Idempotent.
  4. (v0.1.15) On ECR approval the source Work Order is ALSO set to "Stopped" (after its Job Cards are held,
     since ERPNext blocks Job Card transactions against a Stopped WO). Same effect as the Desk "Stop" button
     (erpnext work_order.stop_unstop -> WorkOrder.update_status("Stopped") + update_planned_qty), without its
     user-permission check / msgprint so an Engineering approver without WO write rights still triggers it.
     Skipped if WO is already Stopped / Closed / Completed / Cancelled / not submitted. Comment added on WO.
  5. (v0.1.15) On ECO approval (standard Submit -> Status Approved, docstatus 1 => ECO on_submit), the
     reverse: the Work Order (ECO.work_order, else source ECR.work_order) is un-stopped the Desk "Re-open"
     way (update_status("Resumed") -> ERPNext recomputes Not Started / In Process / Completed), then the Job
     Cards this engineering change put On Hold are resumed via the Desk "Resume Job" path (add_time_log
     status "Resume Job" -> Work In Progress). Only Job Cards carrying our "Put On Hold: ... <ECR>" comment
     are resumed; Job Cards paused manually by the shop floor are left alone. WO is only un-stopped if it is
     currently Stopped (never touches Completed / Closed). Idempotent.
"""

import frappe
from frappe.utils import now_datetime

IN_PROCESS = "In Process"
ECR = "Engineering Change Request"
ECO = "Engineering Change Order"


def _log():
	return frappe.logger("engineering_itagksa")


def on_work_order_change(doc, method=None):
	"""Hooked on Work Order on_change (fires after save and after db_set, incl. ERPNext update_status)."""
	if doc.docstatus != 1 or doc.status != IN_PROCESS:
		return
	before = doc.get_doc_before_save()
	if before and before.get("status") == IN_PROCESS:
		return  # not a transition into In Process
	raise_ecr_for_work_order(doc)


def raise_ecr_for_work_order(wo):
	existing = frappe.db.get_value(ECR, {"work_order": wo.name}, "name")
	if existing:
		return existing
	ecr = frappe.get_doc({
		"doctype": ECR,
		"item": wo.production_item,
		"work_order": wo.name,
		"affected_bom": wo.bom_no or None,
		"urgency": "Medium",
		"description": f"Auto-raised on Work Order {wo.name} start (status {IN_PROCESS}).",
	})
	ecr.flags.ignore_permissions = True
	ecr.insert()
	_log().info(f"Work Order {wo.name} started: raised draft {ECR} {ecr.name}")
	return ecr.name


def on_ecr_submit(doc, method=None):
	"""Hooked on Engineering Change Request on_submit: Approved + WO-linked => raise draft ECO once."""
	if doc.get("workflow_state") != "Approved" or not doc.get("work_order"):
		return
	hold_job_cards_for_ecr(doc)  # before stopping: ERPNext refuses Job Card saves against a Stopped WO
	stop_work_order_for_ecr(doc)
	raise_eco_for_ecr(doc)


JC = "Job Card"
ON_HOLD = "On Hold"


def hold_job_cards_for_ecr(ecr):
	"""Put the source Work Order's open Job Card(s) On Hold. Accepts an ECR doc or name.

	Returns {"work_order", "held": [...], "skipped": {name: status}, "failed": {name: error}}.
	"""
	if isinstance(ecr, str):
		ecr = frappe.get_doc(ECR, ecr)
	wo = ecr.get("work_order")
	out = {"work_order": wo, "held": [], "skipped": {}, "failed": {}}
	if not wo:
		return out
	for jc in frappe.get_all(JC, filters={"work_order": wo, "docstatus": ["!=", 2]},
			fields=["name", "status", "docstatus"], order_by="creation asc"):
		if jc.docstatus != 0 or jc.status in (ON_HOLD, "Completed", "Cancelled", "Submitted"):
			out["skipped"][jc.name] = jc.status  # already held, or submitted/finished: leave as is
			continue
		try:
			_hold_job_card(jc.name, ecr.name)
			out["held"].append(jc.name)
		except Exception as e:
			out["failed"][jc.name] = str(e)
			frappe.log_error(title=f"ECR {ecr.name}: could not hold Job Card {jc.name}",
				message=frappe.get_traceback())
	if out["held"] or out["failed"]:
		_log().info(f"{ECR} {ecr.name} approved: Work Order {wo} Job Cards held={out['held']} failed={list(out['failed'])}")
	return out


def _hold_job_card(jc_name, ecr_name):
	jc = frappe.get_doc(JC, jc_name)
	jc.flags.ignore_permissions = True
	running = any(not r.to_time for r in (jc.time_logs or []))
	if running:
		# Same path as the Desk "Pause Job" button: closes the open time log and saves with status On Hold.
		# (JobCard.add_time_log is what the whitelisted make_time_log calls; it ends in self.save()).
		jc.add_time_log(frappe._dict({"status": ON_HOLD, "complete_time": now_datetime(), "completed_qty": 0}))
	else:
		jc.status = ON_HOLD  # set_status() preserves On Hold for docstatus 0
		jc.save()
	jc.add_comment("Info", f"Put On Hold: {ECR} {ecr_name} approved for Work Order {jc.work_order}.")


def raise_eco_for_ecr(ecr):
	existing = frappe.db.get_value(ECO, {"source_ecr": ecr.name}, "name")
	if existing:
		return existing
	company = frappe.db.get_value("Work Order", ecr.work_order, "company")
	eco = frappe.get_doc({
		"doctype": ECO,
		"source_ecr": ecr.name,
		"item": ecr.item,
		"work_order": ecr.work_order,
		"company": company,
		"impact_assessment": (
			f"Raised from {ECR} {ecr.name} (auto-raised on start of Work Order {ecr.work_order}). "
			"Engineering to define Controlled Changes before Submit for Review."
		),
	})
	eco.flags.ignore_permissions = True
	# Draft only: Controlled Changes (child table, interchangeability decision) are an engineering decision
	# and stay mandatory at save in Desk and at submit (validate_controlled_changes).
	eco.flags.ignore_mandatory = True
	eco.insert()
	_log().info(f"{ECR} {ecr.name} approved: raised draft {ECO} {eco.name} for Work Order {ecr.work_order}")
	return eco.name


# --- v0.1.15: ECR approval also stops the Work Order; ECO approval reverses both -------------------------
WO = "Work Order"
STOPPED = "Stopped"
WO_NO_STOP = (STOPPED, "Closed", "Completed", "Cancelled", "Draft")
HOLD_MARK = "Put On Hold: " + ECR + " {0} approved"


def stop_work_order_for_ecr(ecr):
	"""Desk "Stop" equivalent on ECR.work_order. Returns the WO status after the call (or None)."""
	if isinstance(ecr, str):
		ecr = frappe.get_doc(ECR, ecr)
	wo_name = ecr.get("work_order")
	if not wo_name or not frappe.db.exists(WO, wo_name):
		return None
	wo = frappe.get_doc(WO, wo_name)
	if wo.docstatus != 1 or wo.status in WO_NO_STOP:
		return wo.status  # idempotent / not stoppable
	wo.update_status(STOPPED)
	wo.update_planned_qty()
	wo.add_comment("Info", f"Stopped: {ECR} {ecr.name} approved (engineering change pending).")
	wo.notify_update()
	_log().info(f"{ECR} {ecr.name} approved: Work Order {wo_name} Stopped")
	return STOPPED


def on_eco_submit(doc, method=None):
	"""Hooked on Engineering Change Order on_submit (standard Submit -> Status Approved, docstatus 1)."""
	if doc.get("workflow_state") != "Approved":
		return
	release_work_order_for_eco(doc)


def _eco_context(eco):
	if isinstance(eco, str):
		eco = frappe.get_doc(ECO, eco)
	wo = eco.get("work_order") or (eco.get("source_ecr") and frappe.db.get_value(ECR, eco.source_ecr, "work_order"))
	return eco, wo


def release_work_order_for_eco(eco):
	"""Un-stop the WO (only if Stopped) then resume the Job Cards held for the source ECR.

	Returns {"work_order", "wo_status", "resumed": [...], "skipped": {...}, "failed": {...}}.
	"""
	eco, wo_name = _eco_context(eco)
	out = {"work_order": wo_name, "wo_status": None, "resumed": [], "skipped": {}, "failed": {}}
	if not wo_name or not frappe.db.exists(WO, wo_name):
		return out
	wo = frappe.get_doc(WO, wo_name)
	if wo.docstatus == 1 and wo.status == STOPPED:
		# Desk "Re-open" sends status "Resumed"; update_status recomputes the real status from stock entries.
		wo.update_status("Resumed")
		wo.update_planned_qty()
		wo.reload()
		wo.add_comment("Info", f"Re-opened: {ECO} {eco.name} approved (source {ECR} {eco.source_ecr}).")
		wo.notify_update()
		frappe.clear_document_cache(WO, wo_name)
	out["wo_status"] = frappe.db.get_value(WO, wo_name, "status")
	if out["wo_status"] == STOPPED:
		return out  # could not un-stop: leave Job Cards held

	for jc in frappe.get_all(JC, filters={"work_order": wo_name, "docstatus": 0, "status": ON_HOLD},
			fields=["name"], order_by="creation asc"):
		if not _held_for_ecr(jc.name, eco.source_ecr):
			out["skipped"][jc.name] = "On Hold (not held by this engineering change)"
			continue
		try:
			_resume_job_card(jc.name, eco)
			out["resumed"].append(jc.name)
		except Exception as e:
			out["failed"][jc.name] = str(e)
			frappe.log_error(title=f"ECO {eco.name}: could not resume Job Card {jc.name}",
				message=frappe.get_traceback())
	_log().info(f"{ECO} {eco.name} approved: Work Order {wo_name} -> {out['wo_status']} resumed={out['resumed']}")
	return out


def _held_for_ecr(jc_name, ecr_name):
	return bool(ecr_name) and frappe.db.exists("Comment", {"reference_doctype": JC, "reference_name": jc_name,
		"comment_type": "Info", "content": ["like", HOLD_MARK.format(ecr_name) + "%"]})


def _resume_job_card(jc_name, eco):
	jc = frappe.get_doc(JC, jc_name)
	jc.flags.ignore_permissions = True
	# Same path as the Desk "Resume Job" button (make_time_log -> add_time_log): opens a new time log and
	# reset_timer_value maps "Resume Job" -> "Work In Progress"; ends in self.save().
	jc.add_time_log(frappe._dict({
		"status": "Resume Job",
		"start_time": now_datetime(),
		"employees": [{"employee": e.employee} for e in (jc.employee or []) if e.employee],
	}))
	jc.add_comment("Info", f"Resumed: {ECO} {eco.name} approved for Work Order {jc.work_order}.")
