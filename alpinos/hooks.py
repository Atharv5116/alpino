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
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
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
after_migrate = [
	"alpinos.system_settings_setup.execute",  # Enable guest file uploads for web forms
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

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {

    "Job Applicant": {
        "before_insert": [
            "alpinos.job_applicant_automation.generate_candidate_id",
            "alpinos.job_applicant_automation.set_default_status",
            "alpinos.job_applicant_automation.set_application_date",
        ],
        "validate": [
            "alpinos.job_applicant_automation.validate_mandatory_fields",
            "alpinos.job_applicant_automation.validate_resume_file_type",
        ],
        "before_save": [
            "alpinos.job_applicant_automation.auto_populate_from_job_requisition",
            "alpinos.job_applicant_automation.auto_populate_from_job_opening",
            "alpinos.job_applicant_automation.validate_job_requisition_open",
            "alpinos.job_applicant_automation.validate_job_opening_open",
        ],
        "after_insert": [
            "alpinos.job_applicant_automation.process_web_form_submission",
        ],
    },

    "Job Requisition": {
        "before_save": "alpinos.job_requisition_automation.update_approval_fields",
        "on_update": [
            "alpinos.job_requisition_automation.create_job_opening_on_approval",
            "alpinos.job_requisition_automation.publish_job_opening_on_live",
            "alpinos.job_requisition_automation.sync_status_with_job_opening",
        ],
    },
}

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"alpinos.tasks.all"
# 	],
# 	"daily": [
# 		"alpinos.tasks.daily"
# 	],
# 	"hourly": [
# 		"alpinos.tasks.hourly"
# 	],
# 	"weekly": [
# 		"alpinos.tasks.weekly"
# 	],
# 	"monthly": [
# 		"alpinos.tasks.monthly"
# 	],
# }

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

fixtures = [
	"Custom Field",
	"Property Setter",
]