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
doctype_js = {
	"User": "public/js/user_override.js",
	"Sales Order": "public/js/sales_order_offline_buyer.js",
}
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
boot_session = [
	"alpinos.overrides.interview_override.setup_interview_override",
	"alpinos.overrides.employee_checkin_override.patch_mark_attendance_and_link_log",
]

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
	"alpinos.patches.create_attendance_widget",
	"alpinos.patches.v1_0.delete_unused_employee_bank_fields",
]

after_migrate = [
	"alpinos.custom_fields.setup_custom_fields",
	"alpinos.employee_onboarding_custom_fields.setup_employee_onboarding_custom_fields",
	"alpinos.employee_onboarding_client_scripts.create_employee_onboarding_client_scripts",
	"alpinos.employee_naming_config.setup_employee_manual_naming",
	"alpinos.impersonate.create_impersonate_role",
	"alpinos.workflow_setup.execute",
	"alpinos.patches.v1_0.setup_job_applicant_workflow.execute",
	"alpinos.page_setup.create_screening_page",
	"alpinos.overrides.interview_override.setup_interview_override",
	"alpinos.update_job_application_webform.update_web_form_script",
	"alpinos.customize_expense_claim.execute",
	"alpinos.employee_expense_claim_button.execute",
	"alpinos.patches.create_hrms_email_templates.execute",
	"alpinos.job_requisition_automation.create_job_requisition_client_script",
	"alpinos.work_from_home_request_automation.create_work_from_home_client_script",
	"alpinos.attendance_request_automation.create_attendance_request_client_script",
	"alpinos.attendance_request_automation.create_employee_checkin_client_script",
	"alpinos.attendance_request_custom_fields.setup_attendance_request_custom_fields",
	"alpinos.patches.create_attendance_widget.execute",
	"alpinos.sales_order_custom_fields.setup_sales_order_custom_fields",
	"alpinos.opportunity_custom_fields.setup_opportunity_custom_fields",
	"alpinos.quotation_custom_fields.setup_quotation_custom_fields",
	"alpinos.item_custom_fields.setup_item_custom_fields",
	"alpinos.stock_entry_custom_fields.setup_stock_entry_custom_fields",
	"alpinos.pick_list_custom_fields.setup_pick_list_custom_fields",
	"alpinos.sales_order_client_script.create_sales_order_client_script",
	"alpinos.opportunity_client_script.create_opportunity_client_script",
	"alpinos.stock_entry_client_script.create_stock_entry_client_script",
	"alpinos.quotation_client_script.create_quotation_client_script",
	"alpinos.pick_list_client_script.create_pick_list_client_script",
	"alpinos.web_form_update.execute",
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

permission_query_conditions = {}

# Raven permissions (override from Alpinos, without touching raven app)
# Ensures Raven can list channels/messages by membership (helps imports + visibility).


# DocType Class
# ---------------
# Override standard doctype classes

override_doctype_class = {
	"Job Applicant": "alpinos.overrides.job_applicant_override.CustomJobApplicant",
	"Expense Claim": "alpinos.customize_expense_claim.ExpenseClaimOverride",
	"Interview": "alpinos.overrides.interview_override.CustomInterview",
	"Employee Onboarding": "alpinos.overrides.employee_onboarding_override.CustomEmployeeOnboarding",
	"Job Opening": "alpinos.overrides.job_opening_override.CustomJobOpening",
	"Attendance Request": "alpinos.overrides.attendance_request_override.CustomAttendanceRequest",
	"Employee Checkin": "alpinos.overrides.employee_checkin_override.CustomEmployeeCheckin",
	"Leave Application": "alpinos.overrides.leave_application_override.CustomLeaveApplication",
	"Shift Request": "alpinos.overrides.shift_request_override.CustomShiftRequest",
	"User": "alpinos.overrides.user_override.CustomUser",
}

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Job Requisition": {
		"before_insert": "alpinos.job_requisition_automation.set_requested_by",
		"validate": [
			"alpinos.job_requisition_automation.set_requested_by",
			"alpinos.job_requisition_automation.fetch_designation_details",
			"alpinos.job_requisition_automation.validate_salary_range",
			"alpinos.job_requisition_automation.validate_job_requisition"
		],
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
		"before_save": [
			"alpinos.job_opening_automation.set_job_application_route",
			"alpinos.job_opening_automation.set_source_urls"
		],
		"on_update": "alpinos.job_opening_automation.ensure_job_application_route"
	},
	"Job Applicant": {
		"before_insert": "alpinos.job_applicant_automation.auto_populate_from_job_opening",
		"before_save": [
			"alpinos.job_applicant_automation.auto_populate_from_job_opening",
			"alpinos.job_applicant_automation.generate_candidate_id",
			"alpinos.job_applicant_automation.update_screening_status_automatically"
		],
		"after_insert": "alpinos.job_applicant_automation.process_web_form_submission"
	},
	"Interview": {
		"after_insert": "alpinos.job_applicant_automation.update_screening_status_on_interview_created",
		"on_update": [
			"alpinos.job_applicant_automation.update_screening_status_on_interview_status_change",
			"alpinos.job_applicant_automation.send_interview_scheduled_emails",
		]
	},
	"Quotation": {
		"validate": "alpinos.quotation_validate.validate_partial_payment_fields",
	},
	"Stock Entry": {
		"before_insert": "alpinos.stock_entry_hooks.set_entry_by",
	},
	"Pick List": {
		"validate": "alpinos.pick_list_hooks.validate_pick_list",
	},
	"Delivery Note": {
		"validate": "alpinos.delivery_note_hooks.validate_delivery_note",
	},
	"Sales Order": {
		"validate": [
			"alpinos.sales_order_offline_buyer.validate_sales_order_offline_buyer_customer",
			"alpinos.sales_order_offline_buyer.sync_sales_order_offline_buyer_fields",
		],
	},
	"Employee Onboarding": {
		"before_validate": [
			"alpinos.employee_onboarding_automation.allow_hr_manager_to_save_without_mandatory_fields",
			"alpinos.employee_onboarding_webform.prepare_webform_temp_onboarding",
		],
		"validate": [
			"alpinos.employee_onboarding_automation.populate_from_job_applicant",
			"alpinos.employee_onboarding_automation.validate_date_of_birth"
		],
		"before_save": [
			"alpinos.employee_onboarding_automation.populate_from_job_applicant",
			"alpinos.employee_onboarding_automation.handle_pre_onboarding_workflow"
		],
		"after_insert": [
			"alpinos.employee_onboarding_automation.send_onboarding_created_email",
			"alpinos.employee_onboarding_webform.process_webform_submission"
		]
	},
	"Work From Home Request": {
		"before_insert": "alpinos.work_from_home_request_automation.auto_populate_employee_and_approver",
		"validate": "alpinos.work_from_home_request_automation.auto_populate_employee_and_approver",
		"before_save": "alpinos.work_from_home_request_automation.auto_populate_employee_and_approver"
	},
	"Attendance Request": {
		"validate": "alpinos.attendance_request_automation.set_reporting_person"
	},
	"Attendance": {
		"validate": [
			"alpinos.attendance_request_automation.validate_saturday_attendance_threshold"
		],
		"after_insert": "alpinos.attendance_request_automation.populate_attendance_reason_after_insert",
		"after_submit": "alpinos.attendance_request_automation.populate_attendance_reason_after_submit"
	}
}

# Scheduled Tasks
# ---------------

scheduler_events = {
	"daily": [
		"alpinos.employee_onboarding_automation.send_scheduled_pre_onboarding_emails"
	],
	"cron": {
		"*/30 * * * *": [
			"alpinos.essl_sync.sync_essl_logs",
			"alpinos.attendance_scheduler.process_auto_attendance_periodic"
		]
	}
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
# Monkey-patch OAuth server on every request to extend token expiry for Raven mobile app
before_request = ["alpinos.overrides.oauth_override.patch_oauth_server"]
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

# Automatically update python controller files with type annotations in this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }
