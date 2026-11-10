"""Idempotent LOCAL e2e seed: full Engineering Release path for DEMO-FG-VALVE-001, then Work Order submit.

LOCAL BENCH ONLY (local dev site). Requires seed_demo.run + seed_demo.create_draft_work_order first.
Product Revision (v15.3.3) has a Workflow; as Administrator its Save / Submit steps follow the Workflow
transitions (Released is written directly, as Engineering Release does). Engineering Release and
(v15.3.0) Engineering Drawing move through their Workflows via apply_workflow. v15.3.0: the Drawing has no Item
Code (numbered 500-5NNNN-1 on demo Item Component 500), so run() stops after the Drawing until Product
Revision / Engineering Release are revised for the new Drawing model. All
controller rules run: Spec supersede (soft #1), Drawing attestation stamping, Product Revision baseline,
Release checklist + Approval Matrix, Work Order gate (B5).

Run:
  bench --site <site> execute engineering_itagksa.setup.seed_engineering_release.run
  bench --site <site> execute engineering_itagksa.setup.seed_engineering_release.negative_checks
  bench --site <site> execute engineering_itagksa.setup.seed_engineering_release.verify
Re-running is safe: existing documents are reused and only advanced (Status / Submit), never duplicated.
"""

import frappe
from frappe.utils import add_to_date, now_datetime, nowdate

from engineering_itagksa.constants import (
	APPROVED,
	DRAFT,
	RELEASE_READY,
	RELEASED,
	RELEASED_FOR_PRODUCTION,
	ROLE_ENG_MANAGER,
	ROLE_ENG_MANAGER_MASTER,
	ROLE_ENG_USER,
	UNDER_REVIEW,
)
from engineering_itagksa.setup.seed_demo import FG_ITEM, ITEM_GROUP, _company


DRAWING_URL = "https://example.com/demo-valve-dwg.pdf"
# Demo value only (sha256 of the literal string "ERPCloud demo valve drawing A0"); operator-attested, not fetched.
DRAWING_SHA256 = "8212cd59373915861eaf1cb497b7a52a66e86a083f7d9da57807f429b98d03b2"
MATRIX_RULE = "DEMO-GQD Engineered Product Release"
CHECKLIST = [
	"Drawing released and checksum attested",
	"Material Specification approved",
	"BOM submitted and default",
	"Quality inspection requirements reviewed",
]


def _set(doctype, name, state, field="workflow_state"):
	"""Set the plain Status field and Save (draft or Update After Submit); controllers validate it."""
	d = frappe.get_doc(doctype, name)
	d.set(field, state)
	d.save()
	return d


def _submit(doctype, name):
	"""Standard ERPNext Submit (the controller sets the approved / released Status)."""
	d = frappe.get_doc(doctype, name)
	d.submit()
	return d


def _release_action(name, action):
	"""Engineering Release: apply a Workflow action (the only coded Workflow in the app)."""
	from frappe.model.workflow import apply_workflow

	return apply_workflow(frappe.get_doc("Engineering Release", name), action)


def _state(doctype, name, field="workflow_state"):
	return frappe.db.get_value(doctype, name, field)


def ensure_roles(user="Administrator"):
	u = frappe.get_doc("User", user)
	have = {r.role for r in u.roles}
	missing = [r for r in (ROLE_ENG_USER, ROLE_ENG_MANAGER, ROLE_ENG_MANAGER_MASTER, "Quality Manager", "Manufacturing Manager") if r not in have]
	if missing:
		u.add_roles(*missing)
	return missing


def ensure_matrix(company):
	if not frappe.db.exists("Engineering Approval Matrix", MATRIX_RULE):
		frappe.get_doc({
			"doctype": "Engineering Approval Matrix", "rule_name": MATRIX_RULE, "is_active": 1, "priority": 10,
			"applies_to": "Engineering Release", "company": company, "product_family": ITEM_GROUP,
			"effective_from": "2026-01-01",
			"required_disciplines": [
				{"sequence": 1, "discipline": "Design Engineering", "required_role": ROLE_ENG_MANAGER, "is_mandatory": 1},
				{"sequence": 2, "discipline": "Quality", "required_role": "Quality Manager", "is_mandatory": 1},
			],
		}).insert()
	return MATRIX_RULE


MS_DESC = "Demo gate valve 4in CL300 material specification (Engineering ITAG KSA seed)."


