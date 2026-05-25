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
			_update_email_template(name, data)
		else:
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


def _update_email_template(name, data):
	doc = frappe.get_doc("Email Template", name)
	doc.subject = data["subject"]
	doc.use_html = 1
	doc.response_html = data["response_html"]
	doc.save(ignore_permissions=True)


def _get_templates():
	return {
		# Job Application (already used)
		"Job Application - Candidate Acknowledgement": {
			"subject": "Application received – {{ (doc or {}).get('job_title') or (doc or {}).get('job_requisition') or 'position' }}",
			"response_html": _job_application_candidate_body(),
		},
		"Job Application - HR Notification": {
			"subject": "New application – {{ (doc or {}).get('applicant_name') or 'Candidate' }}",
			"response_html": _job_application_hr_body(),
		},
		# Interview scheduling (already used)
		"Interview Schedule Mail": {
			"subject": "Interview – {{ (doc or {}).get('job_title') or (doc or {}).get('job_requisition') or 'position' }}",
			"response_html": _interview_schedule_body(),
		},
		"Interview Schedule - HR Notification": {
			"subject": "Interview – {{ (doc or {}).get('applicant_name') or 'Candidate' }}",
			"response_html": _interview_schedule_hr_body(),
		},
		# Onboarding (new) – subjects kept ≤140 chars for Email Template field limit
		"Onboarding - Job Confirmation": {
			"subject": "Job confirmation – {{ (doc or {}).get('full_name_display') or (doc or {}).get('applicant_name') or 'Candidate' }}",
			"response_html": _onboarding_job_confirmation_body(),
		},
		"Onboarding - Document Reminder": {
			"subject": "Pre-Onboarding: document upload reminder",
			"response_html": _onboarding_document_reminder_body(),
		},
		# Job Confirmation (from spec doc)
		"Job Confirmation Mail": {
			"subject": "Job confirmation – {{ (doc or {}).get('candidate_name') or (doc or {}).get('applicant_name') or 'Candidate' }}",
			"response_html": _confirmation_mail_body(),
		},
	}


def _interview_schedule_body():
	return _with_alpino_layout("""<p>Hello {{ (doc or {}).get('candidate_name') or (doc or {}).get('applicant_name') or 'Candidate' }},</p>
<p>Thank you for your interest in the {{ (doc or {}).get('job_title') or (doc or {}).get('job_requisition') or '-' }} position at {{ (doc or {}).get('company_name') or (doc or {}).get('company') or 'Alpino Health Foods' }}.</p>
<p>We are pleased to inform you that your profile has been shortlisted, and we would like to schedule an interview with you. Kindly find the interview details below:</p>
<p><strong>Interview Details:</strong></p>
<ul>
<li><strong>Position:</strong> {{ (doc or {}).get('job_title') or (doc or {}).get('job_requisition') or '-' }}</li>
<li><strong>Date:</strong> {{ (doc or {}).get('interview_day') or '' }}{{ ', ' if (doc or {}).get('interview_day') and (doc or {}).get('interview_date') else '' }}{{ (doc or {}).get('interview_date') or '-' }}</li>
<li><strong>Time:</strong> {{ (doc or {}).get('interview_time') or '-' }}{% if (doc or {}).get('time_zone') %} ({{ (doc or {}).get('time_zone') }}){% endif %}</li>
<li><strong>Location:</strong> {{ (doc or {}).get('location_or_link') or '-' }}</li>
<li><strong>Interview Mode:</strong> {{ (doc or {}).get('interview_mode') or '-' }}</li>
</ul>
<p><strong>Contact Person:</strong></p>
<ul>
<li><strong>Name:</strong> {{ (doc or {}).get('interviewer_name') or (doc or {}).get('hr_name') or 'HR Team' }}</li>
<li><strong>Contact Number:</strong> {{ (doc or {}).get('contact_phone') or '-' }}</li>
<li><strong>Email:</strong> {{ (doc or {}).get('contact_email') or (doc or {}).get('hr_email') or '-' }}</li>
</ul>
<p>Kindly confirm your availability by replying to this email. If you are unable to attend at the scheduled time, kindly let us know so we can explore alternative arrangements.</p>
<p>We look forward to meeting you and discussing your experience in more detail.</p>
<p>Best regards,<br/>
{{ (doc or {}).get('hr_name') or 'HR Team' }}<br/>
{{ (doc or {}).get('hr_designation') or '' }}<br/>
{{ (doc or {}).get('company_name') or (doc or {}).get('company') or 'Alpino Health Foods' }}</p>""")


