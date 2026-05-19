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
from frappe.utils import add_days, getdate, nowdate, get_url
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
	
	# Work Experience fields - Auto-populate from Job Applicant employment fields
	if hasattr(doc, 'work_experience_company_name'):
		# Only populate if fields are empty (don't overwrite user-entered data)
		if not doc.work_experience_company_name and hasattr(job_applicant, 'employment_company_name') and job_applicant.employment_company_name:
			doc.work_experience_company_name = job_applicant.employment_company_name
		
		if not doc.work_experience_designation and hasattr(job_applicant, 'employment_designation') and job_applicant.employment_designation:
			doc.work_experience_designation = job_applicant.employment_designation
		
		if not doc.work_experience_start_date and hasattr(job_applicant, 'employment_start_date') and job_applicant.employment_start_date:
			doc.work_experience_start_date = job_applicant.employment_start_date
		
		if not doc.work_experience_end_date and hasattr(job_applicant, 'employment_end_date') and job_applicant.employment_end_date:
			doc.work_experience_end_date = job_applicant.employment_end_date
		
		# City - try to get from employment_city or city_state
		if not doc.work_experience_city:
			if hasattr(job_applicant, 'employment_city') and job_applicant.employment_city:
				doc.work_experience_city = job_applicant.employment_city
			elif job_applicant.city_state:
				# Extract city from city_state (format: "City/State")
				city_state_parts = job_applicant.city_state.split("/")
				if len(city_state_parts) >= 1:
					doc.work_experience_city = city_state_parts[0].strip()
	
	# Notice Period
	
	# Designation - from Job Applicant
	if job_applicant.designation:
		doc.onboarding_designation = job_applicant.designation
	
	# Auto-populate hidden standard 'designation' field (Link) from designation_company_profile
	# This ensures the hidden field is populated for Employee creation
	# Only populate if designation_company_profile exists and designation is empty
	# If designation_company_profile is empty, ensure designation is also empty (not causing validation errors)
	if hasattr(doc, 'designation_company_profile') and doc.designation_company_profile:
		# Try to find matching Designation record
		# If designation_company_profile is a string, try to match it with Designation doctype
		if not doc.designation:
			try:
				# Check if designation_company_profile matches a Designation name
				designation_match = frappe.db.exists("Designation", doc.designation_company_profile)
				if designation_match:
					doc.designation = designation_match
				else:
					# If no exact match, try to find by name (case-insensitive)
					designation_match = frappe.db.get_value("Designation", 
						{"name": ["like", f"%{doc.designation_company_profile}%"]}, 
						"name"
					)
					if designation_match:
						doc.designation = designation_match
			except Exception:
				# If there's any error, just skip - don't break the save process
				pass
	else:
		# If designation_company_profile is empty, ensure designation is also empty
		# This prevents validation errors on unsaved documents
		if hasattr(doc, 'designation') and doc.designation and not doc.designation_company_profile:
			# Only clear if designation_company_profile is explicitly empty
			# Don't clear if it's just not set yet (unsaved document)
			pass


def allow_hr_manager_to_save_without_mandatory_fields(doc, method=None):
	"""
	Allow saving Employee Onboarding even if certain mandatory fields are not filled.
	- While the form is in Draft workflow state: allow any user to save without mandatory fields.
	- On first save of a new document: allow any user to save without filling mandatory fields.
	- On subsequent saves: allow HR Manager role to skip specific fields (as per SRS).
	Also ensures hidden designation field is non-mandatory for all users.
	"""
	# Normalize legacy status value before field validation runs.
	# "Document Pending" is invalid for current options; valid value is "Email Sent".
	if getattr(doc, "boarding_status", None) in ["Document Pending", "Documents Pending"]:
		doc.boarding_status = "Email Sent"

	# 1) While form is in Draft state: bypass ALL mandatory checks for all users.
	# This lets HR create an onboarding shell with minimal data and complete details later.
	if hasattr(doc, "is_new") and doc.is_new():
		doc.flags.ignore_mandatory = True
		return

	# Draft and Email Sent workflow states: bypass mandatory for all users.
	# Only the final "Employee Created" state should enforce mandatory checks.
	current_state = getattr(doc, "boarding_status", None) or getattr(doc, "workflow_state", None)
	if current_state in ("Draft", "Email Sent"):
		doc.flags.ignore_mandatory = True
		return
	
	# Ensure hidden designation field is always non-mandatory (for all users, not just HR Manager)
	meta = get_meta("Employee Onboarding")
	designation_field = meta.get_field("designation")
	if designation_field and designation_field.reqd:
		# Temporarily make it non-mandatory
		if not hasattr(designation_field, '_original_reqd'):
			designation_field._original_reqd = designation_field.reqd
		designation_field.reqd = 0
		# Also update in doc meta if it exists
		if hasattr(doc, 'meta') and hasattr(doc.meta, 'fields'):
			for doc_field in doc.meta.fields:
				if doc_field.fieldname == "designation" and doc_field.reqd:
					if not hasattr(doc_field, '_original_reqd'):
						doc_field._original_reqd = doc_field.reqd
					doc_field.reqd = 0
					break
	
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
		elif hasattr(doc, 'job_applicant') and doc.job_applicant:
			try:
				job_applicant = frappe.get_doc("Job Applicant", doc.job_applicant)
				if job_applicant.expected_date_of_joining:
					doc.date_of_joining_onboarding = job_applicant.expected_date_of_joining
			except:
				pass


