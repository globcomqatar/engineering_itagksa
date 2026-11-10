"""Idempotent setup run on after_install and after_migrate: Engineering roles, the Engineering Release
approval Workflow, link backfills, settings.

v15.1.32: a Workflow is created in code -- "Engineering ITAG KSA Engineering Release" on Engineering Release
(``release_status``), for the release approval process (Owner request). ECR and ECO keep plain Select
``workflow_state`` fields (Product Revision has its own Workflow since v15.3.3, a copy of the Drawing one)
driven by standard Save / Submit / Cancel. send_email_alert=0 (no automatic workflow e-mail, POL-EML / B9).

v15.2.1 (Owner CLEAR 2026-11-04): a second Workflow, "Engineering ITAG KSA Master Engineering Release" on Master Engineering
Release (``release_status``), plus Desk Notifications (email) on Approved / Released for Production / Return to
Draft. Both are created ONLY when missing, so changes the Owner makes on Desk (transitions, roles, recipients,
message) survive every migrate. The controller still enforces roles + segregation of duties on every move.
"""

import frappe

from engineering_itagksa import constants as C

EU, EM, EMM = C.ROLE_ENG_USER, C.ROLE_ENG_MANAGER, C.ROLE_ENG_MANAGER_MASTER
SM = "System Manager"

# Coded Workflow for Engineering Release approval. Engineering Release is not submittable,
# so every state is docstatus 0.
RELEASE_WORKFLOW_NAME = "Engineering ITAG KSA Engineering Release"
RELEASE_WORKFLOW_DOCTYPE = "Engineering Release"
RELEASE_WORKFLOW_FIELD = "release_status"
RELEASE_STATES = [
	# (state, doc_status, allow_edit, style)
	(C.DRAFT, 0, EU, ""),
	(C.UNDER_REVIEW, 0, EM, "Warning"),
	(C.APPROVED, 0, EM, "Success"),
	(C.RELEASED_FOR_PRODUCTION, 0, EMM, "Primary"),
	(C.SUPERSEDED, 0, SM, "Inverse"),
	(C.OBSOLETE, 0, SM, "Inverse"),
]
# (state, action, next_state, allowed roles, allow_self_approval)
RELEASE_TRANSITIONS = [
	(C.DRAFT, "Submit for Review", C.UNDER_REVIEW, (EU, EM), 1),
	(C.UNDER_REVIEW, "Return to Draft", C.DRAFT, (EM,), 1),
	(C.UNDER_REVIEW, "Approve", C.APPROVED, (EM,), 0),
	(C.APPROVED, "Return to Draft", C.DRAFT, (EM,), 1),
	(C.APPROVED, "Release for Production", C.RELEASED_FOR_PRODUCTION, (EMM,), 1),  # v15.1.34: EMM only
	(C.RELEASED_FOR_PRODUCTION, "Mark Obsolete", C.OBSOLETE, (EM,), 1),
	(C.SUPERSEDED, "Mark Obsolete", C.OBSOLETE, (EM,), 1),
]


# v15.3.0 Engineering Drawing Workflow (not submittable -> every state docstatus 0). Superseded is system-only
# (set when a newer revision with ``revises`` is Approved), so no transition leads to it.
DRAWING_WORKFLOW_NAME = "Engineering ITAG KSA Engineering Drawing"
DRAWING_WORKFLOW_DOCTYPE = "Engineering Drawing"
DRAWING_WORKFLOW_FIELD = "workflow_state"
DRAWING_STATES = [
	# (state, doc_status, allow_edit, style)
	(C.DRAFT, 0, EU, ""),
	(C.UNDER_REVIEW, 0, EM, "Warning"),
	(C.APPROVED, 0, SM, "Success"),  # content frozen (controller LOCKED_NEXT)
	(C.SUPERSEDED, 0, SM, "Inverse"),
	(C.OBSOLETE, 0, SM, "Inverse"),
]
# (state, action, next_state, allowed roles, allow_self_approval)
DRAWING_TRANSITIONS = [
	(C.DRAFT, "Submit for Review", C.UNDER_REVIEW, (EU, EM), 1),
	(C.UNDER_REVIEW, "Return to Draft", C.DRAFT, (EM,), 1),
	# allow_self_approval 0 (owner may not approve); the controller also requires an approver different from the
	# user who submitted for review (submitted_for_review_by).
	(C.UNDER_REVIEW, "Approve", C.APPROVED, (EM,), 0),
	(C.APPROVED, "Mark Obsolete", C.OBSOLETE, (EM,), 1),
	(C.SUPERSEDED, "Mark Obsolete", C.OBSOLETE, (EM,), 1),
]