def _interview_schedule_hr_body():
	return _with_alpino_layout("""<p>A new interview has been scheduled.</p>
<p><strong>Candidate:</strong> {{ doc.applicant_name or doc.candidate_name }}<br/>
<strong>Candidate ID:</strong> {{ doc.candidate_id or "" }}<br/>
<strong>Position:</strong> {{ doc.job_title or "" }}<br/>
<strong>Date:</strong> {{ doc.interview_date or "" }}<br/>
<strong>Time:</strong> {{ doc.interview_time or "" }}<br/>
<strong>Mode:</strong> {{ doc.interview_mode or "" }}</p>
<p>Please review the interview details in the system.</p>
<p>Best regards,<br/>System</p>""")


def _confirmation_mail_body():
	return _with_alpino_layout("""<p>Hello {{ (doc or {}).get('candidate_name') or (doc or {}).get('applicant_name') or 'Candidate' }},</p>
<p>We are pleased to inform you that your candidature for the position of {{ (doc or {}).get('job_title') or (doc or {}).get('job_requisition') or '-' }} at {{ (doc or {}).get('company_name') or (doc or {}).get('company') or 'Alpino Health Foods' }} has been confirmed.</p>
<p>We are delighted to confirm your selection and welcome you to join our organization. Your <strong>date of joining</strong> is scheduled as follows:</p>
<p><strong>Joining Details:</strong></p>
<ul>
<li>Position: {{ (doc or {}).get('job_title') or (doc or {}).get('job_requisition') or '-' }}</li>
<li>Department: {{ (doc or {}).get('department_name') or (doc or {}).get('department') or '-' }}</li>
<li>Date of Joining: {{ (doc or {}).get('joining_date') or (doc or {}).get('date_of_joining') or '-' }}</li>
<li>Reporting Location: {{ (doc or {}).get('reporting_location') or (doc or {}).get('location') or (doc or {}).get('office_location') or (doc or {}).get('branch_name') or '-' }}</li>
<li>Reporting To: {{ (doc or {}).get('reporting_to_name') or (doc or {}).get('reporting_manager') or (doc or {}).get('manager_name') or (doc or {}).get('hr_name') or 'HR Team' }}</li>
<li>Reporting Time: {{ (doc or {}).get('reporting_time') or (doc or {}).get('time') or '-' }}</li>
</ul>
<p>Kindly note that your <strong>formal offer letter</strong>, along with <strong>detailed compensation</strong>, will be shared with you <strong>prior to your joining date</strong>.</p>
<p>We are excited about the opportunity to work with you and look forward to your valuable contribution to our team. Should you have any questions in the meantime, kindly feel free to reach out to us.</p>
<p>Once again, congratulations on your selection, and welcome aboard!</p>
<p>Warm regards,<br/>
{{ (doc or {}).get('hr_name') or 'HR Team' }}<br/>
{{ (doc or {}).get('hr_designation') or (doc or {}).get('designation') or '' }}<br/>
{{ (doc or {}).get('company_name') or (doc or {}).get('company') or 'Alpino Health Foods' }}<br/>
{{ (doc or {}).get('hr_email') or (doc or {}).get('hr_email_address') or '' }}{% if ((doc or {}).get('hr_email') or (doc or {}).get('hr_email_address')) and ((doc or {}).get('hr_phone') or (doc or {}).get('hr_phone_number')) %} | {% endif %}{{ (doc or {}).get('hr_phone') or (doc or {}).get('hr_phone_number') or '' }}</p>""")


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
	return _with_alpino_layout("""<p>Hello {{ (doc or {}).get('applicant_name') or 'Candidate' }},</p>
<p>Thank you for applying for the position at {{ (doc or {}).get('company_name') or (doc or {}).get('company') or 'Alpino Health Foods' }}.</p>
<p>We have received your application (Candidate ID: <strong>{{ (doc or {}).get('candidate_id') or (doc or {}).get('name') or '-' }}</strong>) for <strong>{{ (doc or {}).get('job_title') or (doc or {}).get('job_requisition') or 'the position' }}</strong>. Our HR team will review your profile and get in touch with you if your qualifications match our requirements.</p>
<p>We appreciate your interest in joining our team and will keep you updated on the status of your application.</p>
<p>Best regards,<br/>HR Team<br/>{{ (doc or {}).get('company_name') or (doc or {}).get('company') or 'Alpino Health Foods' }}</p>""")


def _job_application_hr_body():
	return _with_alpino_layout("""<p>A new job application has been submitted.</p>
<p><strong>Candidate:</strong> {{ (doc or {}).get('applicant_name') or '-' }}<br/>
<strong>Candidate ID:</strong> {{ (doc or {}).get('candidate_id') or (doc or {}).get('name') or '-' }}<br/>
<strong>Email:</strong> {{ (doc or {}).get('email_id') or '-' }}<br/>
<strong>Phone:</strong> {{ (doc or {}).get('phone_number') or '-' }}<br/>
<strong>Position:</strong> {{ (doc or {}).get('job_title') or (doc or {}).get('job_requisition') or '-' }}<br/>
<strong>Application Date:</strong> {{ (doc or {}).get('application_date') or (doc or {}).get('creation') or '-' }}</p>
<p>Please review the application in the system.</p>
<p>Best regards,<br/>System</p>""")


