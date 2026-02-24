"""
Workflow for Attendance Request: Draft -> Send for Approval -> Submit
- Employee saves as Draft, then sends for approval
- HR Manager receives and submits the request
- HR only sees requests when status is "Send for Approval" (approval queue)
"""

import frappe
from frappe import _


def get_permission_query_conditions(user=None, doctype=None):
	"""
	Restrict list view for HR Manager: only show Attendance Request when status is "Send for Approval".
	Employees see their own (standard permissions); HR Manager sees only the approval queue.
	"""
	user = user or frappe.session.user
	doctype = doctype or "Attendance Request"

	roles = frappe.get_roles(user)

	# HR Manager (and HR User) see "Send for Approval" (pending) and "Submit" (submitted) requests
	if "System Manager" in roles:
		return None  # System Manager sees all
	if "HR Manager" in roles or "HR User" in roles:
		return "`tabAttendance Request`.status in ('Send for Approval', 'Submit')"

	return None


def create_workflow_states():
	"""Create Workflow State master records for Attendance Request workflow"""
	workflow_states = [
		"Draft",
		"Send for Approval",
		"Submit",
	]
	for state_name in workflow_states:
		if not frappe.db.exists("Workflow State", state_name):
			try:
				frappe.get_doc({
					"doctype": "Workflow State",
					"workflow_state_name": state_name,
					"icon": "",
					"style": ""
				}).insert(ignore_permissions=True)
				frappe.db.commit()
				print(f"✅ Created Workflow State: {state_name}")
			except Exception as e:
				print(f"⚠️  Could not create Workflow State {state_name}: {str(e)}")


def create_workflow_actions():
	"""Create Workflow Action Master records for Attendance Request workflow"""
	workflow_actions = [
		"Send for Approval",
		"Submit",
	]
	for action_name in workflow_actions:
		if not frappe.db.exists("Workflow Action Master", action_name):
			try:
				frappe.get_doc({
					"doctype": "Workflow Action Master",
					"workflow_action_name": action_name
				}).insert(ignore_permissions=True)
				frappe.db.commit()
				print(f"✅ Created Workflow Action: {action_name}")
			except Exception as e:
				print(f"⚠️  Could not create Workflow Action {action_name}: {str(e)}")


def set_status_field_allow_on_submit():
	"""Set allow_on_submit = 1 for status field (required for workflow)"""
	try:
		# Status may be a custom field; try DocField first (if added to core), then Custom Field
		field = frappe.db.get_value(
			"DocField",
			{"parent": "Attendance Request", "fieldname": "status"},
			"name"
		)
		if field:
			doc = frappe.get_doc("DocField", {"parent": "Attendance Request", "fieldname": "status"})
			if not doc.allow_on_submit:
				doc.allow_on_submit = 1
				doc.save(ignore_permissions=True)
				frappe.db.commit()
				print("✅ Attendance Request status field: allow_on_submit = 1")
		# Custom fields get allow_on_submit from our add_attendance_request_workflow_status_field
	except Exception as e:
		print(f"⚠️  Could not set status allow_on_submit: {str(e)}")


def setup_attendance_request_workflow():
	"""Create workflow for Attendance Request: Draft -> Send for Approval -> Submit"""
	workflow_name = "Attendance Request Workflow"
	doctype = "Attendance Request"

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
			"allow_edit": "Employee",
			"send_email": 0
		},
		{
			"state": "Send for Approval",
			"doc_status": "0",
			"update_field": "status",
			"update_value": "Send for Approval",
			"is_optional_state": 0,
			"next_action_email_template": "",
			"allow_edit": "HR Manager",
			"send_email": 1
		},
		{
			"state": "Submit",
			"doc_status": "1",
			"update_field": "status",
			"update_value": "Submit",
			"is_optional_state": 0,
			"next_action_email_template": "",
			"allow_edit": "HR Manager",
			"send_email": 0
		},
	]

	transitions = [
		{
			"state": "Draft",
			"action": "Send for Approval",
			"next_state": "Send for Approval",
			"allowed": "Employee",
			"allow_self_approval": 1,  # Employee (doc owner) must be able to send their own request
			"condition": "",
			"send_email_to_creator": 0
		},
		{
			"state": "Send for Approval",
			"action": "Submit",
			"next_state": "Submit",
			"allowed": "HR Manager",
			"allow_self_approval": 0,
			"condition": "",
			"send_email_to_creator": 1
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

	print(f"✅ Created Workflow: {workflow_name} for {doctype}")


def execute():
	"""Run Attendance Request workflow setup"""
	try:
		create_workflow_states()
		create_workflow_actions()
		set_status_field_allow_on_submit()
		frappe.clear_cache()
		setup_attendance_request_workflow()
		frappe.clear_cache()
		print("✅ Attendance Request Workflow setup completed successfully!")
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Attendance Request Workflow Setup Error")
		raise