# v15.3.0 Material Specification Workflow, mirrors the Drawing one (not submittable -> every state docstatus 0).
# Superseded is system-only (set when a newer revision of the same MS-BV chain is Approved).
MS_WORKFLOW_NAME = "Engineering ITAG KSA Material Specification"
MS_WORKFLOW_DOCTYPE = "Material Specification"
MS_WORKFLOW_FIELD = "workflow_state"
MS_STATES = DRAWING_STATES
MS_TRANSITIONS = DRAWING_TRANSITIONS


# v15.3.3 Product Revision Workflow (Owner 2026-11-10): an exact copy of the Engineering Drawing Workflow (same
# states, transitions, roles, allow_self_approval, no conditions, no update fields, send_email_alert 0, field
# ``workflow_state``), with the minimal adaptations Product Revision needs because it is SUBMITTABLE and has
# system-set states (each one listed in the build report):
#  1. doc_status: Approved / Superseded / Obsolete are 1 (Drawing: 0). "Approve" therefore runs the standard
#     Submit, so the Approved-drawing / Approved-Material-Specification checks (before_submit), the supersede of
#     the previous active revision (on_submit) and "ER needs a submitted PR" keep working.
#  2. Release Ready (doc_status 1) + "Mark Release Ready" (Approved -> Release Ready, Engineering Manager): the
#     existing PR step that requires a submitted BOM; it is reachable only from Approved.
#  3. Released (doc_status 1) is system-only like Superseded: set by Engineering Release / Master Engineering
#     Release "Released for Production" (mark_released, direct DB write); no transition leads to it.
#  4. "Mark Obsolete" also from Release Ready and Released (Drawing: from every non-draft active state).
#  5. Cancelled (doc_status 2, no transition): keeps the standard Cancel / Amend of a submitted PR (on_cancel
#     writes Cancelled); Frappe shows Cancel because no transition leads to a doc_status 2 state.
PR_WORKFLOW_NAME = "Engineering ITAG KSA Product Revision"
PR_WORKFLOW_DOCTYPE = "Product Revision"
PR_WORKFLOW_FIELD = "workflow_state"
PR_STATES = [
	# (state, doc_status, allow_edit, style)
	(C.DRAFT, 0, EU, ""),
	(C.UNDER_REVIEW, 0, EM, "Warning"),
	(C.APPROVED, 1, SM, "Success"),
	(C.SUPERSEDED, 1, SM, "Inverse"),
	(C.OBSOLETE, 1, SM, "Inverse"),
	(C.RELEASE_READY, 1, SM, "Info"),  # adaptation 2
	(C.RELEASED, 1, SM, "Primary"),  # adaptation 3 (system-only)
	(C.CANCELLED, 2, SM, "Danger"),  # adaptation 5 (standard Cancel)
]
PR_TRANSITIONS = DRAWING_TRANSITIONS + [
	(C.APPROVED, "Mark Release Ready", C.RELEASE_READY, (EM,), 1),  # adaptation 2
	(C.RELEASE_READY, "Mark Obsolete", C.OBSOLETE, (EM,), 1),  # adaptation 4
	(C.RELEASED, "Mark Obsolete", C.OBSOLETE, (EM,), 1),  # adaptation 4
]


