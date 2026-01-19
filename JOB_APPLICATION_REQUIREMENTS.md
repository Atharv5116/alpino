# Job Application System - Software Requirements Specification

## Document Overview
This document outlines the complete requirements for the Job Application System as per the Software Requirements Specification (SRS) for Alpino.

---

## a. Actors / User Roles

The system involves three primary actors with distinct responsibilities:

| Role | Description |
|------|-------------|
| **Candidate** | External user who applies for a job position. They initiate the application process and fill out the application form. |
| **HR** | Internal user who receives application notifications and has access to candidate data. They review and manage applications through the HR dashboard. |
| **System** | Automated system component that handles form submission, email notifications, data storage, and application status management. |

---

## b. High-Level Workflow Overview

The job application process follows these sequential steps:

1. **New candidate initiates job application** - A candidate starts the application process for an open vacancy.
2. **Candidate fills out the application form** - The candidate completes all required fields in the online job application form.
3. **Candidate submits application** - The candidate finalizes and submits the completed application form.
4. **System sends acknowledgement emails** - Automated emails are sent to both the Candidate and HR confirming application receipt.
5. **Application stored in Candidate Application System** - The application data is securely stored and linked to the respective job requisition.

---

## c. Detailed Requirements

### i. New Candidate Application Initiation

**Requirement 1.1**: The system shall allow a new candidate to initiate a job application for an open vacancy.

**Key Points:**
- Candidates must be able to access and start applications for available job positions
- The system should validate that the vacancy is still open before allowing application initiation
- No authentication should be required for external candidates to start an application

---

### ii. Job Application Form

**Requirement 2.1**: Candidate completes an online job application form.

**Requirement 2.2**: All form fields are specified in the Google Sheet (reference document).

**Requirement 2.3**: The CV/Resume attachment field shall support **PDF and Word files only**.

**Key Points:**
- The form must be accessible online (web-based)
- All required fields must be clearly defined and validated
- File upload validation must restrict CV/Resume attachments to:
  - PDF files (`.pdf`)
  - Microsoft Word files (`.doc`, `.docx`)
- Other file formats should be rejected with appropriate error messages

---

### iii. Application Submission

**Requirement 3.1**: After submission of the application form, the system should generate a **Candidate ID**.

**Key Points:**
- Candidate ID generation must be automatic upon successful form submission
- The Candidate ID should be unique and follow a defined naming convention
- The Candidate ID should be communicated to the candidate (likely in the acknowledgement email)
- The ID serves as a reference for tracking the application throughout the process

---

### iv. Acknowledgement Email Notification

**Requirement 4.1**: Email sent to Candidate confirming application receipt - Email sent to HR with candidate and job details - Email templates should be configurable.

**Requirement 4.2**: Email ID (recipient configuration).

**Requirement 4.3**: Email Template (template configuration).

**Key Points:**
- **Dual Email Notifications:**
  - **Candidate Email**: Confirmation that their application has been received
  - **HR Email**: Notification containing candidate details and job information
  
- **Email Configuration Requirements:**
  - Email templates must be configurable (not hardcoded)
  - System administrators should be able to modify email content, subject lines, and formatting
  - Templates should support dynamic data insertion (candidate name, job title, Candidate ID, etc.)
  
- **Email Content:**
  - Candidate email should include:
    - Confirmation of receipt
    - Candidate ID (generated reference number)
    - Job position applied for
    - Next steps or timeline information
  
  - HR email should include:
    - Candidate name and contact information
    - Job requisition details
    - Candidate ID
    - Link to view application in HR dashboard

---

### v. Candidate Application System Entry

**Requirement 5.1**: Candidate profile created automatically - Application linked to the respective job requisition - Resume and documents stored securely - Status maintained as "New Application" - Application visible in HR dashboard.

**Key Points:**
- **Automatic Profile Creation:**
  - Candidate profile/document should be created automatically upon form submission
  - No manual intervention required for profile creation
  
