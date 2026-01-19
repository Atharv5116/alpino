"""
Automation scripts for Employee Onboarding
- Auto-populate fields from Job Applicant
- Create Employee Onboarding from Job Applicant/Interview
- Allow HR Manager to save without mandatory fields
- Handle pre-onboarding workflow with interview creation and email scheduling
"""

import frappe
from frappe import _
from frappe.model.meta import get_meta
from frappe.utils import add_days, getdate, nowdate
from datetime import datetime, timedelta


def populate_from_job_applicant(doc, method=None):
	"""
	Auto-populate Employee Onboarding fields from Job Applicant
	This runs on validate and before_save to populate fields marked as "Auto"
	"""
	if not doc.job_applicant:
		# Clear candidate_id if job_applicant is cleared
		if hasattr(doc, 'candidate_id'):
			doc.candidate_id = ""
		return
	
	try:
		job_applicant = frappe.get_doc("Job Applicant", doc.job_applicant)
	except:
		return
	
	# Candidate ID = Link to Job Applicant
	# Always update to ensure it's synced with job_applicant
	if hasattr(doc, 'candidate_id'):
		doc.candidate_id = doc.job_applicant
	
	# Company - fetch from Job Opening -> Company
	if job_applicant.job_requisition:
		try:
			job_opening = frappe.get_doc("Job Opening", job_applicant.job_requisition)
			if job_opening.company:
				doc.company = job_opening.company
			
			# Location - from Job Opening (if available)
			if hasattr(job_opening, 'location') and job_opening.location:
				doc.location = job_opening.location
			
			# Department - from Job Opening (standard field)
			if job_opening.department:
				doc.department = job_opening.department
				
				# HOD and Reporting Manager - from Department
				try:
					department_doc = frappe.get_doc("Department", job_opening.department)
					if hasattr(department_doc, 'hod') and department_doc.hod:
						doc.hod = department_doc.hod
					if hasattr(department_doc, 'reports_to') and department_doc.reports_to:
						doc.reporting_manager = department_doc.reports_to
				except:
					pass
		except Exception as e:
			frappe.log_error(f"Error fetching Job Opening data: {str(e)}", "Employee Onboarding Auto-fill Error")
	
	# Full Name - split applicant_name into first, middle, last
	if job_applicant.applicant_name:
		name_parts = job_applicant.applicant_name.strip().split()
		if len(name_parts) >= 1:
			doc.first_name = name_parts[0]
		if len(name_parts) >= 2:
			doc.middle_name = name_parts[1] if len(name_parts) > 2 else ""
		if len(name_parts) >= 3:
			doc.last_name = " ".join(name_parts[2:])
		else:
			doc.last_name = name_parts[-1] if len(name_parts) > 1 else ""
		
		# Full Name Display
		doc.full_name_display = job_applicant.applicant_name
	
	# Personal Mobile Number
	if job_applicant.phone_number:
		doc.personal_mobile_number = job_applicant.phone_number
	
	# Personal Email
	if job_applicant.email_id:
		doc.personal_email = job_applicant.email_id
	
	# Marital Status
	if job_applicant.marital_status:
		doc.marital_status_onboarding = job_applicant.marital_status
	
	# City and State - split from city_state
	if job_applicant.city_state:
		city_state_parts = job_applicant.city_state.split("/")
		if len(city_state_parts) >= 1:
			doc.city = city_state_parts[0].strip()
		if len(city_state_parts) >= 2:
			doc.state = city_state_parts[1].strip()
		
		# Also set the combined city/state field
		doc.city_state_combined = job_applicant.city_state
	
	# Degree
	if job_applicant.degree:
		doc.degree = job_applicant.degree
	
	# Work Experience fields - NOT auto-filled, user will enter manually
	# DO NOT populate these fields from job_applicant.employment_* fields
	# These must be entered manually by the user
	# Explicitly clear them if they match employment fields (were auto-populated)
	if hasattr(doc, 'work_experience_company_name'):
		# Check if work experience was auto-populated from employment fields and clear them
		should_clear = False
		if hasattr(job_applicant, 'employment_company_name') and job_applicant.employment_company_name:
			if doc.work_experience_company_name == job_applicant.employment_company_name:
				should_clear = True
		if hasattr(job_applicant, 'employment_designation') and job_applicant.employment_designation:
			if doc.work_experience_designation == job_applicant.employment_designation:
				should_clear = True
		if hasattr(job_applicant, 'employment_start_date') and job_applicant.employment_start_date:
			if doc.work_experience_start_date == job_applicant.employment_start_date:
				should_clear = True
		if hasattr(job_applicant, 'employment_end_date') and job_applicant.employment_end_date:
			if doc.work_experience_end_date == job_applicant.employment_end_date:
				should_clear = True
		
		# Clear all work experience fields if any match (they were auto-populated)
		if should_clear:
			doc.work_experience_company_name = ""
			doc.work_experience_designation = ""
			doc.work_experience_start_date = None
			doc.work_experience_end_date = None
			doc.work_experience_city = ""
	
	# Notice Period
	
	# Designation - from Job Applicant
	if job_applicant.designation:
		doc.onboarding_designation = job_applicant.designation


