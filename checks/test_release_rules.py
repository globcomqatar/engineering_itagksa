"""Builder checks for release comparisons. These do not install Frappe."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engineering_itagksa.engineering_itag_ksa.release_rules import (
	operation_sequence,
	release_key,
	sequences_match,
)


class ReleaseRuleTests(unittest.TestCase):
	def test_release_key_depends_on_item_and_bom_only(self):
		self.assertEqual(release_key("VALVE", "BOM-1"), release_key("VALVE", "BOM-1"))
		self.assertNotEqual(release_key("VALVE", "BOM-1"), release_key("VALVE", "BOM-2"))
		self.assertNotEqual(release_key("VALVE", "BOM-1"), release_key("BODY", "BOM-1"))

	def test_times_and_workstations_are_not_part_of_the_match(self):
		bom = [{"operation": "Cut", "sequence_id": 1, "time_in_mins": 5, "workstation": "Saw"}]
		routing = [{"operation": "Cut", "sequence_id": 1, "time_in_mins": 90, "workstation": "Lathe"}]
		self.assertTrue(sequences_match(bom, routing))

	def test_sequence_and_operation_must_match(self):
		bom = [
			{"operation": "Cut", "sequence_id": 1},
			{"operation": "Weld", "sequence_id": 2},
		]
		self.assertFalse(
			sequences_match(
				bom, [{"operation": "Weld", "sequence_id": 1}, {"operation": "Cut", "sequence_id": 2}]
			)
		)
		self.assertFalse(sequences_match(bom, [{"operation": "Cut", "sequence_id": 1}]))
		self.assertTrue(
			sequences_match(
				[
					{"operation": "Weld", "sequence_id": 2, "idx": 1},
					{"operation": "Cut", "sequence_id": 1, "idx": 2},
				],
				[{"operation": "Cut", "sequence_id": 1}, {"operation": "Weld", "sequence_id": 2}],
			)
		)

	def test_blank_sequences_use_row_order(self):
		self.assertEqual(
			operation_sequence([{"operation": "Cut", "idx": 4}, {"operation": "Weld", "idx": 9}]),
			[(4, "Cut"), (9, "Weld")],
		)


if __name__ == "__main__":
	raise SystemExit(unittest.main())
