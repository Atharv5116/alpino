"""
Patch: Create HRMS Email Templates as per spec and SRS.
From HRMS spec doc: Interview Schedule Mail, Confirmation Mail, Pre Onboarding Mail, Salary Slip.
From code: Job Application - Candidate Acknowledgement, Job Application - HR Notification.
From SRS (not in spec doc): Job Applicant - Rejection, Employee Onboarding - Complete Profile,
Probation - Near Completion, Probation - Complete.
"""

import frappe


def execute():
	templates = _get_templates()
	for name, data in templates.items():
		if frappe.db.exists("Email Template", name):
			continue
		_create_email_template(name, data)
	frappe.db.commit()


def _create_email_template(name, data):
	doc = frappe.get_doc(
		{
			"doctype": "Email Template",
			"name": name,
			"subject": data["subject"],
			"use_html": 1,
			"response_html": data["response_html"],
		}
	)
	doc.insert(ignore_permissions=True)


def _get_templates():
	return {
		"Interview Schedule Mail": {
			"subject": "Interview scheduled – {{ doc.job_title }} at {{ doc.company_name }}",
			"response_html": _interview_schedule_body(),
		},
		"Confirmation Mail": {
			"subject": "Your candidature confirmed – {{ doc.job_title }} at {{ doc.company_name }}",
			"response_html": _confirmation_mail_body(),
		},
		"Pre Onboarding Mail": {
			"subject": "Pre-joining: Complete your onboarding before {{ doc.joining_date }} – {{ doc.company_name }}",
			"response_html": _pre_onboarding_mail_body(),
		},
		"Salary Slip": {
			"subject": "Salary slip for {{ doc.month_year }} – {{ doc.company_name }}",
			"response_html": _salary_slip_body(),
		},
		"Job Application - Candidate Acknowledgement": {
			"subject": "Application received – {{ doc.job_title or doc.job_requisition }}",
			"response_html": _job_application_candidate_body(),
		},
		"Job Application - HR Notification": {
			"subject": "New job application – {{ doc.applicant_name }} ({{ doc.candidate_id or doc.name }})",
			"response_html": _job_application_hr_body(),
		},
		# SRS requirements not in HRMS spec doc
		"Job Applicant - Rejection": {
			"subject": "Update on your application – {{ doc.job_title or doc.job_requisition }}",
			"response_html": _job_applicant_rejection_body(),
		},
		"Employee Onboarding - Complete Profile": {
			"subject": "Complete your profile – {{ doc.company_name }}",
			"response_html": _complete_profile_body(),
		},
		"Probation - Near Completion": {
			"subject": "Probation ending soon – {{ doc.employee_name }}",
			"response_html": _probation_near_completion_body(),
		},
		"Probation - Complete": {
			"subject": "Probation completed – {{ doc.employee_name }}",
			"response_html": _probation_complete_body(),
		},
	}


def _interview_schedule_body():
	return """<p>Hello {{ doc.candidate_name }},</p>
<p>Thank you for your interest in the {{ doc.job_title }} position at {{ doc.company_name }}.</p>
<p>We are pleased to inform you that your profile has been shortlisted, and we would like to schedule an interview with you. Kindly find the interview details below:</p>
<p><strong>Interview Details:</strong></p>
<ul>
<li>Position: {{ doc.job_title }}</li>
<li>Date: {{ doc.interview_day }}, {{ doc.interview_date }}</li>
<li>Time: {{ doc.interview_time }} ({{ doc.time_zone }})</li>
<li>Location: {{ doc.location_or_link }}</li>
<li>Interview Mode: {{ doc.interview_mode }}</li>
<li>Contact Person: {{ doc.interviewer_name }}</li>
<li>Contact Number: {{ doc.contact_phone }}</li>
<li>Email: {{ doc.contact_email }}</li>
</ul>
<p>Kindly confirm your availability by replying to this email. If you are unable to attend at the scheduled time, kindly let us know so we can explore alternative arrangements.</p>
<p>We look forward to meeting you and discussing your experience in more detail.</p>
<p>Best regards,<br/>
{{ doc.hr_name }}<br/>
{{ doc.hr_designation }}<br/>
{{ doc.company_name }}</p>"""


def _confirmation_mail_body():
	return """<p>Hello {{ doc.candidate_name }},</p>
<p>We are pleased to inform you that your candidature for the position of {{ doc.job_title }} at {{ doc.company_name }} has been confirmed.</p>
<p>We are delighted to confirm your selection and welcome you to join our organization. Your date of joining is scheduled as follows:</p>
<p><strong>Joining Details:</strong></p>
<ul>
<li>Position: {{ doc.job_title }}</li>
<li>Department: {{ doc.department_name }}</li>
<li>Date of Joining: {{ doc.joining_date }}</li>
<li>Reporting Location: {{ doc.reporting_location }}</li>
<li>Reporting To: {{ doc.reporting_to_name }}</li>
<li>Reporting Time: {{ doc.reporting_time }}</li>
</ul>
<p>Kindly note that your formal offer letter, along with detailed compensation, will be shared with you prior to your joining date.</p>
<p>We are excited about the opportunity to work with you and look forward to your valuable contribution to our team. Should you have any questions in the meantime, kindly feel free to reach out to us.</p>
<p>Once again, congratulations on your selection, and welcome aboard!</p>
<p>Warm regards,<br/>
{{ doc.hr_name }}<br/>
{{ doc.hr_designation }}<br/>
{{ doc.company_name }}<br/>
{{ doc.hr_email }} | {{ doc.hr_phone }}</p>"""