def allow_hr_manager_to_save_without_mandatory_fields(doc, method=None):
	"""
	Allow HR Manager role to save Employee Onboarding even if certain mandatory fields are not filled.
	This function temporarily makes specified fields non-mandatory for HR Managers during validation.
	"""
	# Check if current user has HR Manager role
	user_roles = frappe.get_roles()
	
	# Check if user has HR Manager role
	if "HR Manager" not in user_roles:
		return
	
	# Fields that should be allowed to be empty for HR Managers
	fields_to_make_optional = [
		# Company Profile Details
		"company_mobile_number",
		"company_email",
		"date_of_joining_onboarding",
		"category",
		"employment_status",
		"resign_date",
		"last_working_date",
		# Salary Details
		"ctc_monthly",
		"salary_template",
		"salary_start_date",
		"salary_end_date",
		"period_in_months",
		"pay_frequency",
		"notice_period_salary",
		"probation_period",
		"probation_end_date",
		"salary_mode",
		"increment_cycle",
		"tax_regime",
		# Policy
		"policy_assignment",
		"leave_policy",
		"document_policy",
		"shift_policy",
		"overtime_policy",
		"holiday_policy",
		"comp_off_policy",
		"attendance_policy",
		"wfh_policy",
		"grace_policy",
		"reimbursement_policy",
		"geofencing_policy",
		"other_policy",
		# Access Level
		"roles",
		"rights",
		# Company Documents
		"offer_letter",
		"bond_letter",
		"exit_letter",
	]
	
	# Set a flag to indicate HR Manager can skip these validations
	# This will be checked in a custom validation
	if not hasattr(frappe.local, 'hr_manager_optional_fields'):
		frappe.local.hr_manager_optional_fields = set()
	
	frappe.local.hr_manager_optional_fields.update(fields_to_make_optional)
	
	# Temporarily modify meta to make fields non-mandatory
	meta = get_meta("Employee Onboarding")
	
	for fieldname in fields_to_make_optional:
		# Check if field exists in meta
		field = meta.get_field(fieldname)
		if field and field.reqd:
			# Store original value and set to non-mandatory
			if not hasattr(field, '_original_reqd'):
				field._original_reqd = field.reqd
			field.reqd = 0
			
			# Also update the doc's meta cache if it exists
			if hasattr(doc, 'meta') and hasattr(doc.meta, 'fields'):
				for doc_field in doc.meta.fields:
					if doc_field.fieldname == fieldname and doc_field.reqd:
						if not hasattr(doc_field, '_original_reqd'):
							doc_field._original_reqd = doc_field.reqd
						doc_field.reqd = 0
						break
	
	# Date of Joining - use existing date_of_joining field or expected_date_of_joining
	if not doc.date_of_joining_onboarding:
		if doc.date_of_joining:
			doc.date_of_joining_onboarding = doc.date_of_joining
		elif job_applicant.expected_date_of_joining:
			doc.date_of_joining_onboarding = job_applicant.expected_date_of_joining


