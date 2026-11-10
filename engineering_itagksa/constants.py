"""Single source of truth for Status values (``workflow_state`` Selects / Engineering Release ``release_status``).

Engineering Release uses a Workflow (v15.1.32, "Engineering ITAG KSA Engineering Release" on ``release_status``, a
Link -> Workflow State); Master Engineering Release uses "Engineering ITAG KSA Master Engineering Release" (v15.2.1, on its
``release_status`` Select); Engineering Drawing uses "Engineering ITAG KSA Engineering Drawing" (v15.3.0, on its
``workflow_state`` Select, not submittable); Product Revision uses "Engineering ITAG KSA Product Revision" (v15.3.3, a copy
of the Drawing Workflow adapted to a submittable DocType). All other DocTypes use no Workflow: submittable docs get their approved status from
standard Submit and "Cancelled" from Cancel; the field name ``workflow_state`` there is historic only (a normal
Select field).
"""

DRAFT = "Draft"
UNDER_REVIEW = "Under Review"
APPROVED = "Approved"
REJECTED = "Rejected"
SUPERSEDED = "Superseded"
OBSOLETE = "Obsolete"
CANCELLED = "Cancelled"
RELEASED = "Released"
RELEASE_READY = "Release Ready"
RELEASED_FOR_PRODUCTION = "Released for Production"
COMPLETED = "Completed"

ROLE_ENG_USER = "Engineering User"
ROLE_ENG_MANAGER = "Engineering Manager"
# v15.1.34: only this role may run "Release for Production" on Engineering Release.
ROLE_ENG_MANAGER_MASTER = "Engineering Manager Master"

# Item category values (Engineering tab on Item / Item Request)
MANUFACTURING_CATEGORIES = ("Manufacturing", "Sub-Assembly")

# Locked custom fieldname on Item Group for the Work Order gate (Ahmed soft #3).
ITEM_GROUP_GATE_FIELD = "requires_engineering_release"

# Inactive (history) states: a doc in one of these never counts as "active".
INACTIVE_STATES = (SUPERSEDED, OBSOLETE, CANCELLED, REJECTED)