def _pre_onboarding_mail_body():
	return """<p>Hello {{ doc.candidate_name }},</p>
<p>Congratulations once again on your selection for the position of {{ doc.job_title }} at {{ doc.company_name }}.</p>
<p>To proceed with your joining formalities, we request you to complete your pre-joining process through our onboarding portal. This includes creating your login credentials, completing your profile details, and uploading the required documents.</p>
<p><strong>Action Required</strong></p>
<p>Kindly click the link below to access the onboarding portal:</p>
<p><a href="{{ doc.onboarding_portal_link }}" style="background:#2490ef;color:#fff;padding:10px 20px;text-decoration:none;border-radius:5px;">Complete Your Joining Process</a></p>
<p><strong>Steps to follow:</strong></p>
<ol>
<li>Click the link above and create your password.</li>
<li>Log in to the portal using your registered email ID.</li>
<li>Complete all pending profile details.</li>
<li>Upload the required documents listed below.</li>
<li>Submit the information for HR verification.</li>
</ol>
<p><strong>Documents Required</strong> (scanned copies / clear photos):</p>
<ul>
<li>Aadhar Card</li>
<li>PAN Card</li>
<li>School Leaving Certificate</li>
<li>Last Marksheet and Degree Certificate</li>
<li>Experience/Relieving Letter of all previous employers</li>
<li>Bank Cheque photo</li>
<li>Passport Size Photo</li>
<li>Last 3 Months Salary Slips</li>
<li>Last 3 Months Bank Statement</li>
<li>Offer Letter/Appointment Letter of the previous employer</li>
</ul>
<p>Kindly ensure that all details are accurate and documents are clearly readable. This will help us complete the onboarding process smoothly before your date of joining: {{ doc.joining_date }}.</p>
<p>If you face any issues while accessing the portal or uploading documents, kindly contact us at {{ doc.hr_email }} or {{ doc.hr_phone }}.</p>
<p>We look forward to welcoming you to {{ doc.company_name }}.</p>
<p>Warm regards,<br/>
{{ doc.hr_name }}<br/>
{{ doc.hr_designation }}<br/>
{{ doc.company_name }}<br/>
{{ doc.hr_email }} | {{ doc.hr_phone }}</p>"""


def _salary_slip_body():
	return """<p>Hello {{ doc.employee_name }},</p>
<p>Kindly find attached your salary slip for the month of {{ doc.month_year }} for your reference and records.</p>
<p>We request you to review the details carefully. If you have any questions or notice any discrepancies, kindly contact the HR.</p>
<p>For confidentiality reasons, we advise you not to share your salary slip with anyone.</p>
<p>Thank you.</p>
<p>Best regards,<br/>HR Team<br/>{{ doc.company_name }}</p>"""


def _job_application_candidate_body():
	return """<p>Hello {{ doc.applicant_name }},</p>
<p>Thank you for applying for the position at our company.</p>
<p>We have received your application (Candidate ID: {{ doc.candidate_id or doc.name }}) for {{ doc.job_title or doc.job_requisition }}. Our HR team will review your profile and get in touch with you if your qualifications match our requirements.</p>
<p>Best regards,<br/>HR Team</p>"""


def _job_application_hr_body():
	return """<p>A new job application has been submitted.</p>
<p><strong>Candidate:</strong> {{ doc.applicant_name }}<br/>
<strong>Candidate ID:</strong> {{ doc.candidate_id or doc.name }}<br/>
<strong>Email:</strong> {{ doc.email_id }}<br/>
<strong>Phone:</strong> {{ doc.phone_number or '-' }}<br/>
<strong>Position:</strong> {{ doc.job_title or doc.job_requisition }}<br/>
<strong>Application Date:</strong> {{ doc.application_date or doc.creation }}</p>
<p>Please review the application in the system.</p>
<p>Best regards,<br/>System</p>"""


def _job_applicant_rejection_body():
	return """<p>Hello {{ doc.applicant_name }},</p>
<p>Thank you for your interest in the {{ doc.job_title or doc.job_requisition }} position at {{ doc.company_name or 'our company' }}.</p>
<p>After careful consideration, we regret to inform you that we will not be moving forward with your application at this time. We encourage you to apply for other suitable positions that match your profile.</p>
<p>We wish you the best in your job search.</p>
<p>Best regards,<br/>HR Team<br/>{{ doc.company_name or '' }}</p>"""


def _complete_profile_body():
	return """<p>Hello {{ doc.candidate_name }},</p>
<p>Welcome to {{ doc.company_name }}. Your date of joining is {{ doc.joining_date }}.</p>
<p>To complete your onboarding, please log in to the portal and fill in any pending profile details.</p>
<p><a href="{{ doc.profile_completion_link }}" style="background:#2490ef;color:#fff;padding:10px 20px;text-decoration:none;border-radius:5px;">Complete Your Profile</a></p>
<p>If you have any questions, please contact HR at {{ doc.hr_email }} or {{ doc.hr_phone }}.</p>
<p>Best regards,<br/>HR Team<br/>{{ doc.company_name }}</p>"""


def _probation_near_completion_body():
	return """<p>Hello {{ doc.recipient_name }},</p>
<p>This is a reminder that the probation period for <strong>{{ doc.employee_name }}</strong> ({{ doc.employee_id }}) is ending on {{ doc.probation_end_date }}.</p>
<p>Please complete the probation review and take the necessary action.</p>
<p>Best regards,<br/>HR Team<br/>{{ doc.company_name }}</p>"""


def _probation_complete_body():
	return """<p>Hello {{ doc.recipient_name }},</p>
<p>The probation period for <strong>{{ doc.employee_name }}</strong> ({{ doc.employee_id }}) has been completed on {{ doc.probation_end_date }}.</p>
<p>Please ensure confirmation and related formalities are completed.</p>
<p>Best regards,<br/>HR Team<br/>{{ doc.company_name }}</p>"""
