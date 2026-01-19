"""
Automation scripts for Job Applicant
- Auto-generate Candidate ID
- File upload validation (PDF and Word only)
- Status management automation
- Email notifications
- Job Requisition/Job Opening validation
"""

import frappe
from frappe import _
from frappe.utils import now, getdate, today
import os

def generate_candidate_id(doc, method=None):
	"""
	Set Candidate ID = Job Applicant ID (name)
	Both will be in AHFPL0000 format
	This runs before_save to set candidate_id to the document name
	The document name is set by autoname in before_insert, so we can use it in before_save
	"""
	# Set candidate_id to the Job Applicant's name (ID) if not already set
	# Both will be in AHFPL0000 format (e.g., AHFPL0001, AHFPL0002)
	if not doc.candidate_id and doc.name:
		doc.candidate_id = doc.name


def update_screening_status_automatically(doc, method=None):
	"""
	Automatically update screening_status based on category changes and other triggers
	Rules:
	- Default (new applicant): "Pending Screening"
	- Category White -> "Shortlisted"
	- Category Black -> "Not Eligible"
	- Category Hold -> "On Hold"
	- Interview created -> "Screening Call Scheduled" (handled in Interview hook)
	"""
	# Only update if category is being changed
	if doc.has_value_changed("candidate_category"):
		if doc.candidate_category == "White":
			doc.screening_status = "Shortlisted"
		elif doc.candidate_category == "Black":
			doc.screening_status = "Not Eligible"
		elif doc.candidate_category == "Hold":
			doc.screening_status = "On Hold"
		elif not doc.candidate_category:
			# Category removed, set back to default
			if not doc.screening_status:
				doc.screening_status = "Pending Screening"
	
	# Set default screening status for new applicants
	if doc.is_new() and not doc.screening_status:
		doc.screening_status = "Pending Screening"


def validate_resume_file_type(doc, method=None):
	"""
	Validate that Resume/CV file is PDF or Word format only
	"""
	if doc.resume_attachment:
		try:
			# Get file document
			file_doc = frappe.get_doc("File", {"file_url": doc.resume_attachment})
			file_name = file_doc.file_name or file_doc.name or ""
			file_ext = os.path.splitext(file_name)[1].lower()
			
			# Allowed extensions
			allowed_extensions = [".pdf", ".doc", ".docx"]
			
			if file_ext not in allowed_extensions:
				frappe.throw(
					_("Resume/CV must be a PDF or Word document (.pdf, .doc, .docx). "
					  "Current file: {0}").format(file_name),
					title=_("Invalid File Type")
				)
		except frappe.DoesNotExistError:
			# File might not be saved yet, skip validation
			pass
		except Exception as e:
			# If file URL format is different, try to extract extension from URL
			file_url = doc.resume_attachment
			if file_url:
				file_ext = os.path.splitext(file_url)[1].lower()
				allowed_extensions = [".pdf", ".doc", ".docx"]
				if file_ext and file_ext not in allowed_extensions:
					frappe.throw(
						_("Resume/CV must be a PDF or Word document (.pdf, .doc, .docx). "
						  "Current file: {0}").format(file_url),
						title=_("Invalid File Type")
					)


def set_default_status(doc, method=None):
	"""
	Set default status to "Draft" if not set and document is new
	"""
	if doc.is_new() and not doc.status:
		doc.status = "Draft"


def validate_job_requisition_open(doc, method=None):
	"""
	Validate that Job Opening is still open/published
	Note: job_requisition field now links to Job Opening (not Job Requisition)
	"""
	if doc.job_requisition:
		# job_requisition field now directly links to Job Opening
		job_opening_status = frappe.db.get_value("Job Opening", doc.job_requisition, "status")
		
		if job_opening_status == "Closed":
			frappe.throw(
				_("Cannot apply for Job Opening {0} as it is closed. Please select an open Job Opening.").format(
					doc.job_requisition
				),
				title=_("Job Opening Not Available")
			)
		
		# Check if Job Opening is published
		publish = frappe.db.get_value("Job Opening", doc.job_requisition, "publish")
		if not publish:
			frappe.throw(
				_("Cannot apply for Job Opening {0} as it is not published. Please select a published Job Opening.").format(
					doc.job_requisition
				),
				title=_("Job Opening Not Available")
			)


