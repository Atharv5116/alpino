app_name = "alpinos"
app_title = "Alpinos Development"
app_publisher = "Hetvi Patel"
app_description = "All the custom development for Alpinos"
app_email = "hetvipatel2302@gmail.com"
app_license = "mit"

# Only list callables that exist under alpinos/ (missing modules break bench migrate).
after_migrate = [
	"alpinos.custom_fields.setup_custom_fields",
	"alpinos.pick_list_custom_fields.setup_pick_list_alpinos_fields",
	"alpinos.workflow_setup.execute",
	"alpinos.web_form_update.execute",
]

doc_events = {
	"Job Requisition": {
		"before_save": "alpinos.job_requisition_automation.update_approval_fields",
		"on_update": [
			"alpinos.job_requisition_automation.create_published_job_opening_on_live",
			"alpinos.job_requisition_automation.sync_status_with_job_opening",
		],
	},
	"Job Applicant": {
		"before_insert": [
			"alpinos.job_applicant_automation.generate_candidate_id",
			"alpinos.job_applicant_automation.set_default_status",
			"alpinos.job_applicant_automation.set_application_date",
			"alpinos.job_applicant_automation.handle_web_form_submission",
		],
		"before_save": [
			"alpinos.job_applicant_automation.auto_populate_from_job_requisition",
			"alpinos.job_applicant_automation.auto_populate_from_job_opening",
			"alpinos.job_applicant_automation.validate_job_requisition_open",
			"alpinos.job_applicant_automation.validate_job_opening_open",
			"alpinos.job_applicant_automation.handle_web_form_submission",
		],
		"validate": [
			"alpinos.job_applicant_automation.validate_mandatory_fields",
			"alpinos.job_applicant_automation.validate_resume_file_type",
		],
		"after_insert": [
			"alpinos.job_applicant_automation.process_web_form_submission",
		],
		"on_submit": [
			"alpinos.job_applicant_automation.update_status_on_submit",
		],
		"after_submit": [
			"alpinos.job_applicant_automation.update_status_after_submit",
		],
	},
	"Delivery Note": {
		"validate": "alpinos.delivery_note_hooks.validate_delivery_note",
	},
	"Pick List": {
		"validate": "alpinos.pick_list_hooks.validate_pick_list",
	},
}

fixtures = [
	"Custom Field",
	"Property Setter",
]
