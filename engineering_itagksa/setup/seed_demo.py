"""Idempotent LOCAL demo seed for Engineering ITAG KSA e2e (Release + Work Order gate).

LOCAL BENCH ONLY. Does NOT create a Company and does NOT run the setup wizard: it requires the
setup wizard to be complete and uses the default Company (or the one passed in).

Run:
  bench --site <site> execute engineering_itagksa.setup.seed_demo.run
  bench --site <site> execute engineering_itagksa.setup.seed_demo.run --kwargs "{'company': 'Globcom Qatar Demo'}"
  bench --site <site> execute engineering_itagksa.setup.seed_demo.verify
Re-running is safe: existing records are reused, never duplicated.
"""

import frappe

ITEM_GROUP = "Engineering ITAG KSA Demo - Engineered Products"
COMPONENT_GROUP = "Engineering ITAG KSA Demo - Components"
FG_ITEM = "DEMO-FG-VALVE-001"
COMPONENTS = [
	("DEMO-RM-BODY-001", "Demo Valve Body (Cast A216 WCB)", 1),
	("DEMO-RM-TRIM-001", "Demo Valve Trim Set (SS316)", 1),
]
WORKSTATION = "DEMO-ASSEMBLY-WS"


def _company(company=None):
	if not frappe.is_setup_complete():
		frappe.throw("Setup wizard not complete; finish it (Company) before seeding.")
	company = company or frappe.defaults.get_global_default("company") or frappe.db.get_value("Company", {}, "name")
	if not company or not frappe.db.exists("Company", company):
		frappe.throw("No Company found; complete setup wizard first.")
	return company


def _uom():
	for u in ("Nos", "Unit"):
		if frappe.db.exists("UOM", u):
			return u
	frappe.get_doc({"doctype": "UOM", "uom_name": "Nos", "must_be_whole_number": 1}).insert()
	return "Nos"


def _item_group(name, flag):
	if not frappe.db.exists("Item Group", name):
		parent = frappe.db.get_value("Item Group", {"is_group": 1, "parent_item_group": ["in", ["", None]]}, "name") or "All Item Groups"
		frappe.get_doc({"doctype": "Item Group", "item_group_name": name, "parent_item_group": parent, "is_group": 0,
			"requires_engineering_release": flag}).insert()
	else:
		frappe.db.set_value("Item Group", name, "requires_engineering_release", flag)
	return name


def _warehouse(company, wh_name):
	abbr = frappe.get_cached_value("Company", company, "abbr")
	name = f"{wh_name} - {abbr}"
	if not frappe.db.exists("Warehouse", name):
		parent = frappe.db.get_value("Warehouse", {"company": company, "is_group": 1}, "name")
		frappe.get_doc({"doctype": "Warehouse", "warehouse_name": wh_name, "company": company,
			"parent_warehouse": parent}).insert()
	return name


def _item(code, item_name, group, uom, category, extra=None):
	if not frappe.db.exists("Item", code):
		d = {"doctype": "Item", "item_code": code, "item_name": item_name, "item_group": group, "stock_uom": uom,
			"is_stock_item": 1, "include_item_in_manufacturing": 1, "eng_item_category": category,
			"valuation_rate": 100}
		d.update(extra or {})
		frappe.get_doc(d).insert()
	return code


def run(company=None):
	company = _company(company)
	uom = _uom()
	_item_group(ITEM_GROUP, 1)
	_item_group(COMPONENT_GROUP, 1)
	stores = _warehouse(company, "Stores")
	wip = _warehouse(company, "Work In Progress")
	fg_wh = _warehouse(company, "Finished Goods")

	for code, nm, _q in COMPONENTS:
		_item(code, nm, COMPONENT_GROUP, uom, "Raw Material", {"is_purchase_item": 1})
	_item(FG_ITEM, "Demo Gate Valve 4in CL300 (Engineering ITAG KSA seed)", ITEM_GROUP, uom, "Manufacturing",
		{"default_bom": None})

	ms = frappe.get_single("Manufacturing Settings")
	changed = False
	for f, v in (("default_wip_warehouse", wip), ("default_fg_warehouse", fg_wh)):
		if not ms.get(f):
			ms.set(f, v); changed = True
	if changed:
		ms.save()

	bom = frappe.db.get_value("BOM", {"item": FG_ITEM, "docstatus": 1, "is_active": 1, "is_default": 1, "company": company}, "name")
	if not bom:
		b = frappe.get_doc({"doctype": "BOM", "item": FG_ITEM, "company": company, "quantity": 1,
			"is_active": 1, "is_default": 1, "rm_cost_as_per": "Valuation Rate",
			"items": [{"item_code": c, "qty": q, "uom": uom, "rate": 100} for c, _n, q in COMPONENTS]})
		b.insert(); b.submit(); bom = b.name

	frappe.db.commit()
	out = {"company": company, "uom": uom, "item_groups": [ITEM_GROUP, COMPONENT_GROUP],
		"warehouses": [stores, wip, fg_wh], "items": [FG_ITEM] + [c for c, *_ in COMPONENTS], "bom": bom}
	print(frappe.as_json(out))
	return out


def create_draft_work_order(company=None):
	"""Create (or reuse) ONE draft Work Order for the FG item; then prove the gate on submit (rolled back)."""
	company = _company(company)
	bom = frappe.db.get_value("BOM", {"item": FG_ITEM, "docstatus": 1, "is_default": 1}, "name")
	wo_name = frappe.db.get_value("Work Order", {"production_item": FG_ITEM, "docstatus": 0, "company": company}, "name")
	if not wo_name:
		abbr = frappe.get_cached_value("Company", company, "abbr")
		wo = frappe.get_doc({"doctype": "Work Order", "production_item": FG_ITEM, "bom_no": bom, "qty": 1,
			"company": company, "wip_warehouse": f"Work In Progress - {abbr}", "fg_warehouse": f"Finished Goods - {abbr}",
			"source_warehouse": f"Stores - {abbr}"})
		wo.insert(); wo_name = wo.name
		frappe.db.commit()
	# gate proof: try submit inside a savepoint, always roll back
	result = None
	frappe.db.savepoint("gate_proof")
	try:
		frappe.get_doc("Work Order", wo_name).submit()
		result = "SUBMITTED (gate did NOT block)"
	except Exception as e:
		result = f"BLOCKED: {frappe.utils.strip_html(str(e))}"
	finally:
		frappe.db.rollback(save_point="gate_proof")
	frappe.message_log = []
	out = {"work_order": wo_name, "docstatus": frappe.db.get_value("Work Order", wo_name, "docstatus"), "gate_submit_test": result}
	print(frappe.as_json(out))
	return out


def verify(company=None):
	company = _company(company)
	out = {
		"company": frappe.db.get_value("Company", company, ["name", "abbr", "default_currency", "country"], as_dict=True),
		"item_groups": frappe.get_all("Item Group", filters={"name": ["in", [ITEM_GROUP, COMPONENT_GROUP]]}, fields=["name", "requires_engineering_release"]),
		"items": frappe.get_all("Item", filters={"name": ["like", "DEMO-%"]}, fields=["name", "item_group", "eng_item_category", "is_stock_item", "default_bom"]),
		"boms": frappe.get_all("BOM", filters={"item": FG_ITEM}, fields=["name", "docstatus", "is_active", "is_default"]),
		"warehouses": frappe.get_all("Warehouse", filters={"company": company, "is_group": 0}, pluck="name"),
		"work_orders": frappe.get_all("Work Order", filters={"production_item": FG_ITEM}, fields=["name", "docstatus", "status", "bom_no"]),
	}
	print(frappe.as_json(out))
	return out
