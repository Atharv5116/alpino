"""
Workflow Setup for Employee Onboarding
Creates a simple workflow: Draft → Email Sent → Employee Created
"""

import frappe
from frappe import _


def create_workflow_states():
	"""Create Workflow State master records for Employee Onboarding workflow"""
	workflow_states = [
		{"workflow_state_name": "Draft", "style": ""},
		{"workflow_state_name": "Email Sent", "style": "Primary"},
		{"workflow_state_name": "Employee Created", "style": "Success"},
	]

	for state_data in workflow_states:
		name = state_data["workflow_state_name"]
		if not frappe.db.exists("Workflow State", name):
			try:
				doc = frappe.get_doc({"doctype": "Workflow State", **state_data})
				doc.insert(ignore_permissions=True)
				frappe.db.commit()
				print(f"✅ Created Workflow State: {name}")
			except Exception as e:
				print(f"⚠️  Could not create Workflow State {name}: {str(e)}")
		else:
			print(f"ℹ️  Workflow State {name} already exists")


def create_workflow_actions():
	"""Create Workflow Action Master records for Employee Onboarding workflow"""
	actions = [
		"Send Email to Candidate",
		"Create Employee",
	]

	for action_name in actions:
		if not frappe.db.exists("Workflow Action Master", action_name):
			try:
				doc = frappe.get_doc({
					"doctype": "Workflow Action Master",
					"workflow_action_name": action_name,
				})
				doc.insert(ignore_permissions=True)
				frappe.db.commit()
				print(f"✅ Created Workflow Action: {action_name}")
			except Exception as e:
				print(f"⚠️  Could not create Workflow Action {action_name}: {str(e)}")
		else:
			print(f"ℹ️  Workflow Action {action_name} already exists")


def setup_employee_onboarding_workflow():
	"""Create the Employee Onboarding workflow"""

	workflow_name = "Employee Onboarding Workflow"
	doctype = "Employee Onboarding"

	# Delete existing workflow if any
	if frappe.db.exists("Workflow", workflow_name):
		frappe.delete_doc("Workflow", workflow_name, force=1, ignore_permissions=True)
		frappe.db.commit()

	# Workflow states
	states = [
		{
			"state": "Draft",
			"doc_status": "0",
			"update_field": "boarding_status",
			"update_value": "Draft",
			"is_optional_state": 0,
			"allow_edit": "HR Manager",
			"send_email": 0,
		},
		{
			"state": "Email Sent",
			"doc_status": "0",
			"update_field": "boarding_status",
			"update_value": "Email Sent",
			"is_optional_state": 0,
			"allow_edit": "HR Manager",
			"send_email": 0,
		},
		{
			"state": "Employee Created",
			"doc_status": "0",
			"update_field": "boarding_status",
			"update_value": "Employee Created",
			"is_optional_state": 0,
			"allow_edit": "HR Manager",
			"send_email": 0,
		},
	]

	# Workflow transitions
	transitions = [
		{
			"state": "Draft",
			"action": "Send Email to Candidate",
			"next_state": "Email Sent",
			"allowed": "HR Manager",
			"allow_self_approval": 1,
			"condition": "",
		},
		{
			"state": "Email Sent",
			"action": "Create Employee",
			"next_state": "Employee Created",
			"allowed": "HR Manager",
			"allow_self_approval": 1,
			"condition": "",
		},
	]

	# Create workflow
	workflow_doc = frappe.get_doc({
		"doctype": "Workflow",
		"workflow_name": workflow_name,
		"document_type": doctype,
		"is_active": 1,
		"override_status": 0,
		"workflow_state_field": "boarding_status",
		"send_email_alert": 0,
	})

	for state_data in states:
		workflow_doc.append("states", state_data)

	for transition_data in transitions:
		workflow_doc.append("transitions", transition_data)

	workflow_doc.insert(ignore_permissions=True)
	frappe.db.commit()

	print(f"✅ Created Workflow: {workflow_name}")
	print(f"   - States: {len(states)}")
	print(f"   - Transitions: {len(transitions)}")

	return workflow_doc.name


def update_boarding_status_options():
	"""Update boarding_status field options to match the new workflow states.
	This ensures 'Draft', 'Email Sent', 'Employee Created' are valid values."""
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	new_options = "Draft\nEmail Sent\nEmployee Created"

	# Update options via property setter
	try:
		existing = frappe.db.exists(
			"Property Setter",
			{"doc_type": "Employee Onboarding", "field_name": "boarding_status", "property": "options"}
		)
		if existing:
			ps = frappe.get_doc("Property Setter", existing)
			ps.value = new_options
			ps.save(ignore_permissions=True)
		else:
			ps = frappe.get_doc({
				"doctype": "Property Setter",
				"doctype_or_field": "DocField",
				"doc_type": "Employee Onboarding",
				"field_name": "boarding_status",
				"property": "options",
				"value": new_options,
				"property_type": "Text",
			})
			ps.insert(ignore_permissions=True)
		frappe.db.commit()
		print(f"✅ Updated boarding_status options: {new_options.replace(chr(10), ', ')}")
	except Exception as e:
		print(f"⚠️  Could not update boarding_status options: {str(e)}")

	# Update default value
	try:
		existing = frappe.db.exists(
			"Property Setter",
			{"doc_type": "Employee Onboarding", "field_name": "boarding_status", "property": "default"}
		)
		if existing:
			ps = frappe.get_doc("Property Setter", existing)
			ps.value = "Draft"
			ps.save(ignore_permissions=True)
		else:
			ps = frappe.get_doc({
				"doctype": "Property Setter",
				"doctype_or_field": "DocField",
				"doc_type": "Employee Onboarding",
				"field_name": "boarding_status",
				"property": "default",
				"value": "Draft",
				"property_type": "Data",
			})
			ps.insert(ignore_permissions=True)
		frappe.db.commit()
		print("✅ Updated boarding_status default to 'Draft'")
	except Exception as e:
		print(f"⚠️  Could not update boarding_status default: {str(e)}")


def execute():
	"""Execute Employee Onboarding workflow setup"""
	try:
		# Step 1: Update boarding_status field options FIRST
		update_boarding_status_options()

		# Step 2: Create workflow states
		create_workflow_states()

		# Step 3: Create workflow actions
		create_workflow_actions()

		# Step 4: Clear cache so meta is fresh
		frappe.clear_cache()

		# Step 5: Create the workflow
		setup_employee_onboarding_workflow()

		frappe.clear_cache()
		print("\n✅ Employee Onboarding Workflow setup completed!")
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Employee Onboarding Workflow Setup Error")
		raise

