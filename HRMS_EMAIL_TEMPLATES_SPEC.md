# HRMS Email Templates – Spec vs Alpinos

Maps your HRMS Email Template spec to Frappe Email Template names, Jinja placeholders, and where to use them in Alpinos.

---

## 1. Global header and footer

**Your spec:** Header = Company Logo, Email Name. Footer = Website Link, Address, Social Media (LinkedIn, Instagram, Facebook, Youtube, Pinterest).

**In Frappe:** No built-in global header/footer. Add the same HTML block at top and bottom of each Email Template in Setup, or build it in code. Pass in `doc`: `company_logo_url`, `email_name`, `website_url`, `company_address`, `linkedin_url`, `instagram_url`, `facebook_url`, `youtube_url`, `pinterest_url` (or leave blank for optional).

---

## 2. Interview Schedule Mail

**Your spec:** To Candidate. Copy: To Reporting Person, CC HR.

**Frappe template name:** `Interview Schedule Mail`

**Placeholder mapping (pass in `doc` when sending):**

| Your placeholder | Use in Jinja | Source in code |
|------------------|--------------|----------------|
| Candidate Name | `doc.candidate_name` | Job Applicant `applicant_name` |
| Job Title | `doc.job_title` | Job Opening designation/name |
| Company Name | `doc.company_name` | Company |
| Interview Day | `doc.interview_day` | e.g. Monday from scheduled date |
| Interview Date | `doc.interview_date` | Interview scheduled date |
| Interview Time | `doc.interview_time` | Interview from_time / to_time |
| Time Zone | `doc.time_zone` | Company/system timezone |
| Office Address / Virtual Link | `doc.location_or_link` | Interview location or link |
| Interview Mode | `doc.interview_mode` | In-person / Online / Hybrid |
| Interviewer / HR Name | `doc.interviewer_name` | From Interview Round / interview_details |
| Phone Number | `doc.contact_phone` | HR / interviewer |
| Email Address | `doc.contact_email` | HR / interviewer |

**Where to use:** New file `alpinos/interview_notifications.py`. Trigger when Interview is created or status set to Scheduled. Send to candidate; copy to RM and CC HR. Register in `hooks.py` doc_events for Interview.

**Subject (Jinja):** `Interview scheduled – {{ doc.job_title }} at {{ doc.company_name }}`

---

## 3. Confirmation Mail

**Your spec:** To Candidate. Copy: TO Reporting Person, CC HR and HOD.

**Frappe template name:** `Confirmation Mail`

**Placeholder mapping:**

| Your placeholder | Use in Jinja | Source in code |
|------------------|--------------|----------------|
| Candidate Name | `doc.candidate_name` | Employee Onboarding / Job Applicant applicant_name |
| Job Title | `doc.job_title` | Employee Onboarding designation |
| Company Name | `doc.company_name` | Employee Onboarding company |
| Joining Date | `doc.joining_date` | date_of_joining_onboarding |
| Department Name | `doc.department_name` | department |
| Office Location / Branch | `doc.reporting_location` | location |
| Manager / HR Name | `doc.reporting_to_name` | reporting_manager / hod |
| Time | `doc.reporting_time` | Optional |
| HR Name, Designation, Email, Phone | `doc.hr_name`, `doc.hr_designation`, `doc.hr_email`, `doc.hr_phone` | From User/Employee |

**Where to use:** `alpinos/employee_onboarding_automation.py`. Add function e.g. `send_job_confirmation_email(doc)` and call from doc_events when Employee Onboarding status becomes "Job Confirmed". To: Candidate; copy: RM; CC: HR and HOD.

**Subject (Jinja):** `Your candidature confirmed – {{ doc.job_title }} at {{ doc.company_name }}`

---

## 4. Pre Onboarding Mail

**Your spec:** To Candidate. Link + list of documents (Aadhar, PAN, etc.).

**Frappe template name:** `Pre Onboarding Mail`

**Placeholder mapping:**