def validate_date_of_birth(doc, method=None):
	"""
	Validate that date_of_birth is at least 18 years old
	"""
	if not doc.date_of_birth:
		return
	
	dob = getdate(doc.date_of_birth)
	today = getdate(nowdate())
	
	# Calculate age
	age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
	
	if age < 18:
		frappe.throw(
			_("Date of Birth must be at least 18 years old. Current age: {0} years").format(age),
			title=_("Invalid Date of Birth")
		)


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
		# Return the existing document name - JavaScript callback will handle routing
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
	# DEBUG: Log that this function was called and from where
	frappe.log_error(
		f"[EMAIL DEBUG] send_pre_onboarding_email called for {doc.name} | recipient: {applicant_email}\nTraceback:\n{frappe.get_traceback()}",
		"Onboarding Email Trace"
	)
	try:
		template_name = "Onboarding - Document Reminder"

		if not frappe.db.exists("Email Template", template_name):
			frappe.log_error(
				f"[EMAIL DEBUG] Template '{template_name}' NOT FOUND in DB for {doc.name}",
				"Onboarding Email Trace"
			)
			return

		# Generate webform link with Employee Onboarding name
		from alpinos.employee_onboarding_webform import get_webform_url
		webform_link = get_webform_url(doc.name)
		desk_onboarding_link = get_url(f"/app/employee-onboarding/{doc.name}")

		# Get company name
		company = getattr(doc, "company", "") or ""
		company_name = company
		if company:
			company_name = frappe.db.get_value("Company", company, "company_name") or company

		# Fetch HR Manager details (name, phone, email, designation)
		hr_name = "HR Team"
		hr_email = ""
		hr_phone = ""
		hr_designation = ""
		try:
			hr_users = frappe.get_all(
				"Has Role",
				filters={"role": "HR Manager", "parenttype": "User"},
				fields=["parent"],
			)
			for hr_user in hr_users:
				user_details = frappe.db.get_value(
					"User",
					hr_user.parent,
					["full_name", "email", "phone", "enabled"],
					as_dict=True
				)
				if user_details and user_details.enabled:
					hr_name = user_details.full_name or hr_user.parent or "HR Team"
					hr_email = user_details.email or ""
					hr_phone = user_details.phone or ""
					# Attempt to get HR Manager's designation from Employee doctype
					employee_designation = frappe.db.get_value("Employee", {"user_id": hr_user.parent}, "designation")
					hr_designation = employee_designation or "HR Team"
					break
		except Exception:
			hr_name = frappe.session.user_fullname or "HR Team"
			hr_email = frappe.session.user if frappe.session.user and "@" in frappe.session.user else ""
			hr_phone = ""
			hr_designation = "HR Team"

		# Get candidate/applicant name from Job Applicant if available
		candidate_name = getattr(doc, "full_name_display", "") or getattr(doc, "employee_name", "") or "Candidate"
		job_title = getattr(doc, "designation", "") or ""
		if getattr(doc, "job_applicant", None):
			try:
				job_applicant = frappe.get_doc("Job Applicant", doc.job_applicant)
				candidate_name = job_applicant.applicant_name or candidate_name
				job_title = job_applicant.job_title or job_applicant.job_requisition or ""
				if job_applicant.job_requisition:
					job_opening_designation = frappe.db.get_value("Job Opening", job_applicant.job_requisition, "designation")
					job_title = job_opening_designation or job_title
			except Exception:
				pass

		# Format joining date
		joining_date = ""
		if getattr(doc, "date_of_joining_onboarding", None):
			try:
				joining_date = frappe.utils.formatdate(doc.date_of_joining_onboarding, "dd-MMM-yyyy")
			except Exception:
				joining_date = str(doc.date_of_joining_onboarding)

		email_doc = {
			"doctype": "Employee Onboarding",
			"name": doc.name,
			"full_name_display": candidate_name,
			"candidate_name": candidate_name,
			"company": company,
			"company_name": company_name,
			"date_of_joining_onboarding": getattr(doc, "date_of_joining_onboarding", "") or "",
			"joining_date": joining_date,
			"job_title": job_title,
			"designation": job_title,
			# Keep onboarding_link mapped to webform for backward compatibility with older templates.
			"onboarding_link": webform_link,
			"webform_link": webform_link,
			"desk_onboarding_link": desk_onboarding_link,
			"hr_name": hr_name,
			"hr_designation": hr_designation,
			"hr_email": hr_email,
			"hr_email_address": hr_email,
			"hr_phone": hr_phone,
			"hr_phone_number": hr_phone,
		}

		tmpl = frappe.get_doc("Email Template", template_name)
		formatted = tmpl.get_formatted_email({"doc": email_doc})

		# DEBUG: Log exactly which template and subject is being sent
		frappe.log_error(
			f"[EMAIL DEBUG] ABOUT TO SEND via send_pre_onboarding_email\n"
			f"  Doc: {doc.name}\n"
			f"  Template: {template_name}\n"
			f"  Subject: {formatted.get('subject')}\n"
			f"  Recipient: {applicant_email}",
			"Onboarding Email Trace"
		)

		frappe.sendmail(
			recipients=[applicant_email],
			subject=formatted["subject"],
			message=formatted["message"],
			reference_doctype="Employee Onboarding",
			reference_name=doc.name,
			now=True,
		)
		
		# Ensure status is Email Sent, don't set to invalid 'Documents Pending'
		frappe.db.set_value("Employee Onboarding", doc.name, "boarding_status", "Email Sent", update_modified=False)
		frappe.db.commit()
		
		frappe.log_error(f"[EMAIL DEBUG] SUCCESS: Pre-onboarding email sent to {applicant_email} for {doc.name} using template '{template_name}'", "Onboarding Email Trace")
		
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