def _ms_action(name, action, user=None):
	"""Material Specification (v15.3.0): apply a Workflow action ("Engineering ITAG KSA Material Specification")."""
	from frappe.model.workflow import apply_workflow

	prev = frappe.session.user
	if user:
		frappe.set_user(user)
	try:
		return apply_workflow(frappe.get_doc("Material Specification", name), action)
	finally:
		frappe.set_user(prev)


def ensure_spec():
	"""v15.3.0: no Item Code; MSBV-NNNNN-0. Reused by its seed description (prefers the Approved one); Submit for
	Review (demo engineer) -> Approve (Administrator, a different user)."""
	name = (frappe.db.get_value("Material Specification", {"description": MS_DESC, "workflow_state": APPROVED}, "name")
		or frappe.db.get_value("Material Specification", {"description": MS_DESC, "workflow_state": ["in", [DRAFT, UNDER_REVIEW]]}, "name"))
	if not name:
		name = frappe.get_doc({
			"doctype": "Material Specification", "description": MS_DESC,
			"applicable_standards": "API 600; ASME B16.34; API 598",
			"material_requirements": "Body A216 WCB; Trim SS316",
			"pressure_limit": "CL300 (51.1 bar @ 38C)", "temperature_limit": "-29C to 425C",
			"testing_requirements": "Shell and seat test per API 598",
		}).insert().name
	if _state("Material Specification", name) == DRAFT:
		_ms_action(name, "Submit for Review", ensure_demo_submitter())
	if _state("Material Specification", name) == UNDER_REVIEW:
		_ms_action(name, "Approve")
	return name


DEMO_COMPONENT = "500"
DEMO_COMPONENT_NAME = "Demo Valve Body"
DRAWING_NAME = "Demo Gate Valve 4in CL300 - General Arrangement"
DEMO_SUBMITTER = "demo.eng.user@itagksa.localhost"


def ensure_demo_component():
	"""v15.3.0: drawings are numbered per Item Component ({component}-5NNNN-{revision})."""
	if not frappe.db.exists("Item Component", DEMO_COMPONENT):
		frappe.get_doc({"doctype": "Item Component", "part_code_prefix": DEMO_COMPONENT,
			"component_name": DEMO_COMPONENT_NAME, "item_group": ITEM_GROUP}).insert()
	return DEMO_COMPONENT


def ensure_demo_submitter():
	"""Local demo Engineering User who submits drawings for review (approval needs a different user)."""
	if not frappe.db.exists("User", DEMO_SUBMITTER):
		u = frappe.get_doc({"doctype": "User", "email": DEMO_SUBMITTER, "first_name": "Demo Engineer",
			"send_welcome_email": 0, "user_type": "System User"}).insert(ignore_permissions=True)
		u.add_roles(ROLE_ENG_USER)
	return DEMO_SUBMITTER


def _drawing_action(name, action, user=None):
	"""Engineering Drawing (v15.3.0): apply a Workflow action ("Engineering ITAG KSA Engineering Drawing")."""
	from frappe.model.workflow import apply_workflow

	prev = frappe.session.user
	if user:
		frappe.set_user(user)
	try:
		return apply_workflow(frappe.get_doc("Engineering Drawing", name), action)
	finally:
		frappe.set_user(prev)


def ensure_drawing():
	"""v15.3.0: no Item Code on the drawing; 500-5NNNN-0 (Revision is system-assigned), Submit for Review (demo engineer) -> Approve
	(Administrator, a different user). Reused by component + drawing name."""
	comp = ensure_demo_component()
	name = frappe.db.get_value("Engineering Drawing",
		{"item_component": comp, "drawing_name": DRAWING_NAME}, "name", order_by="creation desc")
	if not name:
		name = frappe.get_doc({
			"doctype": "Engineering Drawing", "drawing_name": DRAWING_NAME, "item_component": comp,
			"item_group": ITEM_GROUP, "drawing_type": "General Arrangement",
			"security_classification": "Internal", "applicable_standard": "ASME Y14.5",
			# link-only drawing: since v0.1.9 the SHA-256 is computed only from an attached local file, so a typed
			# hash is ignored and the demo drawing is not checksum-attested.
			"external_file_link": DRAWING_URL,
			"revision_date": nowdate(), "effective_date": nowdate(), "change_description": "Initial release (demo)",
		}).insert().name
	if _state("Engineering Drawing", name) in (None, "", "Draft"):
		_drawing_action(name, "Submit for Review", ensure_demo_submitter())
	if _state("Engineering Drawing", name) == UNDER_REVIEW:
		_drawing_action(name, "Approve")
	return name


