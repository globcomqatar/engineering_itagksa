### Engineering ITAG KSA

Customer-specific Engineering ITAG KSA on Frappe v15 and ERPNext v15.

Publisher: Globcom Qatar. App name `engineering_itagksa`, module **Engineering ITAG KSA**.
Custom app + custom fields + supported hooks only (STD-SDL-001). No core fork.

#### Install

Requires a Frappe v15 bench with ERPNext v15 installed on the site.

```
bench get-app https://github.com/globcomqatar/engineering_itagksa
bench --site <site> install-app engineering_itagksa
bench --site <site> migrate
bench build --app engineering_itagksa
```

`after_install` / `after_migrate` create the roles, the five coded Workflows, the Master Engineering Release
Notifications and the Work Order `custom_subcontracted_job` field. The Custom Fields on Item, Item Group, BOM and
Work Order ship as the `fixtures/custom_field.json` fixture (module Engineering ITAG KSA). Master data (Item
Components, value lists, Approval Matrix rules, Engineering Settings) is entered or imported on the new site.

#### DocTypes (module "Engineering ITAG KSA")
| DocType | Type | Naming | Status |
|---|---|---|---|
| Engineering Approval Matrix (+ Discipline child) | master | `rule_name` | none — **resolver only (B1)** |
| Engineering Item Request | submittable | `EIR-.YYYY.-.#####` | Submit creates the Item as `<Part Code Prefix>-1000501` (7 digits, then 1000502, and 1000600 after 1000599) |
| Material Specification (+ Critical Requirement child) | **not** submittable | `MSBV-NNNNN-{n}`: first issue `MSBV-00001-0`; Create Revision keeps the number (`MSBV-00001-1`) | **Engineering ITAG KSA Material Specification** Workflow (`workflow_state`): Draft → Under Review → Approved → Obsolete; Superseded is system-only |
| Engineering Drawing | **not** submittable | `{component}-5NNNN-{n}`: first issue `500-50001-0`; Create Revision keeps the base (`500-50001-1`, then `-2`; 10 after 9). Existing drawings keep their names. The 5XXXX number is shared with Product Revision so the two DocTypes never get the same name. | **Engineering ITAG KSA Engineering Drawing** Workflow (`workflow_state`): Draft → Under Review → Approved → Obsolete; Superseded is system-only |
| Product Revision | submittable | `{component}-5NNNN-{n}`: first issue `500-50001-0`; Create Revision keeps the base (`500-50001-1`). Shares the 5XXXX space with Engineering Drawing. | **Engineering ITAG KSA Product Revision** Workflow (`workflow_state`): same path as Drawing, plus Mark Release Ready. Released and Superseded are set by the system |
| Engineering Release (+ Checklist, Distribution children) | **not** submittable | `ER-.YYYY.-.#####` | **Engineering ITAG KSA Engineering Release** Workflow (`release_status`): Draft → Under Review → Approved → Released for Production → Obsolete; Superseded is system-only. The Work Order gate reads Released for Production |
| Master Engineering Release (+ Items child) | **not** submittable | `MER-.YYYY.-.####` | **Engineering ITAG KSA Master Engineering Release** Workflow: Draft → Approved → Released for Production; Superseded is system-only |
| Engineering Change Request (+ Affected Object child) | submittable | `ECR-.YYYY.-.#####` | Draft / Under Review / Rejected → **Submit** = Approved (Rejected stays Rejected); Cancel = Cancelled |
| Engineering Change Order (+ Controlled Change child) | submittable | `ECO-.YYYY.-.#####` | Draft / Under Review → **Submit** = Approved → Completed; Cancel = Cancelled |

WIP Unit Register is **not** in v1 (A3, Deferred v2).

Roles (`Engineering User`, `Engineering Manager`, `Engineering Manager Master`) are created idempotently by
`engineering_itagksa/install.py` on `after_install` / `after_migrate`. Coded Workflows (all `send_email_alert = 0`):

* **Engineering ITAG KSA Engineering Drawing** and **Engineering ITAG KSA Material Specification** (`workflow_state`): Draft → Under Review
  (Engineering User or Manager) → Approved (Engineering Manager, no self-approval) → Obsolete; Under Review can
  return to Draft; Superseded is set by the system when a newer revision is Approved, and can be marked Obsolete.
* **Engineering ITAG KSA Product Revision** (`workflow_state`): the Drawing path, plus Approved → Release Ready (Engineering
  Manager). Released is set by the system when an Engineering Release reaches Released for Production; Superseded
  is set when a later revision is approved. The document is submittable: Approve submits it.
