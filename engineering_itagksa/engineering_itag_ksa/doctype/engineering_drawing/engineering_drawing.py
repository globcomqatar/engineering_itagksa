# Copyright (c) 2026, Globcom Qatar and contributors
# For license information, please see license.txt

import hashlib
import json
import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from engineering_itagksa import lifecycle as L
from engineering_itagksa.constants import APPROVED, DRAFT, OBSOLETE, SUPERSEDED, UNDER_REVIEW

# v15.3.0 (Owner decisions 2026-11-09): Engineering Drawing is NOT submittable. Its Status (``workflow_state``) is
# driven by the standard Desk Workflow "Engineering ITAG KSA Engineering Drawing" (install.py DRAWING_STATES /
# DRAWING_TRANSITIONS), modelled on Engineering Release:
#   Draft -> Under Review -> Approved -> Obsolete;  Under Review -> Draft;  Superseded -> Obsolete.
# Superseded is system-only: when a drawing with ``revises`` is Approved, the revised drawing becomes Superseded
# (superseded_by / superseded_date) in the same DB transaction. Once Approved the status only moves forward and
# the drawing content is frozen (Engineering Release LOCKED_NEXT pattern).
# Naming (v15.3.6): {component}-5NNNN-{revision}, e.g. 500-50001-0. A first issue takes the next number of
# the per-component series (key still "DWG-<component>-5" so existing counters continue; 50001..59999) and
# starts at revision 0. The DWG- prefix is not used. A revision of a recognised base keeps that canonical
# base and only changes the revision to the next digit: 500-50001-0 -> 500-50001-1, and 10 follows 9.
# A source name that is not in the 5NNNN pattern takes a fresh number and starts at 0 (Revises is kept).
# Existing drawings are not renamed. The 9,999 cap applies only when a new number is issued. Numbers are
# shared with Product Revision so the same {component}-5NNNN-{n} string is not issued to both DocTypes.
FIELD = "workflow_state"
LOCKED_STATES = (APPROVED, SUPERSEDED, OBSOLETE)
LOCKED_NEXT = {
	APPROVED: (APPROVED, SUPERSEDED, OBSOLETE),
	SUPERSEDED: (SUPERSEDED, OBSOLETE),
	OBSOLETE: (OBSOLETE,),
}
# fields that may still change once a drawing is locked (status and system-owned fields)
MUTABLE_WHEN_LOCKED = {FIELD, "superseded_by", "superseded_date", "modified", "modified_by"}
from engineering_itagksa.component_series import (
	DRAWING_SERIES,
	issue_base,
	next_revision_on_base,
	split_component_base,
)

SERIES_PREFIX = DRAWING_SERIES  # "DWG-{0}-5" — existing counter continues

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
USERINFO_RE = re.compile(r"^[a-z][a-z0-9+.-]*://[^/?#\s]*@", re.I)
SECRET_PARAM_RE = re.compile(
	r"[?&#](access_token|token|apikey|api_key|key|sig|signature|secret|password|passwd|pwd|auth|"
	r"x-amz-signature|x-amz-credential|x-amz-security-token|x-goog-signature|code)=",
	re.I,
)
BAD_SCHEMES = ("javascript:", "data:", "vbscript:")


def split_name(name):
	"""(canonical base, revision) for a {component}-5NNNN-{n} name (including an Amend suffix),
	else (None, None). An unexpected name returns (None, None) and does not raise."""
	return split_component_base(name)


def next_letter_for_base(source_name):
	"""Next digit revision on the same canonical base (v15.3.6). Kept name for callers.

	500-50001-0 -> 1. An unrecognised source starts at 0.
	"""
	base, _rev = split_name(source_name)
	if not base:
		return "0"
	return next_revision_on_base(source_name, first="0")


