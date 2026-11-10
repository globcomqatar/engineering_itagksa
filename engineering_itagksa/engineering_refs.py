"""Item -> engineering references (Owner-approved Product Revision draft v0.1, 2026-11-10).

Since v15.3.0 an Engineering Drawing / Material Specification carries no Item Code. An Item's engineering
references now come from the Engineering Item Request that created it (``created_item``):
  * Drawing: EIR.engineering_drawing (fallback Item.eng_design), moved forward to the current Approved revision
  * Material Specification: EIR.material_specification (the Item stores none itself), moved forward the same way
  * BOM: Item.default_bom, else Item.eng_bom, else the latest active submitted BOM of the Item.

Drawing rule (replaces the old "submitted, Released, same item_code" check): the drawing must be Approved
(Approved is the final released state of the "Engineering ITAG KSA Engineering Drawing" Workflow; there is no Released and no
docstatus 1). Where the Item's own drawing is known, the drawing must be that drawing or another revision in the same
``revises`` chain (a revision is a new drawing document, so a plain name compare would refuse every later
revision). When the Item's drawing is unknown the match is skipped (nothing reliable to compare with).

Auto-fill (v15.3.6): ``item_engineering_defaults`` looks up those names and codes on the server without requiring
Item or BOM read permission. The caller must be able to create or read Product Revision or Engineering Release.
It does not return document contents and does not widen role permissions.
"""

import frappe
from frappe import _

from engineering_itagksa.constants import APPROVED

DRAWING = "Engineering Drawing"
SPEC = "Material Specification"
_MAX_CHAIN = 200  # loop guard for revises / superseded_by walks


def chain_root(doctype, name):
	"""First document of the ``revises`` chain that ``name`` belongs to (``name`` itself if it revises nothing)."""
	seen = set()
	cur = name
	while cur and cur not in seen and len(seen) < _MAX_CHAIN:
		seen.add(cur)
		prev = frappe.db.get_value(doctype, cur, "revises")
		if not prev:
			return cur
		cur = prev
	return cur


def current_approved(doctype, name):
	"""``name`` if Approved; if Superseded, follow ``superseded_by`` to the Approved revision. Else None."""
	seen = set()
	cur = name
	while cur and cur not in seen and len(seen) < _MAX_CHAIN:
		seen.add(cur)
		row = frappe.db.get_value(doctype, cur, ["workflow_state", "superseded_by"], as_dict=True)
		if not row:
			return None
		if row.workflow_state == APPROVED:
			return cur
		cur = row.superseded_by
	return None


def creating_item_request(item):
	"""Latest submitted Engineering Item Request whose ``created_item`` is ``item`` (name, drawing, spec) or None."""
	if not item:
		return None
	rows = frappe.get_all(
		"Engineering Item Request",
		filters={"created_item": item, "docstatus": 1},
		fields=["name", "engineering_drawing", "material_specification"],
		order_by="creation desc",
		limit=1,
	)
	return rows[0] if rows else None


def item_drawing(item):
	"""The Item's own drawing as recorded on its Engineering Item Request, else Item.eng_design (may be None)."""
	eir = creating_item_request(item)
	if eir and eir.engineering_drawing:
		return eir.engineering_drawing
	if item and frappe.get_meta("Item").has_field("eng_design"):
		return frappe.db.get_value("Item", item, "eng_design")
	return None


def items_for_drawing(drawing):
	"""Submitted Engineering Item Requests whose drawing is ``drawing`` or another revision in the same
	``revises`` chain; returns the created Item codes (may be empty)."""
	if not drawing:
		return []
	root = chain_root(DRAWING, drawing)
	rows = frappe.get_all(
		"Engineering Item Request",
		filters={"docstatus": 1, "engineering_drawing": ["is", "set"], "created_item": ["is", "set"]},
		fields=["created_item", "engineering_drawing"],
	)
	items = []
	seen = set()
	for r in rows:
		if not r.created_item or r.created_item in seen:
			continue
		if r.engineering_drawing == drawing or chain_root(DRAWING, r.engineering_drawing) == root:
			seen.add(r.created_item)
			items.append(r.created_item)
	return items