| Your placeholder | Use in Jinja | Source in code |
|------------------|--------------|----------------|
| Candidate Name | `doc.candidate_name` | Job Applicant applicant_name |
| Job Title | `doc.job_title` | Employee Onboarding designation |
| Company Name | `doc.company_name` | company |
| Onboarding Portal Link | `doc.onboarding_portal_link` | e.g. /app/employee-onboarding/{{ name }} or portal URL |
| Joining Date | `doc.joining_date` | date_of_joining_onboarding |
| HR Email, Phone, Name, Designation | `doc.hr_email`, `doc.hr_phone`, `doc.hr_name`, `doc.hr_designation` | HR User/Employee |

**Where to use:** `alpinos/employee_onboarding_automation.py`. In `send_pre_onboarding_email()` replace the hardcoded message with: get Email Template "Pre Onboarding Mail", build `doc` with above keys, call `get_formatted_email({"doc": doc})`, then frappe.sendmail with subject and message.

**Subject (Jinja):** `Pre-joining: Complete your onboarding before {{ doc.joining_date }} – {{ doc.company_name }}`

**Body:** Use your full Pre Onboarding Mail text in the template; replace placeholders with `{{ doc.xxx }}` as in the table. Keep the document list (Aadhar, PAN, etc.) in the template body.

---

## 5. Salary Slip

**Your spec:** To Employee. Attach salary slip.

**Frappe template name:** `Salary Slip`

**Placeholder mapping:** `doc.employee_name`, `doc.month_year`, `doc.company_name` (from Salary Slip doctype).

**Where to use:** HRMS/Payroll app (not Alpinos). After payment confirmation, next day: for each Salary Slip get template, build doc, attach PDF, send to employee personal email.

**Subject (Jinja):** `Salary slip for {{ doc.month_year }} – {{ doc.company_name }}`

---

## 6. Already in Alpinos (Job Application)

These are separate from your 4 templates and already wired:

- **Job Application - Candidate Acknowledgement** – used in `job_applicant_automation.send_application_emails` (to candidate after submit).
- **Job Application - HR Notification** – same function (to HR Managers).

No change needed; only add the 4 templates above.

---

## 7. Checklist – Create in Setup then wire in code

1. Create Email Template **Interview Schedule Mail** (subject + body with doc.xxx). Use in `interview_notifications.py` when interview scheduled.
2. Create **Confirmation Mail**. Use in `employee_onboarding_automation.py` when status = Job Confirmed.
3. Create **Pre Onboarding Mail**. Use in `send_pre_onboarding_email()` instead of hardcoded body.
4. Create **Salary Slip**. Use in Payroll app after payment confirmation.
5. Optionally add header/footer HTML to each template and pass company logo, website, address, social links in `doc`.
ocation / Branch | `{{ doc.reporting_location }}` | Employee Onboarding: location |
| Manager / HR Name    | `{{ doc.reporting_to_name }}` | Employee Onboarding: reporting_manager / hod |
| Time                 | `{{ doc.reporting_time }}` | Optional – default or custom field |
| HR Name / Designation / Email / Phone | Same as footer / signature | From User/Employee |

**Where to use in Alpinos:**  
- **File:** `alpinos/employee_onboarding_automation.py`.  
- **When:** Employee Onboarding status is set to “Job Confirmed” (or your confirmation status).  
- **Recipients:** Candidate (To), Reporting Person (To), HR & HOD (CC).  
- **Code:** Add e.g. `send_job_confirmation_email(doc)` in `doc_events["Employee Onboarding"]` on_update when status becomes “Job Confirmed”; build `doc` from Employee Onboarding + Job Applicant + Company; use template `Confirmation Mail`.

**Body (Jinja):**

```html
<p>Hello {{ doc.candidate_name }},</p>
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
{{ doc.hr_email }} | {{ doc.hr_phone }}</p>
```

---

## 4. Pre Onboarding Mail (document upload – 1 week before DOJ)

**Your spec:** To Candidate. Link + list of documents.

**Frappe Email Template name:**  
`Pre Onboarding Mail`

**Subject (Jinja):**  
`Pre-joining: Complete your onboarding before {{ doc.joining_date }} – {{ doc.company_name }}`