@frappe.whitelist()
def create_employee_onboarding_from_job_applicant(job_applicant_name):
	"""
	Open new Employee Onboarding form with prefetched values from Job Applicant
	This is called from the button in Job Applicant form
	Just opens a new form, doesn't create/submit - user can fill and save manually
	"""
	if not job_applicant_name:
		frappe.throw(_("Job Applicant is required"))
	
	# Check if Employee Onboarding already exists for this Job Applicant
	existing = frappe.db.exists("Employee Onboarding", {"job_applicant": job_applicant_name})
	if existing:
		frappe.msgprint(_("Employee Onboarding already exists for this Job Applicant"))
		frappe.set_route("Form", "Employee Onboarding", existing)
		return existing
	
	# Just return the job_applicant_name - JavaScript will handle opening the form
	# The JavaScript will auto-populate fields when job_applicant is set
	return {
		"job_applicant": job_applicant_name,
		"action": "open_new_form"
	}


@frappe.whitelist()
def create_employee_onboarding_from_interview(interview_name):
	"""
	Create Employee Onboarding from Interview
	This is called from the button in Interview form
	"""
	if not interview_name:
		frappe.throw(_("Interview is required"))
	
	# Get Interview
	interview = frappe.get_doc("Interview", interview_name)
	
	if not interview.job_applicant:
		frappe.throw(_("Job Applicant is not linked to this Interview"))
	
	# Use the same function as Job Applicant
	return create_employee_onboarding_from_job_applicant(interview.job_applicant)


def create_job_offer_from_applicant(job_applicant):
	"""
	Create a Job Offer from Job Applicant if it doesn't exist
	"""
	try:
		job_offer = frappe.get_doc({
			"doctype": "Job Offer",
			"job_applicant": job_applicant.name,
			"offer_date": frappe.utils.today(),
			"status": "Accepted",
		})
		
		if job_applicant.job_requisition:
			job_offer.job_opening = job_applicant.job_requisition
		
		job_offer.insert(ignore_permissions=True)
		frappe.db.commit()
		
		return job_offer.name
	except Exception as e:
		frappe.log_error(f"Error creating Job Offer: {str(e)}", "Create Job Offer Error")
		return None