- **Application Linking:**
  - The application must be linked to the specific job requisition for which it was submitted
  - This linkage enables tracking and filtering applications by job position
  
- **Secure Document Storage:**
  - CV/Resume and other uploaded documents must be stored securely
  - Access control should be implemented to ensure only authorized users (HR) can access documents
  - Documents should be stored in a way that maintains data integrity and privacy
  
- **Initial Status:**
  - Upon creation, the application status should be automatically set to "New Application"
  - This status indicates the application is ready for HR review
  
- **HR Dashboard Visibility:**
  - The application must be immediately visible in the HR dashboard
  - HR users should be able to view, filter, and manage applications from the dashboard
  - Dashboard should show key information: candidate name, job position, application date, status

---

## d. Application Status Management

The system must support the following application statuses with their respective meanings:

| Status | Description |
|--------|-------------|
| **Draft** | Application saved but not submitted. Candidate can edit and complete the form later. |
| **Submitted** | Application successfully submitted by the candidate. This is the status immediately after submission, before HR review. |
| **New Application** | Application is available for HR review. This is the status set automatically when the application enters the system after submission. |
| **Rejected** | Application has been rejected by HR after review. |
| **Archived** | Application has been archived (for future purposes). This may be used for historical record-keeping or compliance. |

**Status Flow:**
- **Draft** → **Submitted** (when candidate submits)
- **Submitted** → **New Application** (automatic system update)
- **New Application** → **Rejected** (HR action)
- **New Application** → **Archived** (HR action, or automatic after certain conditions)
- Any status → **Archived** (for historical purposes)

---

## Implementation Considerations

### Technical Requirements

1. **Form Validation:**
   - Client-side and server-side validation for all form fields
   - File type validation for CV/Resume (PDF and Word only)
   - File size limits should be enforced

2. **Candidate ID Generation:**
   - Should follow a consistent format (e.g., `CAND-YYYY-#####`)
   - Must be unique across all applications
   - Should be generated server-side to ensure uniqueness

3. **Email System:**
   - Integration with email service provider
   - Template engine support for dynamic content
   - Email queue system for reliable delivery
   - Retry mechanism for failed email deliveries

4. **Security:**
   - Secure file upload handling
   - Protection against malicious file uploads
   - Access control for HR dashboard
   - Data encryption for sensitive candidate information

5. **Database Design:**
   - Candidate profile/document structure
   - Link to Job Requisition document
   - Status tracking fields
   - Audit trail for status changes

6. **Integration Points:**
   - Job Requisition system (to validate open vacancies)
   - Email notification system
   - File storage system
   - HR dashboard/portal

---

## Current System Context

Based on the existing codebase:

- **Job Requisition System**: Already implemented with custom fields and automation
- **Job Opening**: Created automatically when Job Requisition is approved
- **Job Applicant DocType**: Exists in HRMS module (may need customization)
- **Email Notifications**: Frappe framework supports email templates and notifications

### Potential Implementation Approach

1. **Customize Job Applicant DocType** or create new **Candidate Application DocType**:
   - Add custom fields as per Google Sheet requirements
   - Implement file validation for CV/Resume
   - Add Candidate ID field with auto-generation

2. **Web Form Creation**:
   - Create public web form for candidate application
   - Link to Job Opening/Job Requisition
   - Implement form validation

3. **Email Notifications**:
   - Create email templates for candidate and HR notifications
   - Set up Notification records in Frappe
   - Configure email recipients

4. **Status Management**:
   - Customize status options in DocType
   - Implement status workflow/automation
   - Add status change tracking

5. **HR Dashboard**:
   - Create custom dashboard or customize existing
   - Add filters for status, job requisition, date range
   - Implement document access controls

---

## Open Questions / Clarifications Needed

