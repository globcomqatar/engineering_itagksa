"""Rollback-only lifecycle smoke (no data persists). No Workflow: documents move with standard Save / Submit /
Cancel (v15.1.31); Engineering Drawing and Material Specification (v15.3.0) move with their Desk Workflows. Run:
  bench --site <site> execute engineering_itagksa.tests.smoke_lifecycle.run
  bench --site <site> execute engineering_itagksa.tests.smoke_lifecycle.run_drawing   # Drawing only
Covers: Material Specification MSBV naming / revisions / supersede (run_material_spec), ECR/ECO guards, Item Request -> Item mapping (run);
Item Request Engineering Drawing / Material Specification links, write-back, connections, amend (run_item_request_refs);
Item Component Item naming <prefix>-1000501 (7 digits, run_item_naming);
Product Revision Material Specification link field, no Specifications table (run_product_revision_ms_link);
Product Revision draft v0.1 auto-fill / Approved drawing / spec submit rule / ER Material Specification link / MER resolve (run_product_revision_v01);
Product Revision v15.3.3 auto revision digits 0/1/2 per Item number base + lock, Interchangeable default, Workflow copied from
Drawing incl. Release Ready / ER Released / Superseded / Obsolete / Cancel / Amend, Revise after approval
(run_product_revision_v153);
Drawing same-base digit revision naming (v15.3.6, starts at 0, no DWG- prefix), Revision lock, Workflow path, segregation of duties, revises -> Superseded, forward-only lock, 9,999 cap,
checksum attestation stamping (run_drawing).
"""

import hashlib
import os

import frappe

RESULTS = []
_FILES = []


def _pfile(name, content):
	"""Private File for a local drawing attachment (row rolls back; the disk file is removed in run's finally)."""
	f = frappe.get_doc({"doctype": "File", "file_name": name, "is_private": 1, "content": content}).insert()
	_FILES.append(f.get_full_path())
	return f.file_url


def ok(label, cond):
	RESULTS.append((label, bool(cond)))
	print(("PASS " if cond else "FAIL ") + label)


def raises(label, fn):
	try:
		fn()
	except (frappe.ValidationError, frappe.DuplicateEntryError) as e:
		ok(label, True)
		frappe.clear_messages()
		return str(e)
	ok(label + " (did not raise)", False)


def review(doc):
	"""Draft -> Under Review (plain Status field, normal Save)."""
	d = frappe.get_doc(doc.doctype, doc.name)
	d.workflow_state = "Under Review"
	d.save()
	return d


def submit(doc):
	"""Standard ERPNext Submit (sets the approved / released Status)."""
	d = frappe.get_doc(doc.doctype, doc.name)
	d.submit()
	return d


def set_status(doc, state):
	"""Update After Submit of the Status field (e.g. ECO Completed)."""
	d = frappe.get_doc(doc.doctype, doc.name)
	d.workflow_state = state
	d.save()
	return d


def _setup():
	if not frappe.db.exists("Item Group", "All Item Groups"):
		frappe.get_doc({"doctype": "Item Group", "item_group_name": "All Item Groups", "is_group": 1}).insert()
	frappe.get_doc({"doctype": "Item Group", "item_group_name": "ZZ Smoke Valves", "parent_item_group": "All Item Groups"}).insert()
	if not frappe.db.exists("UOM", "Nos"):
		frappe.get_doc({"doctype": "UOM", "uom_name": "Nos"}).insert()
	for dt, fn, val in (("Nominal Size", "nominal_size", "2in"), ("Pressure Class", "pressure_class", "600")):
		if not frappe.db.exists(dt, val):
			frappe.get_doc({"doctype": dt, fn: val}).insert()

	# Item Request no longer carries an item_code: the Item is named by a Document Naming Rule.
	frappe.get_doc({"doctype": "Document Naming Rule", "document_type": "Item", "prefix": "ZZ-VLV-", "prefix_digits": 1,
		"priority": 99, "conditions": [{"field": "item_group", "condition": "=", "value": "ZZ Smoke Valves"}]}).insert()

	for dt, val in (("Nominal Size", "2in"), ("Pressure Class", "600")):
		attr = frappe.get_doc("Item Spec Attribute", dt) if frappe.db.exists("Item Spec Attribute", dt) else frappe.get_doc({"doctype": "Item Spec Attribute", "attribute_name": dt})
		if val not in [r.attribute_value for r in attr.item_spec_attribute_values]:
			attr.append("item_spec_attribute_values", {"attribute_value": val})
			attr.save() if not attr.is_new() else attr.insert()


def _item_attr_rows(pairs):
	# Value strings (ERPNext Item Variant Attribute pattern), not Link names to istable ISAV.
	return [{"item_attribute": a, "attribute_value": v} for a, v in pairs]


def run():
	frappe.set_user("Administrator")
	try:
		_setup()
		ok("Item Group gate flag defaults to 1 (fail-closed)", frappe.db.get_value("Item Group", "ZZ Smoke Valves", "requires_engineering_release") == 1)

		# Item Request -> Item
		ir = frappe.get_doc({"doctype": "Engineering Item Request", "item_name": "Smoke Valve",
			"item_group": "ZZ Smoke Valves", "stock_uom": "Nos", "eng_item_category": "Manufacturing",
			"item_request_attribute": _item_attr_rows((("Nominal Size", "2in"), ("Pressure Class", "600")))}).insert()
		raises("Item Component outside Item Group blocked", lambda: frappe.get_doc({"doctype": "Engineering Item Request",
			"item_name": "Smoke Bad", "item_group": "ZZ Smoke Valves", "stock_uom": "Nos", "eng_item_category": "Manufacturing",
			"item_component": "621"}).insert())
		ir.submit()
		ok("Item Request created Item", ir.created_item == "ZZ-VLV-1" and frappe.db.get_value("Engineering Item Attribute", {"parent": "ZZ-VLV-1", "item_attribute": "Pressure Class"}, "attribute_value") == "600")
		item = ir.created_item

		run_item_request_refs()

		run_item_naming()

		run_product_revision_ms_link(item)

		# Draft v0.1 (2026-11-10): Product Revision auto-fill / Approved drawing / spec submit rule / ER mapping.
		# Runs before run_material_spec, which exhausts the MS-BV- series (99,999 cap check).
		run_product_revision_v01()

		# v15.3.3: auto revision letters, Interchangeable default, Product Revision Workflow (copy of Drawing's).
		run_product_revision_v153()

		run_material_spec()


		# ECR / ECO
		ecr = frappe.get_doc({"doctype": "Engineering Change Request", "item": item, "description": "smoke"}).insert()
		raises("ECO refused while ECR not Approved", lambda: frappe.get_doc({"doctype": "Engineering Change Order", "source_ecr": ecr.name,
			"controlled_changes": [{"change_type": "Drawing", "change_description": "x", "interchangeability": "Interchangeable"}]}).insert())
		review(ecr); submit(ecr)
		item_mod = frappe.db.get_value("Item", item, "modified")
		eco = frappe.get_doc({"doctype": "Engineering Change Order", "source_ecr": ecr.name,
			"controlled_changes": [{"change_type": "Drawing", "change_description": "rev B", "interchangeability": "Interchangeable"}]}).insert()
		submit(eco)
		ok("ECO Approved by standard Submit", frappe.db.get_value("Engineering Change Order", eco.name, "workflow_state") == "Approved")
		set_status(eco, "Completed")
		e = frappe.get_doc("Engineering Change Order", eco.name)
		ok("ECO Completed with completed_on", e.workflow_state == "Completed" and e.completed_on)
		e.reload(); e.cancel()
		ok("ECO Cancel sets Status Cancelled", frappe.db.get_value("Engineering Change Order", eco.name, "workflow_state") == "Cancelled")
		ok("B7: Item not mutated by ECR/ECO", frappe.db.get_value("Item", item, "modified") == item_mod)
	finally:
		frappe.db.rollback()
		frappe.clear_messages()
		for path in _FILES:
			if os.path.exists(path):
				os.remove(path)
	left = frappe.db.count("Item", {"name": "ZZ-VLV-1"}) + frappe.db.count("Material Specification", {"description": ["like", "ZZ smoke%"]})
	print("ROLLBACK residue rows:", left)
	run_drawing(report=False)
	_report()


MS_USERS = {
	"zz.ms.user@example.com": ("Engineering User",),
	"zz.ms.mgr@example.com": ("Engineering Manager", "Engineering User"),
}




