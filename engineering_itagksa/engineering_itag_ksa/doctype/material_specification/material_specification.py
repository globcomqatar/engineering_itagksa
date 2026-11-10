# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt

"""Material Specification (v15.3.0, Owner decisions 2026-11-09). Mirrors Engineering Drawing v2.

* No Item Code. Not submittable. Status (``workflow_state``) is driven by the standard Desk Workflow
  "Engineering ITAG KSA Material Specification" (install.py MS_STATES / MS_TRANSITIONS):
  Draft -> Under Review -> Approved -> Obsolete;  Under Review -> Draft;  Superseded -> Obsolete.
  Superseded is system-only. Once Approved the status only moves forward and the content is frozen.
* Name MSBV-NNNNN-<revision> (v15.3.5: the hyphen between MS and BV is dropped). A new specification takes the
  next number of the existing ``MS-BV-`` series (the Series key is unchanged so numbers already issued are not
  reused) with revision 0: MSBV-00001-0, MSBV-00002-0. Create Revision keeps the source's number and adds 1:
  MSBV-00001-1, MSBV-00001-2. Unlike Drawing, a revision does NOT take a new number.
* Revision is set by the system (read-only, fixed at creation). Revises (hidden, read-only) links a revision to its
  source. One open (Draft / Under Review) revision per chain.
* One Approved specification per revision chain (same MSBV number, plus the Revises source): approving
  MSBV-00001-1 supersedes MSBV-00001-0 (or an existing MS-BV-00001-0, which keeps its name) in the same DB
  transaction. A revision of an existing MS-BV-00001-0 is named MSBV-00001-1 (same number, new prefix, next digit).
* Old records (MS-BV-NNNNN-<rev>, and TS-{item}-{revision} from before the v15.3.0 DocType rename) keep their
  names. A revision of a TS- named record takes a fresh MSBV number with revision 0 (Revises is kept).
"""

import json
import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import make_autoname
from frappe.utils import cint, now_datetime

from engineering_itagksa import lifecycle as L
from engineering_itagksa.constants import APPROVED, DRAFT, OBSOLETE, SUPERSEDED, UNDER_REVIEW

DOCTYPE = "Material Specification"
FIELD = "workflow_state"
FIRST_REVISION = "0"
# Series key stays "MS-BV-" so the existing counter continues; new names use the MSBV- prefix.
SERIES = "MS-BV-.#####"
SERIES_KEY = "MS-BV-"
SERIES_MAX = 99999
OLD_NAME_RE = re.compile(r"^(MS-BV-\d{5})-(\d+)$")
NEW_NAME_RE = re.compile(r"^(MSBV-\d{5})-(\d+)$")
OPEN_STATES = (DRAFT, UNDER_REVIEW)
LOCKED_STATES = (APPROVED, SUPERSEDED, OBSOLETE)
LOCKED_NEXT = {
	APPROVED: (APPROVED, SUPERSEDED, OBSOLETE),
	SUPERSEDED: (SUPERSEDED, OBSOLETE),
	OBSOLETE: (OBSOLETE,),
}
# descriptive content copied by Create Revision
COPY_FIELDS = ("specification_name", "description", "applicable_standards", "material_requirements", "pressure_limit", "temperature_limit",
	"design_constraints", "testing_requirements", "certification_requirements")
MUTABLE_WHEN_LOCKED = {FIELD, "superseded_by", "superseded_on", "modified", "modified_by"}


def _canonical_base(base):
	"""MS-BV-00001 -> MSBV-00001; already-canonical bases are returned as-is."""
	if base and base.startswith("MS-BV-"):
		return "MSBV-" + base[6:]
	return base


def _search_bases(canonical_base):
	"""Both prefixes of the same number, so a revision of MS-BV-00001-0 sees MSBV-00001-1 and vice versa."""
	if not canonical_base:
		return []
	bases = [canonical_base]
	if canonical_base.startswith("MSBV-"):
		bases.append("MS-BV-" + canonical_base[5:])
	elif canonical_base.startswith("MS-BV-"):
		bases.append("MSBV-" + canonical_base[6:])
	return bases