**Context to pass from code:**

| Your placeholder     | Jinja                    | Source in code |
|----------------------|--------------------------|----------------|
| Candidate Name       | `{{ doc.candidate_name }}` | Job Applicant / Employee Onboarding |
| Job Title            | `{{ doc.job_title }}`    | Employee Onboarding |
| Company Name         | `{{ doc.company_name }}` | Company |
| Onboarding Portal Link | `{{ doc.onboarding_portal_link }}` | e.g. `/app/employee-onboarding/{{ doc.name }}` or portal URL |
| Joining Date         | `{{ doc.joining_date }}` | date_of_joining_onboarding |
| HR Email / Phone     | `{{ doc.hr_email }}`, `{{ doc.hr_phone }}` | From HR User / Employee |
| HR Name, Designation | `{{ doc.hr_name }}`, `{{ doc.hr_designation }}` | Optional |

**Where to use in Alpinos:**  
- **File:** `alpinos/employee_onboarding_automation.py`.  
- **Current:** `send_pre_onboarding_email()` builds the body in Python (no Email Template).  
- **Change:** Create Email Template `Pre Onboarding Mail` and use it here: build `doc` with the keys above (and `name` for link), call `get_formatted_email({"doc": doc})`, then `frappe.sendmail` with that subject and message. Optionally keep the same document list in the template body as in your spec (Aadhar, PAN, etc.).

**Body (Jinja)** – use in Response HTML (document list as in your spec):

```html
<p>Hello {{ doc.candidate_name }},</p>
<p>Congratulations once again on your selection for the position of {{ doc.job_title }} at {{ doc.company_name }}.</p>
<p>To proceed with your joining formalities, we request you to complete your pre-joining process through our onboarding portal. This includes creating your login credentials, completing your profile details, and uploading the required documents.</p>
<p><strong>Action Required</strong></p>
<p>Kindly click the button below to access the onboarding portal:</p>
<p><a href="{{ doc.onboarding_portal_link }}" style="background:#2490ef;color:#fff;padding:10px 20px;text-decoration:none;border-radius:5px;">Complete Your Joining Process</a></p>
<p><strong>Steps to follow:</strong></p>
<ol>
  <li>Click the link above and create your password.</li>
  <li>Log in to the portal using your registered email ID.</li>
  <li>Complete all pending profile details.</li>
  <li>Upload the required documents listed below.</li>
  <li>Submit the information for HR verification.</li>
</ol>
<p><strong>Documents Required</strong></p>
<p>Kindly keep the following documents ready for upload (scanned copies / clear photos):</p>
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
{{ doc.hr_email }} | {{ doc.hr_phone }}</p>
```

---

## 5. Salary Slip

**Your spec:** To Employee. Attach salary slip.

**Frappe Email Template name:**  
`Salary Slip`

**Subject (Jinja):**  
`Salary slip for {{ doc.month_year }} – {{ doc.company_name }}`

**Context to pass from code:**

| Your placeholder | Jinja                 | Source in code |
|-----------------|------------------------|----------------|
| Employee Name   | `{{ doc.employee_name }}` | Salary Slip: employee_name |
| Month Year      | `{{ doc.month_year }}` | Salary Slip: month, year or posting_date |
| Company Name    | `{{ doc.company_name }}` | Salary Slip: company |

**Where to use:**  
- **App:** HRMS / Payroll (not Alpinos), on “payment confirmation” or after payroll submit.  
- **Logic:** Next day after payment confirmation, for each Salary Slip: build `doc`, get_formatted_email with template `Salary Slip`, attach PDF of Salary Slip, send to employee’s personal email.

**Body (Jinja):**

```html
<p>Hello {{ doc.employee_name }},</p>
<p>Kindly find attached your salary slip for the month of {{ doc.month_year }} for your reference and records.</p>
<p>We request you to review the details carefully. If you have any questions or notice any discrepancies, kindly contact the HR.</p>
<p>For confidentiality reasons, we advise you not to share your salary slip with anyone.</p>
<p>Thank you.</p>
<p>Best regards,<br/>HR Team<br/>{{ doc.company_name }}</p>
```