def run_item_naming():
	"""v15.3.5 Item codes from Item Component: <prefix>-1000501 (7 digits, continues past 1000599)."""
	from frappe.model.naming import set_naming_from_document_naming_rule
	from frappe.utils import cint

	from engineering_itagksa.engineering_itag_ksa.doctype.item_component.item_component import (
		ITEM_NAMING_COUNTER_START,
		ITEM_NAMING_DIGITS,
		ITEM_NAMING_FIELD,
		ensure_item_naming_rule,
	)

	# Isolated Item Group so the smoke ZZ-VLV- (priority 99) rule does not win over the component rule.
	frappe.get_doc({
		"doctype": "Item Group",
		"item_group_name": "ZZ Naming Group",
		"parent_item_group": "All Item Groups",
	}).insert()
	comp = frappe.get_doc({
		"doctype": "Item Component",
		"part_code_prefix": "880",
		"component_name": "ZZ Smoke Naming Body",
		"item_group": "ZZ Naming Group",
	}).insert()
	parents = frappe.get_all(
		"Document Naming Rule Condition",
		filters={"parenttype": "Document Naming Rule", "field": ITEM_NAMING_FIELD, "condition": "=", "value": "880"},
		pluck="parent",
	)
	ok("New Item Component creates an Item Document Naming Rule", bool(parents))
	rule_name = parents[0]
	rule = frappe.db.get_value(
		"Document Naming Rule", rule_name,
		["prefix", "prefix_digits", "counter", "priority", "disabled"], as_dict=True,
	)
	ok("New rule is prefix 880-, 7 digits, counter 1000500, priority 10",
		rule.prefix == "880-" and cint(rule.prefix_digits) == ITEM_NAMING_DIGITS
		and cint(rule.counter) == ITEM_NAMING_COUNTER_START and cint(rule.priority) == 10 and not rule.disabled)

	def _make_item(n):
		item = frappe.new_doc("Item")
		item.item_name = f"ZZ Naming {n}"
		item.item_group = "ZZ Naming Group"
		item.stock_uom = "Nos"
		item.is_stock_item = 1
		item.eng_item_component = "880"
		set_naming_from_document_naming_rule(item)
		item.item_code = item.name
		item.insert(set_name=item.name)
		return item.name

	a = _make_item(1)
	b = _make_item(2)
	ok("First Item from component 880 is 880-1000501", a == "880-1000501")
	ok("Second Item from component 880 is 880-1000502", b == "880-1000502")
	ok("Rule counter advanced to 1000502",
		cint(frappe.db.get_value("Document Naming Rule", rule_name, "counter")) == 1000502)

	# Floor bump: a 5-digit / low counter is raised to 1000500 and digits pinned to 7;
	# a high 7-digit counter is not lowered.
	frappe.db.set_value("Document Naming Rule", rule_name, {"counter": 12, "prefix_digits": 3})
	ensure_item_naming_rule(comp)
	rule = frappe.db.get_value("Document Naming Rule", rule_name, ["counter", "prefix_digits"], as_dict=True)
	ok("Existing rule counter below 1000500 is bumped to the highest existing 7-digit Item (1000502) and digits pinned to 7",
		cint(rule.counter) == 1000502 and cint(rule.prefix_digits) == 7)

	frappe.db.set_value("Document Naming Rule", rule_name, "counter", 1000600)
	ensure_item_naming_rule(comp)
	ok("Existing rule counter >= 1000500 is not lowered",
		cint(frappe.db.get_value("Document Naming Rule", rule_name, "counter")) == 1000600)

	# Passing 1000599: the next issued Item is 880-1000600
	frappe.db.set_value("Document Naming Rule", rule_name, "counter", 1000599)
	c = _make_item(3)
	ok("Item after 1000599 is 880-1000600", c == "880-1000600")



def run_item_request_refs():
	"""v15.3.1 Engineering Item Request links to Engineering Drawing / Material Specification (rollback only)."""
	from frappe.model.workflow import apply_workflow

	from engineering_itagksa.connections import get_open_count
	from engineering_itagksa.engineering_itag_ksa.doctype.engineering_item_request.engineering_item_request import (
		make_engineering_drawing,
	)

	# Component under the smoke Item Group so Drawing group/component filters match the request.
	frappe.get_doc({
		"doctype": "Item Component",
		"part_code_prefix": "993",
		"component_name": "ZZ Smoke EIR Body",
		"item_group": "ZZ Smoke Valves",
	}).insert()

	users = {
		"zz.eir.user@example.com": ("Engineering User",),
		"zz.eir.mgr@example.com": ("Engineering Manager", "Engineering User"),
	}
	for email, roles in users.items():
		u = frappe.get_doc({
			"doctype": "User", "email": email, "first_name": email.split("@")[0],
			"send_welcome_email": 0, "user_type": "System User",
		}).insert(ignore_permissions=True)
		u.add_roles(*roles)
	EU, EM = list(users)

	def as_user(user, fn):
		prev = frappe.session.user
		frappe.set_user(user)
		try:
			return fn()
		finally:
			frappe.set_user(prev)

	def approve_dwg(name):
		as_user(EU, lambda: apply_workflow(frappe.get_doc("Engineering Drawing", name), "Submit for Review"))
		as_user(EM, lambda: apply_workflow(frappe.get_doc("Engineering Drawing", name), "Approve"))

	def approve_ms(name):
		as_user(EU, lambda: apply_workflow(frappe.get_doc("Material Specification", name), "Submit for Review"))
		as_user(EM, lambda: apply_workflow(frappe.get_doc("Material Specification", name), "Approve"))

	meta = frappe.get_meta("Engineering Item Request")
	ok("EIR has engineering_drawing + material_specification allow_on_submit, not no_copy",
		meta.has_field("engineering_drawing") and meta.has_field("material_specification")
		and meta.get_field("engineering_drawing").allow_on_submit
		and meta.get_field("material_specification").allow_on_submit
		and not meta.get_field("engineering_drawing").no_copy
		and not meta.get_field("material_specification").no_copy)
	ok("EIR field order: is_stock_item then engineering_drawing then material_specification then created_item",
		meta.get_field("engineering_drawing") and meta.get_field("material_specification")
		and [f.fieldname for f in meta.fields if f.fieldname in (
			"is_stock_item", "engineering_drawing", "material_specification", "created_item"
		)] == ["is_stock_item", "engineering_drawing", "material_specification", "created_item"])

	# Request with Item Component (needed for Drawing match + Create Drawing button prefill)
	ir = frappe.get_doc({
		"doctype": "Engineering Item Request",
		"item_name": "Smoke EIR Valve",
		"item_group": "ZZ Smoke Valves",
		"item_component": "993",
		"stock_uom": "Nos",
		"eng_item_category": "Manufacturing",
		"item_request_attribute": _item_attr_rows((("Nominal Size", "2in"), ("Pressure Class", "600"))),
	}).insert()
	ir.submit()
	ok("EIR with Item Component submitted and created Item", bool(ir.created_item))

	# Drawings: matching Approved, wrong component, Obsolete, Superseded
	base = {
		"doctype": "Engineering Drawing",
		"drawing_type": "Assembly",
		"item_component": "993",
		"item_group": "ZZ Smoke Valves",
		"external_file_link": "https://dms.example.local/dwg/eir.pdf",
	}
	dwg = as_user(EU, lambda: frappe.get_doc(dict(base, drawing_name="EIR GA")).insert())
	approve_dwg(dwg.name)
	ok("Approved Drawing ready for EIR link", frappe.db.get_value("Engineering Drawing", dwg.name, "workflow_state") == "Approved")

	# Wrong component drawing (992 under ZZ DWG Group) — create component+group if needed for isolation
	if not frappe.db.exists("Item Group", "ZZ DWG Group"):
		frappe.get_doc({"doctype": "Item Group", "item_group_name": "ZZ DWG Group", "parent_item_group": "All Item Groups"}).insert()
	if not frappe.db.exists("Item Component", "992"):
		frappe.get_doc({"doctype": "Item Component", "part_code_prefix": "992", "component_name": "ZZ Smoke Bonnet", "item_group": "ZZ DWG Group"}).insert()
	wrong = frappe.get_doc(dict(base, item_component="992", item_group="ZZ DWG Group", drawing_name="Wrong",
		external_file_link="https://dms.example.local/dwg/wrong.pdf")).insert()
	approve_dwg(wrong.name)

	obs = frappe.get_doc(dict(base, drawing_name="Obsolete one",
		external_file_link="https://dms.example.local/dwg/obs.pdf")).insert()
	approve_dwg(obs.name)
	as_user(EM, lambda: apply_workflow(frappe.get_doc("Engineering Drawing", obs.name), "Mark Obsolete"))

	# Material Specs
	ms = as_user(EU, lambda: frappe.get_doc({
		"doctype": "Material Specification",
		"description": "ZZ smoke EIR spec",
		"critical_requirements": [{"description": "Leak tight", "acceptance_criteria": "API 598"}],
	}).insert())
	approve_ms(ms.name)
	ms_draft = frappe.get_doc({"doctype": "Material Specification", "description": "ZZ smoke EIR draft"}).insert()
	ms_obs = frappe.get_doc({"doctype": "Material Specification", "description": "ZZ smoke EIR obs",
		"critical_requirements": [{"description": "x", "acceptance_criteria": "y"}]}).insert()
	approve_ms(ms_obs.name)
	as_user(EM, lambda: apply_workflow(frappe.get_doc("Material Specification", ms_obs.name), "Mark Obsolete"))

	# Happy path link after submit
	ir.engineering_drawing = dwg.name
	ir.material_specification = ms.name
	ir.save()
	ok("Submitted EIR accepts Approved Drawing + Approved Material Specification",
		ir.engineering_drawing == dwg.name and ir.material_specification == ms.name)

	def link_wrong():
		d = frappe.get_doc("Engineering Item Request", ir.name)
		d.engineering_drawing = wrong.name
		d.save()
	raises("Wrong Item Component Drawing blocked", link_wrong)

	def link_obs_dwg():
		d = frappe.get_doc("Engineering Item Request", ir.name)
		d.engineering_drawing = obs.name
		d.save()
	raises("Obsolete Drawing blocked", link_obs_dwg)

	def link_draft_ms():
		d = frappe.get_doc("Engineering Item Request", ir.name)
		d.material_specification = ms_draft.name
		d.save()
	raises("Draft Material Specification blocked", link_draft_ms)

	def link_obs_ms():
		d = frappe.get_doc("Engineering Item Request", ir.name)
		d.material_specification = ms_obs.name
		d.save()
	raises("Obsolete Material Specification blocked", link_obs_ms)

	# Restore good links then supersede in place -> warning, not block
	d = frappe.get_doc("Engineering Item Request", ir.name)
	d.engineering_drawing = dwg.name
	d.material_specification = ms.name
	d.save()

	# Supersede the linked drawing via a newer Approved revision
	rev = as_user(EU, lambda: frappe.get_doc(dict(base, drawing_name="EIR GA", revises=dwg.name,
		external_file_link="https://dms.example.local/dwg/eir-b.pdf")).insert())
	approve_dwg(rev.name)
	ok("Linked Drawing became Superseded", frappe.db.get_value("Engineering Drawing", dwg.name, "workflow_state") == "Superseded")
	frappe.clear_messages()
	d = frappe.get_doc("Engineering Item Request", ir.name)
	d.material_specification = ms.name  # touch to force validate
	d.flags.ignore_version = True
	d.save()
	msgs = " ".join(str(m) for m in (frappe.message_log or []))
	ok("Already-linked Superseded Drawing warns (orange) but does not block",
		"Superseded" in msgs and d.engineering_drawing == dwg.name)

	# New pick of that Superseded drawing must be refused (clear then re-set)
	def new_pick_superseded():
		x = frappe.get_doc("Engineering Item Request", ir.name)
		x.engineering_drawing = None
		x.save()
		x.engineering_drawing = dwg.name
		x.save()
	raises("New pick of Superseded Drawing blocked", new_pick_superseded)

	# Material Specification: restore Approved link, then supersede in place
	d = frappe.get_doc("Engineering Item Request", ir.name)
	d.engineering_drawing = rev.name
	d.material_specification = ms.name
	d.save()
	from engineering_itagksa.engineering_itag_ksa.doctype.material_specification.material_specification import create_revision
	ms_rev = as_user(EU, lambda: frappe.get_doc(create_revision(ms.name)).insert())
	approve_ms(ms_rev.name)
	ok("Linked Material Specification became Superseded",
		frappe.db.get_value("Material Specification", ms.name, "workflow_state") == "Superseded")
	frappe.clear_messages()
	d = frappe.get_doc("Engineering Item Request", ir.name)
	d.save()
	msgs = " ".join(str(m) for m in (frappe.message_log or []))
	ok("Already-linked Superseded Material Specification warns but does not block",
		"Superseded" in msgs and d.material_specification == ms.name)

	def new_pick_ss_ms():
		x = frappe.get_doc("Engineering Item Request", ir.name)
		x.material_specification = None
		x.save()
		x.material_specification = ms.name
		x.save()
	raises("New pick of Superseded Material Specification blocked", new_pick_ss_ms)

	# Switch to Approved revision for remaining link tests
	d = frappe.get_doc("Engineering Item Request", ir.name)
	d.material_specification = ms_rev.name
	d.save()

	# make_engineering_drawing prefills + write-back via source_item_request / after_insert
	mapped = make_engineering_drawing(ir.name)
	ok("make_engineering_drawing prefills item_group, item_component, drawing_name, source_item_request",
		mapped.item_group == "ZZ Smoke Valves" and mapped.item_component == "993"
		and mapped.drawing_name == "Smoke EIR Valve" and mapped.source_item_request == ir.name
		and not mapped.get("item_code"))
	frappe.db.set_value("Engineering Item Request", ir.name, "engineering_drawing", None)
	new_dwg = as_user(EU, lambda: frappe.get_doc({
		"doctype": "Engineering Drawing",
		"drawing_name": mapped.drawing_name,
		"item_group": mapped.item_group,
		"item_component": mapped.item_component,
		"drawing_type": "Assembly",
		"external_file_link": "https://dms.example.local/dwg/eir-wb.pdf",
		"source_item_request": ir.name,
	}).insert())
	ok("Drawing after_insert writes back to EIR.engineering_drawing",
		frappe.db.get_value("Engineering Item Request", ir.name, "engineering_drawing") == new_dwg.name)

	# Connections: outbound links
	cards = get_open_count("Engineering Item Request", ir.name)["count"]["internal_links_found"]
	by_dt = {c["doctype"]: c for c in cards}
	ok("Connections include Engineering Drawing via @engineering_drawing",
		by_dt.get("Engineering Drawing", {}).get("count") == 1
		and new_dwg.name in (by_dt.get("Engineering Drawing", {}).get("names") or []))
	ok("Connections include Material Specification via @material_specification",
		by_dt.get("Material Specification", {}).get("count") == 1
		and ms_rev.name in (by_dt.get("Material Specification", {}).get("names") or []))

	# Amend keeps links (no_copy not set)
	d = frappe.get_doc("Engineering Item Request", ir.name)
	drawing_keep, spec_keep = d.engineering_drawing, d.material_specification
	d.cancel()
	amended = frappe.copy_doc(d)
	amended.amended_from = d.name
	amended.insert()
	ok("Amend keeps engineering_drawing and material_specification",
		amended.engineering_drawing == drawing_keep and amended.material_specification == spec_keep)

	# Drawing connections count BOMs through Items created by EIRs that reference the drawing
	dwg_cards = get_open_count("Engineering Drawing", new_dwg.name)["count"]["internal_links_found"]
	bom_card = next((c for c in dwg_cards if c["doctype"] == "BOM"), None)
	eir_item = frappe.db.get_value("Engineering Item Request", ir.name, "created_item")
	expected_boms = frappe.db.count("BOM", {"item": eir_item, "docstatus": ("!=", 2)}) if eir_item else 0
	ok("Drawing Connections count BOMs through the EIR Item",
		bom_card is not None and bom_card.get("count") == expected_boms)




