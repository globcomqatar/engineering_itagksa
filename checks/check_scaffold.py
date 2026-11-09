#!/usr/bin/env python3
"""Static checks for the Engineering ITAG KSA foundation scaffold.

These checks do not install Frappe or ERPNext. They are builder scaffold
verification, not functional acceptance, independent QA, or a compatibility
certificate.
"""

from __future__ import annotations

import ast
import hashlib
import sys
import unittest
from pathlib import Path

# Stdlib on Python 3.11 and newer. Ruff's py310 target classifies it as
# third-party, so this import stays separate from the stdlib block above.
import tomllib

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "engineering_itagksa"

ALLOWED_HOOK_ASSIGNMENTS = {
	"after_install",
	"after_migrate",
	"app_description",
	"app_email",
	"app_license",
	"app_name",
	"app_publisher",
	"app_title",
	"doctype_js",
	"has_permission",
	"required_apps",
}

FORBIDDEN_PATH_PARTS = ("product_revision", "work_order", "custom_field", "fixtures")


def scrub(txt: str) -> str:
	"""Frappe version-15 frappe.scrub, without importing Frappe."""
	return txt.replace(" ", "_").replace("-", "_").lower()


class ScaffoldChecks(unittest.TestCase):
	def test_tracked_tree_is_scaffold_only(self):
		for path in self._project_files():
			for part in path.parts:
				self.assertNotIn(part, FORBIDDEN_PATH_PARTS, path.as_posix())
		required = [
			"engineering_itagksa/hooks.py",
			"engineering_itagksa/install.py",
			"engineering_itagksa/engineering_itag_ksa/doctype/engineering_drawing/engineering_drawing.json",
			"engineering_itagksa/engineering_itag_ksa/doctype/material_specification/material_specification.json",
			"engineering_itagksa/engineering_itag_ksa/doctype/engineering_item_request/engineering_item_request.json",
			"engineering_itagksa/engineering_itag_ksa/doctype/engineering_release/engineering_release.json",
			"docs/acceptance-matrix.md",
		]
		found = {path.as_posix() for path in self._project_files()}
		for item in required:
			self.assertIn(item, found)

	def test_package_identity(self):
		hooks = self._hooks()
		self.assertEqual(hooks["app_name"], "engineering_itagksa")
		self.assertEqual(hooks["app_title"], "Engineering ITAG KSA")
		self.assertEqual(
			hooks["app_publisher"],
			"Globcom Qatar (Globcom Solutions and Services)",
		)
		self.assertEqual(hooks["app_license"], "custom")
		self.assertEqual(hooks["app_email"], "")
		self.assertIn("Engineering ITAG KSA", hooks["app_description"])
		self.assertNotIn("frappe", " ".join(self._pyproject()["project"].get("dependencies") or []).lower())
		self.assertEqual(hooks["required_apps"], ["frappe/erpnext"])

	def test_hooks_stay_minimal(self):
		self.assertEqual(set(self._hooks()), ALLOWED_HOOK_ASSIGNMENTS)

	def test_pyproject_bench_dependencies(self):
		data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
		project = data["project"]
		self.assertEqual(project["name"], "engineering_itagksa")
		self.assertEqual(project["requires-python"], ">=3.10")
		self.assertEqual(project["dynamic"], ["version"])
		self.assertEqual(project["readme"], "README.md")
		self.assertEqual(
			project["authors"],
			[{"name": "Globcom Qatar (Globcom Solutions and Services)"}],
		)
		self.assertNotIn("license", project)
		for dep in project.get("dependencies") or []:
			lowered = dep.lower()
			self.assertNotIn("frappe", lowered)
			self.assertNotIn("erpnext", lowered)
		build = data["build-system"]
		self.assertEqual(build["build-backend"], "flit_core.buildapi")
		self.assertEqual(build["requires"], ["flit_core >=3.4,<4"])
		frappe_deps = data["tool"]["bench"]["frappe-dependencies"]
		self.assertEqual(frappe_deps["frappe"], ">=15.0.0,<16.0.0")
		self.assertEqual(frappe_deps["erpnext"], ">=15.0.0,<16.0.0")

	def test_version_and_default_module(self):
		init = (PKG / "__init__.py").read_text(encoding="utf-8")
		self.assertEqual(init, '__version__ = "0.0.1"\n')
		modules = (PKG / "modules.txt").read_text(encoding="utf-8")
		self.assertEqual(modules, "Engineering ITAG KSA\n")
		self.assertEqual(scrub("Engineering ITAG KSA"), "engineering_itag_ksa")
		module_init = PKG / "engineering_itag_ksa" / "__init__.py"
		self.assertTrue(module_init.is_file())
		self.assertEqual(module_init.read_text(encoding="utf-8"), "")

	def test_no_migrations_or_schema(self):
		for line in (PKG / "patches.txt").read_text(encoding="utf-8").splitlines():
			stripped = line.strip()
			if not stripped or stripped.startswith("#") or stripped.startswith("["):
				continue
			self.fail(f"unexpected patch entry: {stripped}")
		for path in PKG.rglob("*.json"):
			relative = path.relative_to(PKG).as_posix()
			self.assertTrue("/doctype/" in relative or "/workspace/" in relative, relative)
		joined = "\n".join(path.read_text(encoding="utf-8") for path in PKG.rglob("*.json"))
		for series in ("EIR-.#####", "DWG-.#####", "MS-.#####", "ER-.#####"):
			self.assertIn(series, joined)
		self.assertNotIn("Product Revision", joined)
		self.assertNotIn("Work Order", joined)
		self.assertIsNone(self._hooks().get("doc_events"))

	def test_license_file_grants_nothing(self):
		text = (ROOT / "license.txt").read_text(encoding="utf-8").lower()
		for phrase in (
			"permission is hereby granted",
			"mit license",
			"gnu general public license",
			"apache license",
			"redistribution and use",
		):
			self.assertNotIn(phrase, text)
		self.assertIn("have not been supplied", text)
		self.assertIn("globcom qatar (globcom solutions and services)", text)

	def test_readme_distinguishes_scaffold_from_acceptance(self):
		readme = (ROOT / "README.md").read_text(encoding="utf-8")
		self.assertTrue(readme.startswith("# engineering_itagksa\n"))
		for phrase in (
			"engineering_itag_ksa",
			"not independent QA",
			"itag.localhost",
			"License terms were not supplied",
			"Publisher contact email was not supplied",
			"Product Revision",
			"Material Specification",
			"Globcom Qatar (Globcom Solutions and Services)",
			"Foundation work is proceeding",
			"Functional design decisions are awaiting the Owner",
			"Before any specific function is built",
		):
			self.assertIn(phrase, readme)

	def test_package_imports_without_frappe(self):
		sys.path.insert(0, str(ROOT))
		try:
			import engineering_itagksa
			import engineering_itagksa.hooks as hooks
		finally:
			if sys.path and sys.path[0] == str(ROOT):
				sys.path.pop(0)
		self.assertEqual(engineering_itagksa.__version__, "0.0.1")
		self.assertEqual(hooks.app_name, "engineering_itagksa")
		self.assertEqual(hooks.app_title, "Engineering ITAG KSA")
		self.assertFalse(hasattr(hooks, "fixtures"))
		self.assertFalse(hasattr(hooks, "doc_events"))
		self.assertFalse(hasattr(hooks, "override_doctype_class"))

	def test_copied_v15_editor_files_match_upstream(self):
		# Exact copies of Frappe branch version-15 as fetched for this scaffold.
		# .eslintrc is ESLint's JSON-with-trailing-commas form, so stdlib json
		# cannot parse it. The hash keeps the copy faithful to that file.
		digest = {
			name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
			for name in (".editorconfig", ".eslintrc")
		}
		self.assertEqual(
			digest[".editorconfig"],
			"e4a2b430367eab28cffd4ed6551e0d947efbb8f2ee7ad85a35ff0f0297acc64a",
		)
		self.assertEqual(
			digest[".eslintrc"],
			"2dafc387a039a42b4d2caf9485700e56aece26c1da17045da705ff6eab5cc862",
		)
		eslintrc = (ROOT / ".eslintrc").read_text(encoding="utf-8")
		self.assertIn('"extends": "eslint:recommended"', eslintrc)
		self.assertIn('"frappe": true', eslintrc)
		editor = (ROOT / ".editorconfig").read_text(encoding="utf-8")
		self.assertIn("indent_style = tab", editor)
		self.assertIn("root = true", editor)

	def _project_files(self):
		files = []
		for path in ROOT.rglob("*"):
			if not path.is_file():
				continue
			relative = path.relative_to(ROOT)
			if ".git" in relative.parts or "__pycache__" in relative.parts:
				continue
			posix = relative.as_posix()
			if posix.startswith(("dist/", ".ruff_cache/")) or posix.endswith(".pyc"):
				continue
			files.append(relative)
		return files

	def _pyproject(self) -> dict:
		return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

	def _hooks(self) -> dict:
		tree = ast.parse((PKG / "hooks.py").read_text(encoding="utf-8"))
		values = {}
		for node in tree.body:
			if not isinstance(node, ast.Assign) or len(node.targets) != 1:
				continue
			target = node.targets[0]
			if isinstance(target, ast.Name):
				values[target.id] = ast.literal_eval(node.value)
		return values


if __name__ == "__main__":
	suite = unittest.defaultTestLoader.loadTestsFromTestCase(ScaffoldChecks)
	result = unittest.TextTestRunner(verbosity=2).run(suite)
	raise SystemExit(0 if result.wasSuccessful() else 1)
