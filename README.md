# engineering_itagksa

Customer-specific Engineering ITAG KSA on Frappe version 15 and ERPNext version 15. Publisher: Globcom Qatar (Globcom Solutions and Services).

Foundation work is proceeding. The confirmed process from 2026-11-08 21:51 Qatar is in this branch. Functional design decisions are awaiting the Owner for anything outside that confirmed list.

## Governance

Owner Waheed Ali authorized this build and push. That authorization is not merge, release, or deployment approval.

Before any specific function is built beyond the confirmed list, the builder will place the viable options, the trade-offs, and one recommendation in front of the Owner, then wait for his choice.

These reviews remain pending:

- Independent CTO review
- Security review
- Separate QA
- Owner release approval

Builder self-tests in this repository are not independent QA and are not a compatibility certificate. The acceptance matrix is `docs/acceptance-matrix.md`.

## Identity

| Item | Value |
| --- | --- |
| App title | Engineering ITAG KSA |
| Bench app / Python package | `engineering_itagksa` |
| Publisher | Globcom Qatar (Globcom Solutions and Services) |
| Package version | `0.0.1` |
| Default module | `Engineering ITAG KSA` in `engineering_itagksa/engineering_itag_ksa/` |
| Python | `>=3.10` |
| Frappe | `>=15.0.0,<16.0.0` |
| ERPNext | `>=15.0.0,<16.0.0` |
| `required_apps` | `frappe/erpnext` |

The default module folder is `engineering_itag_ksa` because Frappe `scrub()` of the app title lowercases it and replaces spaces with underscores. `modules.txt` records `Engineering ITAG KSA`.

## Confirmed process

- Engineering Item Request `EIR-00001`, Engineering Drawing `DWG-00001`, Material Specification `MS-00001`, Engineering Release `ER-00001`.
- Drawing and Material Specification have no Item and no Revision. Product Revision is absent.
- Engineering Release uses the Desk workflow Draft → Approved → Released for Production.
- Master Engineering Release and Work Order integration are not in this build.

Details, blockers, and the requirement rows are in `docs/acceptance-matrix.md`.

## Missing required metadata

License terms were not supplied. `app_license` is `custom`. `license.txt` records that absence and does not grant reuse rights.

Publisher contact email was not supplied. `hooks.py` leaves `app_email` empty.

## Dependencies

Frappe and ERPNext are bench apps. They are not pip dependencies. Version ranges live in `[tool.bench.frappe-dependencies]`. Packaging is `flit_core`, Python `>=3.10`.

Install sets up the three roles, the Engineering Release workflow, and read permission on Item, Item Group, UOM, BOM, Routing, and Quality Inspection Template. `add_permission` copies existing DocPerm rows into Custom DocPerm once, then adds read. It does not add Item fields and it does not grant create, write, submit, or cancel on those ERPNext documents. Engineering User and Engineering Manager also receive create, read, and write on Data Import so they can import Engineering Item Request drafts. Import permission is not added to any other DocType.

## Development

Use a bench that already has Frappe version 15 and ERPNext version 15. Point `bench get-app` at this branch. Do not deploy this branch to staging or production from this work.

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch cursor/engineering-itagksa-v15-scaffold-248f
bench --site $SITE install-app engineering_itagksa
bench --site $SITE migrate
bench build --app engineering_itagksa
bench --site $SITE run-tests --app engineering_itagksa
```

Static checks without a bench:

```bash
python3 checks/check_scaffold.py
python3 checks/test_release_rules.py
python3 -m compileall -q engineering_itagksa checks
python3 -m ruff check engineering_itagksa checks
python3 -m ruff format --check engineering_itagksa checks
python3 -m build --wheel
```

`checks/check_scaffold.py` uses `tomllib` and needs Python 3.11 or newer. The app package stays on the Frappe v15 floor of Python 3.10.

## Verification and acceptance

Static checks cover package identity, the v15 bench dependency declaration, operation-sequence comparison, byte-compile, and the DocType files. A wheel build checks packaging only.

On the disposable site `itag.localhost`, builder self-tests were executed with Frappe v15.126.0, ERPNext v15.124.5, bench 5.31.1, Python 3.12.3, and MariaDB 10.11.14:

```bash
bench --site itag.localhost install-app engineering_itagksa
bench --site itag.localhost migrate
bench build --app engineering_itagksa
bench --site itag.localhost run-tests --app engineering_itagksa
```

`run-tests` reported `Ran 8 tests in 5.713s` and `OK`. These are builder self-tests, not independent QA. The site was created for this run and is not a customer site.

Functional acceptance of rules outside `docs/acceptance-matrix.md` remains with the Owner. Independent CTO review, security review, separate QA, and Owner release approval remain pending.
