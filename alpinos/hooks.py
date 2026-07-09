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
app_include_js = [
	"/assets/alpinos/js/sales_order_hub_desk_v3.js",
	"/assets/alpinos/js/item_row_colors.js",
]

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
	"Quotation": "public/js/quotation_sales_order_redirect.js",
}
doctype_list_js = {
	"Pick List": "public/js/pick_list_list.js",
	"Item": "public/js/item_list_colors.js",
}
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
# NOTE: each entry must be a dotted path to a FUNCTION (exposed under its own name).
# Pointing at a dict (alpinos.utils.jinja_methods) does NOT expose its members to Jinja.
jinja = {
	"methods": [
		"alpinos.utils.get_combined_items",
	],
}

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
	"alpinos.patches.create_hr_lifecycle_widget",
	"alpinos.patches.create_missing_checkin_widget",
	"alpinos.patches.create_approvals_widget",
	"alpinos.patches.create_outside_geo_widget",
	"alpinos.patches.v1_0.delete_unused_employee_bank_fields",
	"alpinos.patches.v1_0.remove_pick_list_batch_mandatory",
	"alpinos.patches.v1_0.install_alpinos_removed_pick_list_item",
]

after_migrate = [
	"alpinos.custom_fields.setup_custom_fields",
	"alpinos.employee_onboarding_custom_fields.setup_employee_onboarding_custom_fields",
	"alpinos.employee_onboarding_client_scripts.create_employee_onboarding_client_scripts",
	"alpinos.employee_naming_config.setup_employee_manual_naming",
	"alpinos.impersonate.create_impersonate_role",
	"alpinos.workflow_setup.execute",
	"alpinos.employee_onboarding_workflow_setup.execute",
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
	"alpinos.essl_sync.get_essl_settings",
	"alpinos.attendance_request_custom_fields.setup_attendance_request_custom_fields",
	"alpinos.attendance_request_workflow_setup.execute",
	"alpinos.salary_category_setup.seed_salary_categories",
	"alpinos.attendance_batch_workflow_setup.execute",
	"alpinos.leave_application_custom_fields.setup_leave_application_custom_fields",
	"alpinos.work_from_home_custom_fields.setup_work_from_home_custom_fields",
	"alpinos.employee_probation_automation.setup_employee_probation",
	"alpinos.salary_visibility.setup_employee_salary_field_permissions",
	"alpinos.raven_notifications.setup_raven_notification_bot",
	"alpinos.designation_branch_policy.setup_designation_branch_policy",
	"alpinos.patches.create_attendance_widget.execute",
	"alpinos.patches.create_hr_lifecycle_widget.execute",
	"alpinos.patches.create_missing_checkin_widget.execute",
	"alpinos.patches.create_approvals_widget.execute",
	"alpinos.approval_access.setup_approvals_access",
	"alpinos.patches.create_outside_geo_widget.execute",
	"alpinos.data_import_shortcuts.ensure_allow_import",
	"alpinos.sales_order_custom_fields.setup_sales_order_custom_fields",
	"alpinos.opportunity_custom_fields.setup_opportunity_custom_fields",
	"alpinos.quotation_custom_fields.setup_quotation_custom_fields",
	"alpinos.sales_order_scheme_damage_migration.run_sales_order_scheme_damage_split_migration",
	"alpinos.item_custom_fields.setup_item_custom_fields",
	"alpinos.product_bundle_sync.backfill_product_bundles",
	"alpinos.offline_buyer_api.seed_customer_types",
	"alpinos.assigned_visibility.setup_visibility_roles",
	"alpinos.stock_entry_custom_fields.setup_stock_entry_custom_fields",
	"alpinos.pick_list_custom_fields.setup_pick_list_custom_fields",
	"alpinos.sales_order_client_script.create_sales_order_client_script",
	"alpinos.opportunity_client_script.create_opportunity_client_script",
	"alpinos.stock_entry_client_script.create_stock_entry_client_script",
	"alpinos.quotation_client_script.create_quotation_client_script",
	"alpinos.pick_list_client_script.create_pick_list_client_script",
	"alpinos.item_customer_access.create_item_customer_access_client_script",
	"alpinos.workflow_role_access.execute",
	"alpinos.web_form_update.execute",
	"alpinos.sales_order_print_format_patch.execute",
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

permission_query_conditions = {
	"Pick List": "alpinos.assigned_visibility.pick_list_query_conditions",
	"Delivery Note": "alpinos.assigned_visibility.delivery_note_query_conditions",
	"Salary Slip": "alpinos.salary_visibility.salary_slip_query_conditions",
}

has_permission = {
	"Pick List": "alpinos.assigned_visibility.pick_list_has_permission",
	"Delivery Note": "alpinos.assigned_visibility.delivery_note_has_permission",
	"Salary Slip": "alpinos.salary_visibility.salary_slip_has_permission",
}

# Raven permissions (override from Alpinos, without touching raven app)
# Ensures Raven can list channels/messages by membership (helps imports + visibility).


# DocType Class
# ---------------
# Override standard doctype classes

override_whitelisted_methods = {
	"erpnext.crm.doctype.opportunity.opportunity.make_quotation": (
		"alpinos.opportunity_make_quotation.make_quotation"
	),
	"erpnext.accounts.party.get_party_details": "alpinos.item_details.get_party_details",
	"erpnext.accounts.party.set_taxes": "alpinos.item_details.set_taxes",
	"erpnext.stock.get_item_details.get_item_details": "alpinos.item_details.get_item_details",
	"erpnext.stock.get_item_details.get_item_tax_template": "alpinos.item_details.get_item_tax_template",
}

override_doctype_class = {
	"Pick List": "alpinos.overrides.pick_list_override.CustomPickList",
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
	"Delivery Note": "alpinos.overrides.delivery_note_override.CustomDeliveryNote",
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
			"alpinos.job_requisition_automation.sync_status_with_job_opening",
			"alpinos.raven_notifications.notify_job_requisition"
		]
	},
	"Leave Application": {
		"on_update": "alpinos.raven_notifications.notify_leave_application",
		"on_submit": "alpinos.raven_notifications.notify_leave_application"
	},
	"Expense Claim": {
		"on_update": "alpinos.raven_notifications.notify_expense_claim",
		"on_submit": "alpinos.raven_notifications.notify_expense_claim",
		"on_update_after_submit": "alpinos.raven_notifications.notify_expense_claim"
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
		"before_validate": ["alpinos.quotation_validate.before_validate_quotation_alpinos"],
		"validate": [
			"alpinos.quotation_validate.validate_quotation_alpinos",
			"alpinos.qty_flow.quotation_qty_remarks",
		],
	},
	"Opportunity": {
		"validate": ["alpinos.opportunity_validate.validate_opportunity_alpinos"],
	},
	"Stock Entry": {
		"before_insert": "alpinos.stock_entry_hooks.set_entry_by",
	},
	"Pick List": {
		"before_validate": "alpinos.pick_list_hooks.before_validate_pick_list",
		"validate": [
			"alpinos.pick_list_hooks.validate_pick_list",
			"alpinos.expiry_validation.validate_expiry_on_pick_list",
			"alpinos.qty_flow.pick_list_qty_remarks",
		],
		"after_insert": [
			"alpinos.workflow_engine.pick_list_after_insert",
			"alpinos.stock_reservation.reserve_for_pick_list",
		],
		"on_update": "alpinos.workflow_engine.pick_list_on_update",
		"on_submit": "alpinos.workflow_engine.pick_list_on_submit",
		"on_cancel": [
			"alpinos.workflow_engine.pick_list_on_cancel",
			"alpinos.stock_reservation.release_for_cancelled_pick_list",
		],
	},
	"Delivery Note": {
		"before_validate": "alpinos.delivery_note_hooks.strip_non_batch_item_batches",
		"validate": [
			"alpinos.delivery_note_hooks.validate_delivery_note",
			"alpinos.expiry_validation.validate_expiry_on_delivery_note",
			"alpinos.qty_flow.delivery_note_qty_remarks",
		],
		"after_insert": "alpinos.workflow_engine.delivery_note_after_insert",
		"on_submit": [
			"alpinos.workflow_engine.delivery_note_on_submit",
			"alpinos.stock_reservation.release_leftover_after_delivery_note",
		],
		"on_cancel": "alpinos.workflow_engine.delivery_note_on_cancel",
	},
	"Batch": {
		"before_validate": "alpinos.batch_hooks.compute_expiry_from_shelf_life",
	},
	"Item": {
		"before_insert": "alpinos.item_sequence.reorder_on_insert",
		"before_save": "alpinos.item_sequence.reorder_on_save",
		"validate": "alpinos.product_bundle_sync.force_bundle_non_stock",
		"on_update": "alpinos.product_bundle_sync.sync_item_product_bundle",
	},
	"File": {
		"after_insert": "alpinos.product_sale_files.make_product_sale_file_public",
	},
	"Sales Order": {
		"validate": [
			"alpinos.sales_order_offline_buyer.validate_sales_order_offline_buyer_customer",
			"alpinos.sales_order_offline_buyer.sync_sales_order_offline_buyer_fields",
			"alpinos.sales_order_api.validate_sales_order_pricing",
			"alpinos.sales_order_api.validate_so_freebies_and_box_multiples",
			"alpinos.dispatch_date_utils.validate_dispatch_date_on_save",
			"alpinos.workflow_engine.sales_order_validate",
			"alpinos.qty_flow.sales_order_qty_remarks",
		],
		"on_submit": "alpinos.workflow_engine.sales_order_on_submit",
		"on_cancel": "alpinos.workflow_engine.sales_order_on_cancel",
	},
	"Employee Onboarding": {
		"before_validate": [
			"alpinos.employee_onboarding_automation.allow_hr_manager_to_save_without_mandatory_fields",
			"alpinos.employee_onboarding_webform.prepare_webform_temp_onboarding",
		],
		"validate": [
			"alpinos.employee_onboarding_automation.populate_from_job_applicant",
			"alpinos.designation_branch_policy.autofill_onboarding_policy",
			"alpinos.employee_onboarding_automation.calculate_probation_end_date",
			"alpinos.employee_onboarding_automation.validate_date_of_birth"
		],
		"before_save": [
			"alpinos.employee_onboarding_automation.populate_from_job_applicant",
			"alpinos.employee_onboarding_automation.handle_pre_onboarding_workflow"
		],
		"after_insert": [
			"alpinos.employee_onboarding_webform.process_webform_submission"
		],
		"on_update": [
			"alpinos.employee_onboarding_automation.handle_workflow_transition"
		]
	},
	"Employee": {
		"validate": "alpinos.employee_probation_automation.calculate_probation_end_date",
		"on_update": [
			"alpinos.approval_access.grant_rm_role_for_employee",
		]
	},
	"Work From Home Request": {
		"before_insert": "alpinos.work_from_home_request_automation.auto_populate_employee_and_approver",
		"validate": [
			"alpinos.work_from_home_request_automation.auto_populate_employee_and_approver",
			"alpinos.work_from_home_request_automation.enforce_single_day",
		],
		"before_save": [
			"alpinos.work_from_home_request_automation.auto_populate_employee_and_approver",
			"alpinos.work_from_home_request_automation.enforce_single_day",
		],
		"on_update": "alpinos.raven_notifications.notify_work_from_home"
	},
	"Attendance Request": {
		"validate": "alpinos.attendance_request_automation.set_reporting_person",
		"on_submit": "alpinos.raven_notifications.notify_attendance_request"
	},
	"Attendance": {
		"validate": [
			"alpinos.attendance_request_automation.validate_saturday_attendance_threshold",
			"alpinos.attendance_request_automation.mark_half_day_absent_below_threshold"
		],
		"after_insert": "alpinos.attendance_request_automation.populate_attendance_reason_after_insert",
		"after_submit": "alpinos.attendance_request_automation.populate_attendance_reason_after_submit"
	}
}

# Scheduled Tasks
# ---------------

scheduler_events = {
	"daily": [
		"alpinos.employee_onboarding_automation.send_scheduled_pre_onboarding_emails",
		"alpinos.approval_access.sync_reporting_manager_roles",
		"alpinos.workflow_engine.refresh_todays_dispatch"
	],
	"cron": {
		"*/5 * * * *": [
			"alpinos.essl_sync.sync_essl_logs"
		],
		"*/30 * * * *": [
			"alpinos.attendance_scheduler.process_auto_attendance_periodic"
		],
		"30 11 * * *": [
			"alpinos.attendance_alerts.notify_missing_checkins"
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


from alpinos.quotation_obm_patch import apply_quotation_obm_customer_patch

apply_quotation_obm_customer_patch()