def DEPRECATED_send_onboarding_created_email(doc, method=None):
	"""
	DEPRECATED: This was sending the wrong email.
	"""
	frappe.log_error(f"DEPRECATED_send_onboarding_created_email called for {doc.name}", "Onboarding Email Debug")
	return
	# try:
	# 	template_name = "Onboarding - Job Confirmation"
	# 
	# 	if not frappe.db.exists("Email Template", template_name):
	# 		return
	# 
	# 	# Prefer personal_email from onboarding, else from linked Job Applicant
	# 	applicant_email = getattr(doc, "personal_email", None) or None
	# 
	# 	if not applicant_email and getattr(doc, "job_applicant", None):
	# 		try:
	# 			job_applicant = frappe.get_doc("Job Applicant", doc.job_applicant)
	# 			applicant_email = getattr(job_applicant, "email_id", None)
	# 		except Exception:
	# 			applicant_email = None
	# 
	# 	if not applicant_email:
	# 		return
	# 
	# 	# Get company name
	# 	company = getattr(doc, "company", "") or ""
	# 	company_name = company
	# 	if company:
	# 		company_name = frappe.db.get_value("Company", company, "company_name") or company
	# 
	# 	# Fetch HR Manager details (name, phone, email)
	# 	hr_name = "HR Team"
	# 	hr_email = ""
	# 	hr_phone = ""
	# 	hr_designation = ""
	# 	try:
	# 		# Get all HR Manager role users
	# 		hr_users = frappe.get_all(
	# 			"Has Role",
	# 			filters={"role": "HR Manager", "parenttype": "User"},
	# 			fields=["parent"],
	# 		)
	# 		# Get first HR Manager's full details
	# 		for hr_user in hr_users:
	# 			user_details = frappe.db.get_value(
	# 				"User",
	# 				hr_user.parent,
	# 				["full_name", "email", "phone", "enabled"],
	# 				as_dict=True
	# 			)
	# 			if user_details and user_details.enabled:
	# 				hr_name = user_details.full_name or hr_user.parent or "HR Team"
	# 				hr_email = user_details.email or ""
	# 				hr_phone = user_details.phone or ""
	# 				# Try to get designation from Employee record if exists
	# 				employee = frappe.db.get_value("Employee", {"user_id": hr_user.parent}, "designation")
	# 				if employee:
	# 					hr_designation = frappe.db.get_value("Employee", employee, "designation") or ""
	# 				break
	# 	except Exception:
	# 		pass
	# 
	# 	# Get candidate/applicant name from Job Applicant if available
	# 	candidate_name = getattr(doc, "full_name_display", "") or getattr(doc, "employee_name", "") or ""
	# 	applicant_name = ""
	# 	job_title = getattr(doc, "designation", "") or ""
	# 	if getattr(doc, "job_applicant", None):
	# 		try:
	# 			job_applicant = frappe.get_doc("Job Applicant", doc.job_applicant)
	# 			applicant_name = getattr(job_applicant, "applicant_name", "") or ""
	# 			if not candidate_name:
	# 				candidate_name = applicant_name
	# 			# Get job title from Job Applicant's job_requisition -> Job Opening
	# 			if not job_title and getattr(job_applicant, "job_requisition", None):
	# 				job_opening_designation = frappe.db.get_value("Job Opening", job_applicant.job_requisition, "designation")
	# 				if job_opening_designation:
	# 					job_title = job_opening_designation
	# 		except Exception:
	# 			pass
	# 
	# 	# Get reporting manager name if it's a link
	# 	reporting_to_name = getattr(doc, "reporting_manager", "") or ""
	# 	if reporting_to_name:
	# 		try:
	# 			# Check if it's an Employee link
	# 			if frappe.db.exists("Employee", reporting_to_name):
	# 				reporting_to_name = frappe.db.get_value("Employee", reporting_to_name, "employee_name") or reporting_to_name
	# 			# Check if it's a User link
	# 			elif frappe.db.exists("User", reporting_to_name):
	# 				reporting_to_name = frappe.db.get_value("User", reporting_to_name, "full_name") or reporting_to_name
	# 		except Exception:
	# 			pass
	# 
	# 	email_doc = {
	# 		"doctype": "Employee Onboarding",
	# 		"name": doc.name,
	# 		"candidate_name": candidate_name,
	# 		"applicant_name": applicant_name,
	# 		"full_name_display": candidate_name,
	# 		"company": company,
	# 		"company_name": company_name,
	# 		"job_title": job_title,
	# 		"designation": job_title,
	# 		"joining_date": getattr(doc, "date_of_joining_onboarding", "") or "",
	# 		"date_of_joining": getattr(doc, "date_of_joining_onboarding", "") or "",
	# 		"date_of_joining_onboarding": getattr(doc, "date_of_joining_onboarding", "") or "",
	# 		"department": getattr(doc, "department", "") or "",
	# 		"department_name": getattr(doc, "department", "") or "",
	# 		"location": getattr(doc, "location", "") or "",
	# 		"reporting_location": getattr(doc, "location", "") or "",
	# 		"reporting_manager": getattr(doc, "reporting_manager", "") or "",
	# 		"reporting_to_name": reporting_to_name,
	# 		"reporting_time": "",  # Not typically stored in Employee Onboarding
	# 		"hr_name": hr_name,
	# 		"hr_email": hr_email,
	# 		"hr_email_address": hr_email,
	# 		"hr_phone": hr_phone,
	# 		"hr_phone_number": hr_phone,
	# 		"hr_designation": hr_designation,
	# 	}
	# 
	# 	tmpl = frappe.get_doc("Email Template", template_name)
	# 	formatted = tmpl.get_formatted_email({"doc": email_doc})
	# 
	# 	frappe.sendmail(
	# 		recipients=[applicant_email],
	# 		subject=formatted["subject"],
	# 		message=formatted["message"],
	# 		reference_doctype="Employee Onboarding",
	# 		reference_name=doc.name,
	# 		now=True,
	# 	)
	# except Exception as e:
	# 	frappe.log_error(
	# 		f"Error sending onboarding created email for {doc.name}: {str(e)}",
	# 		"Onboarding Job Confirmation Email Error",
	# 	)


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


