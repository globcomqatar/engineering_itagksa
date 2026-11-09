"""Names shared by the Engineering ITAG KSA process."""

ENGINEERING_USER = "Engineering User"
ENGINEERING_MANAGER = "Engineering Manager"
ENGINEERING_MANAGER_MASTER = "Engineering Manager Master"
ROLES = (ENGINEERING_USER, ENGINEERING_MANAGER, ENGINEERING_MANAGER_MASTER)

DRAWING = "Engineering Drawing"
MATERIAL_SPECIFICATION = "Material Specification"
ITEM_REQUEST = "Engineering Item Request"
ENGINEERING_RELEASE = "Engineering Release"

CANCELLABLE = (DRAWING, MATERIAL_SPECIFICATION, ITEM_REQUEST, ENGINEERING_RELEASE)

ITEM_CATEGORIES = ("Manufacturing", "Purchase", "Raw Material", "Sub-Assembly")
SECURITY_CLASSIFICATIONS = ("Internal", "Confidential", "Customer Controlled")

MS_CONTENT_FIELDS = (
	"standards",
	"materials",
	"limits",
	"design",
	"testing",
	"certification",
	"critical_requirements",
)

RELEASE_CONTENT_FIELDS = (
	"item",
	"engineering_drawing",
	"material_specification",
	"bom",
	"routing",
	"inspection_plan",
)