def check_all_required_fields_filled(doc):
	"""
	Check if all required fields for pre-onboarding are filled
	Returns True if all fields are filled, False otherwise
	"""
	required_fields = {
		# Unique ID and Company
		"candidate_id": "Unique ID",
		"company": "Company Name",
		
		# Personal Details
		"first_name": "First Name",
		"last_name": "Last Name",  # middle_name is optional
		"full_name_display": "Full Name",
		"personal_mobile_number": "Personal Mobile Number",
		"personal_email": "Personal Email",
		"marital_status_onboarding": "Marital Status",
		
		# Address (city/state from city_state_combined)
		"city_state_combined": "City/State",
		
		# Company Profile Details
		"location": "Location",
		"designation_company_profile": "Designation",
		"department": "Department",
		"hod": "HOD",
		"reporting_manager": "Reporting Manager",
		"company_mobile_number": "Company Mobile Number",
		"company_email": "Company Email",
		"date_of_joining_onboarding": "Date of Joining (DOJ)",
		"category": "Category",
		"employment_status": "Employment Status",
		"resign_date": "Resign Date",  # Optional
		"last_working_date": "Last Working Date",  # Optional
		
		# Salary Details
		"ctc_monthly": "CTC (Monthly)",
		"salary_template": "Salary Template",
		"salary_start_date": "Start Date",
		"salary_end_date": "End Date",
		"period_in_months": "Period (in months)",
		"pay_frequency": "Pay Frequency",
		"notice_period_salary": "Notice Period",
		"probation_period": "Probation Period",
		"probation_end_date": "Probation End Date",
		"salary_mode": "Salary Mode",
		"increment_cycle": "Increment Cycle",
		"tax_regime": "Tax Regime",
		
		# Policy
		"policy_assignment": "Policy Assignment",
		"leave_policy": "Leave Policy",
		"document_policy": "Document Policy",
		"shift_policy": "Shift Policy",
		"overtime_policy": "Overtime Policy",
		"holiday_policy": "Holiday Policy",
		"comp_off_policy": "Comp Off Policy",
		"attendance_policy": "Attendance Policy",
		"wfh_policy": "WFH Policy",
		"grace_policy": "Grace Policy",
		"reimbursement_policy": "Reimbursement Policy",
		"geofencing_policy": "GeoFencing Policy",
		"other_policy": "Other Policy",
		
		# Access Level
		"roles": "Roles",
		"rights": "Rights",
		
		# Company Documents
		"offer_letter": "Offer Letter",
		"bond_letter": "Bond Letter",
		"exit_letter": "Exit Letter",
	}
	
	missing_fields = []
	
	for fieldname, label in required_fields.items():
		value = doc.get(fieldname)
		
		# Check if field is empty
		if not value:
			# Special handling for optional fields
			if fieldname in ["resign_date", "last_working_date"]:
				continue  # These are optional
			
			missing_fields.append(label)
	
	# If any required fields are missing, return False
	if missing_fields:
		return False, missing_fields
	
	return True, []


def ensure_pre_onboarding_interview_round_exists():
	"""
	Ensure "pre-onboarding" Interview Round exists
	Creates it if it doesn't exist
	Returns the Interview Round name
	"""
	round_name = "pre-onboarding"
	
	# Check if it already exists
	if frappe.db.exists("Interview Round", round_name):
		return round_name
	
	# Create the Interview Round
	try:
		# Get or create interview type
		interview_type = frappe.db.get_value("Interview Type", "Pre-Onboarding", "name")
		if not interview_type:
			try:
				interview_type_doc = frappe.get_doc({
					"doctype": "Interview Type",
					"name": "Pre-Onboarding",
					"description": "Pre-Onboarding Interview"
				})
				interview_type_doc.insert(ignore_permissions=True)
				interview_type = interview_type_doc.name
				frappe.db.commit()
			except Exception:
				# Use existing interview type if creation fails
				interview_type = frappe.db.get_value("Interview Type", {}, "name") or "Pre-Onboarding"
		
		interview_round = frappe.get_doc({
			"doctype": "Interview Round",
			"round_name": round_name,
			"interview_type": interview_type,
			"expected_average_rating": 0.0
		})
		
		# Try to get a default skill or create a minimal skill set
		existing_skill = frappe.db.get_value("Skill", {"name": ("!=", "")}, "name")
		
		if not existing_skill:
			# Create a default skill if none exists
			try:
				skill_doc = frappe.get_doc({
					"doctype": "Skill",
					"skill_name": "Onboarding"
				})
				skill_doc.insert(ignore_permissions=True)
				existing_skill = skill_doc.name
				frappe.db.commit()
			except Exception:
				pass
		
		# Add skill to expected_skill_set if we have one
		if existing_skill:
			interview_round.append("expected_skill_set", {
				"skill": existing_skill
			})
		
		# Insert with ignore_permissions
		interview_round.flags.ignore_validate = True
		interview_round.flags.ignore_mandatory = True
		interview_round.insert(ignore_permissions=True)
		frappe.db.commit()
		
		return round_name
		
	except Exception as e:
		frappe.log_error(f"Error creating pre-onboarding Interview Round: {str(e)}", "Create Interview Round Error")
		# If creation fails, try to return the name anyway (might exist now)
		if frappe.db.exists("Interview Round", round_name):
			return round_name
		raise frappe.ValidationError(_("Could not create Interview Round: {0}").format(str(e)))