def run_product_revision_ms_link(item):
	"""Owner request: optional top-level Link on Product Revision to Material Specification; draft v0.1
	(2026-11-10) moved it right after Drawing Revision and removed the old Specifications child table."""
	meta = frappe.get_meta("Product Revision")
	df = meta.get_field("material_specification")
	order = [f.fieldname for f in meta.fields if f.fieldname in ("drawing_revision", "bom_revision_reference", "material_specification")]
	ok("PR has optional Link to Material Specification right after Drawing Revision, not reqd",
		df and df.fieldtype == "Link" and df.options == "Material Specification" and not df.reqd
		and not df.read_only and not df.set_only_once
		and order == ["drawing_revision", "material_specification", "bom_revision_reference"])
	ok("PR has no Specifications child table / section any more",
		not meta.has_field("specifications") and not meta.has_field("spec_section")
		and not frappe.db.exists("DocField", {"parent": "Product Revision", "fieldname": ["in", ["specifications", "spec_section"]]}))
	ok("Product Revision Specification DocType kept (no data deletion)",
		frappe.db.exists("DocType", "Product Revision Specification") and frappe.db.table_exists("Product Revision Specification"))
	rows = frappe.get_all("DocField", filters={"parent": "Product Revision"}, fields=["fieldname", "idx"], order_by="idx asc")
	ok("PR DocField idx unique and equal to field_order position",
		[r.idx for r in rows] == list(range(1, len(rows) + 1))
		and [r.fieldname for r in rows] == [f.fieldname for f in meta.fields])

	ms = frappe.get_doc({"doctype": "Material Specification", "description": "ZZ PR link spec"}).insert()
	# The first smoke Item is created without an Item Component; v15.3.5 PR names need one.
	if not frappe.db.get_value("Item", item, "eng_item_component"):
		if not frappe.db.exists("Item Component", "889"):
			frappe.get_doc({"doctype": "Item Component", "part_code_prefix": "889",
				"component_name": "ZZ PR link body", "item_group": "ZZ Smoke Valves"}).insert()
		frappe.db.set_value("Item", item, "eng_item_component", "889")
	pr = frappe.get_doc({
		"doctype": "Product Revision",
		"item": item,
		"revision_number": "A",
		"interchangeability_decision": "Interchangeable",
		"material_specification": ms.name,
	}).insert(ignore_mandatory=True)
	ok("PR saves with material_specification set to an existing Material Specification",
		pr.name and pr.material_specification == ms.name
		and frappe.db.get_value("Product Revision", pr.name, "material_specification") == ms.name)