1. **Form Fields**: Reference to "Google Sheet" - need access to determine exact field requirements
2. **Candidate ID Format**: Specific format/naming convention to be confirmed
3. **Email Template Content**: Exact content and formatting requirements for email templates
4. **Status Transitions**: Detailed workflow rules for status changes (who can change, when, conditions)
5. **Archiving Rules**: When and how applications should be archived (automatic vs manual, retention period)
6. **HR Dashboard Requirements**: Specific views, filters, and actions needed in HR dashboard
7. **File Storage**: Storage location and access method for uploaded documents
8. **Integration**: Any additional systems that need to be integrated (ATS, background check systems, etc.)

---

---

## e. Form Fields Specification (From Google Sheet)

### Add Section Fields

#### Candidate Details
- Full Name (Text Box, Alphabets, User, Mandatory)
- Email (Text Box, Universal, User, Mandatory)
- Mobile Number (Text Box, Numbers, User, Mandatory)
- Resume/CV (Attachment, Attachments, User, Mandatory) - PDF and Word files only
- Marital Status (Dropdown, Alphabets, User, Mandatory)
- City / State (Dropdown, Alphabets, User, Mandatory)

#### Work Details
- Applied Position (Text Box, Alphabets, User, Mandatory)
- Application Date (Date Picker, Date/Time, User, Mandatory)
- Source (Dropdown, Alphabets, User, Mandatory)
- Total Experience (Text Box, AlphaNumeric, User, Mandatory)
- Portfolio (Text Box, Universal, User, Non Mandatory)
- Expected Date of Joining (Date Picker, Date/Time, User, Non Mandatory)
- Reference (If Any) (Table, Alphabets, User, Non Mandatory)
  - Table Fields: Name, Mobile Number

#### Employment History
- Company Name (Text Box, Universal, User, Mandatory)
- Designation (Text Box, Alphabets, User, Mandatory)
- Current CTC/Annum (Text Box, Numbers, User, Mandatory)
- Expected CTC/Annum (Text Box, Numbers, User, Mandatory)
- Reason for Leaving (Text Area, Universal, User, Mandatory)
- Start Date (Date Picker, Date/Time, User, Mandatory)
- End Date (Date Picker, Date/Time, User, Mandatory)
- Notice Period (Text Box, Numbers, User, Mandatory)

#### Qualification
- Degree (Text Box, Universal, User, Mandatory)

### Edit Section Fields (Additional to Add Section)
- Candidate ID (Auto Number, AlphaNumeric, Auto, Mandatory, Non Editable)

### Tabular View (HR Dashboard)
- Candidate ID
- Candidate Name
- CV / Resume
- Designation
- Mobile Number
- Status
- Action

---

## Implementation Todo List

### Phase 1: DocType Setup and Core Fields

#### 1.1 DocType Creation/Customization
- [ ] Customize existing "Job Applicant" DocType
- [ ] Set up DocType permissions (Candidate: Create/Read own, HR: Full access)
- [ ] Configure DocType module assignment (HRMS or custom Alpinos module)

#### 1.2 Candidate ID Field
- [ ] Create Candidate ID field (Auto Number, AlphaNumeric, Auto, Mandatory, Read-only)
- [ ] Implement autoname format (e.g., `CAND-YYYY-#####` or similar)
- [ ] Ensure Candidate ID is non-editable after creation
- [ ] Test Candidate ID uniqueness and generation

#### 1.3 Candidate Details Section
- [ ] Create section break: "Candidate Details"
- [ ] Add field: Full Name (Data, Mandatory)
- [ ] Add field: Email (Data with Email validation, Mandatory)
- [ ] Add field: Mobile Number (Data, Mandatory)
- [ ] Add field: Resume/CV (Attach, Mandatory, with file type restriction)
- [ ] Add field: Marital Status (Select/Dropdown, Mandatory, options: Single/Married/Divorced/Widowed)
- [ ] Add field: City / State (Link to custom master or Select, Mandatory)