def _job_applicant_rejection_body():
	return """<p>Hello {{ (doc or {}).get('applicant_name') or 'Candidate' }},</p>
<p>Thank you for your interest in the {{ (doc or {}).get('job_title') or (doc or {}).get('job_requisition') or 'the' }} position at {{ (doc or {}).get('company_name') or (doc or {}).get('company') or 'our company' }}.</p>
<p>After careful consideration, we regret to inform you that we will not be moving forward with your application at this time. We encourage you to apply for other suitable positions that match your profile.</p>
<p>We wish you the best in your job search.</p>
<p>Best regards,<br/>HR Team<br/>{{ (doc or {}).get('company_name') or (doc or {}).get('company') or '' }}</p>"""


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


def _onboarding_job_confirmation_body():
	return _with_alpino_layout("""<p>Hello {{ (doc or {}).get('candidate_name') or (doc or {}).get('full_name_display') or (doc or {}).get('applicant_name') or 'Candidate' }},</p>
<p>We are pleased to inform you that your candidature for the position of {{ (doc or {}).get('job_title') or (doc or {}).get('designation') or '-' }} at {{ (doc or {}).get('company_name') or (doc or {}).get('company') or 'Alpino Health Foods' }} has been confirmed.</p>
<p>We are delighted to confirm your selection and welcome you to join our organization. Your <strong>date of joining</strong> is scheduled as follows:</p>
<p><strong>Joining Details:</strong></p>
<ul>
<li>Position: {{ (doc or {}).get('job_title') or (doc or {}).get('designation') or '-' }}</li>
<li>Department: {{ (doc or {}).get('department_name') or (doc or {}).get('department') or '-' }}</li>
<li>Date of Joining: {{ (doc or {}).get('joining_date') or (doc or {}).get('date_of_joining') or (doc or {}).get('date_of_joining_onboarding') or '-' }}</li>
<li>Reporting Location: {{ (doc or {}).get('reporting_location') or (doc or {}).get('location') or (doc or {}).get('office_location') or (doc or {}).get('branch_name') or '-' }}</li>
<li>Reporting To: {{ (doc or {}).get('reporting_to_name') or (doc or {}).get('reporting_manager') or (doc or {}).get('manager_name') or (doc or {}).get('hr_name') or 'HR Team' }}</li>
<li>Reporting Time: {{ (doc or {}).get('reporting_time') or (doc or {}).get('time') or '-' }}</li>
</ul>
<p>Kindly note that your <strong>formal offer letter</strong>, along with <strong>detailed compensation</strong>, will be shared with you <strong>prior to your joining date</strong>.</p>
<p>We are excited about the opportunity to work with you and look forward to your valuable contribution to our team. Should you have any questions in the meantime, kindly feel free to reach out to us.</p>
<p>Once again, congratulations on your selection, and welcome aboard!</p>
<p>Warm regards,<br/>
{{ (doc or {}).get('hr_name') or 'HR Team' }}<br/>
{{ (doc or {}).get('hr_designation') or (doc or {}).get('designation') or '' }}<br/>
{{ (doc or {}).get('company_name') or (doc or {}).get('company') or 'Alpino Health Foods' }}<br/>
{{ (doc or {}).get('hr_email') or (doc or {}).get('hr_email_address') or '' }}{% if ((doc or {}).get('hr_email') or (doc or {}).get('hr_email_address')) and ((doc or {}).get('hr_phone') or (doc or {}).get('hr_phone_number')) %} | {% endif %}{{ (doc or {}).get('hr_phone') or (doc or {}).get('hr_phone_number') or '' }}</p>""")


