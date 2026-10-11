"""Create the Job Application Workflow (states, actions, transitions)."""

import frappe
from frappe import _


def create_job_applicant_workflow_states():
	workflow_states = [
		"Draft",
		"Submitted",
		"New Application",
		"Rejected",
		"Archived"
	]
	
	created_count = 0
	existing_count = 0
	
	for state_name in workflow_states:
		if not frappe.db.exists("Workflow State", state_name):
			try:
				state_doc = frappe.get_doc({
					"doctype": "Workflow State",
					"workflow_state_name": state_name,
					"icon": "",
					"style": ""
				})
				state_doc.insert(ignore_permissions=True)
				frappe.db.commit()
				created_count += 1
				print(f"✅ Created Workflow State: {state_name}")
			except Exception as e:
				print(f"⚠️  Could not create Workflow State {state_name}: {str(e)}")
				raise
		else:
			existing_count += 1
			print(f"ℹ️  Workflow State {state_name} already exists")
	
	print(f"✅ Workflow States: {created_count} created, {existing_count} already existed")


def create_job_applicant_workflow_actions():
	workflow_actions = [
		"Submit Application",
		"Review",
		"Reject",
		"Archive"
	]
	
	created_count = 0
	existing_count = 0
	
	for action_name in workflow_actions:
		if not frappe.db.exists("Workflow Action Master", action_name):
			try:
				action_doc = frappe.get_doc({
					"doctype": "Workflow Action Master",
					"workflow_action_name": action_name
				})
				action_doc.insert(ignore_permissions=True)
				frappe.db.commit()
				created_count += 1
				print(f"✅ Created Workflow Action: {action_name}")
			except Exception as e:
				print(f"⚠️  Could not create Workflow Action {action_name}: {str(e)}")
				raise
		else:
			existing_count += 1
			print(f"ℹ️  Workflow Action {action_name} already exists")
	
	print(f"✅ Workflow Actions: {created_count} created, {existing_count} already existed")


JOB_APPLICANT_STATUS_OPTIONS = "Draft\nSubmitted\nNew Application\nRejected\nArchived"


def _property_setter(fieldname, prop, value, property_type):
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	make_property_setter(
		"Job Applicant",
		fieldname,
		prop,
		value,
		property_type,
		for_doctype=not fieldname,
		validate_fields_for_doctype=False,
	)


def update_job_applicant_status_options():
	# A Property Setter, not an edit to the DocField: HRMS ships Job Applicant, so a
	# DocField edit is overwritten whenever HRMS updates the doctype (it was, on v16).
	_property_setter("status", "options", JOB_APPLICANT_STATUS_OPTIONS, "Text")
	print("✅ Job Applicant status options set")


def make_job_applicant_submittable():
	"""Job Applicant is submittable here (the Job Application Workflow submits and cancels).

	Stock HRMS ships it non-submittable. Editing the standard DocType record did this
	until v16, whose schema sync resets it; a DocType-level Property Setter plus an
	amended_from Custom Field is the customisation that survives an HRMS update.
	"""
	_property_setter(None, "is_submittable", "1", "Check")
	frappe.clear_cache(doctype="Job Applicant")
	if not frappe.get_meta("Job Applicant").has_field("amended_from"):
		from frappe.custom.doctype.custom_field.custom_field import create_custom_field

		create_custom_field(
			"Job Applicant",
			{
				"fieldname": "amended_from",
				"label": "Amended From",
				"fieldtype": "Link",
				"options": "Job Applicant",
				"read_only": 1,
				"no_copy": 1,
				"print_hide": 1,
				"search_index": 1,
				"insert_after": "upper_range",
			},
		)
	print("✅ Job Applicant submittable")


def update_status_field_allow_on_submit():
	_property_setter("status", "allow_on_submit", "1", "Check")
	print("✅ Job Applicant status allow_on_submit")


# Roles that run applications through the workflow ("Review" / "Reject" / "Archive" are
# HR User transitions). "Submit Application" submits the document and "Reject" cancels it,
# so beyond Write they need Submit and Cancel, which the site's Job Applicant permissions
# (Custom DocPerm, replacing HRMS's own) never granted: every Submit Application by HR
# ended in "does not have doctype access via role permission".
WORKFLOW_ROLES = ("HR User", "HR Manager")


