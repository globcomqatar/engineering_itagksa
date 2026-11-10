# Changelog

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