class EngineeringDrawing(Document):
	def before_naming(self):
		# revision is assigned by the system before autoname so the name carries it
		self.assign_revision()
		L.normalize_revision(self, "revision")
		if not self.item_component:
			frappe.throw(_("Item Component is required: it is part of the drawing number."))

	def autoname(self):
		# v15.3.6: keep the canonical base when revising a recognised drawing; otherwise issue the next
		# number from the existing DWG-{component}-5 series, skipping numbers already taken by Product
		# Revision. The 9,999 cap runs only for new numbers.
		base = split_name(self.revises)[0] if self.revises else None
		if not base:
			base = issue_base(self.item_component, SERIES_PREFIX)
		self.name = f"{base}-{self.revision}"
		if frappe.db.exists("Engineering Drawing", self.name):
			frappe.throw(
				_("Engineering Drawing {0} already exists.").format(frappe.bold(self.name)),
				frappe.DuplicateEntryError,
			)

	def validate(self):
		if self.is_new():
			self.assign_revision()
		L.normalize_revision(self, "revision")
		if not self.get(FIELD):
			self.set(FIELD, DRAFT)
		old, new = L.get_transition(self, FIELD)
		if self.is_new() and new != DRAFT:
			frappe.throw(_("A new Engineering Drawing starts as {0}.").format(DRAFT))
		if new == SUPERSEDED and old != SUPERSEDED:
			frappe.throw(_("Superseded is set automatically when a newer revision of this drawing is Approved."))
		self.enforce_lock(old)
		if old in LOCKED_STATES and not self.is_new():
			self.flags.entering_approved = False
			return  # locked record: content frozen, no re-stamping
		self.validate_component_group()
		self.validate_revises()
		self.validate_single_open_revision()
		self.validate_external_link()
		self.validate_drawing_file()
		self.validate_file_reference_present()
		self.set_checksum_from_file()
		self.validate_checksum_format()
		self.stamp_attestation()
		self.stamp_review(old, new)
		self.flags.entering_approved = new == APPROVED and old != APPROVED
		if self.flags.entering_approved:
			self.validate_supersede_target()

	def enforce_lock(self, old_state):
		if old_state not in LOCKED_STATES or self.is_new():
			return
		allowed = LOCKED_NEXT[old_state]
		if self.get(FIELD) not in allowed:
			frappe.throw(
				_("Status cannot change from {0} to {1}; allowed: {2}.").format(
					old_state, self.get(FIELD) or "-", ", ".join(allowed)
				)
			)
		before = self.get_doc_before_save()
		for df in self.meta.fields:
			if df.fieldname in MUTABLE_WHEN_LOCKED or df.fieldtype in ("Section Break", "Column Break", "Tab Break"):
				continue
			if df.fieldtype == "Table":
				a = [r.as_dict(no_default_fields=True) for r in before.get(df.fieldname)]
				b = [r.as_dict(no_default_fields=True) for r in self.get(df.fieldname)]
				if json.dumps(a, default=str, sort_keys=True) != json.dumps(b, default=str, sort_keys=True):
					frappe.throw(_("{0} is locked once a drawing is {1}.").format(df.label, old_state))
			elif (before.get(df.fieldname) or None) != (self.get(df.fieldname) or None):
				frappe.throw(_("{0} is locked once a drawing is {1}.").format(df.label, old_state))

	def assign_revision(self):
		"""Revision is never typed (Owner 2026-11-10 / v15.3.6): 0 for a new drawing and for a revision of a
		name that is not in the 5NNNN pattern (fresh number); for a revision of a recognised base, the next
		digit after the highest revision already on that canonical base."""
		if not self.revises:
			self.revision = "0"
			return
		prev = frappe.db.get_value("Engineering Drawing", self.revises, "revision")
		if prev is None:
			frappe.throw(_("Revised drawing {0} not found.").format(self.revises))
		if not split_name(self.revises)[0]:
			# unrecognised source: fresh number starts at 0 (Revises is kept)
			self.revision = "0"
			return
		nxt = next_letter_for_base(self.revises)
		if not nxt:
			frappe.throw(_("Cannot work out the revision after {0} of {1}.").format(prev, self.revises))
		self.revision = nxt

	def validate_component_group(self):
		"""Item Group defaults from the Item Component; when both are set they must agree."""
		comp_group = frappe.db.get_value("Item Component", self.item_component, "item_group")
		if not self.item_group and comp_group:
			self.item_group = comp_group
		elif self.item_group and comp_group and comp_group != self.item_group:
			frappe.throw(
				_("Item Component {0} belongs to Item Group {1}, not {2}.").format(
					frappe.bold(self.item_component), comp_group, self.item_group
				)
			)

	def validate_revises(self):
		if not self.revises:
			return
		if self.revises == self.name:
			frappe.throw(_("A drawing cannot revise itself."))
		prev = frappe.db.get_value("Engineering Drawing", self.revises, ["item_component", "revision"], as_dict=True)
		if not prev:
			frappe.throw(_("Revised drawing {0} not found.").format(self.revises))
		if prev.item_component != self.item_component:
			frappe.throw(
				_("Revises: {0} is for Item Component {1}; a revision must keep the same component ({2}).").format(
					self.revises, prev.item_component or "-", self.item_component
				)
			)
		if (prev.revision or "").upper() == (self.revision or "").upper():
			frappe.throw(_("Revision {0} is the same as the revised drawing {1}.").format(self.revision, self.revises))

	def validate_single_open_revision(self):
		"""Only one Draft / Under Review drawing may revise the same drawing at a time."""
		if not self.revises:
			return
		open_rev = open_revision_of(self.revises, exclude=self.name)
		if open_rev:
			frappe.throw(
				_("{0} is already being revised by {1} ({2}). Finish or obsolete that revision first.").format(
					frappe.bold(self.revises), frappe.bold(open_rev.name), open_rev.get(FIELD)
				)
			)

	def validate_supersede_target(self):
		"""On Approve: the revised drawing must be the current Approved one (it becomes Superseded on_update)."""
		if not self.revises:
			return
		state, by = frappe.db.get_value("Engineering Drawing", self.revises, [FIELD, "superseded_by"])
		if state == SUPERSEDED:
			frappe.throw(_("{0} is already superseded by {1}.").format(self.revises, by))
		if state not in (APPROVED, OBSOLETE):
			frappe.throw(
				_("Revised drawing {0} is {1}; approve or obsolete it before approving this revision.").format(
					self.revises, state
				)
			)

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
					_("Approve must be done by a different user from the one who submitted the drawing for review ({0}).").format(user),
					title=_("Self approval is not allowed"),
				)
			self.approved_by, self.approved_on = user, now_datetime()

	def after_insert(self):
		"""Write this Drawing back to the source Engineering Item Request when created from its button."""
		self._link_back_to_item_request()

	def _link_back_to_item_request(self):
		"""Always write this Drawing onto the source Item Request (allow_on_submit)."""
		src = self.get("source_item_request")
		if not src or not frappe.db.exists("Engineering Item Request", src):
			return
		if not frappe.has_permission("Engineering Item Request", "write", doc=src):
			return
		frappe.db.set_value("Engineering Item Request", src, "engineering_drawing", self.name)

	def on_update(self):
		if not self.flags.entering_approved:
			return
		self.flags.entering_approved = False
		if self.revises and frappe.db.get_value("Engineering Drawing", self.revises, FIELD) == APPROVED:
			# same DB transaction as this Approve (db set_value, no commit)
			L.supersede(self, [frappe._dict(name=self.revises)], SUPERSEDED, link_field="superseded_by", date_field="superseded_date")

	def validate_external_link(self):
		link = (self.external_file_link or "").strip()
		self.external_file_link = link
		low = link.lower()
		if low.startswith(BAD_SCHEMES):
			frappe.throw(_("External File Link scheme is not allowed."))
		if USERINFO_RE.search(link) or SECRET_PARAM_RE.search(link):
			frappe.throw(
				_("External File Link must not contain credentials, tokens or signed-URL secrets. Use a plain controlled link/path.")
			)

	def validate_drawing_file(self):
		"""Local attachment (Attach field) must be a private File so Customer Controlled /
		Confidential drawings are not exposed via a public /files/ URL."""
		url = (self.drawing_file or "").strip()
		self.drawing_file = url or None
		if url and not url.startswith("/private/files/"):
			frappe.throw(
				_("Drawing File must be uploaded as a private file (tick 'Is Private' when attaching)."),
				title=_("Private attachment required"),
			)

	def validate_file_reference_present(self):
		"""Owner rule (v0.1.3): at least one of external_file_link OR drawing_file is required."""
		if not (self.external_file_link or "").strip() and not (self.drawing_file or "").strip():
			frappe.throw(
				_("Provide either an external drawing link or attach a local drawing file."),
				frappe.ValidationError,
			)

	def set_checksum_from_file(self):
		"""v0.1.9: SHA-256 is computed by the server from the attached local file (never typed).
		No local file -> checksum is not user-editable (read_only); a hash left over from a removed
		file is cleared, a legacy operator-attested hash on a link-only drawing is kept as is."""
		if self.drawing_file:
			self.file_checksum_sha256 = sha256_of_file_url(self.drawing_file)
			return
		before = self.get_doc_before_save() if not self.is_new() else None
		if before and (before.drawing_file or "").strip():
			self.file_checksum_sha256 = None
		elif before:
			self.file_checksum_sha256 = before.file_checksum_sha256
		else:
			self.file_checksum_sha256 = None

	def validate_checksum_format(self):
		self.file_checksum_sha256 = (self.file_checksum_sha256 or "").strip().lower()
		if self.file_checksum_sha256 and not SHA256_RE.match(self.file_checksum_sha256):
			frappe.throw(_("File Checksum (SHA-256) must be exactly 64 hexadecimal characters."))
		if self.checksum_attested and not self.file_checksum_sha256:
			frappe.throw(
				_("Cannot attest: no SHA-256. Attach the local Drawing File (the checksum is computed automatically on save)."),
				title=_("Checksum missing"),
			)

	def stamp_attestation(self):
		"""A4: server stamps attester/time; client-supplied values are ignored."""
		before = self.get_doc_before_save() if not self.is_new() else None
		changed = bool(before) and (
			(before.external_file_link or "").strip() != self.external_file_link
			or (before.drawing_file or "").strip() != (self.drawing_file or "")
			or (before.file_checksum_sha256 or "").strip().lower() != self.file_checksum_sha256
		)
		if before and before.checksum_attested and changed:
			self.checksum_attested = 0
			frappe.msgprint(
				_("External link, drawing file or checksum changed: attestation cleared. Re-attest the SHA-256."), alert=True
			)
		if not self.checksum_attested:
			self.checksum_attested_by = None
			self.checksum_attested_on = None
		elif before and before.checksum_attested and not changed:
			self.checksum_attested_by = before.checksum_attested_by
			self.checksum_attested_on = before.checksum_attested_on
		else:
			self.checksum_attested_by = frappe.session.user
			self.checksum_attested_on = now_datetime()