def ensure_product_revision(spec, drawing, bom):
	name = frappe.db.get_value(
		"Product Revision", {"item": FG_ITEM, "docstatus": ["!=", 2]}, "name", order_by="creation desc",
	)
	if not name:
		name = frappe.get_doc({
			"doctype": "Product Revision", "item": FG_ITEM, "drawing_revision": drawing,
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


def ensure_release(company, pr, drawing, spec, bom):
	existing = frappe.get_all("Engineering Release", filters={"item": FG_ITEM, "product_revision": pr,
		"release_status": ["not in", ["Superseded", "Obsolete"]]}, pluck="name", order_by="creation desc", limit=1)
	if existing:
		name = existing[0]
	else:
		er = frappe.get_doc({
			"doctype": "Engineering Release", "release_classification": "Standard", "company": company,
			"effective_datetime": add_to_date(now_datetime(), minutes=-1), "item": FG_ITEM, "product_revision": pr,
			"drawing_revision": drawing, "material_specification": spec, "bom": bom,
			"applicable_standards": "API 600; ASME B16.34",
			"release_checklist": [{"checklist_item": c, "is_complete": 1} for c in CHECKLIST],
			"release_distribution": [{"recipient": "Administrator", "method": "System Notification"}],
		})
		er.insert()
		name = er.name
	field = "release_status"
	if _state("Engineering Release", name, field) in (None, "", "Draft"):
		_release_action(name, "Submit for Review")
	if _state("Engineering Release", name, field) == UNDER_REVIEW:
		_release_action(name, "Approve")  # Approval Matrix enforced here
	if _state("Engineering Release", name, field) == APPROVED:
		_release_action(name, "Release for Production")
	return name


def submit_work_order(company, bom):
	submitted = frappe.db.get_value("Work Order", {"production_item": FG_ITEM, "docstatus": 1, "company": company}, "name")
	if submitted:
		return submitted, "ALREADY SUBMITTED (reused)"
	wo_name = frappe.db.get_value("Work Order", {"production_item": FG_ITEM, "docstatus": 0, "company": company}, "name")
	if not wo_name:
		from engineering_itagksa.setup.seed_demo import create_draft_work_order
		wo_name = create_draft_work_order(company)["work_order"]
	wo = frappe.get_doc("Work Order", wo_name)
	wo.submit()
	return wo.name, f"SUBMITTED (status {wo.status}, engineering_release {wo.get('engineering_release')})"


def run(company=None):
	company = _company(company)
	bom = frappe.db.get_value("BOM", {"item": FG_ITEM, "docstatus": 1, "is_active": 1, "is_default": 1, "company": company}, "name")
	if not bom:
		frappe.throw("Run engineering_itagksa.setup.seed_demo.run first (no default BOM).")
	out = {"company": company, "bom": bom, "roles_added_to_Administrator": ensure_roles()}
	frappe.db.commit()
	out["approval_matrix"] = ensure_matrix(company); frappe.db.commit()
	out["material_specification"] = ensure_spec(); frappe.db.commit()
	out["engineering_drawing"] = ensure_drawing(); frappe.db.commit()
	# draft v0.1 (2026-11-10): Product Revision / Engineering Release accept an Approved drawing (no item_code /
	# Released state since v15.3.0), so the PR -> ER -> Work Order chain runs again.
	out["product_revision"] = ensure_product_revision(out["material_specification"], out["engineering_drawing"], bom); frappe.db.commit()
	out["engineering_release"] = ensure_release(company, out["product_revision"], out["engineering_drawing"], out["material_specification"], bom)
	frappe.db.commit()
	out["work_order"], out["work_order_result"] = submit_work_order(company, bom)
	frappe.db.commit()
	print(frappe.as_json(out))
	return out


def negative_checks(company=None):
	"""Each check runs inside a savepoint and is ALWAYS rolled back. Nothing persists."""
	company = _company(company)
	abbr = frappe.get_cached_value("Company", company, "abbr")
	bom = frappe.db.get_value("BOM", {"item": FG_ITEM, "docstatus": 1, "is_default": 1}, "name")
	res = {}

	def attempt(key, fn):
		frappe.db.savepoint("neg")
		try:
			fn()
			res[key] = "NOT BLOCKED (unexpected)"
		except Exception as e:
			res[key] = "BLOCKED: " + frappe.utils.strip_html(str(e)).strip()
		finally:
			frappe.db.rollback(save_point="neg")
			frappe.message_log = []

	# 1. WO gate without a Released-for-Production release (temporarily demote all releases in the savepoint)
	def wo_without_release():
		frappe.db.sql("update `tabEngineering Release` set release_status='Draft' where item=%s", FG_ITEM)
		wo = frappe.get_doc({"doctype": "Work Order", "production_item": FG_ITEM, "bom_no": bom, "qty": 1, "company": company,
			"wip_warehouse": f"Work In Progress - {abbr}", "fg_warehouse": f"Finished Goods - {abbr}",
			"source_warehouse": f"Stores - {abbr}"})
		wo.insert(); wo.submit()
	attempt("wo_submit_without_release", wo_without_release)

	# 2. A draft Drawing cannot be saved straight to Approved: only the Workflow (Under Review -> Approve) gets there
	def drawing_draft_approved():
		d = frappe.get_doc({"doctype": "Engineering Drawing", "drawing_name": "Negative check", "item_component": ensure_demo_component(),
			"revision": "Z9", "drawing_type": "Detail", "security_classification": "Internal", "external_file_link": DRAWING_URL})
		d.insert()
		d.workflow_state = APPROVED
		d.save()
	attempt("drawing_draft_saved_as_approved", drawing_draft_approved)

	print(frappe.as_json(res))
	return res


def verify(company=None):
	company = _company(company)
	out = {
		"material_specification": frappe.get_all("Material Specification", filters={"description": MS_DESC}, fields=["name", "revision", "workflow_state", "superseded_by"]),
		"engineering_drawing": frappe.get_all("Engineering Drawing", filters={"item_component": DEMO_COMPONENT},
			fields=["name", "drawing_name", "revision", "revises", "workflow_state", "superseded_by", "checksum_attested", "checksum_attested_by", "checksum_attested_on"]),
		"product_revision": frappe.get_all("Product Revision", filters={"item": FG_ITEM},
			fields=["name", "workflow_state", "docstatus", "release_readiness", "bom_revision_reference"]),
		"engineering_release": frappe.get_all("Engineering Release", filters={"item": FG_ITEM},
			fields=["name", "release_status", "product_revision", "bom", "approval_rule", "release_checksum", "effective_datetime"]),
		"approval_matrix": frappe.get_all("Engineering Approval Matrix", fields=["name", "applies_to", "is_active"]),
		"work_orders": frappe.get_all("Work Order", filters={"production_item": FG_ITEM},
			fields=["name", "docstatus", "status", "bom_no", "engineering_release"]),
	}
	print(frappe.as_json(out))
	return out


# ---------------------------------------------------------------------------------------------
# E2E gap closers (01-Nov-2026). Optional; idempotent.
# ---------------------------------------------------------------------------------------------
TEST_USER = "eng_user@local.test"


def _attempt(fn):
	"""Run fn in a savepoint; ALWAYS roll back. Returns 'BLOCKED: msg' or 'NOT BLOCKED'."""
	frappe.db.savepoint("gap")
	user = frappe.session.user
	try:
		fn()
		return "NOT BLOCKED (unexpected)"
	except Exception as e:
		return "BLOCKED: " + frappe.utils.strip_html(str(e)).strip()
	finally:
		frappe.set_user(user)
		frappe.db.rollback(save_point="gap")
		frappe.message_log = []


def gap_spec_supersede():
	"""Persistent: Create Revision of the Approved demo specification and approve it; the prior one must become
	Superseded in the same transaction (v15.3.0: same MSBV number, revision + 1)."""
	from engineering_itagksa.engineering_itag_ksa.doctype.material_specification.material_specification import (
		create_revision,
	)

	prior = ensure_spec()
	new = frappe.get_doc(create_revision(prior))
	new.description = MS_DESC
	new.insert()
	_ms_action(new.name, "Submit for Review", ensure_demo_submitter())
	_ms_action(new.name, "Approve")
	pre_commit = frappe.db.get_value("Material Specification", prior, "workflow_state")
	frappe.db.commit()
	p = frappe.db.get_value("Material Specification", prior, ["workflow_state", "superseded_by", "superseded_on"], as_dict=True)
	out = {"new": new.name, "new_state": _state("Material Specification", new.name), "prior": prior,
		"prior_state_before_commit": pre_commit, "prior_after": p,
		"PASS": _state("Material Specification", new.name) == APPROVED and p.workflow_state == "Superseded" and p.superseded_by == new.name}
	print(frappe.as_json(out))
	return out


def gap_bom_mismatch(company=None):
	"""Persistent alt BOM (non-default, submitted); WO with that BOM must be blocked by the gate (rolled back)."""
	company = _company(company)
	abbr = frappe.get_cached_value("Company", company, "abbr")
	rel = frappe.db.get_value("Engineering Release", {"item": FG_ITEM, "release_status": RELEASED_FOR_PRODUCTION}, "bom")
	alt = frappe.db.get_value("BOM", {"item": FG_ITEM, "docstatus": 1, "name": ["!=", rel]}, "name")
	if not alt:
		src = frappe.get_doc("BOM", rel)
		b = frappe.get_doc({"doctype": "BOM", "item": FG_ITEM, "company": company, "quantity": 1,
			"is_active": 1, "is_default": 0, "rm_cost_as_per": "Valuation Rate",
			"items": [{"item_code": i.item_code, "qty": i.qty * 2, "uom": i.uom, "rate": i.rate} for i in src.items]})
		b.insert(); b.submit(); alt = b.name
		frappe.db.commit()
	if frappe.db.get_value("BOM", rel, "is_default") != 1:
		frappe.throw("Released BOM is no longer default; aborting")

	def wo_alt():
		wo = frappe.get_doc({"doctype": "Work Order", "production_item": FG_ITEM, "bom_no": alt, "qty": 1, "company": company,
			"wip_warehouse": f"Work In Progress - {abbr}", "fg_warehouse": f"Finished Goods - {abbr}",
			"source_warehouse": f"Stores - {abbr}"})
		wo.insert(); wo.submit()
	r = _attempt(wo_alt)
	out = {"release_bom": rel, "alt_bom": alt, "result": r, "PASS": r.startswith("BLOCKED") and "does not match" in r}
	print(frappe.as_json(out))
	return out


def _ensure_test_user(roles):
	if not frappe.db.exists("User", TEST_USER):
		frappe.get_doc({"doctype": "User", "email": TEST_USER, "first_name": "Eng Test User", "enabled": 1,
			"send_welcome_email": 0, "user_type": "System User"}).insert(ignore_permissions=True)
	u = frappe.get_doc("User", TEST_USER)
	u.enabled = 1
	u.set("roles", [])
	u.add_roles(*roles)
	return u


def gap_matrix_refusal(company=None):
	"""Test user with Engineering User only (and a second variant with Engineering Manager but no
	Quality Manager) applies the Approve Workflow action on an Under Review Engineering Release. All in savepoints; user disabled after."""
	company = _company(company)
	rel = frappe.get_doc("Engineering Release", frappe.db.get_value("Engineering Release",
		{"item": FG_ITEM, "release_status": RELEASED_FOR_PRODUCTION}, "name"))

	def make_under_review():
		er = frappe.get_doc({
			"doctype": "Engineering Release", "release_classification": "Standard", "company": company,
			"effective_datetime": add_to_date(now_datetime(), minutes=-1), "item": FG_ITEM,
			"product_revision": rel.product_revision, "drawing_revision": rel.drawing_revision,
			"material_specification": rel.material_specification, "bom": rel.bom,
			"applicable_standards": "API 600",
			"release_checklist": [{"checklist_item": c, "is_complete": 1} for c in CHECKLIST],
			"release_distribution": [{"recipient": "Administrator", "method": "System Notification"}],
		})
		er.insert()
		_release_action(er.name, "Submit for Review")
		return er.name

	res = {}
	for key, roles in (("eng_user_only", [ROLE_ENG_USER]), ("eng_manager_without_quality", [ROLE_ENG_USER, ROLE_ENG_MANAGER])):
		def go(roles=roles):
			_ensure_test_user(roles)
			name = make_under_review()
			frappe.set_user(TEST_USER)
			_release_action(name, "Approve")
		res[key] = _attempt(go)
	# leave test user existing but DISABLED with no roles (safer than delete; nothing else persisted)
	u = _ensure_test_user([])
	u.enabled = 0
	u.save(ignore_permissions=True)
	frappe.db.commit()
	res["test_user_final"] = frappe.db.get_value("User", TEST_USER, ["enabled"], as_dict=True)
	res["PASS"] = all(res[k].startswith("BLOCKED") for k in ("eng_user_only", "eng_manager_without_quality"))
	print(frappe.as_json(res))
	return res


def run_gaps(company=None):
	return {"spec_supersede": gap_spec_supersede(), "bom_mismatch": gap_bom_mismatch(company),
		"matrix_refusal": gap_matrix_refusal(company)}
