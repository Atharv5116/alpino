"""
Server-side hooks for Job Application Web Form
"""
import frappe
from frappe import _


@frappe.whitelist(allow_guest=True)
def set_job_applicant_defaults(web_form_name, docname=None):
	"""
	Set default values for Job Applicant web form from URL parameters
	This ensures job_title is set before form validation
	"""
	from frappe.website.doctype.web_form.web_form import get_form_data
	
	# Get the standard web form data
	result = get_form_data(
		doctype="Job Applicant",
		docname=docname,
		web_form_name=web_form_name
	)
	
	# Get job_title from URL query parameter
	job_title = frappe.form_dict.get('job_title') or frappe.local.request.args.get('job_title')
	source_param = frappe.form_dict.get('source') or frappe.local.request.args.get('source')
	
	def normalize_source(value):
		if not value:
			return None
		value = value.strip()
		lower_value = value.lower()
		source_map = {
			"linkedin": "LinkedIn",
			"indeed": "Indeed",
			"naukari.com": "Naukari.com",
			"naukari": "Naukari.com",
			"naukri.com": "Naukri.com",
			"naukri": "Naukri.com",
		}
		return source_map.get(lower_value, value)
	
	if job_title and frappe.db.exists("Job Opening", job_title):
		# Set default value in the result
		if not hasattr(result, 'defaults'):
			result.defaults = frappe._dict()
		result.defaults['job_title'] = job_title
		
		# Also set in doc if it exists
		if hasattr(result, 'doc') and result.doc:
			result.doc.job_title = job_title
		
		frappe.logger().info(f"Job Application Web Form: Setting default job_title to {job_title}")
	
	source_value = normalize_source(source_param)
	if source_value and frappe.db.exists("Job Applicant Source", source_value):
		if not hasattr(result, 'defaults'):
			result.defaults = frappe._dict()
		result.defaults['source'] = source_value
		
		if hasattr(result, 'doc') and result.doc:
			result.doc.source = source_value
		
		frappe.logger().info(f"Job Application Web Form: Setting default source to {source_value}")
	
	return result