def _onboarding_document_reminder_body():
	return _with_alpino_layout("""<p>Hello {{ (doc or {}).get('candidate_name') or (doc or {}).get('full_name_display') or 'Candidate' }},</p>
<p>Congratulations once again on your selection for the position of <strong>{{ (doc or {}).get('job_title') or (doc or {}).get('designation') or '-' }}</strong> at <strong>{{ (doc or {}).get('company_name') or (doc or {}).get('company') or 'Alpino Health Foods' }}</strong>.</p>
<p>The purpose of this email is to guide you through your <strong>pre-joining process</strong> via our <strong>onboarding portal</strong>. This process includes creating your login credentials, completing your profile details, and uploading the required documents.</p>
<p><strong>• Action Required</strong></p>
<p>Kindly click the button below to access the onboarding portal:</p>
<p style="text-align:center;margin:24px 0;"><a href="{{ (doc or {}).get('webform_link') or (doc or {}).get('onboarding_link') or '#' }}" style="background:#15803d;color:#ffffff;padding:12px 24px;text-decoration:none;border-radius:6px;font-weight:600;display:inline-block;">Complete Your Joining Process</a></p>
<p><strong>Steps to follow:</strong></p>
<ol style="margin:16px 0;padding-left:24px;">
<li>Click the link above and create your password.</li>
<li>Log in to the portal using your registered email ID.</li>
<li>Complete all pending profile details.</li>
<li>Upload the required documents listed below.</li>
<li>Submit the information for HR verification.</li>
</ol>
<p><strong>Documents Required</strong></p>
<p>Kindly keep the following documents ready for upload (scanned copies / clear photos):</p>
<ul style="margin:16px 0;padding-left:24px;">
<li>Aadhar Card</li>
<li>PAN Card</li>
<li>School Leaving Certificate</li>
<li>Last Marksheet with Degree Certificate</li>
<li>Experience/Relieving Letter of all previous employers</li>
<li>Bank Cheque photo</li>
<li>Passport Size Photo</li>
<li>Last 3 Months Salary Slips</li>
<li>Last 3 Months Bank Statement</li>
<li>Offer Letter/Appointment Letter of the previous employer</li>
</ul>
<p>Kindly ensure that all details are accurate and documents are clearly readable. This will help us complete the onboarding process smoothly before your date of joining: <strong>{{ (doc or {}).get('joining_date') or (doc or {}).get('date_of_joining_onboarding') or '-' }}</strong>.</p>
<p>If you face any issues while accessing the portal or uploading documents, kindly contact us at <strong>{{ (doc or {}).get('hr_email') or (doc or {}).get('hr_email_address') or '' }}</strong>{% if (doc or {}).get('hr_email') or (doc or {}).get('hr_email_address') %} or {% endif %}<strong>{{ (doc or {}).get('hr_phone') or (doc or {}).get('hr_phone_number') or '' }}</strong>.</p>
<p>We look forward to welcoming you to <strong>{{ (doc or {}).get('company_name') or (doc or {}).get('company') or 'Alpino Health Foods' }}</strong>.</p>
<p>Warm regards,<br/>
<strong>{{ (doc or {}).get('hr_name') or 'HR Team' }}</strong><br/>
<strong>{{ (doc or {}).get('hr_designation') or '' }}</strong><br/>
<strong>{{ (doc or {}).get('company_name') or (doc or {}).get('company') or 'Alpino Health Foods' }}</strong><br/>
{{ (doc or {}).get('hr_email') or (doc or {}).get('hr_email_address') or '' }}{% if ((doc or {}).get('hr_email') or (doc or {}).get('hr_email_address')) and ((doc or {}).get('hr_phone') or (doc or {}).get('hr_phone_number')) %} | {% endif %}{{ (doc or {}).get('hr_phone') or (doc or {}).get('hr_phone_number') or '' }}</p>""")


def _with_alpino_layout(content_html):
	# Default Alpino logo URL
	alpino_logo_url = "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcR0cfjJi3U8tgoX4Jk3zp07AXjRNveFA-jxLA&s"
	
	return f"""<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#1f2937;line-height:1.6;">
<div style="text-align:center;background:#15803d;padding:16px 12px;border-radius:8px 8px 0 0;">
{{% set logo_url = (doc or {{}}).get('company_logo') or '{alpino_logo_url}' %}}
<img src="{{{{ logo_url }}}}" alt="Alpino" style="max-height:72px;max-width:260px;height:auto;" />
</div>
<div style="padding:18px 16px;background:#ffffff;border:1px solid #e5e7eb;border-top:0;">
{content_html}
</div>
<div style="padding:14px 16px;background:#f8fafc;border:1px solid #e5e7eb;border-top:0;border-radius:0 0 8px 8px;font-size:13px;color:#374151;">
<p style="margin:0 0 8px 0;"><strong>Website:</strong> <a href="https://alpino.store/" target="_blank">https://alpino.store/</a></p>
<p style="margin:0 0 8px 0;"><strong>Address:</strong> Alpino Health Foods, Bungalow No.7, Napoleon Estate, Near VR Mall, Udhana-Magdalla Road, New Magdalla, Dumas, Surat, Gujarat - 395007, India</p>
<p style="margin:0;"><strong>Social:</strong>
<a href="https://www.linkedin.com/company/alpinohealthfoods/" target="_blank">LinkedIn</a> |
<a href="https://www.instagram.com/alpinohealthfoods" target="_blank">Instagram</a> |
<a href="https://www.facebook.com/alpinohealthfoods" target="_blank">Facebook</a>
</p>
</div>
</div>"""
