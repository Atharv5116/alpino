import frappe

def get_context(context):
	"""
	Get context for webform
	Extract employee_onboarding_name from URL parameter and set it in context
	"""
	# Get the name parameter from URL
	employee_onboarding_name = frappe.form_dict.get('name')
	
	if employee_onboarding_name:
		context.employee_onboarding_name = employee_onboarding_name
		
		# Validate that Employee Onboarding exists
		if frappe.db.exists("Employee Onboarding", employee_onboarding_name):
			onboarding_doc = frappe.get_doc("Employee Onboarding", employee_onboarding_name)
			
			# Check if already submitted
			if onboarding_doc.get('webform_submitted'):
				context.already_submitted = True
				context.submitted_on = onboarding_doc.get('webform_submitted_on')
			else:
				context.already_submitted = False
		else:
			context.invalid_reference = True
	else:
		context.missing_reference = True

