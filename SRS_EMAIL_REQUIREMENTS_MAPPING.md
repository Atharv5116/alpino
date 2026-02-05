# SRS Email Requirements – Where to Add in Alpinos

This document maps every email/notification requirement from the **ALP_HRMS_001 (HRMS + Payroll)** SRS to the Alpinos app: what is already implemented and **where to add** the rest.

---

## Index by SRS Section

| SRS Section      | Email requirement summary                               | Status    | Where to add / already implemented |
|------------------|----------------------------------------------------------|----------|------------------------------------|
| Job Application  | Acknowledgement to Candidate + HR                        | Done     | `job_applicant_automation.send_application_emails` |
| Screening        | Interview scheduled → email to RM, HR, Candidate         | To add   | New: interview email on create/schedule |
| Screening        | Rejected candidates → email at any stage                 | To add   | Job Applicant / Interview doc_events |
| Onboarding       | Job confirmation email                                   | To add   | Employee Onboarding doc_events |
| Onboarding       | 1 week before DOJ: document upload link + list           | Done     | `employee_onboarding_automation.send_pre_onboarding_email` |
| Onboarding       | On Joining Day: email to complete onboarding (profile)   | To add   | Employee Onboarding (DOJ / status) |
| Vacancy          | Workflow transition emails (optional)                    | Partial  | Workflow states: add Email Templates |
| Reimbursement    | (No explicit email in SRS)                               | Optional | Expense Claim workflow templates |
| Payroll          | Salary slip to employee next day after payment confirm   | Not here | HRMS/Payroll app |
| Dashboard        | Probation near completion / complete reminders           | To add   | New scheduler + notifications |

---

## 1. Job Application (SRS: Job Application)

### 1.1 Acknowledgement Email Notification

**SRS text:**  
- *Email sent to Candidate confirming application receipt.*  
- *Email sent to HR with candidate and job details.*  
- *Email templates should be configurable.*

**Status:** Implemented.

**Where it is implemented:**
- **File:** `alpinos/job_applicant_automation.py`
- **Function:** `send_application_emails(doc)`
- **Triggered from:** Web form submission flow (after workflow moves to "New Application") and when status becomes "New Application".
- **Templates used (create in Email Template doctype if missing):**
  - `Job Application - Candidate Acknowledgement` → to candidate (`doc.email_id`)
  - `Job Application - HR Notification` → to users with role **HR Manager**

**What to do:**  
Ensure these two Email Template records exist and are configured (Setup → Email Template). No code change needed for this requirement.

---

## 2. Screening (SRS: Screening)

### 2.1 Interview scheduling – Email to RM, HR, and Candidate

**SRS text:**  
*Schedule an Interview with RM and HR and inform them via Email, including the candidate.*  
*Email Template: Interview Outcome & Decision* (context: scheduling and outcome).

**Status:** Not implemented.

**Where to add:**

1. **New module (recommended):** e.g. `alpinos/interview_notifications.py`  
   - Add a function e.g. `send_interview_scheduled_emails(interview_doc)` that:
     - Loads Interview doc (with `job_applicant`, `interview_round`, `interview_details`).
     - Gets candidate email from Job Applicant.
     - Gets RM and HR from Job Applicant / Employee / Interview Round (interviewers) or custom logic.
     - Renders an Email Template (e.g. **"Interview Scheduled - Candidate"**, **"Interview Scheduled - RM"**, **"Interview Scheduled - HR"**) and sends via `frappe.sendmail`.
   - Call this from a **document event** when an Interview is created or when it is “scheduled” (e.g. status set to "Scheduled" or on first save after creation).

2. **Hook in `hooks.py`:**
   - In `doc_events` for **Interview**:
     - `after_insert`: call `send_interview_scheduled_emails(doc)`  
     or
     - `on_update`: if `doc.has_value_changed("status")` and status is something like "Scheduled", call the same.

3. **Email Templates to create (Setup → Email Template):**
   - **Interview Scheduled - Candidate** (date/time, round, link/instructions).
   - **Interview Scheduled - RM** (candidate name, round, date/time).
   - **Interview Scheduled - HR** (same as RM or combined with RM).

**File to create or extend:**  
- New: `alpinos/interview_notifications.py`  
- Register in `alpinos/hooks.py` under `doc_events["Interview"]`.

---

### 2.2 Rejected candidates – Email at any stage

**SRS text:**  
*Rejected candidates … receive communication through email.*

**Status:** Not implemented.

**Where to add:**

1. **Option A – On Job Applicant rejection**
   - **File:** `alpinos/job_applicant_automation.py`
   - In a **doc_events** handler for **Job Applicant** (in `hooks.py`): `on_update` (or `before_save`/`after_save`).
   - When `doc.has_value_changed("screening_status")` and new value is **"Rejected"** (or status field changes to "Rejected"), call a new function e.g. `send_rejection_email_to_candidate(doc)`.
   - Function: load candidate email from `doc.email_id`, render Email Template **"Job Applicant - Rejection"**, send via `frappe.sendmail`.