#### 1.4 Work Details Section
- [ ] Create section break: "Work Details"
- [ ] Add field: Applied Position (Link to Job Opening/Job Requisition, Mandatory)
- [ ] Add field: Application Date (Date, Mandatory, default to today)
- [ ] Add field: Source (Select/Dropdown, Mandatory, options: Website/Referral/LinkedIn/etc.)
- [ ] Add field: Total Experience (Data, Mandatory)
- [ ] Add field: Portfolio (Data, Non Mandatory)
- [ ] Add field: Expected Date of Joining (Date, Non Mandatory)
- [ ] Create Child DocType: "Job Application Reference" (Table)
  - [ ] Add field: Name (Data, Mandatory)
  - [ ] Add field: Mobile Number (Data, Mandatory)
- [ ] Link Reference table to main DocType

#### 1.5 Employment History Section (Child Table)
- [ ] Create Child DocType: "Employment History"
- [ ] Add field: Company Name (Data, Mandatory)
- [ ] Add field: Designation (Data, Mandatory)
- [ ] Add field: Current CTC/Annum (Currency/Float, Mandatory)
- [ ] Add field: Expected CTC/Annum (Currency/Float, Mandatory)
- [ ] Add field: Reason for Leaving (Small Text/Text Editor, Mandatory)
- [ ] Add field: Start Date (Date, Mandatory)
- [ ] Add field: End Date (Date, Mandatory)
- [ ] Add field: Notice Period (Int, Mandatory, unit: days)
- [ ] Link Employment History table to main DocType

#### 1.6 Qualification Section (Child Table)
- [ ] Create Child DocType: "Qualification"
- [ ] Add field: Degree (Data, Mandatory)
- [ ] Link Qualification table to main DocType
- [ ] Allow multiple qualification entries (Note: Client-approved deviation - Google Sheet shows single field, but multiple entries are supported)

### Phase 2: Validation and Business Logic

#### 2.1 File Upload Validation
- [ ] Implement server-side validation for Resume/CV file type
- [ ] Restrict file types to: PDF (.pdf), Word (.doc, .docx)
- [ ] Display user-friendly error messages for invalid file types

#### 2.2 Status Management
- [ ] Update Status field options: Draft, Submitted, New Application, Rejected, Archived
- [ ] Set default status to "Draft" on save (before submission)
- [ ] Implement status change automation:
  - [ ] On submit: Draft → Submitted
  - [ ] After submit: Submitted → New Application (automatic)
- [ ] Ensure default status is "New Application" after submission
- [ ] Ensure 'Rejected' and 'Archived' are HR-only actions

#### 2.4 Application Linking
- [ ] Add field: Job Requisition (Link to Job Requisition, Mandatory)
- [ ] Add field: Job Opening (Link to Job Opening, Optional)
- [ ] Implement auto-linking logic (link to Job Opening if available)
- [ ] Validate that Job Requisition/Job Opening is still open/active
- [ ] Prevent application submission for closed positions

### Phase 3: Web Form Creation

#### 3.1 Web Form Setup
- [ ] Create Web Form for "Job Application"
- [ ] Configure web form to use Job Application DocType
- [ ] Set up public access (no login required)
- [ ] Configure form route/URL
- [ ] Add form title and description

#### 3.2 Web Form Fields Mapping
- [ ] Map all Candidate Details fields to web form
- [ ] Map all Work Details fields to web form
- [ ] Map Employment History child table to web form (allow multiple entries)
- [ ] Map Qualification child table to web form (allow multiple entries)
- [ ] Map Reference child table to web form (optional, allow multiple entries)
- [ ] Configure field visibility (hide Candidate ID, status, etc. from candidates)

#### 3.3 Web Form Validation
- [ ] Ensure mandatory fields and file type restrictions are enforced on the web form
- [ ] Add required field indicators
- [ ] Add field format hints/placeholders
- [ ] Implement file upload validation on web form
- [ ] Add form submission confirmation


### Phase 4: Email Notifications