def send_welcome_formalities_reminders():
	"""
	Scheduled job to send notifications to HR Manager:
	1. 1 day before welcome formalities are due (reminder)
	2. When TAT has passed and formality is still pending (overdue reminder)
	Runs daily to check for employees with welcome formalities due tomorrow or overdue
	"""
	from frappe.desk.doctype.notification_log.notification_log import make_notification_logs
	
	# Field name to label mapping for welcome formalities
	field_label_map = {
		"collect_documents": "Collect Documents",
		"prepare_the_system": "Prepare the System",
		"welcome_kit": "Welcome Kit",
		"introduction_session_and_sops_allocation": "Introduction Session + SOPs Allocation",
		"bond_letter": "Bond Letter",
		"hrms_training": "HRMS Training",
		"culture_training": "Culture Training",
		"provide_credentials": "Provide Credentials",
		"system_training": "System Training",
		"product_training": "Product Training",
		"meeting_with_department_head": "Meeting with Department Head"
	}
	
	# Get all welcome formalities configs
	configs = frappe.get_all(
		"Welcome Formalities Config",
		fields=["field_name", "tat_days"]
	)
	
	# Create a dictionary for quick lookup
	tat_config = {config.field_name: config.tat_days for config in configs}
	
	# Get all active employees with date_of_joining
	employees = frappe.get_all(
		"Employee",
		filters={
			"status": "Active",
			"date_of_joining": ["is", "set"]
		},
		fields=["name", "employee_name", "date_of_joining"]
	)
	
	today = getdate(nowdate())
	tomorrow = add_days(today, 1)
	
	# Get all HR Manager users
	hr_managers = frappe.get_all(
		"Has Role",
		filters={"role": "HR Manager", "parenttype": "User"},
		fields=["parent"]
	)
	hr_manager_users = [user.parent for user in hr_managers]
	
	if not hr_manager_users:
		frappe.log_error("No HR Manager users found for welcome formalities reminders", "Welcome Formalities Reminder")
		return
	
	notifications_sent = 0
	overdue_notifications_sent = 0
	
	for employee_data in employees:
		try:
			employee = frappe.get_doc("Employee", employee_data.name)
			date_of_joining = getdate(employee_data.date_of_joining)
			
			# Check each welcome formality checkbox
			for field_name, label in field_label_map.items():
				# Skip if checkbox is already checked
				if employee.get(field_name):
					continue
				
				# Get TAT for this field
				tat_days = tat_config.get(field_name)
				if not tat_days:
					continue
				
				# Calculate due date (date_of_joining + TAT days)
				due_date = add_days(date_of_joining, tat_days)
				employee_name = employee_data.employee_name or employee_data.name
				
				# Check if due date is tomorrow (1 day before reminder)
				if due_date == tomorrow:
					# Check if "due tomorrow" notification has already been sent for this employee and formality
					# Only send one notification per employee+formality combination
					subject = f"Welcome Formality Due Tomorrow: {label}"
					existing_tomorrow_notification = frappe.get_all(
						"Notification Log",
						filters={
							"type": "Alert",
							"document_type": "Employee",
							"document_name": employee_data.name,
							"subject": subject,
							"for_user": ["in", hr_manager_users] if hr_manager_users else []
						},
						limit=1
					)
					
					# Only send if notification doesn't already exist
					if len(existing_tomorrow_notification) == 0:
						# Send notification to all HR Managers
						message = f"<p>The welcome formality <strong>{label}</strong> is due tomorrow for employee <strong>{employee_name}</strong> (Employee ID: {employee_data.name}).</p><p>Please ensure this task is completed on time.</p>"
						
						notification_doc = {
							"type": "Alert",
							"document_type": "Employee",
							"document_name": employee_data.name,
							"subject": subject,
							"from_user": "Administrator",
							"email_content": message,
							"link": f"/app/employee/{employee_data.name}",
						}
						
						make_notification_logs(notification_doc, hr_manager_users)
						notifications_sent += 1
						
						frappe.log_error(
							f"Reminder sent: {label} for {employee_name}",
							"Welcome Formalities Reminder"
						)
				
				# Check if due date has passed (overdue reminder)
				elif due_date < today:
					# Calculate days overdue
					days_overdue = (today - due_date).days
					
					# Check if overdue notification has already been sent for this employee and formality
					# Only send one overdue notification per employee+formality combination
					subject = f"Welcome Formality Overdue: {label}"
					existing_overdue_notification = frappe.get_all(
						"Notification Log",
						filters={
							"type": "Alert",
							"document_type": "Employee",
							"document_name": employee_data.name,
							"subject": subject,
							"for_user": ["in", hr_manager_users] if hr_manager_users else []
						},
						limit=1
					)
					
					# Only send if notification doesn't already exist
					if len(existing_overdue_notification) == 0:
						# Send overdue notification to all HR Managers
						message = f"<p>The welcome formality <strong>{label}</strong> is <strong>overdue by {days_overdue} day(s)</strong> for employee <strong>{employee_name}</strong> (Employee ID: {employee_data.name}).</p><p>The TAT deadline was {due_date.strftime('%d-%m-%Y')}. Please complete this task immediately.</p>"
						
						notification_doc = {
							"type": "Alert",
							"document_type": "Employee",
							"document_name": employee_data.name,
							"subject": subject,
							"from_user": "Administrator",
							"email_content": message,
							"link": f"/app/employee/{employee_data.name}",
						}
						
						make_notification_logs(notification_doc, hr_manager_users)
						overdue_notifications_sent += 1
						
						frappe.log_error(
							f"Overdue reminder: {label} for {employee_name} ({days_overdue} days)",
							"Welcome Formalities Overdue Reminder"
						)
		
		except Exception as e:
			frappe.log_error(
				f"Error processing reminder for {employee_data.name}: {str(e)[:100]}",
				"Welcome Formalities Reminder Error"
			)
	
	total_notifications = notifications_sent + overdue_notifications_sent
	if total_notifications > 0:
		# Commit all notifications
		frappe.db.commit()
		frappe.log_error(
			f"Reminders sent: {notifications_sent} upcoming, {overdue_notifications_sent} overdue (Total: {total_notifications})",
			"Welcome Formalities Reminder Summary"
		)