---

## 6. Templates already in use (Job Application – not in your template list)

These are used in Alpinos for **application submission** (different from Interview/Confirmation/Pre Onboarding):

| Frappe template name                         | Used in code                    | Purpose |
|--------------------------------------------|----------------------------------|--------|
| Job Application - Candidate Acknowledgement | `job_applicant_automation.send_application_emails` | To candidate after application submit |
| Job Application - HR Notification           | Same                            | To HR Managers after application submit |

They are **separate** from Interview Schedule / Confirmation / Pre Onboarding. Keep them as-is; only add the new templates above for Interview, Confirmation, Pre Onboarding, and (in Payroll app) Salary Slip.

---

## 7. Checklist – Create in Setup → Email Template

Create these in **Setup → Email Template** (enable “Use HTML” and paste body in “Response HTML” where applicable):

- [ ] **Interview Schedule Mail** – subject + body as in §2; use when interview is scheduled.
- [ ] **Confirmation Mail** – subject + body as in §3; use when Employee Onboarding status = “Job Confirmed”.
- [ ] **Pre Onboarding Mail** – subject + body as in §4; use in `send_pre_onboarding_email()` in Alpinos.
- [ ] **Salary Slip** – subject + body as in §5; use in Payroll/HRMS after payment confirmation.

Optional (for global look):

- [ ] Add the **header/footer** HTML (§1) at top and bottom of each template, and ensure code passes `company_logo_url`, `email_name`, `website_url`, `company_address`, and social links in `doc`.

---

## 8. Quick reference – Template name → code location

| Template name            | Where to use / status |
|--------------------------|------------------------|
| Interview Schedule Mail  | **To add:** `alpinos/interview_notifications.py` – send when Interview created/scheduled; To: Candidate; copy: RM, CC: HR. |
| Confirmation Mail        | **To add:** `alpinos/employee_onboarding_automation.py` – when status = “Job Confirmed”; To: Candidate; copy: RM, CC: HR & HOD. |
| Pre Onboarding Mail      | **To add:** In `alpinos/employee_onboarding_automation.send_pre_onboarding_email()` – replace hardcoded body with this template and `doc` context above. |
| Salary Slip             | **HRMS/Payroll app** – after payment confirmation; send with attachment. |
| Job Application - Candidate Acknowledgement | **Done** – `job_applicant_automation.send_application_emails`. |
| Job Application - HR Notification         | **Done** – same. |

This aligns your HRMS Email Template spec with Frappe template names, placeholders, context, and where to add or change code in Alpinos.

---

## 9. Templates from SRS not in HRMS spec doc

These are required by the **SRS** (ALP_HRMS_001) but were **not** in your HRMS Email Template spec. They are created by the patch and wired as below:

| Template name | SRS requirement | Where to use |
|---------------|----------------|--------------|
| **Job Applicant - Rejection** | "Rejected candidates receive communication through email" | `job_applicant_automation.py` or `interview_notifications.py`: when Job Applicant `screening_status` or Interview `status` becomes Rejected; send to candidate. |
| **Employee Onboarding - Complete Profile** | "On Joining Day … send an email to the candidate's personal email to complete the onboarding process" | `employee_onboarding_automation.py`: when Employee Onboarding status becomes "Joined"; send to candidate with profile completion link. |
| **Probation - Near Completion** | Dashboard: "Probation near completion reminder" | New `probation_reminders.py`: daily/weekly scheduler; send to RM/HR when `probation_end_date` is within e.g. 7 days. |
| **Probation - Complete** | Dashboard: "Probation complete reminder" | Same scheduler; send when probation has ended. |

**Placeholders (doc):**
- **Job Applicant - Rejection:** `applicant_name`, `job_title`, `job_requisition`, `company_name`
- **Employee Onboarding - Complete Profile:** `candidate_name`, `company_name`, `joining_date`, `profile_completion_link`, `hr_email`, `hr_phone`
- **Probation - Near Completion / Complete:** `recipient_name`, `employee_name`, `employee_id`, `probation_end_date`, `company_name`