#### 4.1 Email Templates Creation
- [ ] Create email template: "Job Application - Candidate Acknowledgement"
  - [ ] Include Candidate ID
  - [ ] Include job position applied for
  - [ ] Include application date
  - [ ] Add professional formatting
- [ ] Create email template: "Job Application - HR Notification"
  - [ ] Include candidate name and contact details
  - [ ] Include job requisition details
  - [ ] Include Candidate ID
  - [ ] Include link to view application in HR list/form view

#### 4.2 Email Notification Setup
- [ ] Create Notification record: "Job Application Submitted - Candidate"
  - [ ] Event: After Insert
  - [ ] Channel: Email
  - [ ] Recipient: Candidate email
  - [ ] Template: Candidate Acknowledgement
- [ ] Create Notification record: "Job Application Submitted - HR"
  - [ ] Event: After Insert
  - [ ] Channel: Email
  - [ ] Recipient: HR email (configurable)
  - [ ] Template: HR Notification
- [ ] Configure email recipients (HR email addresses)
- [ ] Test email delivery for both templates

#### 4.3 Email Configuration
- [ ] Make email templates configurable (allow editing)
- [ ] Set up email account for outgoing emails
- [ ] Configure email queue system
- [ ] Add email retry mechanism for failed deliveries
- [ ] Test email notifications with sample data

### Phase 5: Automation and Hooks

#### 5.1 Document Hooks
- [ ] Implement `before_save` hook:
  - [ ] Validate Job Requisition/Job Opening is open
  - [ ] Set default status to "Draft" (if not submitted)
- [ ] Implement `on_submit` hook:
  - [ ] Change status from "Draft" to "Submitted"
  - [ ] Change status from "Submitted" to "New Application" (automatic)
  - [ ] Trigger email notifications
- [ ] Implement `validate` hook:
  - [ ] Validate all mandatory fields
  - [ ] Validate file types for Resume/CV

#### 5.2 Custom Methods
- [ ] Create method: `generate_candidate_id()` for auto-numbering
- [ ] Create method: `validate_resume_file_type()` for file validation
- [ ] Create method: `send_acknowledgement_emails()` for email sending
- [ ] Create method: `update_status_to_new_application()` for status update

### Phase 6: HR Dashboard and Views

#### 6.1 List View Configuration
- [ ] Configure list view columns:
  - [ ] Candidate ID
  - [ ] Candidate Name (Full Name)
  - [ ] CV / Resume (with download link)
  - [ ] Designation (from Employment History or Work Details)
  - [ ] Mobile Number
  - [ ] Status
  - [ ] Basic actions like View only (no Accept/Reject here)
- [ ] Add filters: Status, Job Requisition, Application Date, Source
- [ ] Add sorting options
- [ ] Configure default filters (show "New Application" by default for HR)

#### 6.2 Form View Customization
- [ ] Customize form layout for HR view
- [ ] Add comments/notes section for HR
- [ ] Add document attachment section
- [ ] Configure field visibility based on user role

### Phase 7: Integration and Linking

#### 7.1 Job Requisition Integration
- [ ] Link Job Application to Job Requisition
- [ ] Validate Job Requisition status before allowing application
- [ ] Auto-populate Applied Position from Job Requisition

#### 7.2 Job Opening Integration
- [ ] Link Job Application to Job Opening (if available)
- [ ] Validate Job Opening is published/open
- [ ] Auto-populate fields from Job Opening

---

## Summary

The Job Application System is a comprehensive solution that enables external candidates to apply for job positions through an online form, with automatic profile creation, email notifications, and HR list and form views. The system emphasizes document storage as per system defaults, configurable email templates, and clear status management throughout the application lifecycle.

**Key Success Criteria:**
- Seamless candidate experience with easy form submission
- Automatic system processing with minimal manual intervention
- Document storage as per system defaults
- Effective HR workflow with list and form view visibility
- Configurable and maintainable email notifications
- Clear status tracking and management

