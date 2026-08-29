"""Approval workflow setup for Job Requisition."""

import frappe
from frappe import _


def create_required_roles():
	required_roles = [
		{
			"role_name": "Reporting Manager",
			"desk_access": 1,
			"is_custom": 1
		},
		{
			"role_name": "HOD",
			"desk_access": 1,
			"is_custom": 1
		},
		{
			"role_name": "HR Manager",
			"desk_access": 1,
			"is_custom": 1
		}
	]
	
	for role_data in required_roles:
		if not frappe.db.exists("Role", role_data["role_name"]):
			try:
				role_doc = frappe.get_doc({
					"doctype": "Role",
					**role_data
				})
				role_doc.insert(ignore_permissions=True)
				frappe.db.commit()
				print(f"✅ Created role: {role_data['role_name']}")
			except Exception as e:
				print(f"⚠️  Could not create role {role_data['role_name']}: {str(e)}")


def create_workflow_actions():
	workflow_actions = [
		"Submit for Approval",
		"Approve",
		"Approve (Skip HOD)",
		"Live",
		"Reject",
		"Return to Requestor",
		"Put on Hold",
		"Resume",
		"Resume to HOD",
		"Resume to HR",
		"Resubmit"
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


def create_workflow_states():
	workflow_states = [
		"Draft",
		"Pending Reporting Manager Approval",
		"Pending HOD Approval",
		"Pending HR Approval",
		"Live",
		"Rejected",
		"Returned to Requestor",
		"On Hold"
	]
	
	created_count = 0
	existing_count = 0
	failed_states = []
	
	for state_name in workflow_states:
		if not frappe.db.exists("Workflow State", state_name):
			try:
				state_doc = frappe.get_doc({
					"doctype": "Workflow State",
					"workflow_state_name": state_name,
					"icon": "",
					"style": ""  # valid: "", Primary, Info, Success, Warning, Danger, Inverse
				})
				state_doc.insert(ignore_permissions=True)
				frappe.db.commit()
				created_count += 1
				print(f"✅ Created Workflow State: {state_name}")
			except Exception as e:
				error_msg = str(e)
				print(f"⚠️  Could not create Workflow State {state_name}: {error_msg}")
				failed_states.append((state_name, error_msg))
				# collect all failures before raising
		else:
			existing_count += 1
			print(f"ℹ️  Workflow State {state_name} already exists")
	
	if failed_states:
		error_details = "\n".join([f"  - {name}: {error}" for name, error in failed_states])
		raise Exception(
			f"Failed to create {len(failed_states)} Workflow State(s):\n{error_details}\n"
			f"Created: {created_count}, Existing: {existing_count}, Failed: {len(failed_states)}"
		)
	
	print(f"✅ Workflow States: {created_count} created, {existing_count} already existed")


def update_status_field_options():
	status_options = (
		"Draft\n"
		"Pending Reporting Manager Approval\n"
		"Pending HOD Approval\n"
		"Pending HR Approval\n"
		"Live\n"
		"Rejected\n"
		"Returned to Requestor\n"
		"On Hold"
	)
	
	try:
		field = frappe.get_doc("DocField", {"parent": "Job Requisition", "fieldname": "status"})
		if field:
			field.options = status_options
			field.save(ignore_permissions=True)
			frappe.db.commit()
			print("✅ Updated status field options")
	except Exception as e:
		print(f"⚠️  Could not update status field: {str(e)}")
		try:
			from alpinos.patches.v1_0.update_job_requisition_fields import update_property_setter
			update_property_setter("Job Requisition", "status", "options", status_options, "Text")
			print("✅ Updated status field options via property setter")
		except Exception as e2:
			print(f"⚠️  Could not update status field via property setter: {str(e2)}")
		else:
			print(f"ℹ️  Role {role_data['role_name']} already exists")


def setup_job_requisition_workflow():
	
	workflow_name = "Job Requisition Approval Workflow"
	doctype = "Job Requisition"

	if frappe.db.exists("Workflow", workflow_name):
		frappe.delete_doc("Workflow", workflow_name, force=1, ignore_permissions=True)
		frappe.db.commit()

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
			"state": "Pending Reporting Manager Approval",
			"doc_status": "0",
			"update_field": "status",
			"update_value": "Pending Reporting Manager Approval",
			"is_optional_state": 0,
			"next_action_email_template": "",
			"allow_edit": "Reporting Manager",
			"send_email": 1
		},
		{
			"state": "Pending HOD Approval",
			"doc_status": "0",
			"update_field": "status",
			"update_value": "Pending HOD Approval",
			"is_optional_state": 0,
			"next_action_email_template": "",
			"allow_edit": "HOD",
			"send_email": 1
		},
		{
			"state": "Pending HR Approval",
			"doc_status": "0",
			"update_field": "status",
			"update_value": "Pending HR Approval",
			"is_optional_state": 0,
			"next_action_email_template": "",
			"allow_edit": "HR Manager",
			"send_email": 1
		},
		{
			"state": "Live",
			"doc_status": "1",
			"update_field": "status",
			"update_value": "Live",
			"is_optional_state": 0,
			"next_action_email_template": "",
			"allow_edit": "HR Manager",
			"send_email": 0
		},
		{
			"state": "Rejected",
			"doc_status": "0",
			"update_field": "status",
			"update_value": "Rejected",
			"is_optional_state": 0,
			"next_action_email_template": "",
			"allow_edit": "All",
			"send_email": 1
		},
		{
			"state": "Returned to Requestor",
			"doc_status": "0",
			"update_field": "status",
			"update_value": "Returned to Requestor",
			"is_optional_state": 0,
			"next_action_email_template": "",
			"allow_edit": "All",
			"send_email": 1
		},
		{
			"state": "On Hold",
			"doc_status": "0",
			"update_field": "status",
			"update_value": "On Hold",
			"is_optional_state": 0,
			"next_action_email_template": "",
			"allow_edit": "HR Manager",
			"send_email": 1
		}
	]
	
	transitions = [
		# forward flow
		{
			"state": "Draft",
			"action": "Submit for Approval",
			"next_state": "Pending Reporting Manager Approval",
			"allowed": "All",
			"allow_self_approval": 1,
			"condition": "",
			"send_email_to_creator": 0
		},
		{
			"state": "Pending Reporting Manager Approval",
			"action": "Approve",
			"next_state": "Pending HOD Approval",
			"allowed": "Reporting Manager",
			"allow_self_approval": 1,
			"condition": "",
			"send_email_to_creator": 1
		},
		{
			"state": "Pending Reporting Manager Approval",
			"action": "Approve (Skip HOD)",
			"next_state": "Pending HR Approval",
			"allowed": "Reporting Manager",
			"allow_self_approval": 1,
			"condition": "",
			"send_email_to_creator": 1
		},
		{
			"state": "Pending HOD Approval",
			"action": "Approve",
			"next_state": "Pending HR Approval",
			"allowed": "HOD",
			"allow_self_approval": 0,
			"condition": "",
			"send_email_to_creator": 1
		},
		{
			"state": "Pending HR Approval",
			"action": "Live",
			"next_state": "Live",
			"allowed": "HR Manager",
			"allow_self_approval": 1,
			"condition": "",
			"send_email_to_creator": 0
		},

		# rejections
		{
			"state": "Pending Reporting Manager Approval",
			"action": "Reject",
			"next_state": "Rejected",
			"allowed": "Reporting Manager",
			"allow_self_approval": 1,
			"condition": "",
			"send_email_to_creator": 1
		},
		{
			"state": "Pending HOD Approval",
			"action": "Reject",
			"next_state": "Rejected",
			"allowed": "HOD",
			"allow_self_approval": 0,
			"condition": "",
			"send_email_to_creator": 1
		},
		{
			"state": "Pending HR Approval",
			"action": "Reject",
			"next_state": "Rejected",
			"allowed": "HR Manager",
			"allow_self_approval": 0,
			"condition": "",
			"send_email_to_creator": 1
		},

		# return to requestor
		{
			"state": "Pending Reporting Manager Approval",
			"action": "Return to Requestor",
			"next_state": "Returned to Requestor",
			"allowed": "Reporting Manager",
			"allow_self_approval": 1,
			"condition": "",
			"send_email_to_creator": 1
		},
		{
			"state": "Pending HOD Approval",
			"action": "Return to Requestor",
			"next_state": "Returned to Requestor",
			"allowed": "HOD",
			"allow_self_approval": 0,
			"condition": "",
			"send_email_to_creator": 1
		},
		{
			"state": "Pending HR Approval",
			"action": "Return to Requestor",
			"next_state": "Returned to Requestor",
			"allowed": "HR Manager",
			"allow_self_approval": 0,
			"condition": "",
			"send_email_to_creator": 1
		},

		# on hold
		{
			"state": "Pending Reporting Manager Approval",
			"action": "Put on Hold",
			"next_state": "On Hold",
			"allowed": "Reporting Manager",
			"allow_self_approval": 1,
			"condition": "",
			"send_email_to_creator": 1
		},
		{
			"state": "Pending HOD Approval",
			"action": "Put on Hold",
			"next_state": "On Hold",
			"allowed": "HOD",
			"allow_self_approval": 0,
			"condition": "",
			"send_email_to_creator": 1
		},
		{
			"state": "Pending HR Approval",
			"action": "Put on Hold",
			"next_state": "On Hold",
			"allowed": "HR Manager",
			"allow_self_approval": 1,
			"condition": "",
			"send_email_to_creator": 1
		},
		# resume from hold
		{
			"state": "On Hold",
			"action": "Resume",
			"next_state": "Pending Reporting Manager Approval",
			"allowed": "HR Manager",
			"allow_self_approval": 1,
			"condition": "",
			"send_email_to_creator": 1
		},
		{
			"state": "On Hold",
			"action": "Resume to HOD",
			"next_state": "Pending HOD Approval",
			"allowed": "HR Manager",
			"allow_self_approval": 1,
			"condition": "",
			"send_email_to_creator": 1
		},
		{
			"state": "On Hold",
			"action": "Resume to HR",
			"next_state": "Pending HR Approval",
			"allowed": "HR Manager",
			"allow_self_approval": 1,
			"condition": "",
			"send_email_to_creator": 1
		},

		# resubmit after return
		{
			"state": "Returned to Requestor",
			"action": "Resubmit",
			"next_state": "Pending Reporting Manager Approval",
			"allowed": "All",
			"allow_self_approval": 1,
			"condition": "",
			"send_email_to_creator": 0
		}
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


def verify_workflow_states_exist():
	required_states = [
		"Draft",
		"Pending Reporting Manager Approval",
		"Pending HOD Approval",
		"Pending HR Approval",
		"Approved",
		"Live",
		"Rejected",
		"Returned to Requestor",
		"On Hold"
	]
	
	missing_states = []
	for state_name in required_states:
		if not frappe.db.exists("Workflow State", state_name):
			missing_states.append(state_name)
	
	if missing_states:
		raise Exception(
			f"The following Workflow States are missing and required for workflow: {', '.join(missing_states)}"
		)
	
	print("✅ All required Workflow States exist")


def execute():
	try:
		# states and actions must exist before the workflow references them
		create_workflow_states()
		verify_workflow_states_exist()
		create_workflow_actions()
		update_status_field_options()
		create_required_roles()
		frappe.clear_cache()
		setup_job_requisition_workflow()
		frappe.clear_cache()
		print("\n✅ Job Requisition Workflow setup completed successfully!")
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Job Requisition Workflow Setup Error")
		raise