def run_product_revision_v01():
	"""Draft v0.1 (Owner approved 2026-11-10), rollback only: auto-fill from the Item's Engineering Item Request /
	BOM, Approved-drawing check (revises chain), Material Specification submit rule, ER Material Specification link, MER resolve."""
	from frappe.model.workflow import apply_workflow

	from engineering_itagksa.engineering_itag_ksa.doctype.master_engineering_release import (
		master_engineering_release as M,
	)
	from engineering_itagksa.engineering_itag_ksa.doctype.product_revision import product_revision as PRM

	EU, EM = "zz.eir.user@example.com", "zz.eir.mgr@example.com"  # created in run_item_request_refs

	def approve(dt, name):
		_as(EU, lambda: apply_workflow(frappe.get_doc(dt, name), "Submit for Review"))
		_as(EM, lambda: apply_workflow(frappe.get_doc(dt, name), "Approve"))

	base = {"doctype": "Engineering Drawing", "drawing_type": "Assembly", "item_component": "993",
		"item_group": "ZZ Smoke Valves"}
	dwg = _as(EU, lambda: frappe.get_doc(dict(base, drawing_name="PR v01 GA",
		external_file_link="https://dms.example.local/dwg/prv01-a.pdf")).insert())
	approve("Engineering Drawing", dwg.name)
	other = _as(EU, lambda: frappe.get_doc(dict(base, drawing_name="PR v01 other",
		external_file_link="https://dms.example.local/dwg/prv01-x.pdf")).insert())
	approve("Engineering Drawing", other.name)
	draft_dwg = frappe.get_doc(dict(base, drawing_name="PR v01 draft",
		external_file_link="https://dms.example.local/dwg/prv01-d.pdf")).insert()
	ms = _as(EU, lambda: frappe.get_doc({"doctype": "Material Specification", "description": "ZZ smoke PR v01 spec",
		"critical_requirements": [{"description": "Leak tight", "acceptance_criteria": "API 598"}]}).insert())
	approve("Material Specification", ms.name)
	ms_draft = frappe.get_doc({"doctype": "Material Specification", "description": "ZZ smoke PR v01 draft"}).insert()

	ir = frappe.get_doc({"doctype": "Engineering Item Request", "item_name": "Smoke PR v01 Valve",
		"item_group": "ZZ Smoke Valves", "item_component": "993", "stock_uom": "Nos", "eng_item_category": "Manufacturing",
		"is_stock_item": 1, "engineering_drawing": dwg.name, "material_specification": ms.name,
		"item_request_attribute": _item_attr_rows((("Nominal Size", "2in"), ("Pressure Class", "600")))}).insert()
	ir.submit()
	item = ir.created_item

	company = frappe.db.get_value("Company", {}, "name")
	rm = frappe.get_doc({"doctype": "Item", "item_code": "ZZ-PRV01-RM", "item_name": "ZZ PR v01 RM",
		"item_group": "ZZ DWG Group", "stock_uom": "Nos", "is_stock_item": 1}).insert()
	bom = frappe.get_doc({"doctype": "BOM", "item": item, "company": company, "quantity": 1,
		"rm_cost_as_per": "Valuation Rate", "items": [{"item_code": rm.name, "qty": 1, "rate": 1}]}).insert()
	bom.submit()
	ok("Smoke Item has a default BOM", frappe.db.get_value("Item", item, "default_bom") == bom.name)

	# (a) auto-fill
	d = PRM.get_item_engineering_defaults(item)
	ok("get_item_engineering_defaults: Drawing + Material Specification from the creating EIR, default BOM",
		d["drawing_revision"] == dwg.name and d["material_specification"] == ms.name
		and d["bom_revision_reference"] == bom.name and d["item_request"] == ir.name)
	empty = PRM.get_item_engineering_defaults(rm.name)
	ok("Item without EIR / BOM -> nothing to fill", not any((empty["drawing_revision"], empty["material_specification"],
		empty["bom_revision_reference"])))
	pr = frappe.get_doc({"doctype": "Product Revision", "item": item, "revision_number": "A",
		"interchangeability_decision": "Interchangeable"}).insert()
	ok("New PR save fills Drawing, Material Specification and BOM from the Item",
		(pr.drawing_revision, pr.material_specification, pr.bom_revision_reference) == (dwg.name, ms.name, bom.name))
	keep = frappe.get_doc({"doctype": "Product Revision", "item": item, "revision_number": "B",
		"interchangeability_decision": "Interchangeable", "material_specification": ms_draft.name}).insert()
	ok("Save never overwrites a value entered by the user (only empty fields filled)",
		keep.material_specification == ms_draft.name and keep.drawing_revision == dwg.name)

	# (e) drawing check: Approved accepted, Draft refused, other chain refused
	PRM.assert_drawing_released(dwg.name, item)
	ok("Drawing check accepts the Item's Approved drawing", True)
	raises("Drawing check refuses a Draft drawing", lambda: PRM.assert_drawing_released(draft_dwg.name, item))
	raises("Drawing check refuses an Approved drawing of another chain", lambda: PRM.assert_drawing_released(other.name, item))

	def save_other():
		x = frappe.get_doc("Product Revision", keep.name); x.drawing_revision = other.name; x.save()
	raises("PR save refuses a drawing that is not the Item's drawing (or a revision of it)", save_other)

	# (c) submit rule: Approved Material Specification in the new field
	def submit_pr(name):
		x = frappe.get_doc("Product Revision", name)
		x.workflow_state = "Under Review"; x.save(); x.submit()
	raises("Submit refused with a Draft Material Specification", lambda: submit_pr(keep.name))
	frappe.db.set_value("Product Revision", keep.name, {"material_specification": None, "workflow_state": "Draft"})
	raises("Submit refused without a Material Specification", lambda: submit_pr(keep.name))
	frappe.delete_doc("Product Revision", keep.name, force=1)
	submit_pr(pr.name)
	ok("Submit allowed with Approved drawing + Approved Material Specification",
		frappe.db.get_value("Product Revision", pr.name, ["docstatus", "workflow_state"]) == (1, "Approved"))

	# (d) v15.3.4: Engineering Release from PR gets the parent Material Specification link; ER baseline uses it
	from engineering_itagksa.engineering_itag_ksa.doctype.engineering_release import engineering_release as ERM

	ermeta = frappe.get_meta("Engineering Release")
	ok("ER has Material Specification link in Baseline after Drawing Revision, not reqd",
		ermeta.has_field("material_specification") and ermeta.get_field("material_specification").options == "Material Specification"
		and not ermeta.get_field("material_specification").reqd
		and [f.fieldname for f in ermeta.fields if f.fieldname in ("drawing_revision", "material_specification", "bom")]
		== ["drawing_revision", "material_specification", "bom"])
	ok("ER has no Specifications child table / section on the form",
		not ermeta.has_field("specifications") and not ermeta.has_field("spec_section")
		and not frappe.db.exists("DocField", {"parent": "Engineering Release", "fieldname": ["in", ["specifications", "spec_section"]]}))
	ok("Engineering Release Specification DocType kept (no data deletion)",
		frappe.db.exists("DocType", "Engineering Release Specification"))

	er = PRM.make_engineering_release(pr.name)
	ok("Engineering Release from PR gets the Product Revision's Material Specification",
		er.material_specification == ms.name and er.drawing_revision == dwg.name and er.bom == bom.name)
	er.validate_baseline()
	ok("ER baseline check accepts Approved drawing / submitted BOM / Approved spec", True)

	# auto-fill on Item, refresh on PR change, MS mandatory at Approve, MER carry-over
	filled = ERM.get_item_release_defaults(item)
	ok("ER auto-fill on Item: Product Revision + Drawing, BOM, Routing, Inspection, MS from the PR",
		filled["product_revision"] == pr.name and filled["drawing_revision"] == dwg.name
		and filled["bom"] == bom.name and filled["material_specification"] == ms.name)
	blank = frappe.get_doc({"doctype": "Engineering Release", "release_classification": "Standard",
		"company": company, "effective_datetime": frappe.utils.now_datetime(), "item": item})
	blank.fill_item_release_defaults()
	ok("New ER before_validate fills empty fields only from the Item's Product Revision",
		blank.product_revision == pr.name and blank.drawing_revision == dwg.name
		and blank.bom == bom.name and blank.material_specification == ms.name)
	refreshed = ERM.get_product_revision_release_defaults(pr.name)
	ok("Changing the Product Revision refreshes Drawing, BOM, Routing, Inspection and MS from the new PR",
		refreshed["drawing_revision"] == dwg.name and refreshed["bom"] == bom.name
		and refreshed["material_specification"] == ms.name)

	def baseline_without_ms():
		x = frappe.get_doc({"doctype": "Engineering Release", "item": item, "product_revision": pr.name,
			"drawing_revision": dwg.name, "bom": bom.name, "material_specification": None})
		x.validate_baseline()
	raises("MS is mandatory at Approve / Released for Production", baseline_without_ms)

	# MER-to-ER carry-over: _create_missing_releases sets material_specification from the PR
	master = type("_Master", (), {})()
	master.name = None  # no Master record in this smoke; link left empty
	master.company = company
	master.effective_datetime = frappe.utils.now_datetime()
	master.customer = master.project = None
	master.items = [frappe._dict(item=item, product_revision=pr.name, bom=bom.name, engineering_release=None, idx=1)]
	created, skipped = M.MasterEngineeringRelease._create_missing_releases(master)
	ok("MER-created Engineering Release carries the Product Revision's Material Specification",
		not skipped and created and frappe.db.get_value("Engineering Release", created[0], "material_specification") == ms.name)

	# MER: resolve the Item's drawing and row readiness without item_code / Released
	ok("MER resolve_drawing -> Item's Approved drawing", M.resolve_drawing(item) == dwg.name)
	row = frappe._dict(idx=1, item=item, bom=bom.name, drawing=dwg.name, product_revision=pr.name,
		material_specification=ms.name)
	ok("MER row ready with Approved drawing + submitted BOM + active PR + Approved MS", M.row_missing(row) == [])
	ok("MER row with a Draft drawing lacks Approved Drawing",
		"Approved Drawing" in M.row_missing(frappe._dict(row, drawing=draft_dwg.name)))

	# Revision B of the Item's drawing: same chain accepted; auto-fill moves to the current Approved revision
	rev = _as(EU, lambda: frappe.get_doc(dict(base, drawing_name="PR v01 GA", revises=dwg.name,
		external_file_link="https://dms.example.local/dwg/prv01-b.pdf")).insert())
	approve("Engineering Drawing", rev.name)
	PRM.assert_drawing_released(rev.name, item)
	ok("Drawing check accepts a newer Approved revision in the Item's drawing chain", True)
	raises("Superseded drawing refused by the drawing check", lambda: PRM.assert_drawing_released(dwg.name, item))
	ok("Auto-fill and MER resolve move to the current Approved revision",
		PRM.get_item_engineering_defaults(item)["drawing_revision"] == rev.name and M.resolve_drawing(item) == rev.name)


