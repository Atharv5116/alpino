"""
Patch to create Job Application Workflow
Creates workflow for Job Applicant with states: Draft, Submitted, New Application, Rejected, Archived
Based on Application Status Management requirements
"""

import frappe
from frappe import _


def create_job_applicant_workflow_states():
	"""Create Workflow State master records for Job Applicant workflow"""
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
	"""Create Workflow Action Master records for Job Applicant workflow"""
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


def update_job_applicant_status_options():
	"""Update status field options to match workflow states"""
	status_options = (
		"Draft\n"
		"Submitted\n"
		"New Application\n"
		"Rejected\n"
		"Archived"
	)
	
	try:
		# Get the field
		field = frappe.get_doc("DocField", {"parent": "Job Applicant", "fieldname": "status"})
		if field:
			field.options = status_options
			field.save(ignore_permissions=True)
			frappe.db.commit()
			print("✅ Updated status field options")
	except Exception as e:
		print(f"⚠️  Could not update status field: {str(e)}")
		# Try using property setter as fallback
		try:
			from alpinos.patches.v1_0.update_job_applicant_fields import update_property_setter
			update_property_setter("Job Applicant", "status", "options", status_options, "Text")
			print("✅ Updated status field options via property setter")
		except Exception as e2:
			print(f"⚠️  Could not update status field via property setter: {str(e2)}")


def make_job_applicant_submittable():
	"""Make Job Applicant submittable (required for workflow)"""
	try:
		doc_type = frappe.get_doc("DocType", "Job Applicant")
		if not doc_type.is_submittable:
			doc_type.is_submittable = 1
			# Manually add amended_from field if it doesn't exist
			doc_type.make_amendable()
			doc_type.save(ignore_permissions=True)
			frappe.db.commit()
			print("✅ Made Job Applicant submittable")
		else:
			print("ℹ️  Job Applicant is already submittable")
			# Still ensure amended_from exists
			doc_type.make_amendable()
			if doc_type.has_value_changed("fields"):
				doc_type.save(ignore_permissions=True)
				frappe.db.commit()
	except Exception as e:
		print(f"⚠️  Could not make Job Applicant submittable: {str(e)}")


def update_status_field_allow_on_submit():
	"""Set allow_on_submit = 1 for status field (required for workflow)"""
	try:
		status_field = frappe.get_doc("DocField", {"parent": "Job Applicant", "fieldname": "status"})
		if not status_field.allow_on_submit:
			status_field.allow_on_submit = 1
			status_field.save(ignore_permissions=True)
			frappe.db.commit()
			print("✅ Updated status field - allow_on_submit: 1")
	except Exception as e:
		print(f"⚠️  Could not update status field allow_on_submit: {str(e)}")


def setup_job_applicant_workflow():
	"""Create workflow for Job Applicant application process"""
	
	workflow_name = "Job Application Workflow"
	doctype = "Job Applicant"
	
	# Delete existing workflow if any
	if frappe.db.exists("Workflow", workflow_name):
		frappe.delete_doc("Workflow", workflow_name, force=1, ignore_permissions=True)
		frappe.db.commit()
	
	# Define workflow states
	states = [
		{
			"state": "Draft",
			"doc_status": "0",  # Saved (not submitted)
			"update_field": "status",
			"update_value": "Draft",
			"is_optional_state": 0,
			"next_action_email_template": "",
			"allow_edit": "All",  # All can edit
			"send_email": 0
		},
		{
			"state": "Submitted",
			"doc_status": "1",  # Submitted
			"update_field": "status",
			"update_value": "Submitted",
			"is_optional_state": 0,
			"next_action_email_template": "",
			"allow_edit": "HR User",  # Only HR can edit after submission
			"send_email": 1
		},
		{
			"state": "New Application",
			"doc_status": "1",  # Submitted - available for HR review
			"update_field": "status",
			"update_value": "New Application",
			"is_optional_state": 0,
			"next_action_email_template": "",
			"allow_edit": "HR User",  # HR can review and take action
			"send_email": 1
		},
		{
			"state": "Rejected",
			"doc_status": "2",  # Cancelled (rejected)
			"update_field": "status",
			"update_value": "Rejected",
			"is_optional_state": 0,
			"next_action_email_template": "",
			"allow_edit": "HR User",
			"send_email": 1
		},
		{
			"state": "Archived",
			"doc_status": "1",  # Submitted (archived but still submitted)
			"update_field": "status",
			"update_value": "Archived",
			"is_optional_state": 0,
			"next_action_email_template": "",
			"allow_edit": "HR User",
			"send_email": 0
		},
	]
	
	# Define workflow transitions
	transitions = [
		# Draft → Submitted
		{
			"state": "Draft",
			"action": "Submit Application",
			"next_state": "Submitted",
			"allowed": "All",  # Candidate/User can submit
			"allow_self_approval": 1,
			"condition": "",
			"send_email_to_creator": 0
		},
		# Submitted → New Application (automatic review/approval)
		{
			"state": "Submitted",
			"action": "Review",
			"next_state": "New Application",
			"allowed": "HR User",
			"allow_self_approval": 0,
			"condition": "",
			"send_email_to_creator": 1
		},
		# New Application → Rejected
		{
			"state": "New Application",
			"action": "Reject",
			"next_state": "Rejected",
			"allowed": "HR User",
			"allow_self_approval": 0,
			"condition": "",
			"send_email_to_creator": 1
		},
		# New Application → Archived
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
	
	# Create workflow document
	workflow_doc = frappe.get_doc({
		"doctype": "Workflow",
		"workflow_name": workflow_name,
		"document_type": doctype,
		"is_active": 1,
		"override_status": 1,  # Override status field with workflow state
		"workflow_state_field": "status",  # Use existing status field
		"send_email_alert": 1  # Send email alerts
	})
	
	# Add states
	for state_data in states:
		workflow_doc.append("states", state_data)
	
	# Add transitions
	for transition_data in transitions:
		workflow_doc.append("transitions", transition_data)
	
	# Insert workflow
	workflow_doc.insert(ignore_permissions=True)
	frappe.db.commit()
	
	print(f"✅ Created Workflow: {workflow_name}")
	print(f"   - Document Type: {doctype}")
	print(f"   - States: {len(states)}")
	print(f"   - Transitions: {len(transitions)}")
	
	return workflow_doc.name


def execute():
	"""Execute workflow setup"""
	try:
		# Step 1: Make Job Applicant submittable (required for workflow)
		make_job_applicant_submittable()
		
		# Step 2: Create Workflow State master records FIRST
		create_job_applicant_workflow_states()
		
		# Step 3: Create Workflow Action Master records
		create_job_applicant_workflow_actions()
		
		# Step 4: Update status field options
		update_job_applicant_status_options()
		
		# Step 5: Make status field allow_on_submit = 1 (required for workflow)
		update_status_field_allow_on_submit()
		
		# Step 6: Clear cache
		frappe.clear_cache()
		
		# Step 7: Create workflow
		setup_job_applicant_workflow()
		
		frappe.clear_cache()
		print("\n✅ Job Applicant Workflow setup completed successfully!")
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Job Applicant Workflow Setup Error")
		raise