def create_pre_onboarding_interview(doc):
	"""
	Create a pre-onboarding Interview for the Employee Onboarding document
	Returns the Interview name
	"""
	if not doc.job_applicant:
		frappe.throw(_("Job Applicant is required to create Interview"))
	
	# Ensure interview round exists
	interview_round_name = ensure_pre_onboarding_interview_round_exists()
	
	# Check if interview already exists for this job applicant with this round
	existing_interview = frappe.db.get_value("Interview", {
		"job_applicant": doc.job_applicant,
		"interview_round": interview_round_name
	}, "name")
	
	if existing_interview:
		return existing_interview
	
	# Get job applicant
	job_applicant = frappe.get_doc("Job Applicant", doc.job_applicant)
	
	# Create Interview
	try:
		interview = frappe.get_doc({
			"doctype": "Interview",
			"interview_round": interview_round_name,
			"job_applicant": doc.job_applicant,
			"designation": doc.designation_company_profile or doc.onboarding_designation or job_applicant.designation,
			"resume_link": job_applicant.resume_link if hasattr(job_applicant, 'resume_link') else None,
			"job_opening": job_applicant.job_requisition if hasattr(job_applicant, 'job_requisition') else None,
			"status": "Pending"
		})
		
		# Get interviewers from interview round
		interview_round = frappe.get_doc("Interview Round", interview_round_name)
		if hasattr(interview_round, 'interviewers') and interview_round.interviewers:
			for interviewer_row in interview_round.interviewers:
				interview.append("interview_details", {
					"interviewer": interviewer_row.user
				})
		
		interview.insert(ignore_permissions=True)
		frappe.db.commit()
		
		return interview.name
		
	except Exception as e:
		frappe.log_error(f"Error creating pre-onboarding Interview: {str(e)}", "Create Interview Error")
		raise


def schedule_pre_onboarding_email(doc):
	"""
	Schedule an email to be sent to the applicant 1 week before the date of joining
	Sets status to "Document Pending" when email is sent
	This function marks the document for email sending, which will be handled by a scheduled job
	"""
	if not doc.date_of_joining_onboarding:
		return
	
	if not doc.job_applicant:
		return
	
	# Calculate email date (1 week before date of joining)
	date_of_joining = getdate(doc.date_of_joining_onboarding)
	email_date = add_days(date_of_joining, -7)
	
	# If email date is today or in the past, send immediately
	if email_date <= getdate(nowdate()):
		# If date has passed or is today, send immediately
		try:
			job_applicant = frappe.get_doc("Job Applicant", doc.job_applicant)
			applicant_email = job_applicant.email_id if hasattr(job_applicant, 'email_id') else None
			
			if applicant_email:
				send_pre_onboarding_email(doc, applicant_email)
		except Exception as e:
			frappe.log_error(f"Error in schedule_pre_onboarding_email: {str(e)}", "Pre-Onboarding Email Error")
	
	# Otherwise, the scheduled job will handle it when the date arrives


def send_pre_onboarding_email(doc, applicant_email):
	"""
	Send pre-onboarding email to the applicant
	Sets status to "Document Pending" after sending
	"""
	try:
		# Email content
		subject = f"Pre-Onboarding: Document Submission Required - {doc.full_name_display or 'Employee'}"
		
		# Get site URL
		site_url = frappe.utils.get_url()
		
		message = f"""
		Dear {doc.full_name_display or 'Employee'},
		
		Your date of joining is scheduled for {doc.date_of_joining_onboarding}.
		
		Please complete the following documents and submit them:
		- Personal Details
		- Address Details
		- Qualification Details
		- Work Experience
		- Bank Details
		- Family Details
		- Emergency Contact Details
		
		You can access your Employee Onboarding form at: {site_url}/app/employee-onboarding/{doc.name}
		
		Best regards,
		HR Team
		"""
		
		# Send email
		frappe.sendmail(
			recipients=[applicant_email],
			subject=subject,
			message=message,
			now=True
		)
		
		# Update status to "Document Pending"
		frappe.db.set_value("Employee Onboarding", doc.name, "boarding_status", "Document Pending", update_modified=False)
		frappe.db.commit()
		
		frappe.log_error(f"Pre-onboarding email sent to {applicant_email} for Employee Onboarding {doc.name}", "Pre-Onboarding Email")
		
	except Exception as e:
		frappe.log_error(f"Error sending pre-onboarding email: {str(e)}", "Pre-Onboarding Email Error")