def split_name(name):
	"""(canonical base MSBV-NNNNN, revision int) for a current or legacy MS-BV name, else (None, None)."""
	m = NEW_NAME_RE.match(name or "")
	if m:
		return m.group(1), int(m.group(2))
	m = OLD_NAME_RE.match(name or "")
	if m:
		return _canonical_base(m.group(1)), int(m.group(2))
	return None, None


def chain_names(name, revises=None):
	"""Names in the same revision chain: same MSBV number (either prefix), plus the Revises source."""
	base = split_name(name)[0]
	names = set()
	if base:
		for b in _search_bases(base):
			names.update(n for n in frappe.get_all(DOCTYPE, filters={"name": ["like", b + "-%"]}, pluck="name")
				if split_name(n)[0] == base)
	if revises:
		names.add(revises)
	return names


def next_revision(source_name):
	"""(canonical base or None, revision str) for a revision of ``source_name``.

	MS-BV-00001-0 or MSBV-00001-0: same number as MSBV-00001, highest existing revision + 1.
	Old-named (TS-…) source: fresh number, revision 0.
	"""
	base, _rev = split_name(source_name)
	if not base:
		return None, FIRST_REVISION
	return base, str(max(split_name(n)[1] for n in chain_names(source_name)) + 1)


def open_revision_of(source_name, exclude=None):
	"""A Draft / Under Review specification that already revises ``source_name`` or sits in its chain."""
	names = chain_names(source_name) - {source_name}
	filters = {FIELD: ["in", list(OPEN_STATES)]}
	if exclude:
		filters["name"] = ["!=", exclude]
	or_filters = {"revises": source_name}
	if names:
		or_filters["name"] = ["in", list(names)]
	rows = frappe.get_all(DOCTYPE, filters=filters, or_filters=or_filters, fields=["name", FIELD], limit=1)
	return rows[0] if rows else None