def handle_workflow_transition(doc, method=None):
	"""
	Handle Employee Onboarding workflow transitions.
	- When state changes to 'Email Sent': send pre-onboarding email to candidate.
	- When state changes to 'Employee Created': trigger create employee mapped doc.
	"""
	# Determine the current workflow state
	current_state = getattr(doc, "boarding_status", None) or getattr(doc, "workflow_state", None)

	if not current_state:
		return

	# --- Transition to "Email Sent": send the pre-onboarding email ---
	if current_state == "Email Sent":
		_send_email_on_workflow_transition(doc)


def _send_email_on_workflow_transition(doc):
	"""
	Send pre-onboarding email when workflow transitions to 'Email Sent'.
	Uses the 'Onboarding - Document Reminder' email template with webform link.
	"""
	# DEBUG: Log that this function was called
	frappe.log_error(
		f"[EMAIL DEBUG] _send_email_on_workflow_transition called for {doc.name} | boarding_status={doc.boarding_status}\nTraceback:\n{frappe.get_traceback()}",
		"Onboarding Email Trace"
	)

	if not doc.job_applicant:
		frappe.throw(_("Job Applicant is required to send email to candidate."))

	try:
		job_applicant = frappe.get_doc("Job Applicant", doc.job_applicant)
		applicant_email = getattr(job_applicant, "email_id", None)

		if not applicant_email:
			# Fallback to personal_email on the onboarding doc
			applicant_email = getattr(doc, "personal_email", None)

		if not applicant_email:
			frappe.throw(_("No email address found for the candidate. Please set personal email or update Job Applicant."))

		# Reuse the existing send_pre_onboarding_email function
		send_pre_onboarding_email(doc, applicant_email)

		frappe.msgprint(
			_("Pre-onboarding email sent to {0}").format(applicant_email),
			title=_("Email Sent"),
			indicator="green",
		)
	except Exception as e:
		frappe.log_error(
			f"Error sending email on workflow transition for {doc.name}: {str(e)}",
			"Employee Onboarding Workflow Email Error"
		)
		frappe.throw(
			_("Failed to send email to candidate: {0}").format(str(e)),
			title=_("Email Error")
		)