2. **Option B – On Interview rejection**
   - **File:** `alpinos/interview_notifications.py` (or same as above)
   - In `doc_events["Interview"]` → `on_update`: if `doc.has_value_changed("status")` and new status is **"Rejected"**, get linked Job Applicant, then send rejection email to applicant (same template or a dedicated **"Interview Rejected - Candidate"**).

**Email Template to create:**  
- **Job Applicant - Rejection** (or **Interview Rejected - Candidate**) – configurable body, reference to application/interview.

**Hook:**  
- `hooks.py` → `doc_events["Job Applicant"]` and/or `doc_events["Interview"]` pointing to the new functions.

---

## 3. Onboarding (SRS: Onboarding)

### 3.1 Job confirmation email

**SRS text:**  
*Send a Confirmation Email with relevant information.*  
*Email Template.*

**Status:** Not implemented.

**Where to add:**

- **File:** `alpinos/employee_onboarding_automation.py`
- **Trigger:** When HR “confirms” the job (e.g. when **Employee Onboarding** status is set to **"Job Confirmed"** or when a specific “Confirm” action is taken). If you use a status like "Pre-Onboarding Initiated", you can send this email when moving to "Job Confirmed" or when "Pre-Onboarding Initiated" is set (if that is the first confirmation step).
- **Logic:** In `doc_events["Employee Onboarding"]` → `on_update` (or in a workflow transition): if status becomes "Job Confirmed" (or your chosen confirmation status), get candidate email from linked Job Applicant, render Email Template **"Employee Onboarding - Job Confirmation"**, send via `frappe.sendmail`.
- **Email Template to create:** **Employee Onboarding - Job Confirmation** (relevant info: company, DOJ, designation, etc.).

**Hook:**  
- `hooks.py` → `doc_events["Employee Onboarding"]` → e.g. `on_update": "alpinos.employee_onboarding_automation.send_job_confirmation_email_if_status_confirmed"`.

---

### 3.2 One week before DOJ – Document upload link + list

**SRS text:**  
*A week before the DOJ the system will send an email with a link to upload the Document and the List of Documents.*

**Status:** Implemented.

**Where it is implemented:**
- **File:** `alpinos/employee_onboarding_automation.py`
- **Functions:** `send_pre_onboarding_email(doc, applicant_email)`, `schedule_pre_onboarding_email(doc)`, `send_scheduled_pre_onboarding_emails()` (daily scheduler).
- **Trigger:** When `date_of_joining_onboarding` is 7 days from today and status is "Pre-Onboarding Initiated"; daily job sends the email.
- **Note:** Content is currently built in code. For “configurable” list and link, consider moving body to Email Template **"Employee Onboarding - Document Upload Reminder"** and pass link + document list as template context.

**What to do:**  
Optional: create Email Template **"Employee Onboarding - Document Upload Reminder"** and use it in `send_pre_onboarding_email` instead of hardcoded message.

---

### 3.3 On Joining Day – Email to complete onboarding (profile)

**SRS text:**  
*On Joining Day, HR will review and verify the above checklist, then send an email to the candidate's personal email to complete the onboarding process.*

**Status:** Not implemented.

**Where to add:**

- **File:** `alpinos/employee_onboarding_automation.py`
- **Trigger:** When **Employee Onboarding** reaches “joining day” and HR has verified (e.g. status moves to **"Joined"** or a “Joined” action, or when `date_of_joining_onboarding` equals today and status is updated). Add a function e.g. `send_profile_completion_email(doc)`.
- **Logic:** When status becomes "Joined" (or your chosen “on joining day” status), get personal email from `doc.personal_email` or Job Applicant, render Email Template **"Employee Onboarding - Complete Profile"** (with profile completion link), send via `frappe.sendmail`.
- **Email Template to create:** **Employee Onboarding - Complete Profile** – link to portal/form to complete pending fields.

**Hook:**  
- `hooks.py` → `doc_events["Employee Onboarding"]` → `on_update` calling the new function when status = "Joined" (or equivalent).

---

## 4. Vacancy (Job Requisition) – Workflow emails

**SRS:**  
Approval flow is described; emails are not explicitly required but are good practice.

**Status:** Partial. Workflow has `send_email_alert: 1` and `send_email_to_creator` but **next_action_email_template** is empty for all states.

**Where to add (optional):**

- **File:** `alpinos/workflow_setup.py` (or Property Setter / Workflow UI)
- For each workflow state that should notify (e.g. Pending RM/HOD/HR, Rejected, Returned to Requestor), create Email Templates and set **next_action_email_template** on the corresponding Workflow State:
  - e.g. **Job Requisition - Pending RM Approval**, **Job Requisition - Rejected**, **Job Requisition - Returned to Requestor**, etc.
