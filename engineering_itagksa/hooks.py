app_name = "engineering_itagksa"
app_title = "Engineering ITAG KSA"
app_publisher = "Globcom Qatar"
app_description = "Customer-specific Engineering ITAG KSA on Frappe v15 and ERPNext v15."
app_email = "engineering@globcomqatar.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "engineering_itagksa",
# 		"logo": "/assets/engineering_itagksa/logo.png",
# 		"title": "Engineering ITAG KSA",
# 		"route": "/engineering_itagksa",
# 		"has_permission": "engineering_itagksa.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/engineering_itagksa/css/engineering_itagksa.css"
# app_include_js = "/assets/engineering_itagksa/js/engineering_itagksa.js"

# include js, css files in header of web template
# web_include_css = "/assets/engineering_itagksa/css/engineering_itagksa.css"
# web_include_js = "/assets/engineering_itagksa/js/engineering_itagksa.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "engineering_itagksa/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "engineering_itagksa/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "engineering_itagksa.utils.jinja_methods",
# 	"filters": "engineering_itagksa.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "engineering_itagksa.install.before_install"
# after_install = "engineering_itagksa.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "engineering_itagksa.uninstall.before_uninstall"
# after_uninstall = "engineering_itagksa.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "engineering_itagksa.utils.before_app_install"
# after_app_install = "engineering_itagksa.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "engineering_itagksa.utils.before_app_uninstall"
# after_app_uninstall = "engineering_itagksa.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "engineering_itagksa.build.after_build"

# To hook into the build process of other apps
# The list of apps being built is passed as an argument

# after_app_build = "engineering_itagksa.build.after_app_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "engineering_itagksa.notifications.get_notification_config"

# Awesome Bar
# -----------
# Extra search results: list of dicts with label, description, route, index.
# route: ["List", "ToDo"], "/desk/docs/some/page", or "https://example.com"
# awesomebar_search = ["engineering_itagksa.search.awesomebar_results"]

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"engineering_itagksa.tasks.all"
# 	],
# 	"daily": [
# 		"engineering_itagksa.tasks.daily"
# 	],
# 	"hourly": [
# 		"engineering_itagksa.tasks.hourly"
# 	],
# 	"weekly": [
# 		"engineering_itagksa.tasks.weekly"
# 	],
# 	"monthly": [
# 		"engineering_itagksa.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "engineering_itagksa.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "engineering_itagksa.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "engineering_itagksa.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["engineering_itagksa.utils.before_request"]
# after_request = ["engineering_itagksa.utils.after_request"]

# Job Events
# ----------
# before_job = ["engineering_itagksa.utils.before_job"]
# after_job = ["engineering_itagksa.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"engineering_itagksa.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []



# ---------------------------------------------------------------------------
# Engineering ITAG KSA v1 (local bench build, 2026-11-01)
# ---------------------------------------------------------------------------
required_apps = ["erpnext"]

after_install = "engineering_itagksa.install.after_install"
after_migrate = "engineering_itagksa.install.after_migrate"

# Item form: Engineering tab Related Documents refresh.
doctype_js = {
	"Item": "public/js/item.js",
	"Work Order": "public/js/work_order.js",
	# Engineering Settings -> Default Company on new Engineering docs.
	"Engineering Release": "public/js/eng_default_company.js",
	"Engineering Change Order": "public/js/eng_default_company.js",
	"Engineering Approval Matrix": "public/js/eng_default_company.js",
}

# Custom fields (fieldnames locked here, incl. Item Group `requires_engineering_release`).
fixtures = [
	{"dt": "Custom Field", "filters": [["module", "=", "Engineering ITAG KSA"]]},
]

# B5 fail-closed Work Order gate (on submit, per plan).
_ITEM_LINK_EVENTS = ["after_insert", "on_update", "on_submit", "on_cancel", "on_update_after_submit", "on_trash"]

# Work Order Engineering tab -> ECR / ECO stay current (on_submit is listed with the chain hooks).
_WO_LINK_EVENTS = ["after_insert", "on_update", "on_cancel", "on_update_after_submit", "on_trash"]

doc_events = {
	"Work Order": {
		"before_submit": "engineering_itagksa.work_order_gate.check_work_order",
		"on_change": "engineering_itagksa.work_order_change.on_work_order_change",
	},
	"Engineering Change Request": {
		"on_submit": [
			"engineering_itagksa.work_order_change.on_ecr_submit",
			"engineering_itagksa.work_order_links.on_change_doc",
		],
		**{e: "engineering_itagksa.work_order_links.on_change_doc" for e in _WO_LINK_EVENTS},
	},
	"Engineering Change Order": {
		"before_validate": "engineering_itagksa.eng_settings.apply_default_company",
		"on_submit": [
			"engineering_itagksa.work_order_change.on_eco_submit",
			"engineering_itagksa.work_order_links.on_change_doc",
		],
		**{e: "engineering_itagksa.work_order_links.on_change_doc" for e in _WO_LINK_EVENTS},
	},
	"Engineering Approval Matrix": {
		"before_validate": "engineering_itagksa.eng_settings.apply_default_company",
	},
	"BOM": {
		"validate": "engineering_itagksa.bom_parent.validate_parent_bom",
		**{e: "engineering_itagksa.item_links.on_source_change" for e in _ITEM_LINK_EVENTS},
	},
	# Item Engineering tab -> Related Documents (BOM / Design / Release) stay current.
	"Engineering Drawing": {e: "engineering_itagksa.item_links.on_source_change" for e in _ITEM_LINK_EVENTS},
	"Engineering Item Request": {e: "engineering_itagksa.item_links.on_source_change" for e in _ITEM_LINK_EVENTS},
	"Engineering Release": {
		"before_validate": "engineering_itagksa.eng_settings.apply_default_company",
		**{e: "engineering_itagksa.item_links.on_source_change" for e in _ITEM_LINK_EVENTS},
	},
}

# B10: Customer Controlled drawings restricted to privileged roles.
permission_query_conditions = {
	"Engineering Drawing": "engineering_itagksa.permissions.drawing_query_conditions",
}
has_permission = {
	"Engineering Drawing": "engineering_itagksa.permissions.drawing_has_permission",
}

# v15.2.0 Master Engineering Release: block deleting an Engineering Release that belongs to a Master
# (standalone releases keep delete as before); Masters appear on the BOM Connections tab.
doc_events["Engineering Release"]["on_trash"] = [
	"engineering_itagksa.engineering_itag_ksa.doctype.master_engineering_release.master_engineering_release.block_er_delete",
	"engineering_itagksa.item_links.on_source_change",
]
override_doctype_dashboards = {
	"BOM": "engineering_itagksa.master_release_links.bom_dashboard",
}
