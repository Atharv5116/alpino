# Email Template Bodies (Jinja) – Copy to Setup → Email Template

Use **Use HTML** = Yes and paste into **Response HTML**. Replace `doc.xxx` with your context keys (see HRMS_EMAIL_TEMPLATES_SPEC.md).

---

## Interview Schedule Mail

**Subject:** Interview scheduled – {{ doc.job_title }} at {{ doc.company_name }}

**Response HTML:**

```
Hello {{ doc.candidate_name }},

Thank you for your interest in the {{ doc.job_title }} position at {{ doc.company_name }}.

We are pleased to inform you that your profile has been shortlisted, and we would like to schedule an interview with you. Kindly find the interview details below:

Interview Details:
- Position: {{ doc.job_title }}
- Date: {{ doc.interview_day }}, {{ doc.interview_date }}
- Time: {{ doc.interview_time }} ({{ doc.time_zone }})
- Location: {{ doc.location_or_link }}
- Interview Mode: {{ doc.interview_mode }}
Contact Person: {{ doc.interviewer_name }}
Contact Number: {{ doc.contact_phone }}
Email: {{ doc.contact_email }}

Kindly confirm your availability by replying to this email. If you are unable to attend at the scheduled time, kindly let us know so we can explore alternative arrangements.

We look forward to meeting you and discussing your experience in more detail.

Best regards,
{{ doc.hr_name }}
{{ doc.hr_designation }}
{{ doc.company_name }}
```

---

## Confirmation Mail

**Subject:** Your candidature confirmed – {{ doc.job_title }} at {{ doc.company_name }}

**Response HTML:**

```
Hello {{ doc.candidate_name }},

We are pleased to inform you that your candidature for the position of {{ doc.job_title }} at {{ doc.company_name }} has been confirmed.

We are delighted to confirm your selection and welcome you to join our organization. Your date of joining is scheduled as follows:

Joining Details:
- Position: {{ doc.job_title }}
- Department: {{ doc.department_name }}
- Date of Joining: {{ doc.joining_date }}
- Reporting Location: {{ doc.reporting_location }}
- Reporting To: {{ doc.reporting_to_name }}
- Reporting Time: {{ doc.reporting_time }}

Kindly note that your formal offer letter, along with detailed compensation, will be shared with you prior to your joining date.

We are excited about the opportunity to work with you and look forward to your valuable contribution to our team. Should you have any questions in the meantime, kindly feel free to reach out to us.

Once again, congratulations on your selection, and welcome aboard!

Warm regards,
{{ doc.hr_name }}
{{ doc.hr_designation }}
{{ doc.company_name }}
{{ doc.hr_email }} | {{ doc.hr_phone }}
```

---

## Pre Onboarding Mail

**Subject:** Pre-joining: Complete your onboarding before {{ doc.joining_date }} – {{ doc.company_name }}

**Response HTML:**

```
Hello {{ doc.candidate_name }},

Congratulations once again on your selection for the position of {{ doc.job_title }} at {{ doc.company_name }}.

To proceed with your joining formalities, we request you to complete your pre-joining process through our onboarding portal. This includes creating your login credentials, completing your profile details, and uploading the required documents.

Action Required
Kindly click the link below to access the onboarding portal:
{{ doc.onboarding_portal_link }}

Steps to follow:
1. Click the link above and create your password.
2. Log in to the portal using your registered email ID.
3. Complete all pending profile details.
4. Upload the required documents listed below.
5. Submit the information for HR verification.

Documents Required (scanned copies / clear photos):
- Aadhar Card
- PAN Card
- School Leaving Certificate
- Last Marksheet and Degree Certificate
- Experience/Relieving Letter of all previous employers
- Bank Cheque photo
- Passport Size Photo
- Last 3 Months Salary Slips
- Last 3 Months Bank Statement
- Offer Letter/Appointment Letter of the previous employer

Kindly ensure that all details are accurate and documents are clearly readable. This will help us complete the onboarding process smoothly before your date of joining: {{ doc.joining_date }}.

If you face any issues while accessing the portal or uploading documents, kindly contact us at {{ doc.hr_email }} or {{ doc.hr_phone }}.

We look forward to welcoming you to {{ doc.company_name }}.

Warm regards,
{{ doc.hr_name }}
{{ doc.hr_designation }}
{{ doc.company_name }}
{{ doc.hr_email }} | {{ doc.hr_phone }}
```

---

## Salary Slip

**Subject:** Salary slip for {{ doc.month_year }} – {{ doc.company_name }}

**Response HTML:**

```
Hello {{ doc.employee_name }},

Kindly find attached your salary slip for the month of {{ doc.month_year }} for your reference and records.

We request you to review the details carefully. If you have any questions or notice any discrepancies, kindly contact the HR.

For confidentiality reasons, we advise you not to share your salary slip with anyone.

Thank you.

Best regards,
HR Team
{{ doc.company_name }}
```

(Attach Salary Slip PDF when sending from Payroll app.)
