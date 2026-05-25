"""
Webform handler for Employee Onboarding Details
Processes webform submissions and updates the Employee Onboarding record
"""

import frappe
from frappe import _
from frappe.utils import now
import json
from urllib.parse import parse_qs, urlparse


def _delete_temp_onboarding(temp_name, target_name=None):
	"""Best-effort cleanup of temporary onboarding doc created by webform insert."""
	if not temp_name:
		return
	# Safety: never delete the actual target onboarding.
	if target_name and temp_name == target_name:
		return
	if not frappe.db.exists("Employee Onboarding", temp_name):
		return
	frappe.delete_doc("Employee Onboarding", temp_name, force=1, ignore_permissions=True)


def prepare_webform_temp_onboarding(doc, method=None):
	"""
	Prepare temporary webform-created Employee Onboarding docs so they don't fail
	HRMS duplicate validation before our after_insert copy handler runs.
	"""
	web_form_name = frappe.form_dict.get("web_form") or getattr(doc, "web_form_name", None)
	is_webform_submission = (
		bool(getattr(frappe.flags, "in_web_form", False))
		or web_form_name == "employee-onboarding-details"
		or bool(doc.get("employee_onboarding_name"))
		or bool(frappe.form_dict.get("onboarding"))
	)
	if not is_webform_submission:
		return

	# Temp capture docs should bypass only duplicate onboarding check from HRMS.
	# This check can fail for webform temp docs (especially when job_applicant is empty/None)
	# before our after_insert copy logic runs.
	if hasattr(doc, "validate_duplicate_employee_onboarding"):
		doc.validate_duplicate_employee_onboarding = lambda *args, **kwargs: None


def process_webform_submission(doc, method=None):
	"""
	Process webform submission for Employee Onboarding Details
	This function is called when the webform is submitted
	"""
	# Detect web form submission robustly.
	# `frappe.flags.in_web_form` is not always reliable in all event contexts.
	web_form_name = (
		frappe.form_dict.get("web_form")
		or getattr(doc, "web_form_name", None)
	)
	referer = ""
	if getattr(frappe.local, "request", None):
		referer = frappe.local.request.headers.get("Referer", "") or ""
	is_webform_submission = (
		bool(getattr(frappe.flags, "in_web_form", False))
		or web_form_name == "employee-onboarding-details"
		or bool(doc.get("employee_onboarding_name"))
		or bool(frappe.form_dict.get("onboarding"))
		or "employee-onboarding-details" in referer
	)
	if not is_webform_submission:
		return

	# Resolve target Employee Onboarding from multiple sources.
	# `name` is reserved by Frappe; use `onboarding` as primary param.
	employee_onboarding_name = (
		doc.get("employee_onboarding_name")
		or frappe.form_dict.get("onboarding")
	)

	# Fallback: parse posted web form payload
	if not employee_onboarding_name and frappe.form_dict.get("data"):
		try:
			payload = json.loads(frappe.form_dict.get("data"))
			employee_onboarding_name = payload.get("employee_onboarding_name") or payload.get("onboarding")
		except Exception:
			pass

	# Fallback: parse onboarding from browser Referer query params.
	# This helps when submit API call does not carry page query params forward.
	if not employee_onboarding_name and referer:
		try:
			parsed = urlparse(referer)
			params = parse_qs(parsed.query or "")
			employee_onboarding_name = (params.get("onboarding") or [None])[0]
		except Exception:
			pass
	
	if not employee_onboarding_name:
		frappe.throw(_("Employee Onboarding reference is missing. Please use the link provided in your email."))

	# If somehow the temp doc itself is the target, nothing to copy/cleanup.
	if doc.name == employee_onboarding_name:
		return
	
	# Validate that Employee Onboarding exists
	if not frappe.db.exists("Employee Onboarding", employee_onboarding_name):
		frappe.throw(_("Invalid Employee Onboarding reference. Please contact HR."))
	
	# Get the Employee Onboarding document
	onboarding_doc = frappe.get_doc("Employee Onboarding", employee_onboarding_name)
	temp_doc_name = doc.name
	
	# Check if webform has already been submitted
	if onboarding_doc.get('webform_submitted'):
		frappe.throw(_("This form has already been submitted. Please contact HR if you need to make changes."))
	
	# Enqueue the actual processing to run after the current request finishes.
	# This is CRUCIAL because Frappe's webform `accept` method attaches base64 files
	# to this temporary document AFTER `after_insert` hooks run.
	frappe.enqueue(
		"alpinos.employee_onboarding_webform.process_webform_submission_async",
		temp_doc_name=temp_doc_name,
		employee_onboarding_name=employee_onboarding_name,
		enqueue_after_commit=True,
		now=frappe.flags.in_test
	)
	
	# Set a flag to indicate successful processing
	frappe.local.response.message = {
		"success": True,
		"message": _("Your onboarding details have been successfully submitted!")
	}

