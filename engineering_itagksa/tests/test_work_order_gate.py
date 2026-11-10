"""B5 Work Order gate tests (pure decision + hook with patched lookups; no DB fixtures needed).

Cases required by plan §8 B5: Manufacturing blocked without release, Manufacturing allowed with release,
unset -> blocked, service pass-through. Run:
  bench --site <site> execute engineering_itagksa.tests.test_work_order_gate.run
"""

import unittest
from unittest.mock import patch

import frappe

from engineering_itagksa import work_order_gate as G

MOD = "engineering_itagksa.work_order_gate"


def wo(item="VLV-1", bom="BOM-VLV-1-001"):
	return frappe._dict(production_item=item, bom_no=bom, engineering_release=None)


class TestWorkOrderGate(unittest.TestCase):
	def test_decision_matrix(self):
		self.assertTrue(G.requires_release("Valves", "Manufacturing", 0))  # manufacturing always gated
		self.assertTrue(G.requires_release("Valves", "Sub-Assembly", 0))
		self.assertTrue(G.requires_release("Valves", None, None))  # unset -> fail closed
		self.assertTrue(G.requires_release("Valves", None, ""))
		self.assertTrue(G.requires_release(None, None, 0))  # no group -> fail closed
		self.assertTrue(G.requires_release("Valves", "Purchase", 1))
		self.assertFalse(G.requires_release("Services", "Purchase", 0))  # service pass-through
		self.assertFalse(G.requires_release("Services", None, 0))
		# Engineering Settings flag off -> manufacturing follows the Item Group rule
		self.assertFalse(G.requires_release("Valves", "Manufacturing", 0, force_manufacturing=False))
		self.assertTrue(G.requires_release("Valves", "Manufacturing", 1, force_manufacturing=False))
		self.assertTrue(G.requires_release("Valves", "Sub-Assembly", None, force_manufacturing=False))

	def test_manufacturing_blocked_without_release(self):
		with patch(f"{MOD}.get_gate_inputs", return_value=("Valves", "Manufacturing", 1)), patch(
			f"{MOD}.find_release", return_value=None
		):
			self.assertRaises(frappe.ValidationError, G.check_work_order, wo())

	def test_manufacturing_allowed_with_release(self):
		d = wo()
		with patch(f"{MOD}.get_gate_inputs", return_value=("Valves", "Manufacturing", 1)), patch(
			f"{MOD}.find_release", return_value=frappe._dict(name="ER-2026-00001", bom="BOM-VLV-1-001")
		):
			G.check_work_order(d)
		self.assertEqual(d.engineering_release, "ER-2026-00001")

	def test_bom_mismatch_blocked(self):
		with patch(f"{MOD}.get_gate_inputs", return_value=("Valves", "Manufacturing", 1)), patch(
			f"{MOD}.find_release", return_value=frappe._dict(name="ER-2026-00001", bom="BOM-OTHER")
		):
			self.assertRaises(frappe.ValidationError, G.check_work_order, wo())

	def test_unset_blocked(self):
		with patch(f"{MOD}.get_gate_inputs", return_value=("Valves", None, None)), patch(
			f"{MOD}.find_release", return_value=None
		):
			self.assertRaises(frappe.ValidationError, G.check_work_order, wo())

	def test_service_pass_through(self):
		d = wo(item="SVC-1", bom=None)
		with patch(f"{MOD}.get_gate_inputs", return_value=("Services", None, 0)), patch(
			f"{MOD}.find_release", side_effect=AssertionError("must not look up")
		):
			G.check_work_order(d)
		self.assertIsNone(d.engineering_release)

	def test_subcontracted_job_bypass_manufacturing(self):
		"""Owner: custom_subcontracted_job skips release even for Manufacturing."""
		self.assertFalse(
			G.requires_release("Valves", "Manufacturing", 1, subcontracted_job=True)
		)
		d = wo()
		d.custom_subcontracted_job = 1
		with patch(f"{MOD}.get_gate_inputs", return_value=("Valves", "Manufacturing", 1)), patch(
			f"{MOD}.find_release", side_effect=AssertionError("must not look up")
		):
			G.check_work_order(d)
		self.assertIsNone(d.engineering_release)

	def test_non_subcontracted_manufacturing_still_requires(self):
		self.assertTrue(G.requires_release("Valves", "Manufacturing", 1, subcontracted_job=False))
		d = wo()
		d.custom_subcontracted_job = 0
		with patch(f"{MOD}.get_gate_inputs", return_value=("Valves", "Manufacturing", 1)), patch(
			f"{MOD}.find_release", return_value=None
		):
			self.assertRaises(frappe.ValidationError, G.check_work_order, d)

	def test_non_subcontracted_group_flag_off_still_skips(self):
		self.assertFalse(G.requires_release("Services", "Purchase", 0, subcontracted_job=False))
		d = wo(item="SVC-1", bom=None)
		d.custom_subcontracted_job = 0
		with patch(f"{MOD}.get_gate_inputs", return_value=("Services", "Purchase", 0)), patch(
			f"{MOD}.find_release", side_effect=AssertionError("must not look up")
		):
			G.check_work_order(d)


def run():
	suite = unittest.TestLoader().loadTestsFromTestCase(TestWorkOrderGate)
	res = unittest.TextTestRunner(verbosity=2).run(suite)
	print("RESULT", "OK" if res.wasSuccessful() else "FAIL")