def run_material_spec():
	"""v15.3.0 Material Specification (rollback only, inside run()): real DocType rename, no Item Code, not
	submittable + Desk Workflow, MSBV-NNNNN-<revision> names, system Revision, Create Revision keeps the number,
	one Approved per chain (Superseded system-only), forward-only lock, segregation of duties."""
	from frappe.model.workflow import apply_workflow

	from engineering_itagksa.engineering_itag_ksa.doctype.material_specification.material_specification import (
		create_revision,
	)
	from engineering_itagksa.engineering_itag_ksa.doctype.product_revision.product_revision import assert_spec_approved

	dt = "Material Specification"
	for email, roles in MS_USERS.items():
		u = frappe.get_doc({"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0,
			"user_type": "System User"}).insert(ignore_permissions=True)
		u.add_roles(*roles)
	EU, EM = list(MS_USERS)

	def wf(name, action, user):
		return _as(user, lambda: apply_workflow(frappe.get_doc(dt, name), action))

	def approve(name):
		wf(name, "Submit for Review", EU)
		wf(name, "Approve", EM)

	get = lambda n, f: frappe.db.get_value(dt, n, f)
	meta = frappe.get_meta(dt)

	ok("DocType renamed: Material Specification exists, old DocType / table gone",
		frappe.db.exists("DocType", dt) and not frappe.db.exists("DocType", "Technical Spec")
		and frappe.db.table_exists(dt) and not frappe.db.table_exists("Technical Spec"))
	ok("MS not submittable, no item_code, no amended_from", not meta.is_submittable and not meta.has_field("item_code")
		and not meta.has_field("amended_from"))
	ok("MS specification_name above Revision is title_field / list / search", meta.has_field("specification_name")
		and meta.title_field == "specification_name" and meta.get_field("specification_name").in_list_view
		and "specification_name" in (meta.search_fields or "")
		and [f.fieldname for f in meta.fields if f.fieldname in ("specification_name", "revision")] == ["specification_name", "revision"])
	ok("Drawing Item Group is above Item Component in field order",
		[f.fieldname for f in frappe.get_meta("Engineering Drawing").fields
		 if f.fieldname in ("item_group", "item_component")] == ["item_group", "item_component"])
	ok("MS Revision read-only, default 0; Revises hidden + read-only link", meta.get_field("revision").read_only
		and meta.get_field("revision").default == "0" and meta.get_field("revises").hidden and meta.get_field("revises").read_only
		and meta.get_field("revises").options == dt)
	w = frappe.get_doc("Workflow", "Engineering ITAG KSA Material Specification")
	ok("Workflow active on workflow_state, states Draft/Under Review/Approved/Superseded/Obsolete",
		w.is_active and w.document_type == dt and w.workflow_state_field == "workflow_state"
		and [x.state for x in w.states] == ["Draft", "Under Review", "Approved", "Superseded", "Obsolete"])
	ok("No transition leads to Superseded (system-only)", all(t.next_state != "Superseded" for t in w.transitions))
	ok("Approved -> Obsolete transition exists", any(t.state == "Approved" and t.next_state == "Obsolete" for t in w.transitions))

	start = int(frappe.db.get_value("Series", "MS-BV-", "current", order_by="name") or 0)
	n1, n2 = f"MSBV-{start + 1:05d}", f"MSBV-{start + 2:05d}"
	if start:
		print(f"NOTE MS-BV- series already at {start}; expecting {n1}-0 / {n2}-0")
	s1 = _as(EU, lambda: frappe.get_doc({"doctype": dt, "description": "ZZ smoke spec 1", "revision": "7",
		"critical_requirements": [{"description": "Leak tight", "acceptance_criteria": "API 598"}]}).insert())
	ok(f"New spec -> {n1}-0 (typed revision ignored), starts Draft", s1.name == f"{n1}-0" and s1.revision == "0"
		and s1.workflow_state == "Draft")
	s2 = frappe.get_doc({"doctype": dt, "description": "ZZ smoke spec 2"}).insert()
	ok(f"Second new spec -> {n2}-0 (shared counter)", s2.name == f"{n2}-0")
	if not start:
		ok("Owner examples MSBV-00001-0 / MSBV-00002-0", (s1.name, s2.name) == ("MSBV-00001-0", "MSBV-00002-0"))
	# a refused insert would have taken a series number; in Desk the request rolls back, here a savepoint does
	frappe.db.savepoint("ms_bad_start")
	raises("New spec cannot start Approved", lambda: frappe.get_doc({"doctype": dt, "description": "x",
		"workflow_state": "Approved"}).insert())
	frappe.db.rollback(save_point="ms_bad_start")

	def to_approved_by_save():
		d = frappe.get_doc(dt, s2.name); d.workflow_state = "Approved"; d.save()
	raises("Draft cannot be saved straight to Approved (Workflow only)", to_approved_by_save)
	raises("Create Revision refused on a Draft", lambda: create_revision(s1.name))
	wf(s1.name, "Submit for Review", EU)
	ok("Submit for Review stamps submitter", get(s1.name, "workflow_state") == "Under Review" and get(s1.name, "submitted_for_review_by") == EU)
	raises("Submitter cannot approve own review", lambda: wf(s1.name, "Approve", EU))
	wf(s1.name, "Approve", EM)
	ok("Approve by a different Engineering Manager -> Approved, stamped", get(s1.name, "workflow_state") == "Approved"
		and get(s1.name, "approved_by") == EM and get(s1.name, "docstatus") == 0)

	def edit_locked():
		d = frappe.get_doc(dt, s1.name); d.material_requirements = "changed"; d.save()
	raises("Approved content is locked", edit_locked)

	def back_to_draft():
		d = frappe.get_doc(dt, s1.name); d.workflow_state = "Draft"; d.save()
	raises("Approved cannot go back to Draft (forward-only)", back_to_draft)

	def to_superseded():
		d = frappe.get_doc(dt, s1.name); d.workflow_state = "Superseded"; d.save()
	raises("Superseded cannot be set by hand", to_superseded)

	# Create Revision
	pre = _as(EU, lambda: create_revision(s1.name))
	ok("Create Revision prefills content + critical requirements, revises, suggests 1, Draft, no stamps",
		pre.get("revises") == s1.name and pre.get("revision") == "1" and pre.get("description") == "ZZ smoke spec 1"
		and len(pre.get("critical_requirements") or []) == 1 and pre.get("workflow_state") == "Draft"
		and not pre.get("approved_by") and not pre.get("superseded_by"))
	r1 = _as(EU, lambda: frappe.get_doc(pre).insert())
	ok(f"Revision keeps the number -> {n1}-1", r1.name == f"{n1}-1" and r1.revision == "1")
	raises("Second Create Revision blocked while one is open", lambda: create_revision(s1.name))
	raises("Second manual revision of the same spec blocked while one is open", lambda: frappe.get_doc({"doctype": dt,
		"revises": s1.name, "description": "dup"}).insert())

	def change_rev():
		d = frappe.get_doc(dt, r1.name); d.revision = "9"; d.save()
	raises("Revision cannot change after creation", change_rev)
	approve(r1.name)
	a = frappe.db.get_value(dt, s1.name, ["workflow_state", "superseded_by", "superseded_on"], as_dict=True)
	ok("Approving -1 supersedes -0 in the same transaction", a.workflow_state == "Superseded" and a.superseded_by == r1.name
		and a.superseded_on)
	ok("One Approved per chain", frappe.db.count(dt, {"name": ["like", n1 + "-%"], "workflow_state": "Approved"}) == 1)
	raises("Create Revision refused on a Superseded spec", lambda: create_revision(s1.name))
	r2 = frappe.get_doc(create_revision(r1.name)).insert()
	ok(f"Next revision -> {n1}-2", r2.name == f"{n1}-2" and r2.revision == "2")
	ok("Counter not used by revisions", int(frappe.db.get_value("Series", "MS-BV-", "current", order_by="name")) == start + 2)
	approve(r2.name)
	ok("-2 Approved supersedes -1", get(r1.name, "workflow_state") == "Superseded" and get(r1.name, "superseded_by") == r2.name)
	wf(s1.name, "Mark Obsolete", EM)
	ok("Superseded -> Obsolete by Engineering Manager", get(s1.name, "workflow_state") == "Obsolete")
	raises("Engineering User cannot Mark Obsolete", lambda: wf(r2.name, "Mark Obsolete", EU))
	s3 = frappe.get_doc({"doctype": dt, "description": "ZZ smoke spec 3"}).insert()
	ok(f"Next brand-new spec -> MSBV-{start + 3:05d}-0", s3.name == f"MSBV-{start + 3:05d}-0")

	# Product Revision / Engineering Release spec check: Approved Workflow status, no Item Code, no docstatus
	assert_spec_approved(r2.name, "ANY-ITEM")
	ok("PR/ER spec check: Approved spec accepted (no item, no docstatus)", True)
	raises("PR/ER spec check: Superseded spec refused", lambda: assert_spec_approved(r1.name, "ANY-ITEM"))
	raises("PR/ER spec check: Draft spec refused", lambda: assert_spec_approved(s3.name, "ANY-ITEM"))
	wf(r2.name, "Mark Obsolete", EM)
	ok("Approved -> Obsolete by Engineering Manager (manual)", get(r2.name, "workflow_state") == "Obsolete")

	# Old-named record (pre-rename TS-... name): a revision takes a fresh number with revision 0 and supersedes it
	frappe.db.sql(f"update `tab{dt}` set name='TS-ZZ-OLD-A', revision='A', workflow_state='Approved' where name=%s", s3.name)
	ro = frappe.get_doc(create_revision("TS-ZZ-OLD-A")).insert()
	ok(f"Revision of old-named spec -> fresh MSBV-{start + 4:05d}-0, revises kept", ro.name == f"MSBV-{start + 4:05d}-0"
		and ro.revises == "TS-ZZ-OLD-A")
	approve(ro.name)
	ok("Approving it supersedes the old-named spec", get("TS-ZZ-OLD-A", "workflow_state") == "Superseded")

	# 99,999 cap
	frappe.db.sql("update `tabSeries` set `current` = 99998 where `name` = 'MS-BV-'")
	last = frappe.get_doc({"doctype": dt, "description": "ZZ smoke last"}).insert()
	ok("MSBV-99999-0 is the last number", last.name == "MSBV-99999-0")
	raises("100,000th Material Specification refused", lambda: frappe.get_doc({"doctype": dt, "description": "ZZ smoke over"}).insert())