def process_webform_submission_async(temp_doc_name, employee_onboarding_name):
	import frappe
	from frappe.utils import now
	
	# Small delay to ensure all file attachments are fully committed by Frappe
	import time
	time.sleep(1)
	
	if not frappe.db.exists("Employee Onboarding", temp_doc_name):
		return
		
	if not frappe.db.exists("Employee Onboarding", employee_onboarding_name):
		return
		
	doc = frappe.get_doc("Employee Onboarding", temp_doc_name)
	onboarding_doc = frappe.get_doc("Employee Onboarding", employee_onboarding_name)
	
	# Map webform fields to Employee Onboarding fields
	field_mapping = {
		'personal_mobile_number': 'personal_mobile_number',
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
		'current_address': 'current_address',
		'current_accommodation_type': 'current_accommodation_type',
		'permanent_address': 'permanent_address',
		'permanent_accommodation_type': 'permanent_accommodation_type',
		'bank_name': 'bank_name',
		'branch': 'branch',
		'account_number': 'account_number',
		'account_type': 'account_type',
		'ifsc_code': 'ifsc_code',
		'bank_account_proof': 'bank_account_proof',
		'family_name': 'family_name',
		'family_relation': 'family_relation',
		'family_contact_number': 'family_contact_number',
		'family_occupation': 'family_occupation',
		'emergency_contact_name': 'emergency_contact_name',
		'emergency_contact_relation': 'emergency_contact_relation',
		'emergency_contact_number': 'emergency_contact_number',
	}
	
	for webform_field, onboarding_field in field_mapping.items():
		value = doc.get(webform_field)
		if value is not None:
			onboarding_doc.set(onboarding_field, value)
	
	if doc.get('qualification_child'):
		for qual_row in doc.qualification_child:
			new_qual = onboarding_doc.append('qualification_child', {})
			new_qual.degree = qual_row.get('degree')
			new_qual.grade = qual_row.get('grade')
			new_qual.university = qual_row.get('university')
			new_qual.graduation_year = qual_row.get('graduation_year')
			new_qual.degree_certificate_upload = qual_row.get('degree_certificate_upload')
	
	if doc.get('experience'):
		for exp_row in doc.experience:
			new_exp = onboarding_doc.append('experience', {})
			new_exp.company_name = exp_row.get('company_name')
			new_exp.start_date = exp_row.get('start_date')
			new_exp.end_date = exp_row.get('end_date')
			new_exp.designation = exp_row.get('designation')
			new_exp.city = exp_row.get('city')
	
	onboarding_doc.webform_submitted = 1
	onboarding_doc.webform_submitted_on = now()

	current_status = onboarding_doc.get("boarding_status")
	if current_status not in ["Draft", "Email Sent", "Employee Created"]:
		onboarding_doc.boarding_status = "Email Sent"
		
	# Relink all file attachments
	frappe.db.sql("""
		UPDATE `tabFile`
		SET attached_to_name = %s
		WHERE attached_to_doctype = 'Employee Onboarding'
		AND attached_to_name = %s
	""", (employee_onboarding_name, temp_doc_name))
	
	try:
		onboarding_doc.flags.ignore_mandatory = True
		onboarding_doc.save(ignore_permissions=True)
		frappe.db.commit()
		
		try:
			_delete_temp_onboarding(temp_doc_name, employee_onboarding_name)
			frappe.db.commit()
		except Exception as del_error:
			frappe.log_error(
				f"Cleanup failed for temp doc {temp_doc_name}: {str(del_error)}",
				"Employee Onboarding Webform Cleanup",
			)
	except Exception as e:
		frappe.log_error(
			f"Error updating Employee Onboarding async: {str(e)}\n\n{frappe.get_traceback()}",
			"Employee Onboarding Webform Error",
		)


def get_webform_url(employee_onboarding_name):
	"""
	Generate webform URL with Employee Onboarding parameter.
	Use `onboarding` (not `name`) because Frappe reserves `name` for edit/view modes.
	"""
	from frappe.utils import get_url
	
	base_url = get_url()
	# Use /new directly so query param is preserved (base route may redirect to /new)
	webform_url = f"{base_url}/employee-onboarding-details/new?onboarding={employee_onboarding_name}"
	return webform_url

