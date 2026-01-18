"""
Patch to create Job Application Workflow
Creates workflow for Job Applicant with states: New Application, Rejected, Archived
"""

import frappe


def execute():
	"""Execute patch to create Job Application Workflow"""
	
	workflow_name = "Job Application Workflow"
	doctype = "Job Applicant"
	
	# Check if workflow already exists - if so, skip creation
	if frappe.db.exists("Workflow", workflow_name):
		print(f"ℹ️  Workflow '{workflow_name}' already exists, skipping creation")
		return
	
	# Define workflow states
	states = [
		{
			"state": "New Application",
			"doc_status": "0",  # Saved (not submitted)
			"update_field": "status",
			"update_value": "New Application",
			"is_optional_state": 0,
			"next_action_email_template": "",
			"allow_edit": "All",
			"send_email": 0
		},
		{
			"state": "Rejected",
			"doc_status": "0",  # Saved (not submitted)
			"update_field": "status",
			"update_value": "Rejected",
			"is_optional_state": 0,
			"next_action_email_template": "",
			"allow_edit": "HR User",
			"send_email": 0
		},
		{
			"state": "Archived",
			"doc_status": "0",  # Saved (not submitted)
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
		{
			"state": "New Application",
			"action": "Reject",
			"next_state": "Rejected",
			"allowed": "HR User",
			"allow_self_approval": 0,
			"condition": "",
			"send_email_to_creator": 0
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
	
	# Create workflow actions if they don't exist
	create_workflow_actions(["Reject", "Archive"])
	
	# Create workflow document
	workflow_doc = frappe.get_doc({
		"doctype": "Workflow",
		"workflow_name": workflow_name,
		"document_type": doctype,
		"is_active": 1,
		"override_status": 0,  # Don't override status field - use separate workflow_state field
		"workflow_state_field": "workflow_state",  # Use workflow_state field (as shown in screenshot)
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


def create_workflow_actions(actions):
	"""Create Workflow Action master records if they don't exist"""
	for action_name in actions:
		if not frappe.db.exists("Workflow Action Master", action_name):
			try:
				action_doc = frappe.get_doc({
					"doctype": "Workflow Action Master",
					"workflow_action_name": action_name,
				})
				action_doc.insert(ignore_permissions=True)
				frappe.db.commit()
				print(f"✅ Created workflow action: {action_name}")
			except Exception as e:
				print(f"⚠️  Could not create workflow action {action_name}: {str(e)}")
		else:
			print(f"ℹ️  Workflow action {action_name} already exists")