# Master Engineering Release Workflow (created once; editable on Desk). Not submittable -> all docstatus 0.
MASTER_WORKFLOW_NAME = "Engineering ITAG KSA Master Engineering Release"
MASTER_WORKFLOW_DOCTYPE = "Master Engineering Release"
MASTER_WORKFLOW_FIELD = "release_status"
MASTER_STATES = [
	# (state, allow_edit roles, style) -- one Workflow Document State row per role
	(C.DRAFT, (EU, EM, EMM), ""),
	(C.APPROVED, (EM, EMM), "Success"),
	(C.RELEASED_FOR_PRODUCTION, (SM,), "Primary"),  # read-only on Desk for Engineering roles once released
	(C.SUPERSEDED, (SM,), "Inverse"),  # system-only (newer Master Released for Production)
]
# (state, action, next_state, allowed roles, allow_self_approval) -- mirrors master_engineering_release.TRANSITIONS
MASTER_TRANSITIONS = [
	(C.DRAFT, "Approve", C.APPROVED, (EM, EMM), 0),
	(C.APPROVED, "Return to Draft", C.DRAFT, (EM, EMM), 1),
	(C.APPROVED, "Release for Production", C.RELEASED_FOR_PRODUCTION, (EMM,), 0),
]

# Desk Notifications (email) for Master Engineering Release status moves (created once; editable on Desk).
_MER_LINK = '<p><a href="{{ frappe.utils.get_url_to_form(doc.doctype, doc.name) }}">Open {{ doc.name }}</a></p>'
_MER_BODY = (
	"<p>Master Engineering Release <b>{{ doc.name }}</b> ({{ doc.finished_good_item }}, {{ doc.company }}) is now "
	"<b>{{ doc.release_status }}</b>.</p>"
)
MASTER_NOTIFICATIONS = [
	{
		"name": "Master Engineering Release - Approved",
		"subject": "{{ doc.name }} Approved - ready for Release for Production",
		"condition": 'doc.release_status == "Approved"',
		"recipients": [{"receiver_by_document_field": "owner"}, {"receiver_by_role": EMM}],
		"message": _MER_BODY + "<p>Approved by {{ doc.approved_by }}. An Engineering Manager Master (not the creator "
			"or the Approver) can now run <b>Release for Production</b>.</p>" + _MER_LINK,
	},
	{
		"name": "Master Engineering Release - Released for Production",
		"subject": "{{ doc.name }} Released for Production",
		"condition": 'doc.release_status == "Released for Production"',
		"recipients": [{"receiver_by_document_field": "owner"}, {"receiver_by_document_field": "approved_by"},
			{"receiver_by_role": EM}, {"receiver_by_role": EMM}],
		"message": _MER_BODY + "<p>Released by {{ doc.released_by }} (approved by {{ doc.approved_by }}). Every child "
			"Engineering Release is now Released for Production.</p>" + _MER_LINK,
	},
	{
		"name": "Master Engineering Release - Returned to Draft",
		"subject": "{{ doc.name }} returned to Draft",
		# creation != modified: skip the initial insert (Draft is the first state)
		"condition": 'doc.release_status == "Draft" and doc.creation != doc.modified',
		"recipients": [{"receiver_by_document_field": "owner"}],
		"message": _MER_BODY + "<p>Returned to Draft by {{ doc.modified_by }}. Update it and send it for approval "
			"again.</p>" + _MER_LINK,
	},
]



def backfill_item_links():
	"""Fill Item.eng_bom / eng_design / eng_release for Items that already have those documents.

	Kept from the retired 15.3.x patch ``backfill_item_related_documents`` because after_migrate uses it.
	Idempotent; a no-op on an empty site."""
	from engineering_itagksa.item_links import sync_item

	if not frappe.get_meta("Item").has_field("eng_bom"):
		return
	items = set(frappe.get_all("BOM", filters={"docstatus": ("!=", 2)}, pluck="item"))
	if frappe.get_meta("Engineering Drawing").has_field("item_code"):  # v15.3.0 guard: field removed
		items |= set(frappe.get_all("Engineering Drawing", pluck="item_code"))
	items |= set(frappe.get_all("Engineering Release", pluck="item"))
	for item in filter(None, items):
		sync_item(item)

def after_install():
	setup()