def drawing_matches_item(drawing, item):
	"""True if ``drawing`` is in the same revises chain as the Item's drawing, or if the Item's drawing is unknown."""
	expected = item_drawing(item)
	if not expected or not drawing:
		return True
	if expected == drawing:
		return True
	return chain_root(DRAWING, expected) == chain_root(DRAWING, drawing)


def assert_drawing_matches_item(drawing, item):
	if drawing and item and not drawing_matches_item(drawing, item):
		frappe.throw(_("Engineering Drawing {0} is not the drawing of item {1} ({2}) or a revision of it.").format(
			frappe.bold(drawing), frappe.bold(item), item_drawing(item)))


def assert_drawing_approved(drawing, item=None):
	"""Drawing must exist and be Approved; with ``item``, it must also belong to the Item's drawing chain."""
	if not drawing:
		frappe.throw(_("Drawing Revision is required."))
	state = frappe.db.get_value(DRAWING, drawing, "workflow_state")
	if state != APPROVED:
		frappe.throw(_("Engineering Drawing {0} must be {1} (it is {2}).").format(
			frappe.bold(drawing), APPROVED, state or _("not found")))
	assert_drawing_matches_item(drawing, item)


def _readable(doctype, name, check_perm):
	if not name:
		return None
	if not check_perm:
		return name if frappe.db.exists(doctype, name) else None
	return name if frappe.db.exists(doctype, name) and frappe.has_permission(doctype, "read", name) else None


def item_bom(item):
	"""Item.default_bom, else Item.eng_bom (if a submitted active BOM of the Item), else the latest active submitted
	BOM of the Item."""
	if not item:
		return None
	fields = ["default_bom"] + (["eng_bom"] if frappe.get_meta("Item").has_field("eng_bom") else [])
	vals = frappe.db.get_value("Item", item, fields, as_dict=True) or frappe._dict()
	for bom in (vals.get("default_bom"), vals.get("eng_bom")):
		if bom:
			b = frappe.db.get_value("BOM", bom, ["item", "docstatus", "is_active"], as_dict=True)
			if b and b.item == item and b.docstatus == 1 and b.is_active:
				return bom
	return frappe.db.get_value("BOM", {"item": item, "docstatus": 1, "is_active": 1}, "name",
		order_by="creation desc")


def _can_autofill_engineering():
	"""True if the session user may create or read Product Revision or Engineering Release."""
	for dt in ("Product Revision", "Engineering Release"):
		if frappe.has_permission(dt, "create") or frappe.has_permission(dt, "read"):
			return True
	return False


def item_engineering_defaults(item, check_perm=True):
	"""{drawing, material_specification, bom} names/codes for ``item``.

	Drawing / Material Specification are moved forward to the current Approved revision when the linked one was
	Superseded; if none is Approved the linked value is returned as is (the submit check then explains why).

	When ``check_perm`` is True the user must be able to create or read Product Revision or Engineering Release.
	The Item / BOM / Item Request permission check is not applied: the lookup runs on the server and only
	name strings are returned. Document contents are never included.
	"""
	out = frappe._dict(drawing=None, material_specification=None, bom=None, item_request=None)
	if not item or not frappe.db.exists("Item", item):
		return out
	if check_perm and not _can_autofill_engineering():
		return out
	eir = creating_item_request(item)
	drawing = (eir.engineering_drawing if eir else None) or (
		frappe.db.get_value("Item", item, "eng_design") if frappe.get_meta("Item").has_field("eng_design") else None)
	if drawing:
		drawing = current_approved(DRAWING, drawing) or drawing
	spec = eir.material_specification if eir else None
	if spec:
		spec = current_approved(SPEC, spec) or spec
	out.item_request = eir.name if eir else None
	# Names/codes only: skip Item/BOM/EIR/Drawing/MS read checks (v15.3.6 auto-fill).
	out.drawing = _readable(DRAWING, drawing, check_perm=False)
	out.material_specification = _readable(SPEC, spec, check_perm=False)
	out.bom = _readable("BOM", item_bom(item), check_perm=False)
	return out
