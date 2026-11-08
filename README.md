# engineering_itagksa

Installable foundation scaffold for the customer-specific app Engineering ITAG KSA on Frappe version 15 and ERPNext version 15. Publisher: Globcom Qatar (Globcom Solutions and Services).

Foundation work is proceeding under the Owner's authorization. Functional design decisions are awaiting the Owner. This repository is the installable app foundation only.

## Governance

Owner Waheed Ali authorized the start, build, and push of this foundation to this repository. That authorization is not merge, release, or deployment approval.

Before any specific function is built, the builder will place the viable options, the trade-offs, and one recommendation in front of the Owner, then wait for his choice. This scaffold does not choose functional rules and does not implement business functions.

These reviews remain pending:

- Independent CTO review
- Security review
- Separate QA
- Owner release approval

Builder self-tests in this repository are not independent QA and are not a compatibility certificate.

## Identity

| Item | Value |
| --- | --- |
| App title | Engineering ITAG KSA |
| Bench app / Python package | `engineering_itagksa` |
| Publisher | Globcom Qatar (Globcom Solutions and Services) |
| Package version | `0.0.1` (Frappe new-app technical default, not a product release) |
| Default module | `Engineering ITAG KSA` in `engineering_itagksa/engineering_itag_ksa/` |
| Python | `>=3.10` |
| Frappe | `>=15.0.0,<16.0.0` |
| ERPNext | `>=15.0.0,<16.0.0` |
| `required_apps` | `frappe/erpnext` |

### Default module

Frappe version 15 `bench new-app` creates one module folder with `frappe.scrub(app_title)`, which lowercases the title and replaces spaces with underscores. For this title the folder is `engineering_itag_ksa`. `modules.txt` records the title `Engineering ITAG KSA`, which is the Module Def name. The folder is empty apart from `__init__.py`. It is the technical default required to install the app. It is not a business module.

`bench new-app` also creates empty `www`, `templates/includes`, `public/css`, and `public/js` directories. Git does not store empty directories, and the version-15 generator only writes `public/.gitkeep`, so those empty directories are not part of this commit. `public/.gitkeep` is what lets `bench build` symlink the app's assets.

## Missing required metadata

License terms were not supplied. `app_license` is `custom`, the version-15 generator option for a license outside the SPDX list offered by `bench new-app`. `license.txt` records that absence. It does not grant open-source or any other reuse rights.

Publisher contact email was not supplied. `hooks.py` leaves `app_email` empty. `pyproject.toml` lists the publisher name and omits an email, so no address is invented.

## Dependencies and packaging

Frappe and ERPNext are bench apps. The version-15 boilerplate keeps them out of `[project].dependencies`, with a comment that Frappe is installed and managed by bench. This app follows that rule.

Bench reads version constraints from `[tool.bench.frappe-dependencies]`. Frappe HR (`hrms`) on branch `version-15` declares the same v15 line:

```toml
frappe = ">=15.0.0,<16.0.0"
erpnext = ">=15.0.0,<16.0.0"
```

`hooks.py` sets `required_apps = ["frappe/erpnext"]`. Frappe HR v15 uses that org/app form. Frappe's installer resolves the string to the `erpnext` app name.

ERPNext's own `version-15` branch currently requires `frappe >=15.111.0,<16.0.0`. This scaffold targets the v15 line. It does not claim a tighter patch floor verified on an installed site.

Packaging uses `flit_core` (`flit_core >=3.4,<4`), the version-15 replacement for `setup.py`. There is no `requirements.txt` and no `setup.py`.

`hooks.py` keeps the commented examples from the version-15 generator. The only active integration setting is `required_apps`. There are no active document events, fixtures, whitelisted-method overrides, scheduler jobs, or install hooks.

`patches.txt` is the version-15 generator file and registers no patches. Its documentation comment still links to the v14 migration page because that is the current upstream template text.

## Development

Use a bench that already has Frappe version 15 and ERPNext version 15 from the `frappe` GitHub organization. Point `bench get-app` at the branch that contains this scaffold. The default branch of this repository is `main`. This app does not use a `develop` branch unless one is created later.

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch <branch-with-this-scaffold>
bench --site $SITE install-app engineering_itagksa
```

Run `install-app` only on a bench and site chosen for development of this foundation. This repository does not deploy to staging or production, and cloning it does not change an existing site.

Version-15 development files included with the scaffold:

- `.pre-commit-config.yaml` (ruff, eslint, prettier, and the standard pre-commit hooks)
- `.editorconfig` and `.eslintrc`, copied from Frappe `version-15`
- Ruff settings in `pyproject.toml`, copied from the version-15 app template

```bash
pre-commit install
```

Static scaffold checks from a checkout, without a bench. `checks/check_scaffold.py` uses `tomllib`, so run it on Python 3.11 or newer. The app package itself stays within the Frappe v15 floor of Python 3.10 and does not import `tomllib`. Python 3.10 can still byte-compile the package.

```bash
python3 checks/check_scaffold.py
python3 -m compileall -q engineering_itagksa checks
python3 -m pip install build
python3 -m build --wheel
```

Optional, matching the pre-commit pin:

```bash
python3 -m pip install 'ruff==0.8.1'
ruff check engineering_itagksa checks
ruff format --check engineering_itagksa checks
```

GitHub Actions workflow `.github/workflows/scaffold-checks.yml` runs the compile, static checks, and wheel build. The optional `bench new-app` server workflow stays off. That upstream workflow is off by default, runs `bench init` without `--frappe-branch version-15`, and does not install ERPNext, so it would not verify this app.

## Scaffold verification and functional acceptance

Scaffold verification covers package identity, the v15 bench dependency declaration, a flit wheel build, import and byte-compile, and the absence of business schema.

Full bench installation tests were not run. This environment has no bench, site, MariaDB service, or ERPNext install, so `bench get-app`, `bench install-app`, `bench migrate`, and `bench build` were not executed. A wheel build checks packaging only. It is not an installed-site test.

Boundary for this repository:

- Foundation: proceeding. The authorized work is this installable Frappe v15 / ERPNext v15 scaffold.
- Functional design decisions: awaiting the Owner. Before any specific function is built, he receives the viable options, the trade-offs, and one recommendation, and implementation waits for his choice.

The Owner has not chosen these rules, and this foundation does not implement them:

- Independent naming series, and revision, amend, and supersede semantics, for itemless Drawing and Material Specification
- Whether an Engineering Revision uses a single Material Specification link or a specification table
- Baseline sourcing after removal of Product Revision
- MER scope and checks
- Coexistence and collisions with existing documents

The tree has no business DocTypes, workflows, Item or Work Order hooks, custom fields, fixtures, or data migrations. Frappe core and ERPNext core are unchanged. No legacy app is imported or copied.

## Acceptance criteria for this foundation

- Package name `engineering_itagksa` and title `Engineering ITAG KSA` are set in `hooks.py` and `pyproject.toml`.
- Publisher is Globcom Qatar (Globcom Solutions and Services). License terms and publisher email stay absent.
- Frappe 15 and ERPNext 15 are declared as bench dependencies and are absent from pip requirements.
- `python3 checks/check_scaffold.py`, `compileall`, and `python3 -m build --wheel` pass in the builder environment.
- The tree contains no DocType JSON, fixture export, custom field, patch entry, or active document hook.
- Full bench installation tests were not run, and builder self-tests are not independent QA.