def send_scheduled_pre_onboarding_emails():
	"""
	Scheduled job to send pre-onboarding emails 1 week before date of joining
	Runs daily to check for Employee Onboarding documents that need emails sent
	"""
	today = getdate(nowdate())
	email_date = add_days(today, 7)  # 1 week from today
	
	# Find Employee Onboarding documents where:
	# - date_of_joining_onboarding is 7 days from today
	# - boarding_status is "Pre-Onboarding Initiated"
	# - email not yet sent (we'll check if status is still "Pre-Onboarding Initiated")
	
	onboarding_docs = frappe.get_all(
		"Employee Onboarding",
		filters={
			"date_of_joining_onboarding": email_date,
			"boarding_status": "Pre-Onboarding Initiated",
			"docstatus": ["!=", 2]  # Not cancelled
		},
		fields=["name", "job_applicant", "date_of_joining_onboarding", "full_name_display"]
	)
	
	for doc_data in onboarding_docs:
		try:
			doc = frappe.get_doc("Employee Onboarding", doc_data.name)
			
			if not doc.job_applicant:
				continue
			
			# Get job applicant email
			job_applicant = frappe.get_doc("Job Applicant", doc.job_applicant)
			applicant_email = job_applicant.email_id if hasattr(job_applicant, 'email_id') else None
			
			if applicant_email:
				send_pre_onboarding_email(doc, applicant_email)
				
		except Exception as e:
			frappe.log_error(f"Error processing pre-onboarding email for {doc_data.name}: {str(e)}", "Pre-Onboarding Email Scheduler")


def handle_pre_onboarding_workflow(doc, method=None):
	"""
	Handle pre-onboarding workflow when all required fields are filled
	- Set status to "Pre-Onboarding Initiated"
	- Create pre-onboarding Interview
	- Schedule email 1 week before date of joining
	"""
	# Only process if document is being saved (not on validate)
	if doc.is_new():
		return
	
	# Check if all required fields are filled
	all_filled, missing_fields = check_all_required_fields_filled(doc)
	
	if not all_filled:
		return
	
	# Check if status is already set (to avoid duplicate processing)
	if doc.boarding_status == "Pre-Onboarding Initiated":
		# Check if interview already exists
		if not frappe.db.exists("Interview", {
			"job_applicant": doc.job_applicant,
			"interview_round": "pre-onboarding"
		}):
			# Create interview if it doesn't exist
			try:
				interview_name = create_pre_onboarding_interview(doc)
				# Store interview name in doc for client-side redirect
				doc.pre_onboarding_interview = interview_name
			except Exception as e:
				frappe.log_error(f"Error creating pre-onboarding interview: {str(e)}", "Pre-Onboarding Workflow")
		
		# Schedule email if date of joining is set
		if doc.date_of_joining_onboarding:
			schedule_pre_onboarding_email(doc)
		
		return
	
	# Set status to "Pre-Onboarding Initiated"
	doc.boarding_status = "Pre-Onboarding Initiated"
	
	# Create pre-onboarding Interview
	try:
		interview_name = create_pre_onboarding_interview(doc)
		# Store interview name in doc for client-side redirect
		doc.pre_onboarding_interview = interview_name
	except Exception as e:
		frappe.log_error(f"Error creating pre-onboarding interview: {str(e)}", "Pre-Onboarding Workflow")
	
	# Schedule email 1 week before date of joining
	if doc.date_of_joining_onboarding:
		schedule_pre_onboarding_email(doc)

