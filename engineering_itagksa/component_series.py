"""Shared per-component 5XXXX number space for Engineering Drawing and Product Revision (v15.3.6).

Both DocTypes name documents ``{component}-5NNNN-{revision}``. A first issue starts at revision 0
(``500-50001-0``); Create Revision keeps that base and uses 1, 2, … . Frappe uniqueness is per
DocType, so the same string could otherwise exist on both (e.g. Drawing ``500-50001-0`` and
Product Revision ``500-50001-0``). To keep names distinct, a 5XXXX value issued for a component is
used by only one of the two DocTypes. Revisions stay on that base and never increment the series.

The Drawing Series key stays ``DWG-{component}-5`` so existing counters continue. Product Revision
uses ``PR-{component}-5`` and starts after the highest number already taken by a Drawing or a
Product Revision of the same component.

Amend names such as ``500-50001-0-1`` belong to the same base and revision as the cancelled
document. An unrecognised name is treated as having no base (the caller issues a fresh number).
"""

import re

import frappe
from frappe import _
from frappe.utils import cint

SERIES_MAX = 9999  # 50001..59999
DRAWING_SERIES = "DWG-{0}-5"
PR_SERIES = "PR-{0}-5"

# Optional DWG- prefix; component may contain hyphens; revision is digits (or letters);
# an optional trailing -N is the standard Amend suffix (500-50001-0-1).
COMPONENT_NAME_RE = re.compile(r"^(?:DWG-)?(.+)-5(\d{4})-([A-Z]{1,10}|\d+)(?:-\d+)?$")


def split_component_base(name):
	"""``(canonical base, revision)`` for ``{component}-5NNNN-{rev}`` (and an Amend suffix), else ``(None, None)``.

	``500-50001-0`` -> ``("500-50001", "0")``, ``500-50001-0-1`` -> ``("500-50001", "0")``.
	An unexpected or empty name returns ``(None, None)`` and does not raise.
	"""
	try:
		m = COMPONENT_NAME_RE.match("" if name is None else str(name))
		if not m:
			return None, None
		return f"{m.group(1)}-5{m.group(2)}", m.group(3)
	except Exception:
		return None, None


def letter_revision_value(rev):
	"""A=1, Z=26, AA=27. ``None`` if ``rev`` is not letters."""
	rev = (rev or "").strip().upper()
	if not re.fullmatch(r"[A-Z]{1,10}", rev):
		return None
	n = 0
	for ch in rev:
		n = n * 26 + (ord(ch) - ord("A") + 1)
	return n


def revision_value(rev):
	"""Numeric value of a revision: letters (A=1) or a decimal integer; else ``None``."""
	rev = (rev or "").strip()
	letter = letter_revision_value(rev)
	if letter is not None:
		return letter
	if re.fullmatch(r"\d+", rev):
		return int(rev)
	return None


def names_for_base(doctype, base):
	"""Document names of ``doctype`` on canonical base ``500-50001`` (plain and legacy DWG- prefix)."""
	if not base:
		return []
	found = []
	for prefix in ("", "DWG-"):
		for n in frappe.get_all(doctype, filters={"name": ["like", f"{prefix}{base}-%"]}, pluck="name"):
			b, _r = split_component_base(n)
			if b == base:
				found.append(n)
	return found


def next_revision_on_base(source_name, first="0", doctypes=None):
	"""Next digit revision on the canonical base of ``source_name``.

	Looks at both Drawing and Product Revision names on that base when ``doctypes`` is None,
	so a later issue cannot pick a revision string the other DocType already uses on the same
	base (defensive; new numbers are also allocated from a shared 5XXXX space).
	Returns ``first`` when ``source_name`` is not a recognised base.
	"""
	base, src_rev = split_component_base(source_name)
	if not base:
		return first
	doctypes = doctypes or ("Engineering Drawing", "Product Revision")
	values = []
	v = revision_value(src_rev)
	if v is not None:
		values.append(v)
	for dt in doctypes:
		for n in names_for_base(dt, base):
			_b, r = split_component_base(n)
			rv = revision_value(r)
			if rv is not None:
				values.append(rv)
	return str(max(values) + 1) if values else first


def _series_current(key):
	return cint(frappe.db.get_value("Series", key, "current", order_by="name"))


def _set_series_current(key, current):
	if frappe.db.exists("Series", key):
		frappe.db.sql("update `tabSeries` set `current` = %s where `name` = %s", (current, key))
	else:
		frappe.db.sql("insert into `tabSeries` (`name`, `current`) values (%s, %s)", (key, current))


def _max_seq_from_names(doctype, component):
	"""Highest 5XXXX sequence used by ``doctype`` for ``component`` (1 = 50001)."""
	# Match 500-50001-0 and an Amend suffix 500-50001-0-1. Component is an exact prefix of the canonical base.
	pat = re.compile(rf"^(?:DWG-)?{re.escape(component)}-5(\d{{4}})-(?:[A-Z]{{1,10}}|\d+)(?:-\d+)?$")
	highest = 0
	for n in frappe.get_all(doctype, filters={"name": ["like", f"%{component}-5%"]}, pluck="name"):
		m = pat.match(n)
		if m:
			highest = max(highest, int(m.group(1)))
	return highest


def used_sequence(component):
	"""Highest 5XXXX sequence (1 = 50001) already taken by Drawing or Product Revision of this component."""
	used = 0
	used = max(used, _series_current(DRAWING_SERIES.format(component)))
	used = max(used, _series_current(PR_SERIES.format(component)))
	used = max(used, _max_seq_from_names("Engineering Drawing", component))
	used = max(used, _max_seq_from_names("Product Revision", component))
	return used


def issue_base(component, series_template):
	"""Allocate the next unused ``{component}-5NNNN`` base and advance ``series_template``.

	``series_template`` is ``DRAWING_SERIES`` or ``PR_SERIES``. The cap 9,999 (50001-59999)
	applies only when a new number is issued, not when a revision reuses a base.
	"""
	if not component:
		frappe.throw(_("Item Component is required: it is part of the document number."))
	used = used_sequence(component)
	if used >= SERIES_MAX:
		frappe.throw(
			_("Item Component {0} has used all {1} numbers (50001-59999) across Engineering Drawing and Product Revision.").format(
				frappe.bold(component), SERIES_MAX
			)
		)
	nxt = used + 1
	_set_series_current(series_template.format(component), nxt)
	return f"{component}-5{nxt:04d}"