def sha256_of_file_url(file_url):
	"""SHA-256 of the private File record behind an Attach URL (server-side, streamed)."""
	name = frappe.db.get_value("File", {"file_url": file_url, "is_folder": 0}, "name", order_by="creation desc")
	if not name:
		frappe.throw(_("Attached Drawing File {0} was not found. Re-attach the file.").format(file_url))
	file_doc = frappe.get_doc("File", name)
	h = hashlib.sha256()
	try:
		with open(file_doc.get_full_path(), "rb") as fh:
			for chunk in iter(lambda: fh.read(1024 * 1024), b""):
				h.update(chunk)
	except OSError:
		frappe.throw(_("Could not read the attached Drawing File to compute its SHA-256. Re-attach the file."))
	return h.hexdigest()


def open_revision_of(drawing, exclude=None):
	filters = {"revises": drawing, FIELD: ["in", [DRAFT, UNDER_REVIEW]]}
	if exclude:
		filters["name"] = ["!=", exclude]
	return frappe.db.get_value("Engineering Drawing", filters, ["name", FIELD], as_dict=True)


def next_revision_letter(rev):
	"""Suggest the next revision: A->B, Z->AA, AZ->BA; 1->2, 09->10. Anything else: no suggestion."""
	rev = (rev or "").strip().upper()
	if re.fullmatch(r"[A-Z]{1,10}", rev):
		chars = list(rev)
		i = len(chars) - 1
		while i >= 0:
			if chars[i] != "Z":
				chars[i] = chr(ord(chars[i]) + 1)
				break
			chars[i] = "A"
			i -= 1
		out = "".join(chars) if i >= 0 else "A" + "".join(chars)
		return out if len(out) <= 10 else ""
	if re.fullmatch(r"[0-9]{1,10}", rev):
		out = str(int(rev) + 1).zfill(len(rev))
		return out if len(out) <= 10 else ""
	return ""


