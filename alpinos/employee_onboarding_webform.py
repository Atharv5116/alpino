"""
Webform handler for Employee Onboarding Details
Processes webform submissions and updates the Employee Onboarding record
"""

import frappe
from frappe import _
from frappe.utils import now


def process_webform_submission(doc, method=None):
	"""
	Process webform submission for Employee Onboarding Details
	This function is called when the webform is submitted
	"""
	# Check if this is from the employee onboarding webform
	is_webform = False
	
	# Method 1: Check web_form_name attribute
	if hasattr(doc, 'web_form_name') and doc.web_form_name == 'employee-onboarding-details':
		is_webform = True
	
	# Method 2: Check frappe flags
	if not is_webform and hasattr(frappe.flags, 'in_web_form') and frappe.flags.in_web_form:
		# Check if employee_onboarding_name is set (indicates it's our webform)
		if doc.get('employee_onboarding_name'):
			is_webform = True
	
	if not is_webform:
		return
	
	# Get the Employee Onboarding name from the hidden field
	employee_onboarding_name = doc.get('employee_onboarding_name')
	
	if not employee_onboarding_name:
		frappe.throw(_("Employee Onboarding reference is missing. Please use the link provided in your email."))
	
	# Validate that Employee Onboarding exists
	if not frappe.db.exists("Employee Onboarding", employee_onboarding_name):
		frappe.throw(_("Invalid Employee Onboarding reference. Please contact HR."))
	
	# Get the Employee Onboarding document
	onboarding_doc = frappe.get_doc("Employee Onboarding", employee_onboarding_name)
	
	# Check if webform has already been submitted
	if onboarding_doc.get('webform_submitted'):
		# Delete the temporary document that was just created
		try:
			frappe.delete_doc("Employee Onboarding", doc.name, force=1, ignore_permissions=True)
			frappe.db.commit()
		except:
			pass
		frappe.throw(_("This form has already been submitted. Please contact HR if you need to make changes."))
	
	# Map webform fields to Employee Onboarding fields
	field_mapping = {
		# Personal Details
		'date_of_birth': 'date_of_birth',
		'gender': 'gender',
		'blood_group': 'blood_group',
		'physically_handicapped': 'physically_handicapped',
		'nationality': 'nationality',
		'aadhaar_card': 'aadhaar_card',
		'pan_card': 'pan_card',
		'name_as_per_aadhaar': 'name_as_per_aadhaar',
		'name_as_per_pan': 'name_as_per_pan',
		'passport_size_photo': 'passport_size_photo',
		
		# Address Details
		'current_address': 'current_address',
		'current_accommodation_type': 'current_accommodation_type',
		'permanent_address': 'permanent_address',
		'permanent_accommodation_type': 'permanent_accommodation_type',
		
		# Bank Details
		'bank_name': 'bank_name',
		'branch': 'branch',
		'account_number': 'account_number',
		'account_type': 'account_type',
		'ifsc_code': 'ifsc_code',
		'bank_account_proof': 'bank_account_proof',
		
		# Family Details
		'family_name': 'family_name',
		'family_relation': 'family_relation',
		'family_contact_number': 'family_contact_number',
		'family_occupation': 'family_occupation',
		
		# Emergency Contact
		'emergency_contact_name': 'emergency_contact_name',
		'emergency_contact_relation': 'emergency_contact_relation',
		'emergency_contact_number': 'emergency_contact_number',
	}
	
	# Update direct fields
	for webform_field, onboarding_field in field_mapping.items():
		value = doc.get(webform_field)
		if value is not None:
			onboarding_doc.set(onboarding_field, value)
	
	# Handle qualification_child table (append new rows)
	if doc.get('qualification_child'):
		existing_qualifications = onboarding_doc.get('qualification_child', [])
		for qual_row in doc.qualification_child:
			# Create new row in Employee Onboarding
			new_qual = onboarding_doc.append('qualification_child', {})
			new_qual.degree = qual_row.get('degree')
			new_qual.grade = qual_row.get('grade')
			new_qual.university = qual_row.get('university')
			new_qual.graduation_year = qual_row.get('graduation_year')
			new_qual.degree_certificate_upload = qual_row.get('degree_certificate_upload')
	
	# Handle experience table (append new rows)
	if doc.get('experience'):
		existing_experiences = onboarding_doc.get('experience', [])
		for exp_row in doc.experience:
			# Create new row in Employee Onboarding
			new_exp = onboarding_doc.append('experience', {})
			new_exp.company_name = exp_row.get('company_name')
			new_exp.start_date = exp_row.get('start_date')
			new_exp.end_date = exp_row.get('end_date')
			new_exp.designation = exp_row.get('designation')
			new_exp.city = exp_row.get('city')
	
	# Mark webform as submitted
	onboarding_doc.webform_submitted = 1
	onboarding_doc.webform_submitted_on = now()
	
	# Save the Employee Onboarding document
	try:
		onboarding_doc.save(ignore_permissions=True)
		frappe.db.commit()
		
		# Delete the temporary document that was created by the webform
		# This document was only used to capture the form data
		try:
			frappe.delete_doc("Employee Onboarding", doc.name, force=1, ignore_permissions=True)
			frappe.db.commit()
		except Exception as del_error:
			# Log but don't fail if deletion fails
			frappe.log_error(f"Error deleting temporary Employee Onboarding document {doc.name}: {str(del_error)}", "Employee Onboarding Webform Cleanup")
		
		# Set a flag to indicate successful processing
		frappe.local.response.message = {
			"success": True,
			"message": _("Your onboarding details have been successfully submitted!")
		}
	except Exception as e:
		# Delete the temporary document even on error
		try:
			frappe.delete_doc("Employee Onboarding", doc.name, force=1, ignore_permissions=True)
			frappe.db.commit()
		except:
			pass
		
		frappe.log_error(f"Error updating Employee Onboarding from webform: {str(e)}", "Employee Onboarding Webform Error")
		frappe.throw(_("An error occurred while saving your details. Please try again or contact HR."))


def get_webform_url(employee_onboarding_name):
	"""
	Generate webform URL with Employee Onboarding name parameter
	"""
	from frappe.utils import get_url
	
	base_url = get_url()
	# Use /new directly so query param is preserved (base route may redirect to /new)
	webform_url = f"{base_url}/employee-onboarding-details/new?name={employee_onboarding_name}"
	return webform_url

