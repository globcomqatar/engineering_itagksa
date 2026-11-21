# Changelog

## 15.3.7 (2026-11-21) - Phase 1 (ITAG KSA Engineering feedback)

- **Drawing Type master**: new DocType Engineering Drawing Type (Engineering Manager maintains; seeded Manufacturing,
  Pre-Machining, Cladding, Coating, Welding, Forging). Engineering Drawing.drawing_type is now a Link. Item Component
  has an Allowed Drawing Types table; the Drawing Type dropdown and the server check use it (all enabled types when
  none are set). Old Select values still used by a drawing are created disabled by the patch.
- **Component attributes**: Item Component has an Attributes table (attribute, Mandatory, row order). Picking the
  component on an Engineering Item Request fills its attribute rows in that order; values come from the attribute's
  Item Spec Attribute Value list (Autocomplete, stored as the value string); mandatory attributes are required at
  Submit.
- **Item Name / Description** on the Item Request are built and read-only: Item Name = the Component Name;
  Description = Component Name, attribute values, Special Details (new field), joined by ", ", not truncated. The
  created Item gets both.
- Item Component Item Group is optional (a component without a group fits any Item Group). Engineering Drawing.drawing_name removed; the Drawing has a required Description.
- **Drawing number without a file**: a Prepared drawing saves with component, type and description; the file or link
  is required from Reviewed on.
- **Delete**: Engineering User / Manager may delete a Prepared drawing that was never sent for review (hidden
  "Sent for Review" flag); linked drawings stay protected by the standard link check. The number is not reissued.
- **States**: Engineering Drawing and Material Specification Draft -> Prepared, Under Review -> Reviewed (action
  "Return to Prepared"). Product Revision, Engineering Release, Master Engineering Release, ECR and ECO unchanged.
- Patches (post model sync, idempotent): rename_drawing_ms_states, drawing_description_and_types,
  backfill_drawing_sent_for_review.

## 15.3.6 (2026-11-10)

First release of **Engineering ITAG KSA** (`engineering_itagksa`).

- Renamed from `erpcloud_engineering` 15.3.6 (source commit 82a7a040), with the same functionality.
- App name and Python package `engineering_itagksa`; title "Engineering ITAG KSA"; module "Engineering ITAG KSA".
- Coded Workflows renamed: Engineering ITAG KSA Engineering Release, Engineering ITAG KSA Master Engineering
  Release, Engineering ITAG KSA Engineering Drawing, Engineering ITAG KSA Material Specification, Engineering ITAG
  KSA Product Revision. DocTypes, roles and fields are unchanged.
- Fresh-install app: the historical upgrade patches are not included (`patches.txt` is empty). The Item related
  documents backfill used by `after_migrate` now lives in `install.py`.
- Naming unchanged: Items `<prefix>-1000501`, Drawings and Product Revisions `500-5NNNN-0` (shared counter),
  Material Specifications `MSBV-00001-0`. Work Order release gate, ECR / ECO and Master Engineering Release
  behaviour unchanged.
