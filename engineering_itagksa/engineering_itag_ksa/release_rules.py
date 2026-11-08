"""Pure comparisons for Engineering Release. This module does not import Frappe."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence


def release_key(item: str, bom: str) -> str:
	"""Stable uniqueness key for one uncancelled production release of an Item and BOM."""
	payload = f"{item}\n{bom}".encode()
	return hashlib.sha256(payload).hexdigest()


def _sequence(row: Mapping, index: int) -> int:
	sequence = row.get("sequence_id")
	if sequence is None or sequence == "":
		sequence = row.get("idx") or index
	return int(sequence)


def operation_sequence(rows: Sequence[Mapping] | None) -> list[tuple[int, str]]:
	"""Operation identity and sequence only. Times and workstations are ignored."""
	prepared: list[tuple[int, str]] = []
	for index, row in enumerate(rows or (), start=1):
		operation = str(row.get("operation") or "").strip()
		if not operation:
			continue
		prepared.append((_sequence(row, index), operation))
	prepared.sort(key=lambda pair: (pair[0], pair[1]))
	return prepared


def sequences_match(bom_rows: Sequence[Mapping] | None, routing_rows: Sequence[Mapping] | None) -> bool:
	return operation_sequence(bom_rows) == operation_sequence(routing_rows)
