# Acceptance matrix

Confirmed by Owner Mr. Waheed on 2026-11-08 at 21:51 Qatar time (`okk lets start`), after the 21:47–21:49 corrections. This is the builder's matrix. It is not independent QA, security review, CTO review, or Owner release approval.

Reference repository `globcomqatar/erpcloud_engineering` at `42ef3e634f2a53bdcbced35c487089899c1d6a02` returned GitHub 404 from this environment. It was not copied. Where a historical field list could not be read, the row says so.

| # | Requirement | Status |
| --- | --- | --- |
| 1 | Four DocTypes: Engineering Item Request, Engineering Drawing, Material Specification, Engineering Release. No Product Revision. No Master Engineering Release. No Work Order fields, hooks, or gates. No Item applicability on Drawing or Material Specification. Item schema unchanged. | Implemented |
| 2 | Series `EIR-.#####`, `DWG-.#####`, `MS-.#####`, `ER-.#####` (00001, no year). Standard submit, cancel, and amend. No custom supersede. `ignore_links` is not set. | Implemented |
| 3 | Drawing and Material Specification are submittable, with no Item and no Revision. Engineering User prepares. Engineering Manager submits and must differ from the creator. Only Engineering Manager Master cancels, with a reason comment. Drawing requires a private file before submit. Material Specification file is optional; private if present. Content is the fields below. | Implemented |
| 4 | Engineering Item Request: Manager may also be the creator. Submit creates one Item. Optional Drawing and Material Specification links. Draft may point at draft or submitted documents. Cancelled links are rejected. Submit requires a selected document to be submitted. Cancel leaves the Item unchanged. Amendment keeps `created_item`, creates no second Item, and does not write the Item. Forged `created_item` is rejected. | Implemented |
| 5 | Standard Data Import creates new Engineering Item Request drafts only. Engineering User and Engineering Manager have import permission on that DocType only. Updates, submit, Item creation, `docstatus`, `created_item`, `amended_from`, and child rows are rejected server-side. Data Import permission on other DocTypes is not granted. | Implemented |
| 6 | Engineering Release keeps Item, one Drawing link, one Material Specification link, BOM, Routing, and optional Inspection Plan (Quality Inspection Template), chosen directly. Draft may omit Drawing, Material Specification, and BOM. Approval and production release require submitted Drawing, submitted Material Specification, and a submitted active BOM for the same Item. Routing is required at those gates when the BOM uses operations, and any selected Routing must match operation and sequence only. | Implemented |
| 7 | Desk workflow Draft (docstatus 0) → Approved (docstatus 0) → Released for Production (docstatus 1). Engineering User prepares, Engineering Manager approves, Engineering Manager Master releases. The three users must differ, including a user who holds every role. Approved engineering fields cannot be changed. Return to Draft is Master-only, requires a reason, and clears the approver. Standard cancel remains available because the workflow has no transition into Cancelled. | Implemented |
| 8 | At most one uncancelled Released for Production Engineering Release per Item and BOM, held by an `Engineering Release Slot` row and a row lock. Cancel frees the slot. Cancel does not cancel Drawing, Material Specification, BOM, or Item. | Implemented |
| 9 | Workspace Engineering, standard form sections, `*_dashboard.py` connection cards, and the three roles. Roles are not assigned to users. Read access on the ERPNext documents used by the forms is added through Frappe `add_permission`, which copies existing DocPerm rows into Custom DocPerm before adding read. No Item fields are added. | Implemented |

## Technical content that was not in the reference commit

The reference commit could not be read. These fields are the minimum content named by the confirmed process and the previously described Drawing and Material Specification content, minus Item, Revision, checksums, external links, attestation, and supersede:

- Drawing: Drawing Title, Drawing Type (free text, because a closed list was not available), Security Classification (`Internal`, `Confidential`, `Customer Controlled`), Technical Notes, private file on submit.
- Material Specification: Specification Title plus standards, materials, limits, design, testing, certification, and critical requirements. At least one of those content fields is required on submit because the file is optional.
- Engineering Item Request: Item Code, Item Name, Item Group, Stock UOM, Item Category (`Manufacturing`, `Purchase`, `Raw Material`, `Sub-Assembly`), Description, optional Drawing, optional Material Specification, Created Item.

## Blockers and choices not invented

- Item Category is stored on the request only. ERPNext Item has no standard field for those four values, and this app does not add a custom field or write `custom_product_type`.
- Item Code is entered on the request. No separate item-coding series was confirmed.
- Drawing Type has no confirmed option list, so it is text.
- Routing and Quality Inspection Template are not submittable in ERPNext v15. Cancellation does not apply to them. A disabled Routing is rejected.
- A richer historical field set from `erpcloud_engineering` was not imported.

## Explicitly not built

Master Engineering Release, Work Order integration, Product Revision, approval matrix, checklist, distribution, ECO, checksums, attestation, custom supersede, and legacy masters.