def after_migrate():
	setup()
	# Runs after fixtures sync, so Item.eng_bom/eng_design/eng_release exist. Idempotent.
	backfill_item_links()

	from engineering_itagksa import work_order_links

	work_order_links.backfill_baseline()
	work_order_links.backfill()

	from engineering_itagksa.eng_settings import ensure_settings_defaults
	from engineering_itagksa.engineering_itag_ksa.doctype.item_component.item_component import (
		ensure_all_item_naming_rules,
	)

	ensure_settings_defaults()
	ensure_all_item_naming_rules()
	ensure_erpnext_settings_shortcut()
	ensure_engineering_workspace_shortcuts()
	ensure_custom_subcontracted_job()


def ensure_erpnext_settings_shortcut():
	"""Add an Engineering Settings tile to the core ERPNext Settings workspace (data only, idempotent)."""
	import json

	try:
		_ensure_erpnext_settings_shortcut()
	except Exception:
		frappe.log_error(title="engineering_itagksa: ERPNext Settings shortcut skipped")
		print("WARNING: could not add Engineering Settings shortcut (see Error Log)")


def _ensure_erpnext_settings_shortcut():
	import json

	ws_name = "ERPNext Settings"
	if not frappe.db.exists("Workspace", ws_name):
		return
	ws = frappe.get_doc("Workspace", ws_name)
	changed = False
	if not any(s.link_to == "Engineering Settings" for s in ws.shortcuts):
		ws.append("shortcuts", {"type": "DocType", "link_to": "Engineering Settings", "label": "Engineering Settings", "color": "Grey"})
		changed = True
	content = json.loads(ws.content or "[]")
	if not any(b.get("type") == "shortcut" and b.get("data", {}).get("shortcut_name") == "Engineering Settings" for b in content):
		last = max((i for i, b in enumerate(content) if b.get("type") == "shortcut"), default=len(content) - 1)
		content.insert(last + 1, {"id": "EngSetErpN", "type": "shortcut", "data": {"shortcut_name": "Engineering Settings", "col": 3}})
		ws.content = json.dumps(content)
		changed = True
	if changed:
		ws.flags.ignore_permissions = True
		ws.flags.ignore_links = True
		ws.save()

def ensure_engineering_workspace_shortcuts():
	"""Keep Master Engineering Release in Your Shortcuts, right after Engineering Release (idempotent)."""
	try:
		_ensure_engineering_workspace_shortcuts()
	except Exception:
		frappe.log_error(title="engineering_itagksa: Engineering workspace shortcut skipped")
		print("WARNING: could not add Master Engineering Release shortcut (see Error Log)")


def _ensure_engineering_workspace_shortcuts():
	import json

	ws_name = "Engineering"
	if not frappe.db.exists("Workspace", ws_name):
		return
	ws = frappe.get_doc("Workspace", ws_name)
	changed = False

	def _idx(rows, pred):
		for i, r in enumerate(rows):
			if pred(r):
				return i
		return None

	# shortcuts child table: place MER immediately after Engineering Release
	er_i = _idx(ws.shortcuts, lambda s: (s.link_to or s.label) == "Engineering Release")
	mer_i = _idx(ws.shortcuts, lambda s: (s.link_to or s.label) == "Master Engineering Release")
	if er_i is not None:
		if mer_i is None:
			ws.append("shortcuts", {
				"type": "DocType", "link_to": "Master Engineering Release",
				"label": "Master Engineering Release", "color": "Grey",
			})
			# append puts it at the end; move after ER
			mer = ws.shortcuts.pop()
			er_i = _idx(ws.shortcuts, lambda s: (s.link_to or s.label) == "Engineering Release")
			ws.shortcuts.insert(er_i + 1, mer)
			# reindex
			for i, s in enumerate(ws.shortcuts, start=1):
				s.idx = i
			changed = True
		elif mer_i != er_i + 1:
			mer = ws.shortcuts.pop(mer_i)
			er_i = _idx(ws.shortcuts, lambda s: (s.link_to or s.label) == "Engineering Release")
			ws.shortcuts.insert(er_i + 1, mer)
			for i, s in enumerate(ws.shortcuts, start=1):
				s.idx = i
			changed = True

	content = json.loads(ws.content or "[]")

	def is_sc(b, name):
		return b.get("type") == "shortcut" and b.get("data", {}).get("shortcut_name") == name

	er_c = _idx(content, lambda b: is_sc(b, "Engineering Release"))
	mer_c = _idx(content, lambda b: is_sc(b, "Master Engineering Release"))
	if er_c is not None:
		block = {"id": "MerShort01", "type": "shortcut", "data": {"shortcut_name": "Master Engineering Release", "col": 3}}
		if mer_c is None:
			content.insert(er_c + 1, block)
			ws.content = json.dumps(content)
			changed = True
		elif mer_c != er_c + 1:
			mer = content.pop(mer_c)
			er_c = _idx(content, lambda b: is_sc(b, "Engineering Release"))
			content.insert(er_c + 1, mer)
			ws.content = json.dumps(content)
			changed = True
	if changed:
		ws.flags.ignore_permissions = True
		ws.flags.ignore_links = True
		ws.flags.ignore_version = True
		ws.save()