def run_product_revision_v153():
	"""v15.3.5 (Owner 2026-11-10), rollback only: Product Revision revision digits assigned by the system (0, 1, 2
	per Item number base, {component}-5NNNN-{n}, no PR- prefix; another Item gets a new number starting at 0;
	locked after insert), Interchangeability Decision defaults to Interchangeable, and the "Engineering ITAG KSA Product
	Revision" Workflow (copy of the Drawing one) end to end, including Engineering Release Released for Production
	-> PR Released. Numbers are shared with Engineering Drawing of the same component."""
	from frappe.model.workflow import apply_workflow
	from frappe.utils import add_to_date, now_datetime

	from engineering_itagksa import engineering_refs as REF
	from engineering_itagksa import install as I
	from engineering_itagksa.engineering_itag_ksa.doctype.product_revision import product_revision as PRM

	EU, EM = "zz.eir.user@example.com", "zz.eir.mgr@example.com"  # created in run_item_request_refs

	def wf(dt, name, action):
		return apply_workflow(frappe.get_doc(dt, name), action)

	def approve(dt, name):
		_as(EU, lambda: wf(dt, name, "Submit for Review"))
		_as(EM, lambda: wf(dt, name, "Approve"))

	def st(name):
		return frappe.db.get_value("Product Revision", name, ["docstatus", "workflow_state"])

	# --- Workflow definition: exact copy of the Drawing Workflow + the listed adaptations
	dw, pw = frappe.get_doc("Workflow", I.DRAWING_WORKFLOW_NAME), frappe.get_doc("Workflow", I.PR_WORKFLOW_NAME)
	ok("PR Workflow active on Product Revision, same field / email / override settings as Drawing",
		pw.document_type == "Product Revision" and pw.is_active == 1
		and (pw.workflow_state_field, pw.send_email_alert, pw.override_status)
		== (dw.workflow_state_field, dw.send_email_alert, dw.override_status))
	tkey = lambda t: (t.state, t.action, t.next_state, t.allowed, t.allow_self_approval, t.condition or "",
		t.send_email_to_creator)
	ok("Every Drawing transition (state, action, next, role, self-approval, condition) is in the PR Workflow",
		{tkey(t) for t in dw.transitions} <= {tkey(t) for t in pw.transitions})
	extra_t = {(t.state, t.action, t.next_state, t.allowed) for t in pw.transitions} - {
		(t.state, t.action, t.next_state, t.allowed) for t in dw.transitions}
	ok("PR-only transitions are exactly Mark Release Ready + Mark Obsolete from Release Ready / Released", extra_t == {
		("Approved", "Mark Release Ready", "Release Ready", "Engineering Manager"),
		("Release Ready", "Mark Obsolete", "Obsolete", "Engineering Manager"),
		("Released", "Mark Obsolete", "Obsolete", "Engineering Manager")})
	skey = lambda s: (s.state, s.allow_edit, s.update_field or "", s.update_value or "", s.is_optional_state,
		s.send_email, s.next_action_email_template or "", s.message or "")
	pstates = {s.state: s for s in pw.states}
	ok("Every Drawing state is in the PR Workflow with the same edit role / update field / email / optional settings",
		all(s.state in pstates and skey(pstates[s.state]) == skey(s) for s in dw.states))
	ok("PR doc_status: Draft/Under Review 0, Approved/Superseded/Obsolete/Release Ready/Released 1, Cancelled 2",
		{s.state: s.doc_status for s in pw.states} == {"Draft": "0", "Under Review": "0", "Approved": "1",
			"Superseded": "1", "Obsolete": "1", "Release Ready": "1", "Released": "1", "Cancelled": "2"})
	ok("No transition leads to Superseded, Released or Cancelled (system-only / standard Cancel)",
		not any(t.next_state in ("Superseded", "Released", "Cancelled") for t in pw.transitions))
	meta = frappe.get_meta("Product Revision")
	rdf, sdf, idf = (meta.get_field(f) for f in ("revision_number", "workflow_state", "interchangeability_decision"))
	ok("Revision Number read-only + set-only-once; Status read-only (Workflow buttons)",
		rdf.read_only and rdf.set_only_once and not rdf.reqd and sdf.read_only and sdf.allow_on_submit)
	ok("Interchangeability Decision default Interchangeable (option exists)",
		idf.default == "Interchangeable" and "Interchangeable" in (idf.options or "").split("\n"))

	# --- setup: Approved drawing + spec, two Items from EIRs, a default BOM for the first
	base = {"doctype": "Engineering Drawing", "drawing_type": "Assembly", "item_component": "993",
		"item_group": "ZZ Smoke Valves"}
	dwg = _as(EU, lambda: frappe.get_doc(dict(base, drawing_name="PR v153 GA",
		external_file_link="https://dms.example.local/dwg/prv153-a.pdf")).insert())
	approve("Engineering Drawing", dwg.name)
	ms = _as(EU, lambda: frappe.get_doc({"doctype": "Material Specification", "description": "ZZ smoke PR v153 spec",
		"critical_requirements": [{"description": "Leak tight", "acceptance_criteria": "API 598"}]}).insert())
	approve("Material Specification", ms.name)
	ms_draft = frappe.get_doc({"doctype": "Material Specification", "description": "ZZ smoke PR v153 draft"}).insert()
	items = []
	for n in ("1", "2"):
		ir = frappe.get_doc({"doctype": "Engineering Item Request", "item_name": f"Smoke PR v153 Valve {n}",
			"item_group": "ZZ Smoke Valves", "item_component": "993", "stock_uom": "Nos",
			"eng_item_category": "Manufacturing", "is_stock_item": 1, "engineering_drawing": dwg.name,
			"material_specification": ms.name,
			"item_request_attribute": _item_attr_rows((("Nominal Size", "2in"), ("Pressure Class", "600")))}).insert()
		ir.submit()
		items.append(ir.created_item)
	item, item2 = items
	PURE = "zz.smoke.pure.eu@example.com"
	if not frappe.db.exists("User", PURE):
		u = frappe.get_doc({"doctype": "User", "email": PURE, "first_name": "Smoke Pure EU",
			"send_welcome_email": 0, "user_type": "System User"}).insert(ignore_permissions=True)
		u.add_roles("Engineering User")
	pd = _as(PURE, lambda: REF.item_engineering_defaults(item))
	ok("Engineering-User-only (no Item/BOM read required) gets PR auto-fill drawing/MS",
		pd.drawing == dwg.name and pd.material_specification == ms.name)
	company = frappe.db.get_value("Company", {}, "name")
	rm = frappe.get_doc({"doctype": "Item", "item_code": "ZZ-PRV153-RM", "item_name": "ZZ PR v153 RM",
		"item_group": "ZZ DWG Group", "stock_uom": "Nos", "is_stock_item": 1}).insert()
	bom = frappe.get_doc({"doctype": "BOM", "item": item, "company": company, "quantity": 1,
		"rm_cost_as_per": "Valuation Rate", "items": [{"item_code": rm.name, "qty": 1, "rate": 1}]}).insert()
	bom.submit()

	# --- revision digits (shared 5XXXX space with the 993 drawing created above: 993-50001-0)
	def new_pr(it, **kw):
		# created by Administrator; Workflow moves below run as EU / EM
		return frappe.get_doc(dict({"doctype": "Product Revision", "item": it}, **kw)).insert()

	ok("get_next_revision: first revision of an Item is 0", PRM.get_next_revision(item) == "0")
	p1 = new_pr(item, revision_number="Q")
	p1_base = p1.name.rsplit("-", 1)[0]
	ok("First PR of the Item gets 0 (typed value ignored), {component}-5NNNN-0, not the Drawing name, starts Draft",
		p1.revision_number == "0" and p1.name == p1_base + "-0" and p1_base.startswith("993-5")
		and st(p1.name) == (0, "Draft") and p1.name != dwg.name)
	ok("New PR without Interchangeability Decision gets the default Interchangeable",
		frappe.db.get_value("Product Revision", p1.name, "interchangeability_decision") == "Interchangeable")
	p2 = new_pr(item, material_specification=ms_draft.name, interchangeability_decision="Not Interchangeable")
	p3 = new_pr(item)
	ok("Next PRs of the same Item keep the base and get 1 then 2", (p2.revision_number, p3.revision_number) == ("1", "2")
		and p2.name == p1_base + "-1" and p3.name == p1_base + "-2"
		and p2.interchangeability_decision == "Not Interchangeable")
	q1 = new_pr(item2, revision_number="9")
	q1_base = q1.name.rsplit("-", 1)[0]
	ok("A different Item gets a new number starting at 0",
		q1.revision_number == "0" and q1.name == q1_base + "-0" and q1_base.startswith("993-5") and q1_base != p1_base)

	def change_rev():
		x = frappe.get_doc("Product Revision", p1.name); x.revision_number = "9"; x.save()
	raises("Revision Number locked after insert", lambda: _as(EU, change_rev))
	ok("Revision Number unchanged after the refused edit", frappe.db.get_value("Product Revision", p1.name, "revision_number") == "0")

	# --- workflow
	def save_as(name, state):
		x = frappe.get_doc("Product Revision", name); x.workflow_state = state; x.save()
	raises("Draft cannot be saved straight to Approved (Workflow)", lambda: _as(EU, lambda: save_as(p1.name, "Approved")))
	raises("Draft cannot be submitted directly (only Under Review -> Approve)",
		lambda: _as(EM, lambda: frappe.get_doc("Product Revision", p1.name).submit()))
	_as(EU, lambda: wf("Product Revision", p1.name, "Submit for Review"))
	ok("Submit for Review -> Under Review (docstatus 0)", st(p1.name) == (0, "Under Review"))
	raises("Engineering User cannot Approve", lambda: _as(EU, lambda: wf("Product Revision", p1.name, "Approve")))
	_as(EM, lambda: wf("Product Revision", p1.name, "Return to Draft"))
	ok("Return to Draft (Engineering Manager)", st(p1.name) == (0, "Draft"))
	approve("Product Revision", p1.name)
	ok("Approve submits the PR (docstatus 1, Approved)", st(p1.name) == (1, "Approved"))
	_as(EU, lambda: wf("Product Revision", p2.name, "Submit for Review"))
	raises("Approve refused while the Material Specification is not Approved (before_submit)",
		lambda: _as(EM, lambda: wf("Product Revision", p2.name, "Approve")))
	ok("Refused Approve leaves the PR Under Review, not submitted", st(p2.name) == (0, "Under Review"))
	raises("Superseded cannot be set by a user (system-only)", lambda: save_as(p1.name, "Superseded"))
	raises("Released cannot be set by a user (system-only)", lambda: save_as(p1.name, "Released"))
	_as(EM, lambda: wf("Product Revision", p1.name, "Mark Release Ready"))
	ok("Mark Release Ready (needs submitted BOM) -> Release Ready, readiness Ready",
		frappe.db.get_value("Product Revision", p1.name, ["docstatus", "workflow_state", "release_readiness"])
		== (1, "Release Ready", "Ready"))
	rr_draft = _as(EU, lambda: PRM.create_revision(p1.name))
	ok("Revise allowed from Release Ready (Engineering User): unsaved Draft, next digit 3, Previous Revision = 0",
		rr_draft["previous_revision"] == p1.name and rr_draft["revision_number"] == "3"
		and rr_draft["workflow_state"] == "Draft" and not frappe.db.exists("Product Revision", p1_base + "-3"))
	raises("Revise refused on a Draft / Under Review Product Revision", lambda: PRM.create_revision(p2.name))

	# --- Engineering Release Released for Production -> PR Released (mark_released, system write)
	er = PRM.make_engineering_release(p1.name)
	er.update({"release_classification": "Standard", "company": company,
		"effective_datetime": add_to_date(now_datetime(), minutes=-1),
		"release_checklist": [{"checklist_item": "Smoke check", "is_complete": 1}]})
	er.insert()
	for action in ("Submit for Review", "Approve", "Release for Production"):
		apply_workflow(frappe.get_doc("Engineering Release", er.name), action)
	ok("Engineering Release reaches Released for Production",
		frappe.db.get_value("Engineering Release", er.name, "release_status") == "Released for Production")
	ok("ER Released for Production sets the PR Released / Ready (Workflow state, still submitted)",
		frappe.db.get_value("Product Revision", p1.name, ["docstatus", "workflow_state", "release_readiness"])
		== (1, "Released", "Ready"))

	# --- Revise from Released: new Draft (next digit, copied baseline, Previous Revision link); one open revision
	# at a time; approving it supersedes the source through the link (on_submit)
	src = frappe.get_doc("Product Revision", p1.name)
	rd = _as(EU, lambda: PRM.create_revision(p1.name))
	copied = ("item", "drawing_revision", "material_specification", "bom_revision_reference",
		"routing_revision_reference", "inspection_plan_revision_reference", "interchangeability_decision")
	ok("Revise from Released copies Item / Drawing / Material Specification / BOM / Routing / Inspection Plan / "
		"Interchangeability, leaves ECO and history empty",
		all(rd.get(f) == src.get(f) for f in copied) and not rd.get("applicable_eco")
		and not rd.get("superseding_revision") and rd.get("previous_revision") == p1.name)
	r1 = frappe.get_doc(rd)
	r1.insert()
	ok("Saved revision: next digit 3, Draft, Previous Revision = 0 (Released)",
		r1.revision_number == "3" and r1.name == p1_base + "-3" and st(r1.name) == (0, "Draft")
		and r1.previous_revision == p1.name)
	raises("Second Revise of the same Product Revision refused while one is open", lambda: PRM.create_revision(p1.name))
	raises("Saving another new revision of the same Product Revision refused (one open revision)",
		lambda: frappe.get_doc({"doctype": "Product Revision", "item": item, "previous_revision": p1.name}).insert())
	raises("A revision must keep the same Item", lambda: frappe.get_doc({"doctype": "Product Revision",
		"item": item2, "previous_revision": p1.name}).insert())
	approve("Product Revision", r1.name)
	ok("Approving the revision supersedes the Released source through the link",
		st(r1.name) == (1, "Approved") and st(p1.name) == (1, "Superseded")
		and frappe.db.get_value("Product Revision", p1.name, "superseding_revision") == r1.name)
	raises("Revise refused on a Superseded Product Revision", lambda: PRM.create_revision(p1.name))
	ok("Revise allowed from Approved (the new current revision)",
		_as(EM, lambda: PRM.create_revision(r1.name))["revision_number"] == "4")
	raises("An older draft cannot supersede the newer Approved revision", lambda: approve("Product Revision", p3.name))
	_as(EM, lambda: wf("Product Revision", p1.name, "Mark Obsolete"))
	ok("Mark Obsolete from Superseded -> Obsolete", st(p1.name) == (1, "Obsolete"))

	# --- standard Cancel / Amend still work; a cancelled digit is not reused by a new PR
	approve("Product Revision", q1.name)
	ok("Second Item's 0 approved (submitted)", st(q1.name) == (1, "Approved"))
	_as(EM, lambda: frappe.get_doc("Product Revision", q1.name).cancel())
	ok("Standard Cancel -> Cancelled (docstatus 2)", st(q1.name) == (2, "Cancelled"))
	q2 = new_pr(item2)
	ok("Next new PR after a cancelled 0 gets 1 (cancelled name stays taken)",
		q2.revision_number == "1" and q2.name == q1_base + "-1")
	am = frappe.copy_doc(frappe.get_doc("Product Revision", q1.name), ignore_no_copy=False)  # as Desk Amend
	am.amended_from = q1.name
	am.insert()
	ok("Amend keeps the cancelled revision 0 and starts Draft",
		am.revision_number == "0" and am.name == f"{q1.name}-1" and st(am.name) == (0, "Draft"))
	ok("Mark Obsolete from Approved (Drawing transition) -> Obsolete",
		_as(EM, lambda: wf("Product Revision", r1.name, "Mark Obsolete")) and st(r1.name) == (1, "Obsolete"))