@frappe.whitelist()
def create_revision(source_name):
	"""Create Revision (Approved drawings only): returns an unsaved Draft that revises ``source_name``, with
	Drawing Name, Item Group, Item Component, Drawing Type, Security Classification and Revises copied and the next
	revision suggested. File, checksum, attestation, dates and review stamps start empty: a new file must be attached."""
	src = frappe.get_doc("Engineering Drawing", source_name)
	src.check_permission("read")
	frappe.has_permission("Engineering Drawing", "create", throw=True)
	if src.get(FIELD) != APPROVED or src.superseded_by:
		frappe.throw(_("Create Revision is only available on an Approved drawing that is not superseded."))
	open_rev = open_revision_of(src.name)
	if open_rev:
		frappe.throw(
			_("{0} is already being revised by {1} ({2}). Open that draft instead of creating another.").format(
				frappe.bold(src.name), frappe.bold(open_rev.name), open_rev.get(FIELD)
			)
		)
	new = frappe.new_doc("Engineering Drawing")
	for f in ("drawing_name", "item_group", "item_component", "drawing_type", "security_classification"):
		new.set(f, src.get(f))
	new.revises = src.name
	# shown on the draft; re-assigned by the server on save. Legacy unrecognised names start at 1 on a fresh number.
	new.revision = next_letter_for_base(src.name) if split_name(src.name)[0] else "1"
	new.set(FIELD, DRAFT)
	return new.as_dict()


@frappe.whitelist()
def make_product_revision(source_name):
	"""v15.3.0: Drawing no longer carries an Item (item_code removed). The Product Revision mapping is redesigned in
	the separate Product Revision pass; until then this refuses with a clear message instead of mapping."""
	src = frappe.get_doc("Engineering Drawing", source_name)
	src.check_permission("read")
	frappe.throw(
		_("Creating a Product Revision from an Engineering Drawing is disabled until Product Revision is revised for "
			"the new Drawing model (Drawing has no Item Code since v15.3.0).")
	)