def grant_job_applicant_submit_and_cancel():
	from frappe.permissions import add_permission, update_permission_property

	for role in WORKFLOW_ROLES:
		if not frappe.db.exists(
			"Custom DocPerm", {"parent": "Job Applicant", "role": role, "permlevel": 0, "if_owner": 0}
		):
			add_permission("Job Applicant", role, 0)
		for ptype in ("submit", "cancel"):
			update_permission_property("Job Applicant", role, 0, ptype, 1, validate=False)
	frappe.clear_cache(doctype="Job Applicant")
	print("✅ Job Applicant submit/cancel granted to " + ", ".join(WORKFLOW_ROLES))


def setup_job_applicant_workflow():
	workflow_name = "Job Application Workflow"
	doctype = "Job Applicant"

	if frappe.db.exists("Workflow", workflow_name):
		frappe.delete_doc("Workflow", workflow_name, force=1, ignore_permissions=True)
		frappe.db.commit()

	# doc_status: 0 = saved, 1 = submitted, 2 = cancelled
	states = [
		{
			"state": "Draft",
			"doc_status": "0",
			"update_field": "status",
			"update_value": "Draft",
			"is_optional_state": 0,
			"next_action_email_template": "",
			"allow_edit": "All",
			"send_email": 0
		},
		{
			"state": "Submitted",
			"doc_status": "1",
			"update_field": "status",
			"update_value": "Submitted",
			"is_optional_state": 0,
			"next_action_email_template": "",
			"allow_edit": "HR User",
			"send_email": 1
		},
		{
			"state": "New Application",
			"doc_status": "1",
			"update_field": "status",
			"update_value": "New Application",
			"is_optional_state": 0,
			"next_action_email_template": "",
			"allow_edit": "HR User",
			"send_email": 1
		},
		{
			"state": "Rejected",
			"doc_status": "2",
			"update_field": "status",
			"update_value": "Rejected",
			"is_optional_state": 0,
			"next_action_email_template": "",
			"allow_edit": "HR User",
			"send_email": 1
		},
		{
			"state": "Archived",
			"doc_status": "1",
			"update_field": "status",
			"update_value": "Archived",
			"is_optional_state": 0,
			"next_action_email_template": "",
			"allow_edit": "HR User",
			"send_email": 0
		},
	]

	transitions = [
		{
			"state": "Draft",
			"action": "Submit Application",
			"next_state": "Submitted",
			"allowed": "All",
			"allow_self_approval": 1,
			"condition": "",
			"send_email_to_creator": 0
		},
		{
			"state": "Submitted",
			"action": "Review",
			"next_state": "New Application",
			"allowed": "HR User",
			"allow_self_approval": 0,
			"condition": "",
			"send_email_to_creator": 1
		},
		{
			"state": "New Application",
			"action": "Reject",
			"next_state": "Rejected",
			"allowed": "HR User",
			"allow_self_approval": 0,
			"condition": "",
			"send_email_to_creator": 1
		},
		{
			"state": "New Application",
			"action": "Archive",
			"next_state": "Archived",
			"allowed": "HR User",
			"allow_self_approval": 0,
			"condition": "",
			"send_email_to_creator": 0
		},
	]

	workflow_doc = frappe.get_doc({
		"doctype": "Workflow",
		"workflow_name": workflow_name,
		"document_type": doctype,
		"is_active": 1,
		"override_status": 1,
		"workflow_state_field": "status",
		"send_email_alert": 1
	})

	for state_data in states:
		workflow_doc.append("states", state_data)

	for transition_data in transitions:
		workflow_doc.append("transitions", transition_data)

	workflow_doc.insert(ignore_permissions=True)
	frappe.db.commit()
	
	print(f"✅ Created Workflow: {workflow_name}")
	print(f"   - Document Type: {doctype}")
	print(f"   - States: {len(states)}")
	print(f"   - Transitions: {len(transitions)}")
	
	return workflow_doc.name


def execute():
	try:
		make_job_applicant_submittable()
		# states must exist before the workflow references them
		create_job_applicant_workflow_states()
		create_job_applicant_workflow_actions()
		update_job_applicant_status_options()
		update_status_field_allow_on_submit()
		grant_job_applicant_submit_and_cancel()
		frappe.clear_cache()
		setup_job_applicant_workflow()
		frappe.clear_cache()
		print("\n✅ Job Applicant Workflow setup completed successfully!")
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Job Applicant Workflow Setup Error")
		raise
