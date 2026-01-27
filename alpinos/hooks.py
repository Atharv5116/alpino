app_name = "alpinos"
app_title = "Alpinos Development"
app_publisher = "Hetvi Patel"
app_description = "All the custom development for Alpinos"
app_email = "hetvipatel2302@gmail.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "alpinos",
# 		"logo": "/assets/alpinos/logo.png",
# 		"title": "Alpinos Development",
# 		"route": "/alpinos",
# 		"has_permission": "alpinos.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/alpinos/css/alpinos.css"
# app_include_js = "/assets/alpinos/js/alpinos.js"

# include js, css files in header of web template
# web_include_css = "/assets/alpinos/css/alpinos.css"
# web_include_js = "/assets/alpinos/js/alpinos.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "alpinos/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"screening": "public/js/screening.js"}

# include js in doctype views
# Note: Job Applicant, Interview, and Employee Onboarding are in HRMS module
# All JavaScript functionality is handled via Client Scripts (see employee_onboarding_client_scripts.py)
# No doctype_js needed - client scripts are the correct approach for doctypes in other modules
# doctype_js = {
# 	"Employee Onboarding": "doctype.employee_onboarding.employee_onboarding"
# }
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "alpinos/public/icons.svg"

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
# 	"methods": "alpinos.utils.jinja_methods",
# 	"filters": "alpinos.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "alpinos.install.before_install"
# after_install = "alpinos.install.after_install"

# Boot Session Hook
# ------------
# Apply patches when session boots (ensures patch is active on every request)
boot_session = "alpinos.overrides.interview_override.setup_interview_override"

# Fixtures
# --------
fixtures = [
	{
		"dt": "Custom Field",
		"filters": [["module", "=", "Alpinos Development"]]
	},
	{
		"dt": "Property Setter",
		"filters": [["module", "=", "Alpinos Development"]]
	}
]

patches = [
	"alpinos.patches.create_attendance_widget"
]

after_migrate = [
	"alpinos.custom_fields.setup_custom_fields",
	"alpinos.employee_onboarding_custom_fields.setup_employee_onboarding_custom_fields",
	"alpinos.employee_onboarding_client_scripts.create_employee_onboarding_client_scripts",
	"alpinos.workflow_setup.execute",
	"alpinos.page_setup.create_screening_page",
	"alpinos.overrides.interview_override.setup_interview_override",
	"alpinos.update_job_application_webform.update_web_form_script",
	"alpinos.customize_expense_claim.execute",
	"alpinos.page_setup.create_screening_page",
	"alpinos.employee_expense_claim_button.execute"
]

# Uninstallation
# ------------

# before_uninstall = "alpinos.uninstall.before_uninstall"
# after_uninstall = "alpinos.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "alpinos.utils.before_app_install"
# after_app_install = "alpinos.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "alpinos.utils.before_app_uninstall"
# after_app_uninstall = "alpinos.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "alpinos.notifications.get_notification_config"

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

override_doctype_class = {
	"Job Applicant": "alpinos.overrides.job_applicant_override.CustomJobApplicant",
	"Expense Claim": "alpinos.customize_expense_claim.ExpenseClaimOverride"
}

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Job Requisition": {
		"before_insert": "alpinos.job_requisition_automation.set_requested_by",
		"before_save": [
			"alpinos.job_requisition_automation.update_approval_fields",
			"alpinos.job_requisition_automation.fetch_reporting_manager"
		],
		"on_update": [
			"alpinos.job_requisition_automation.create_published_job_opening_on_live",
			"alpinos.job_requisition_automation.sync_status_with_job_opening"
		]
	},
	"Job Opening": {
		"before_save": "alpinos.job_opening_automation.set_job_application_route",
		"on_update": "alpinos.job_opening_automation.ensure_job_application_route"
	},
	"Job Applicant": {
		"before_insert": "alpinos.job_applicant_automation.auto_populate_from_job_opening",
		"before_save": [
			"alpinos.job_applicant_automation.auto_populate_from_job_opening",
			"alpinos.job_applicant_automation.generate_candidate_id",
			"alpinos.job_applicant_automation.update_screening_status_automatically"
		]
	},
	"Interview": {
		"after_insert": "alpinos.job_applicant_automation.update_screening_status_on_interview_created",
		"on_update": "alpinos.job_applicant_automation.update_screening_status_on_interview_status_change"
	},
	"Employee Onboarding": {
		"validate": [
			"alpinos.employee_onboarding_automation.allow_hr_manager_to_save_without_mandatory_fields",
			"alpinos.employee_onboarding_automation.populate_from_job_applicant"
		],
		"before_save": [
			"alpinos.employee_onboarding_automation.populate_from_job_applicant",
			"alpinos.employee_onboarding_automation.handle_pre_onboarding_workflow"
		]
	}
}

# Scheduled Tasks
# ---------------

scheduler_events = {
	"daily": [
		"alpinos.employee_onboarding_automation.send_scheduled_pre_onboarding_emails"
	],
}

# Boot Info Extensions
# --------------------

extend_bootinfo = [
	"alpinos.customize_expense_claim.extend_bootinfo"
]

# Testing
# -------

# before_tests = "alpinos.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "alpinos.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "alpinos.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["alpinos.utils.before_request"]
# after_request = ["alpinos.utils.after_request"]

# Job Events
# ----------
# before_job = ["alpinos.utils.before_job"]
# after_job = ["alpinos.utils.after_job"]

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
# 	"alpinos.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