- No new Python is required; only create templates and set them on the workflow.

---

## 5. Reimbursement (Expense Claim)

**SRS:**  
No explicit email requirement; workflow and RM/HR actions are described.

**Status:** Workflow in `customize_expense_claim.py` has `send_email_alert: 1` and `send_email_to_creator: 1` for some transitions but **next_action_email_template** is empty.

**Where to add (optional):**

- Create Email Templates for key transitions, e.g.:
  - **Expense Claim - Pending RM Approval** (to RM)
  - **Expense Claim - Approved by RM** (to employee)
  - **Expense Claim - Rejected** (to employee)
- Set these template names on the corresponding Workflow State records (via UI or in the same file where workflow is created).

---

## 6. Payroll – Salary slip email

**SRS text:**  
*The salary slips for every month will be automatically sent to the employee's personal email ID on the next day after payment confirmation is done.*

**Status:** Not in Alpinos; this belongs to HRMS/Payroll.

**Where to add:**  
In the **Payroll / HRMS** app (e.g. on Salary Slip or Payroll Entry when payment is confirmed), add a scheduled job or document event that runs “next day after payment confirmation” and sends the salary slip PDF to the employee’s personal email. Alpinos does not need to implement this unless you move payroll into Alpinos.

---

## 7. Dashboard – Probation reminders

**SRS text (Dashboard):**  
*Probation near completion reminder / Probation complete reminder.*

**Status:** Not implemented.

**Where to add:**

- **New file:** e.g. `alpinos/probation_reminders.py`
  - **Daily (or weekly) scheduler:** Get Employees where `probation_end_date` is near (e.g. 7 days) or past; for each, get RM/HR and optionally employee email; create Notification Log entries and/or send emails using Email Templates **"Probation - Near Completion"** and **"Probation - Complete"**.
- **Hook:** In `hooks.py` → `scheduler_events` → `daily` (or `weekly`): add `alpinos.probation_reminders.send_probation_reminders`.

**Email Templates to create:**  
- **Probation - Near Completion** (to RM/HR).  
- **Probation - Complete** (to RM/HR and optionally employee).

---

## Summary – Where to add emails (quick reference)

| # | SRS requirement                         | Add in file                              | Hook / trigger                          | Email template(s) to create |
|---|----------------------------------------|------------------------------------------|-----------------------------------------|------------------------------|
| 1 | Interview scheduled → RM, HR, Candidate| `alpinos/interview_notifications.py` (new) | `doc_events["Interview"]` after_insert / on_update | Interview Scheduled - Candidate / RM / HR |
| 2 | Rejected candidate email               | `job_applicant_automation.py` or `interview_notifications.py` | `doc_events["Job Applicant"]` or `["Interview"]` on status Rejected | Job Applicant - Rejection |
| 3 | Job confirmation (onboarding)          | `employee_onboarding_automation.py`      | `doc_events["Employee Onboarding"]` when status = Job Confirmed | Employee Onboarding - Job Confirmation |
| 4 | On Joining Day – complete profile email| `employee_onboarding_automation.py`      | `doc_events["Employee Onboarding"]` when status = Joined | Employee Onboarding - Complete Profile |
| 5 | (Optional) Pre-onboarding doc reminder | Already sent; optional: use template     | -                                        | Employee Onboarding - Document Upload Reminder |
| 6 | (Optional) Vacancy workflow             | Workflow State records                    | -                                        | Job Requisition - Pending RM/HOD/HR, Rejected, Returned |
| 7 | (Optional) Reimbursement workflow      | Workflow State records                    | -                                        | Expense Claim - Pending RM, Approved, Rejected |
| 8 | Probation reminders                    | `alpinos/probation_reminders.py` (new)    | `scheduler_events` daily/weekly         | Probation - Near Completion, Probation - Complete |
| 9 | Salary slip after payment               | HRMS/Payroll app                          | After payment confirmation              | (in Payroll app)             |

---

## Email templates checklist (create in Setup → Email Template)

- [ ] Job Application - Candidate Acknowledgement (already used)
- [ ] Job Application - HR Notification (already used)
- [ ] Interview Scheduled - Candidate
- [ ] Interview Scheduled - RM
- [ ] Interview Scheduled - HR
- [ ] Job Applicant - Rejection
- [ ] Employee Onboarding - Job Confirmation
- [ ] Employee Onboarding - Document Upload Reminder (optional, replace hardcoded body)
- [ ] Employee Onboarding - Complete Profile
- [ ] Probation - Near Completion
- [ ] Probation - Complete
- [ ] (Optional) Job Requisition workflow templates
- [ ] (Optional) Expense Claim workflow templates

This keeps all SRS email requirements in one place and points to the exact files and hooks to use in Alpinos.