def validate_job_opening_open(doc, method=None):
	"""
	Validate that Job Opening is still open/published
	"""
	if doc.job_title:
		job_opening_status = frappe.db.get_value("Job Opening", doc.job_title, "status")
		
		if job_opening_status == "Closed":
			frappe.throw(
				_("Cannot apply for Job Opening {0} as it is closed").format(doc.job_title),
				title=_("Job Opening Closed")
			)


def update_status_on_submit(doc, method=None):
	"""
	Update status when document is submitted via web form:
	- Draft → Submitted (on save from web form)
	"""
	# Detect if this is a web form submission
	# Web forms set status to Draft initially, then we change to Submitted on submit
	if doc.status == "Draft" and hasattr(doc, 'web_form_name') and doc.web_form_name:
		doc.status = "Submitted"


def update_status_after_submit(doc, method=None):
	"""
	After submit (document submission), change status to "New Application" and send emails
	For web forms, this is called via after_insert hook
	"""
	# After web form submission, change Submitted → New Application
	if doc.status == "Submitted":
		doc.status = "New Application"
		doc.db_set("status", "New Application", update_modified=False)
		
		# Trigger email notifications after status is set to New Application
		# This ensures emails are sent with the correct status
		send_application_emails(doc)


def handle_web_form_submission(doc, method=None):
	"""
	Handle web form submission: Draft → Submitted
	This is called in before_save/before_insert to detect web form submissions
	"""
	# Check if document is from web form
	is_web_form = hasattr(doc, 'web_form_name') and doc.web_form_name
	
	# If from web form and status is Draft, change to Submitted
	# The after_insert hook will then change it to New Application
	if is_web_form and doc.status == "Draft":
		doc.status = "Submitted"


def process_web_form_submission(doc, method=None):
	"""
	Process web form submission after insert: Automatically trigger workflow action "Submit Application"
	This is called in after_insert to handle web form submissions
	"""
	# Check if document is from web form - detect multiple ways
	is_web_form = False
	
	# Method 1: Check if owner is Guest (web forms typically created by Guest)
	if hasattr(doc, 'owner') and doc.owner == "Guest":
		is_web_form = True
	
	# Method 2: Check web_form_name attribute
	if not is_web_form and hasattr(doc, 'web_form_name') and doc.web_form_name:
		is_web_form = True
	
	# Method 3: Check frappe flags
	if not is_web_form and hasattr(frappe.flags, 'in_web_form') and frappe.flags.in_web_form:
		is_web_form = True
	
	# If not from web form, skip
	if not is_web_form:
		return
	
	# Commit current transaction first to ensure document is saved
	frappe.db.commit()
	
	try:
		# Get fresh document from database after commit
		doc.reload()
		
		# Only proceed if status is Draft
		if doc.status != "Draft":
			return
		
		# Check if workflow exists for this doctype
		from frappe.model.workflow import get_workflow_name, get_workflow
		workflow_name = get_workflow_name("Job Applicant")
		
		if not workflow_name:
			# No workflow found - log but don't fail
			frappe.log_error(
				f"No active workflow found for Job Applicant doctype",
				"Job Applicant Workflow Warning"
			)
			return
		
		# Get workflow to find the correct action name from Draft state
		workflow = get_workflow("Job Applicant")
		
		# Find the transition action from Draft state
		action_name = None
		for transition in workflow.transitions:
			if transition.state == "Draft":
				action_name = transition.action
				break
		
		if not action_name:
			frappe.log_error(
				f"No workflow action found for Draft state in Job Applicant workflow",
				"Job Applicant Workflow Warning"
			)
			return
		
		# Automatically apply the workflow action (e.g., "Submit Application")
		# This will transition from Draft → New Application via the workflow
		# and will automatically submit the document (docstatus = 1)
		from frappe.model.workflow import apply_workflow
		apply_workflow(doc, action_name)
		
		# Commit the workflow changes
		frappe.db.commit()
		
		# Reload document after workflow to get updated status
		doc.reload()
		
		# Trigger email notifications after workflow updates status
		# This ensures emails are sent with the correct status set by workflow
		send_application_emails(doc)
		
	except Exception as e:
		# Log error but don't fail the submission - the document is already saved
		frappe.log_error(
			f"Failed to apply workflow action for Job Applicant {doc.name}: {str(e)}\nTraceback: {frappe.get_traceback()}",
			"Job Applicant Workflow Error"
		)