def setup():
	ensure_roles()
	ensure_release_workflow()
	ensure_drawing_workflow()
	ensure_material_specification_workflow()
	ensure_product_revision_workflow()
	ensure_master_release_workflow()
	ensure_master_release_notifications()
	ensure_custom_subcontracted_job()
	frappe.clear_cache()


def ensure_roles():
	for role in (EU, EM, EMM):
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(ignore_permissions=True)


def ensure_release_workflow():
	"""Create / update the Engineering Release approval Workflow. Idempotent."""
	_ensure_coded_workflow(RELEASE_WORKFLOW_NAME, RELEASE_WORKFLOW_DOCTYPE, RELEASE_WORKFLOW_FIELD, RELEASE_STATES,
		RELEASE_TRANSITIONS)


def ensure_drawing_workflow():
	"""v15.3.0: Create / update the Engineering Drawing Workflow. Idempotent."""
	_ensure_coded_workflow(DRAWING_WORKFLOW_NAME, DRAWING_WORKFLOW_DOCTYPE, DRAWING_WORKFLOW_FIELD, DRAWING_STATES,
		DRAWING_TRANSITIONS)


def ensure_material_specification_workflow():
	"""v15.3.0: Create / update the Material Specification Workflow. Idempotent."""
	_ensure_coded_workflow(MS_WORKFLOW_NAME, MS_WORKFLOW_DOCTYPE, MS_WORKFLOW_FIELD, MS_STATES, MS_TRANSITIONS)


def ensure_product_revision_workflow():
	"""v15.3.3: Create / update the Product Revision Workflow (copy of the Drawing one). Idempotent."""
	_ensure_coded_workflow(PR_WORKFLOW_NAME, PR_WORKFLOW_DOCTYPE, PR_WORKFLOW_FIELD, PR_STATES, PR_TRANSITIONS)


def _ensure_coded_workflow(name, doctype, field, states, transitions):
	if not frappe.db.exists("DocType", doctype):
		return
	for state, _docstatus, _edit, style in states:
		if not frappe.db.exists("Workflow State", state):
			frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": state, "style": style}).insert(
				ignore_permissions=True
			)
	for action in dict.fromkeys(t[1] for t in transitions):
		if not frappe.db.exists("Workflow Action Master", action):
			frappe.get_doc({"doctype": "Workflow Action Master", "workflow_action_name": action}).insert(
				ignore_permissions=True
			)

	wf = frappe.get_doc("Workflow", name) if frappe.db.exists("Workflow", name) else frappe.new_doc("Workflow")
	wf.workflow_name = name
	wf.document_type = doctype
	wf.workflow_state_field = field
	wf.is_active = 1
	wf.send_email_alert = 0
	wf.override_status = 0
	wf.set("states", [])
	for state, docstatus, allow_edit, _style in states:
		wf.append("states", {"state": state, "doc_status": str(docstatus), "allow_edit": allow_edit})
	wf.set("transitions", [])
	for state, action, nxt, roles, self_approval in transitions:
		for role in roles:
			wf.append("transitions", {"state": state, "action": action, "next_state": nxt, "allowed": role,
				"allow_self_approval": self_approval})
	wf.flags.ignore_permissions = True
	try:
		wf.save()
	except Exception:
		frappe.log_error(title=f"engineering_itagksa: Workflow {name} not saved")
		print(f"WARNING: Workflow {name} not saved (see Error Log)")