* **Engineering ITAG KSA Engineering Release** (`release_status`):

| From | Action | To | Roles |
|---|---|---|---|
| Draft | Submit for Review | Under Review | Engineering User, Engineering Manager |
| Under Review | Return to Draft | Draft | Engineering Manager |
| Under Review | Approve (no self-approval) | Approved | Engineering Manager |
| Approved | Return to Draft | Draft | Engineering Manager |
| Approved | Release for Production | Released for Production | Engineering Manager Master |
| Released for Production | Mark Obsolete | Obsolete | Engineering Manager |
| Superseded | Mark Obsolete | Obsolete | Engineering Manager |

* **Engineering ITAG KSA Master Engineering Release**: Draft → Approved (Engineering Manager, not the creator) → Released for
  Production (Engineering Manager Master, not the approver). Superseded is set by the system.

Superseded on Engineering Release is set when a newer release goes Released for Production. ECR and ECO keep the
standard Save / Submit / Cancel buttons.


#### Locked configuration surface (Ahmed soft #3)
* **Item Group → `requires_engineering_release`** (Check, default **1**) — fixture `fixtures/custom_field.json`.
* Work Order gate (`work_order_gate.check_work_order`, Work Order `before_submit`) is **fail-closed**:
  submit is blocked unless an Engineering Release with `release_status = "Released for Production"` exists for the
  production item (and, if both set, its BOM equals the Work Order BOM) when the item's category is
  Manufacturing / Sub-Assembly, OR its group flag is 1 / unset, OR it has no group.
  Only items in a group with the flag explicitly **0** and not manufacturing-category pass (services).
  The release name is stamped on Work Order `engineering_release`.
* Item Engineering tab custom fields: `eng_item_category`, `eng_item_component`, `eng_nominal_size`, `eng_pressure_class`,
  `eng_body_material`, `eng_trim_material`, `eng_manufacturer_part_number`.

#### Key server rules
* Material Specification (v15.3.0): no Item Code; Revision is system-assigned (0, then +1 via Create Revision on an
  Approved spec; one open revision per chain); approving a revision supersedes the Approved one of the same MS-BV
  number in the same transaction; Approved content is locked and the status only moves forward.
* One-active: approving a new Material Specification / releasing a new Drawing / approving a new Product Revision / releasing
  a new Engineering Release supersedes the prior active one **in the same server transaction**; an older revision
  cannot supersede a newer active one. Revisions are part of the name; Amend only corrects the same revision.
* Drawing SHA-256 (A4): operator-attested; server validates 64-hex, stamps attester/time (client values ignored),
  clears attestation if link/hash changes. Attestation is optional: it does not block Submit (v15.1.31).
  External link refuses credentials / token / signed-URL params. Track Changes on.
* Product Revision submit requires an Approved Engineering Drawing in the Item's drawing chain and an
  Approved Material Specification (v15.3.0: no Item Code on the specification, so no same-item check).
  Inspection plan = native **Quality Inspection Template**.
* Engineering Release: baseline checks at Approved and Released for Production, checklist complete, server
  `release_checksum`, record locked after Released for Production. Release Distribution: only in-app System
  Notification is generated; Email/Print are never auto-sent (POL-EML).
* ECR/ECO never write to Item/BOM/Routing/Drawing/Spec (B7). ECO needs an Approved ECR and Controlled Changes with
  interchangeability before approval/completion.
* Customer Controlled drawings visible only to Engineering Manager / System Manager (B10; Nasser DocPerm review
  required before production).

#### Desk Workspace
Sidebar entry **Engineering** (module workspace, public). Your Shortcuts includes Engineering Item Request, Material
Specification, Engineering Drawing, Product Revision, Engineering Release, Master Engineering Release (immediately
after Engineering Release), Engineering Change Request, Engineering Change Order, and the Engineering Dashboard.
After changes: `bench --site <site> migrate`, then hard-refresh the desk.


#### Tests

#### Tests
```
bench --site <site> run-tests --app engineering_itagksa
bench --site <site> execute engineering_itagksa.tests.smoke_lifecycle.run        # rollback-only lifecycle smoke
bench --site <site> execute engineering_itagksa.tests.test_work_order_gate.run   # Work Order gate cases
```

#### Changelog
See [CHANGELOG.md](CHANGELOG.md).

#### Frappe Cloud
- Supports Frappe/ERPNext v15 benches only (declared via `[tool.bench.frappe-dependencies]` in `pyproject.toml`).
- Requires ERPNext (`required_apps`). Migrate setup logs Workflow/Notification issues to Error Log instead of failing.

#### License
mit (see `license.txt`).