def _report():
	failed = [l for l, r in RESULTS if not r]
	print("SMOKE", "OK" if not failed else f"FAIL {failed}", f"({len(RESULTS)} checks)")
	return {"checks": len(RESULTS), "failed": failed}


DWG_USERS = {
	"zz.dwg.user@example.com": ("Engineering User",),
	"zz.dwg.mgr@example.com": ("Engineering Manager", "Engineering User"),
	"zz.dwg.mgr2@example.com": ("Engineering Manager",),
}


def _dwg_setup():
	if not frappe.db.exists("Item Group", "All Item Groups"):
		frappe.get_doc({"doctype": "Item Group", "item_group_name": "All Item Groups", "is_group": 1}).insert()
	for g in ("ZZ DWG Group", "ZZ DWG Other"):
		frappe.get_doc({"doctype": "Item Group", "item_group_name": g, "parent_item_group": "All Item Groups"}).insert()
	frappe.get_doc({"doctype": "Item Component", "part_code_prefix": "991", "component_name": "ZZ Smoke Body", "item_group": "ZZ DWG Group"}).insert()
	frappe.get_doc({"doctype": "Item Component", "part_code_prefix": "992", "component_name": "ZZ Smoke Bonnet", "item_group": "ZZ DWG Group"}).insert()
	for email, roles in DWG_USERS.items():
		u = frappe.get_doc({"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0,
			"user_type": "System User"}).insert(ignore_permissions=True)
		u.add_roles(*roles)


def _as(user, fn):
	prev = frappe.session.user
	frappe.set_user(user)
	try:
		return fn()
	finally:
		frappe.set_user(prev)


def _wf(name, action):
	from frappe.model.workflow import apply_workflow

	return apply_workflow(frappe.get_doc("Engineering Drawing", name), action)