def send_application_emails(doc):
	"""
	Send email notifications to candidate and HR after application is submitted
	This is called after status changes to New Application
	"""
	try:
		# Get email templates
		candidate_template = "Job Application - Candidate Acknowledgement"
		hr_template = "Job Application - HR Notification"
		
		# Send email to candidate
		if doc.email_id and frappe.db.exists("Email Template", candidate_template):
			# Prepare document context for template
			email_doc = {
				"doctype": "Job Applicant",
				"name": doc.name,
				"applicant_name": doc.applicant_name,
				"email_id": doc.email_id,
				"candidate_id": doc.candidate_id or doc.name,
				"job_requisition": doc.job_requisition or "",
				"job_title": doc.job_title or "",
				"application_date": doc.application_date or frappe.utils.today(),
			}
			
			try:
				# Get and render email template
				email_template = frappe.get_doc("Email Template", candidate_template)
				formatted_email = email_template.get_formatted_email({"doc": email_doc})
				
				frappe.sendmail(
					recipients=[doc.email_id],
					subject=formatted_email["subject"],
					message=formatted_email["message"],
					reference_doctype="Job Applicant",
					reference_name=doc.name,
					now=True
				)
			except Exception as e:
				frappe.log_error(f"Failed to send candidate email: {str(e)}", "Job Applicant Email Error")
		
		# Send email to HR
		if frappe.db.exists("Email Template", hr_template):
			# Get HR Manager role users
			hr_users = frappe.get_all(
				"Has Role",
				filters={"role": "HR Manager", "parenttype": "User"},
				fields=["parent"]
			)
			hr_emails = []
			for hr_user in hr_users:
				user_email = frappe.db.get_value("User", hr_user.parent, "email")
				if user_email:
					hr_emails.append(user_email)
			
			if hr_emails:
				# Prepare document context for template
				email_doc = {
					"doctype": "Job Applicant",
					"name": doc.name,
					"applicant_name": doc.applicant_name,
					"email_id": doc.email_id,
					"phone_number": doc.phone_number or "",
					"candidate_id": doc.candidate_id or doc.name,
					"job_requisition": doc.job_requisition or "",
					"job_title": doc.job_title or "",
					"application_date": doc.application_date or frappe.utils.today(),
					"source": doc.source or "",
					"total_experience": doc.total_experience or "",
				}
				
				try:
					# Get and render email template
					email_template = frappe.get_doc("Email Template", hr_template)
					formatted_email = email_template.get_formatted_email({"doc": email_doc})
					
					frappe.sendmail(
						recipients=hr_emails,
						subject=formatted_email["subject"],
						message=formatted_email["message"],
						reference_doctype="Job Applicant",
						reference_name=doc.name,
						now=True
					)
				except Exception as e:
					frappe.log_error(f"Failed to send HR email: {str(e)}", "Job Applicant Email Error")
	except Exception as e:
		frappe.log_error(f"Error sending application emails: {str(e)}", "Job Applicant Email Error")


def set_application_date(doc, method=None):
	"""
	Set application date to today if not set
	"""
	if not doc.application_date:
		doc.application_date = today()


def validate_mandatory_fields(doc, method=None):
	"""
	Validate all mandatory fields are filled
	"""
	mandatory_fields = [
		("applicant_name", "Full Name"),
		("email_id", "Email"),
		("phone_number", "Mobile Number"),
		("resume_attachment", "Resume/CV"),
		("marital_status", "Marital Status"),
		("city_state", "City / State"),
		("job_requisition", "Job Requisition"),  # Replaces applied_position
		("application_date", "Application Date"),
		("total_experience", "Total Experience"),
		# Employment History fields
		("employment_company_name", "Company Name"),
		("employment_designation", "Designation"),
		("employment_current_ctc", "Current CTC / Annum"),
		("employment_expected_ctc", "Expected CTC / Annum"),
		("employment_reason_for_leaving", "Reason for Leaving"),
		("employment_start_date", "Start Date"),
		("employment_end_date", "End Date"),
		("employment_notice_period", "Notice Period"),
		# Qualification - Removed from mandatory (field is hidden)
		# ("degree", "Degree"),
	]
	
	for fieldname, label in mandatory_fields:
		if not doc.get(fieldname):
			frappe.throw(
				_("{0} is mandatory").format(label),
				title=_("Missing Required Field")
			)


def auto_populate_from_job_requisition(doc, method=None):
	"""
	Auto-populate fields from Job Opening when selected
	Note: job_requisition field now links to Job Opening (not Job Requisition)
	"""
	if doc.job_requisition:
		# job_requisition field now directly links to Job Opening
		job_opening = frappe.get_doc("Job Opening", doc.job_requisition)
		
		if job_opening:
			# Auto-link job_title to the same Job Opening
			doc.job_title = job_opening.name
			
			# Auto-populate designation from Job Opening
			if job_opening.designation:
				doc.designation = job_opening.designation