def ensure_master_release_workflow():
	"""Create the Master Engineering Release Workflow once (never overwritten, so Desk edits survive migrate)."""
	if not frappe.db.exists("DocType", MASTER_WORKFLOW_DOCTYPE) or frappe.db.exists("Workflow", MASTER_WORKFLOW_NAME):
		return
	for state, _roles, style in MASTER_STATES:
		if not frappe.db.exists("Workflow State", state):
			frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": state, "style": style}).insert(
				ignore_permissions=True
			)
	for action in dict.fromkeys(t[1] for t in MASTER_TRANSITIONS):
		if not frappe.db.exists("Workflow Action Master", action):
			frappe.get_doc({"doctype": "Workflow Action Master", "workflow_action_name": action}).insert(
				ignore_permissions=True
			)
	wf = frappe.new_doc("Workflow")
	wf.workflow_name = MASTER_WORKFLOW_NAME
	wf.document_type = MASTER_WORKFLOW_DOCTYPE
	wf.workflow_state_field = MASTER_WORKFLOW_FIELD
	wf.is_active = 1
	wf.send_email_alert = 0  # email alerts are the editable Notifications below
	wf.override_status = 0
	for state, roles, _style in MASTER_STATES:
		for role in roles:
			wf.append("states", {"state": state, "doc_status": "0", "allow_edit": role})
	for state, action, nxt, roles, self_approval in MASTER_TRANSITIONS:
		for role in roles:
			wf.append("transitions", {"state": state, "action": action, "next_state": nxt, "allowed": role,
				"allow_self_approval": self_approval})
	wf.flags.ignore_permissions = True
	try:
		wf.insert()
	except Exception:
		frappe.log_error(title=f"engineering_itagksa: Workflow {MASTER_WORKFLOW_NAME} not created")
		print(f"WARNING: Workflow {MASTER_WORKFLOW_NAME} not created (see Error Log)")


def ensure_master_release_notifications():
	"""Create the Master Engineering Release email Notifications once (recipients / text editable on Desk)."""
	if not frappe.db.exists("DocType", MASTER_WORKFLOW_DOCTYPE):
		return
	for n in MASTER_NOTIFICATIONS:
		if frappe.db.exists("Notification", n["name"]):
			continue
		doc = frappe.get_doc({
			"doctype": "Notification",
			"name": n["name"],
			"__newname": n["name"],
			"enabled": 1,
			"channel": "Email",
			"document_type": MASTER_WORKFLOW_DOCTYPE,
			"event": "Value Change",
			"value_changed": MASTER_WORKFLOW_FIELD,
			"condition": n["condition"],
			"subject": n["subject"],
			"message_type": "HTML",
			"message": n["message"],
			"send_system_notification": 1,
			"is_standard": 0,
			"recipients": n["recipients"],
		})
		try:
			doc.insert(ignore_permissions=True)
		except Exception:
			frappe.log_error(title=f"engineering_itagksa: Notification {n['name']} not created")
			print(f"WARNING: Notification {n['name']} not created (see Error Log)")


def ensure_custom_subcontracted_job():
	"""Owner: Work Order Check ``custom_subcontracted_job`` bypasses the Engineering Release gate.
	Create only when the field is missing (site may already have it)."""
	if frappe.get_meta("Work Order").has_field("custom_subcontracted_job"):
		return
	if frappe.db.exists("Custom Field", "Work Order-custom_subcontracted_job"):
		return
	doc = frappe.get_doc(
		{
			"doctype": "Custom Field",
			"dt": "Work Order",
			"fieldname": "custom_subcontracted_job",
			"label": "Subcontracted Job",
			"fieldtype": "Check",
			"insert_after": "eng_wo_engineering_tab",
			"default": "0",
			"module": "Engineering ITAG KSA",
		}
	)
	doc.insert(ignore_permissions=True)
	frappe.clear_cache(doctype="Work Order")