def run_drawing(report=True):
	"""v15.3.0 Engineering Drawing checks (rollback only)."""
	from frappe.utils import nowdate

	from engineering_itagksa.engineering_itag_ksa.doctype.engineering_drawing.engineering_drawing import (
		create_revision,
		make_product_revision,
		next_revision_letter,
	)

	frappe.set_user("Administrator")
	EU, EM, EM2 = list(DWG_USERS)
	get = lambda n, f: frappe.db.get_value("Engineering Drawing", n, f)  # noqa: E731
	try:
		_dwg_setup()
		ok("Drawing has no item_code field", not frappe.get_meta("Engineering Drawing").has_field("item_code"))
		ok("Drawing is not submittable", not frappe.get_meta("Engineering Drawing").is_submittable)
		base = {"doctype": "Engineering Drawing", "drawing_type": "Assembly", "item_component": "991",
			"external_file_link": "https://dms.example.local/dwg/991.pdf"}

		# naming series {component}-5NNNN-{revision} (no DWG- prefix); series key remains DWG-{component}-5
		a = _as(EU, lambda: frappe.get_doc(dict(base, drawing_name="Smoke body GA", revision="q")).insert())
		ok("New drawing gets Revision 0 automatically (typed Q ignored): 991-50001-0", a.name == "991-50001-0" and a.revision == "0")
		ok("Item Group defaulted from Item Component", a.item_group == "ZZ DWG Group")
		ok("New drawing starts Draft", a.workflow_state == "Draft")
		other = frappe.get_doc(dict(base, item_component="992", drawing_name="Bonnet", revision="0")).insert()
		ok("Counter is per component (992 starts at 50001-0)", other.name == "992-50001-0")
		ok("Invalid typed revision ignored, 0 assigned", frappe.get_doc(dict(base, drawing_name="x", revision="A_1")).insert().revision == "0")
		ok("Revision field is read-only with default 0", frappe.get_meta("Engineering Drawing").get_field("revision").read_only == 1
			and frappe.get_meta("Engineering Drawing").get_field("revision").default == "0")
		ok("Revises field is hidden", frappe.get_meta("Engineering Drawing").get_field("revises").hidden == 1)
		raises("Item Component outside Item Group refused", lambda: frappe.get_doc(dict(base, drawing_name="x", revision="Q",
			item_group="ZZ DWG Other")).insert())
		raises("Drawing Name required", lambda: frappe.get_doc(dict(base, revision="Q")).insert())
		raises("Item Component required", lambda: frappe.get_doc(dict(base, drawing_name="x", revision="Q", item_component=None)).insert())
		raises("New drawing cannot be inserted as Approved", lambda: frappe.get_doc(dict(base, drawing_name="x", revision="Q",
			workflow_state="Approved")).insert())

		def change_rev():
			d = frappe.get_doc("Engineering Drawing", a.name); d.revision = "Z"; d.save()
		raises("Revision locked after creation (set_only_once)", change_rev)

		def change_comp():
			d = frappe.get_doc("Engineering Drawing", a.name); d.item_component = "992"; d.save()
		raises("Item Component locked after creation (set_only_once)", change_comp)

		def hand_superseded():
			d = frappe.get_doc("Engineering Drawing", a.name); d.workflow_state = "Superseded"; d.save()
		raises("Superseded cannot be set by hand", hand_superseded)

		# checksum attestation (unchanged behaviour)
		ok("Typed SHA-256 ignored on link-only drawing",
			not frappe.get_doc(dict(base, drawing_name="x", revision="X", file_checksum_sha256="abc")).insert().file_checksum_sha256)
		raises("Secret in URL rejected", lambda: frappe.get_doc(dict(base, drawing_name="x", revision="Y",
			external_file_link="https://x/y.pdf?token=abc")).insert())
		raises("Neither link nor local file rejected", lambda: frappe.get_doc(dict(base, drawing_name="x", revision="Y",
			external_file_link="")).insert())
		raises("Public local drawing file rejected", lambda: frappe.get_doc(dict(base, drawing_name="x", revision="Y",
			external_file_link="", drawing_file="/files/x.pdf")).insert())
		fl1, fl2 = _pfile("ZZ-DWG-L.txt", b"L1"), _pfile("ZZ-DWG-L2.txt", b"L2")
		dwl = frappe.get_doc(dict(base, drawing_name="x", revision="L", external_file_link="", drawing_file=fl1,
			checksum_attested_by="Guest")).insert()
		ok("Local private file accepted + SHA-256 computed, client attester ignored",
			dwl.file_checksum_sha256 == hashlib.sha256(b"L1").hexdigest() and not dwl.checksum_attested_by)
		dwl.checksum_attested = 1; dwl.save()
		ok("Server stamped attester/time", dwl.checksum_attested_by == "Administrator" and dwl.checksum_attested_on)
		dwl.drawing_file = fl2; dwl.save()
		ok("File change clears attestation", not dwl.checksum_attested and not dwl.checksum_attested_by)

		# Workflow path + segregation of duties
		_as(EU, lambda: _wf(a.name, "Submit for Review"))
		ok("Draft -> Under Review by Engineering User", get(a.name, "workflow_state") == "Under Review"
			and get(a.name, "submitted_for_review_by") == EU)
		raises("Engineering User cannot Approve", lambda: _as(EU, lambda: _wf(a.name, "Approve")))
		_as(EM, lambda: _wf(a.name, "Return to Draft"))
		ok("Under Review -> Draft by Engineering Manager (review stamp cleared)", get(a.name, "workflow_state") == "Draft"
			and not get(a.name, "submitted_for_review_by"))
		_as(EM, lambda: _wf(a.name, "Submit for Review"))
		raises("Approver must differ from the user who submitted for review", lambda: _as(EM, lambda: _wf(a.name, "Approve")))
		_as(EM2, lambda: _wf(a.name, "Approve"))
		ok("Under Review -> Approved by a different Engineering Manager", get(a.name, "workflow_state") == "Approved"
			and get(a.name, "approved_by") == EM2 and get(a.name, "approved_on"))

		def edit_locked():
			d = frappe.get_doc("Engineering Drawing", a.name); d.change_description = "edit after approve"; d.save()
		raises("Approved drawing content frozen", edit_locked)

		def back_to_draft():
			d = frappe.get_doc("Engineering Drawing", a.name); d.workflow_state = "Draft"; d.save()
		raises("Approved cannot go back to Draft (forward-only)", back_to_draft)

		# Create Revision button (Approved only, prefilled, one open revision per drawing)
		ok("Next revision letters A->B, Z->AA, AZ->BA, 09->10 (helper still used for letter mapping)",
			[next_revision_letter(x) for x in ("A", "Z", "AZ", "09", "B.1")] == ["B", "AA", "BA", "10", ""])
		raises("Create Revision refused on a Draft drawing", lambda: create_revision(other.name))
		cr = _as(EU, lambda: create_revision(a.name))
		ok("Create Revision prefills name/group/component/type/revises, suggests 1, file+checksum empty",
			cr["drawing_name"] == a.drawing_name and cr["item_group"] == a.item_group and cr["item_component"] == "991"
			and cr["drawing_type"] == "Assembly" and cr["revises"] == a.name and cr["revision"] == "1"
			and not cr.get("drawing_file") and not cr.get("external_file_link") and not cr.get("file_checksum_sha256")
			and cr["workflow_state"] == "Draft")
		raises("Create Revision draft without a file cannot be saved",
			lambda: _as(EU, lambda: frappe.get_doc(dict(create_revision(a.name))).insert()))
		cr_doc = _as(EU, lambda: frappe.get_doc(dict(create_revision(a.name),
			external_file_link="https://dms.example.local/dwg/991-b.pdf")).insert())
		ok("Create Revision draft saves once a file is attached", cr_doc.revises == a.name and cr_doc.revision == "1")
		raises("Second Create Revision blocked while one is open", lambda: _as(EU, lambda: create_revision(a.name)))
		raises("Second manual revision of the same drawing blocked while one is open", lambda: frappe.get_doc(dict(base,
			drawing_name="x", revision="Q", revises=a.name)).insert())
		frappe.delete_doc("Engineering Drawing", cr_doc.name, force=1)

		# new revision = new document, same number base, revises -> Superseded on Approve (series unchanged)
		series_before = int(frappe.db.get_value("Series", "DWG-991-5", "current", order_by="name") or 0)
		b = _as(EU, lambda: frappe.get_doc(dict(base, drawing_name="Smoke body GA", revision="Z", revises=a.name)).insert())
		ok("Revision 1 keeps the same drawing number base ({0}-1); series unchanged".format(a.name.rsplit("-", 1)[0]),
			b.name == a.name.rsplit("-", 1)[0] + "-1"
			and int(frappe.db.get_value("Series", "DWG-991-5", "current", order_by="name") or 0) == series_before)
		raises("Revises must keep the same Item Component", lambda: frappe.get_doc(dict(base, item_component="992",
			drawing_name="x", revision="C", revises=a.name)).insert())
		ok("Revision of 0 is assigned 1 automatically (typed Z ignored)", b.revision == "1")
		_as(EU, lambda: _wf(b.name, "Submit for Review"))
		ok("A still Approved while B is Under Review", get(a.name, "workflow_state") == "Approved")
		_as(EM, lambda: _wf(b.name, "Approve"))
		ok("B Approved", get(b.name, "workflow_state") == "Approved")
		ok("A Superseded by B automatically (same transaction)", get(a.name, "workflow_state") == "Superseded"
			and get(a.name, "superseded_by") == b.name and str(get(a.name, "superseded_date")) == nowdate())
		c = frappe.get_doc(dict(base, drawing_name="Smoke body GA", revision="C", revises=a.name)).insert()
		_as(EU, lambda: _wf(c.name, "Submit for Review"))
		raises("Cannot approve a revision of an already Superseded drawing", lambda: _as(EM, lambda: _wf(c.name, "Approve")))
		raises("Create Revision refused on a Superseded drawing", lambda: create_revision(a.name))

		def superseded_back():
			d = frappe.get_doc("Engineering Drawing", a.name); d.workflow_state = "Approved"; d.save()
		raises("Superseded cannot go back to Approved", superseded_back)
		_as(EM, lambda: _wf(a.name, "Mark Obsolete"))
		ok("Superseded -> Obsolete by Engineering Manager", get(a.name, "workflow_state") == "Obsolete")
		raises("Engineering User cannot Mark Obsolete", lambda: _as(EU, lambda: _wf(b.name, "Mark Obsolete")))
		_as(EM, lambda: _wf(b.name, "Mark Obsolete"))
		ok("Approved -> Obsolete by Engineering Manager (manual)", get(b.name, "workflow_state") == "Obsolete")
		raises("Product Revision mapping from Drawing refused until PR redesign", lambda: make_product_revision(b.name))

		# 9,999 drawings per component (50001..59999)
		frappe.db.sql("update `tabSeries` set `current` = 9998 where `name` = %s", "DWG-992-5")
		last = frappe.get_doc(dict(base, item_component="992", drawing_name="last", revision="A")).insert()
		ok("Number 59999 is the last one", last.name == "992-59999-0")
		raises("10,000th drawing of a component refused", lambda: frappe.get_doc(dict(base, item_component="992",
			drawing_name="over", revision="B")).insert())
	finally:
		frappe.db.rollback()
		frappe.set_user("Administrator")
		frappe.clear_messages()
		frappe.clear_cache()
		for path in _FILES:
			if os.path.exists(path):
				os.remove(path)
	print("ROLLBACK residue drawings (991/992):", frappe.db.count("Engineering Drawing", {"item_component": ["in", ["991", "992"]]}))
	if report:
		return _report()