def auto_populate_from_job_opening(doc, method=None):
	"""
	Auto-populate fields from Job Opening when selected via job_title
	Note: job_requisition field now links directly to Job Opening (not Job Requisition)
	"""
	# This is a fallback - if job_title is selected, sync with job_requisition field
	if doc.job_title and not doc.job_requisition:
		# job_requisition field now directly links to Job Opening
		doc.job_requisition = doc.job_title
		
		# Auto-populate designation
		job_opening = frappe.get_doc("Job Opening", doc.job_title)
		if not doc.designation and job_opening.designation:
			doc.designation = job_opening.designation


def send_acknowledgement_emails(doc, method=None):
	"""
	Send acknowledgement emails to candidate and HR
	This will be triggered by Notification records, but we can also call it here
	"""
	# Emails are sent via Notification records configured in Frappe
	# This method can be used for custom email logic if needed
	pass


@frappe.whitelist()
def ensure_call_round_interview_exists():
	"""
	Ensure "Call Round Interview" Interview Round exists
	Creates it if it doesn't exist
	Returns the Interview Round name
	"""
	round_name = "Call Round Interview"
	
	# Check if it already exists
	if frappe.db.exists("Interview Round", round_name):
		return round_name
	
	# Create the Interview Round
	try:
		interview_round = frappe.get_doc({
			"doctype": "Interview Round",
			"round_name": round_name,
			"expected_average_rating": 0.0
		})
		
		# Try to get a default skill or create a minimal skill set
		# Since expected_skill_set is required, we need to add at least one skill
		# First, try to find any existing skill
		existing_skill = frappe.db.get_value("Skill", {"name": ("!=", "")}, "name")
		
		if not existing_skill:
			# Create a default skill if none exists
			try:
				skill_doc = frappe.get_doc({
					"doctype": "Skill",
					"skill_name": "Communication"
				})
				skill_doc.insert(ignore_permissions=True)
				existing_skill = skill_doc.name
				frappe.db.commit()
			except Exception:
				# If skill creation fails, try to proceed without skill set
				pass
		
		# Add skill to expected_skill_set if we have one
		if existing_skill:
			interview_round.append("expected_skill_set", {
				"skill": existing_skill
			})
		
		# Insert with ignore_permissions to bypass validation if needed
		interview_round.flags.ignore_validate = True
		interview_round.flags.ignore_mandatory = True
		interview_round.insert(ignore_permissions=True)
		frappe.db.commit()
		
		return round_name
		
	except Exception as e:
		frappe.log_error(f"Error creating Call Round Interview: {str(e)}", "Create Interview Round Error")
		# If creation fails, try to return the name anyway (might exist now)
		if frappe.db.exists("Interview Round", round_name):
			return round_name
		raise frappe.ValidationError(_("Could not create Interview Round: {0}").format(str(e)))


def update_screening_status_on_interview_created(doc, method=None):
	"""
	Update Job Applicant screening_status to "Interview Scheduled" when Interview is created
	"""
	if doc.job_applicant:
		try:
			frappe.db.set_value("Job Applicant", doc.job_applicant, "screening_status", "Interview Scheduled")
			frappe.db.commit()
		except Exception as e:
			frappe.log_error(f"Error updating screening status: {str(e)}", "Update Screening Status Error")


def update_screening_status_on_interview_status_change(doc, method=None):
	"""
	Update Job Applicant screening_status based on Interview status changes
	Mapping:
	- "Accepted" → "Accepted"
	- "Rejected" → "Rejected"
	- "Hold" → "On Hold"
	- "Interview Scheduled" → "Interview Scheduled"
	"""
	if doc.job_applicant and doc.has_value_changed("status"):
		try:
			status_mapping = {
				"Accepted": "Accepted",
				"Rejected": "Rejected",
				"Hold": "On Hold",
				"Interview Scheduled": "Interview Scheduled"
			}
			
			new_screening_status = status_mapping.get(doc.status)
			if new_screening_status:
				frappe.db.set_value("Job Applicant", doc.job_applicant, "screening_status", new_screening_status)
				frappe.db.commit()
		except Exception as e:
			frappe.log_error(f"Error updating screening status: {str(e)}", "Update Screening Status Error")

