import frappe

def get_context(context):
	"""Populate the web-form context from the `onboarding` URL parameter."""
	# Frappe reserves `name` for doc edit/view, so the param is `onboarding`.
	employee_onboarding_name = frappe.form_dict.get('onboarding')
	
	if employee_onboarding_name:
		context.employee_onboarding_name = employee_onboarding_name
		
		if frappe.db.exists("Employee Onboarding", employee_onboarding_name):
			onboarding_doc = frappe.get_doc("Employee Onboarding", employee_onboarding_name)
			
			if onboarding_doc.get('webform_submitted'):
				context.already_submitted = True
				context.submitted_on = onboarding_doc.get('webform_submitted_on')
			else:
				context.already_submitted = False
		else:
			context.invalid_reference = True
	else:
		context.missing_reference = True