class MaterialSpecification(Document):
	def before_naming(self):
		self.assign_revision()
		L.normalize_revision(self, "revision")

	def autoname(self):
		base = self.revises and next_revision(self.revises)[0]
		if not base:
			used = cint(frappe.db.get_value("Series", SERIES_KEY, "current", order_by="name"))
			if used >= SERIES_MAX:
				frappe.throw(_("All {0} Material Specification numbers are used.").format(SERIES_MAX))
			raw = make_autoname(SERIES, doc=self)  # still MS-BV-NNNNN from the existing series
			base = _canonical_base(raw)
		self.name = f"{base}-{self.revision}"
		if frappe.db.exists(DOCTYPE, self.name):
			frappe.throw(_("Material Specification {0} already exists.").format(frappe.bold(self.name)), frappe.DuplicateEntryError)

	def validate(self):
		if self.is_new():
			self.assign_revision()
		L.normalize_revision(self, "revision")
		if not self.get(FIELD):
			self.set(FIELD, DRAFT)
		old, new = L.get_transition(self, FIELD)
		if self.is_new() and new != DRAFT:
			frappe.throw(_("A new Material Specification starts as {0}.").format(DRAFT))
		if new == SUPERSEDED and old != SUPERSEDED:
			frappe.throw(_("Superseded is set automatically when a newer revision of this specification is Approved."))
		self.enforce_lock(old)
		if old in LOCKED_STATES and not self.is_new():
			self.flags.entering_approved = False
			return
		if self.is_new():
			self.validate_revises()
		self.stamp_review(old, new)
		self.flags.entering_approved = new == APPROVED and old != APPROVED
		if self.flags.entering_approved:
			L.guard_not_older_than_active(self, self._other_approved())

	def assign_revision(self):
		"""Never typed: 0 for a new specification; for a revision (Revises set by Create Revision) the next number."""
		if not self.revises:
			self.revision = FIRST_REVISION
			return
		if not frappe.db.exists(DOCTYPE, self.revises):
			frappe.throw(_("Revised Material Specification {0} not found.").format(self.revises))
		self.revision = next_revision(self.revises)[1]

	def validate_revises(self):
		if not self.revises:
			return
		state, by = frappe.db.get_value(DOCTYPE, self.revises, [FIELD, "superseded_by"])
		if state != APPROVED or by:
			frappe.throw(_("Only an Approved, not superseded Material Specification can be revised ({0} is {1}).").format(
				frappe.bold(self.revises), state))
		other = open_revision_of(self.revises, exclude=self.name)
		if other:
			frappe.throw(_("{0} is already being revised by {1} ({2}). Finish or obsolete that revision first.").format(
				frappe.bold(self.revises), frappe.bold(other.name), other.get(FIELD)))

	def enforce_lock(self, old_state):
		if old_state not in LOCKED_STATES or self.is_new():
			return
		allowed = LOCKED_NEXT[old_state]
		if self.get(FIELD) not in allowed:
			frappe.throw(_("Status cannot change from {0} to {1}; allowed: {2}.").format(
				old_state, self.get(FIELD) or "-", ", ".join(allowed)))
		before = self.get_doc_before_save()
		for df in self.meta.fields:
			if df.fieldname in MUTABLE_WHEN_LOCKED or df.fieldtype in ("Section Break", "Column Break", "Tab Break"):
				continue
			if df.fieldtype == "Table":
				a = [r.as_dict(no_default_fields=True) for r in before.get(df.fieldname)]
				b = [r.as_dict(no_default_fields=True) for r in self.get(df.fieldname)]
				if json.dumps(a, default=str, sort_keys=True) != json.dumps(b, default=str, sort_keys=True):
					frappe.throw(_("{0} is locked once a Material Specification is {1}.").format(df.label, old_state))
			elif (before.get(df.fieldname) or None) != (self.get(df.fieldname) or None):
				frappe.throw(_("{0} is locked once a Material Specification is {1}.").format(df.label, old_state))

	def stamp_review(self, old, new):
		"""Server-stamped review trail; Approve needs a different user from the one who submitted for review."""
		if new == old:
			return
		user = frappe.session.user
		if new == UNDER_REVIEW:
			self.submitted_for_review_by, self.submitted_for_review_on = user, now_datetime()
		elif new == DRAFT:
			self.submitted_for_review_by = self.submitted_for_review_on = None
			self.approved_by = self.approved_on = None
		elif new == APPROVED:
			if user == self.submitted_for_review_by:
				frappe.throw(
					_("Approve must be done by a different user from the one who submitted the specification for review ({0}).").format(user),
					title=_("Self approval is not allowed"))
			self.approved_by, self.approved_on = user, now_datetime()

	def on_update(self):
		if not self.flags.entering_approved:
			return
		self.flags.entering_approved = False
		# one Approved per chain, superseded in the same DB transaction as this Approve
		L.supersede(self, self._other_approved(), SUPERSEDED, link_field="superseded_by", date_field="superseded_on")

	def _other_approved(self):
		names = chain_names(self.name, self.revises) - {self.name}
		if not names:
			return []
		return frappe.get_all(DOCTYPE, filters={"name": ["in", list(names)], FIELD: APPROVED},
			fields=["name", "creation"], order_by="creation asc")


@frappe.whitelist()
def create_revision(source_name):
	"""Create Revision (Approved, not superseded specifications only): returns an unsaved Draft that revises
	``source_name`` with its descriptive content and critical requirements copied and the next revision suggested
	(0 -> 1 -> 2). Status, review stamps and supersede fields start empty."""
	src = frappe.get_doc(DOCTYPE, source_name)
	src.check_permission("read")
	if not frappe.has_permission(DOCTYPE, "create"):
		frappe.throw(_("Not permitted to create a Material Specification."), frappe.PermissionError)
	if src.get(FIELD) != APPROVED or src.superseded_by:
		frappe.throw(_("Only an Approved, not superseded Material Specification can be revised ({0} is {1}).").format(
			frappe.bold(source_name), src.get(FIELD)))
	other = open_revision_of(source_name)
	if other:
		frappe.throw(_("{0} is already being revised by {1} ({2}). Finish or obsolete that revision first.").format(
			frappe.bold(source_name), frappe.bold(other.name), other.get(FIELD)))
	new = frappe.new_doc(DOCTYPE)
	for f in COPY_FIELDS:
		new.set(f, src.get(f))
	for row in src.critical_requirements:
		new.append("critical_requirements", {k: v for k, v in row.as_dict(no_default_fields=True).items()
			if k not in ("doctype",)})
	new.revises = src.name
	new.revision = next_revision(src.name)[1]  # shown on the draft; re-assigned by the server on save
	new.set(FIELD, DRAFT)
	return new.as_dict()
