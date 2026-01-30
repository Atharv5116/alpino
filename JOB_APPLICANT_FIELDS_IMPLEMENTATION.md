# Job Applicant Module - Field Implementation Summary

**Date:** 2025-01-27  
**App:** alpinos  
**DocType:** Job Applicant

---

## ✅ IMPLEMENTED CHANGES

### 1. Custom Fields Added (12 new fields)

| Field Name | Type | Label | Required | Position |
|------------|------|-------|----------|----------|
| `candidate_id` | Data (Read-only) | Candidate ID | No | After `details_section` |
| `marital_status` | Select | Marital Status | Yes | After `country` |
| `city_state` | Data | City / State | Yes | After `marital_status` |
| `application_date` | Date | Application Date | Yes | After `job_title` |
| `total_experience` | Data | Total Experience | Yes | After `application_date` |
| `portfolio` | Data | Portfolio | No | After `total_experience` |
| `expected_date_of_joining` | Date | Expected Date of Joining | No | After `portfolio` |
| `job_requisition` | Link (Job Requisition) | Job Requisition | Yes | After `job_title` |
| `employment_history` | Table | Employment History | No | In Employment History section |
| `qualification` | Table | Qualification | No | In Qualification section |
| `reference` | Table | Reference | No | In Reference section |

### 2. Field Modifications (via Patch)

| Field Name | Modification | Status |
|------------|--------------|--------|
| `phone_number` | Label changed to "Mobile Number" | ✅ Property setter |
| `resume_attachment` | Label changed to "Resume/CV" | ✅ Property setter |
| `resume_attachment` | Made required | ✅ Patch created |
| `status` | Updated options to SRS requirements | ✅ Patch created |
| `status` | Default set to "Draft" | ✅ Property setter |

### 3. Status Field Options Updated

**New Status Options:**
- Draft
- Submitted
- New Application
- Rejected
- Archived

**Old Status Options (replaced):**
- Open
- Replied
- Rejected
- Hold
- Accepted

---

## 📁 FILES CREATED/MODIFIED

### Created Files:
1. `/apps/alpinos/alpinos/patches/v1_0/update_job_applicant_fields.py` - Field modification patch

### Modified Files:
1. `/apps/alpinos/alpinos/custom_fields.py` - Added Job Applicant custom fields section
2. `/apps/alpinos/alpinos/patches.txt` - Added patch entry

---

## 🚀 DEPLOYMENT STEPS

### 1. Create Child Table DocTypes (REQUIRED FIRST)

Before running migration, create the following child table DocTypes:

#### Employment History
- **DocType Name:** `Employment History`
- **Is Child Table:** Yes
- **Fields:**
  - `company_name` (Data, Mandatory)
  - `designation` (Data, Mandatory)
  - `current_ctc` (Currency/Float, Mandatory)
  - `expected_ctc` (Currency/Float, Mandatory)
  - `reason_for_leaving` (Small Text/Text Editor, Mandatory)
  - `start_date` (Date, Mandatory)
  - `end_date` (Date, Mandatory)
  - `notice_period` (Int, Mandatory)

#### Qualification
- **DocType Name:** `Qualification`
- **Is Child Table:** Yes
- **Fields:**
  - `degree` (Data, Mandatory)

#### Job Application Reference
- **DocType Name:** `Job Application Reference`
- **Is Child Table:** Yes
- **Fields:**
  - `reference_name` (Data, Mandatory) - Note: `name` is reserved in Frappe, using `reference_name`
  - `mobile_number` (Data, Mandatory)

### 2. Run Migrate
```bash
cd /home/hetvi/frappe-bench
bench migrate
```

This will:
- Create all custom fields
- Run the patch to update existing fields
- Apply property setters for label changes

### 3. Verify Fields
After migration, verify in Frappe:
- Go to Customize Form → Job Applicant
- Check all new fields are present
- Verify field positions and requirements
- Verify child tables are linked correctly

### 4. Test Field Creation
- Create a new Job Applicant
- Verify all required fields are present
- Test field validation
- Test child table entries

---

## 📋 FIELD POSITIONING

### Details Section
```
- details_section
- candidate_id (NEW - Read-only)
- applicant_name
- email_id
- phone_number (UPDATED label: Mobile Number)
- country
- marital_status (NEW)
- city_state (NEW)
```

### Work Details Section
```
- job_title (Job Opening)
- job_requisition (NEW)
- application_date (NEW)
- total_experience (NEW)
- portfolio (NEW - Optional)
- expected_date_of_joining (NEW - Optional)
- designation
- status (UPDATED options)
```

### Source and Rating Section
```
- source_and_rating_section
- source
- source_name
- applicant_rating
```

### Resume Section
```
- section_break_6 (Resume)
- notes
- cover_letter
- resume_attachment (UPDATED label: Resume/CV, UPDATED: Required)
- resume_link
```

### Employment History Section (NEW)
```
- employment_history_section (NEW)
- employment_history (NEW - Table)
```

### Qualification Section (NEW)
```
- qualification_section (NEW)
- qualification (NEW - Table)
```

### Reference Section (NEW)
```
- reference_section (NEW)
- reference (NEW - Table, Optional)
```

### Compensation Section
```
- section_break_16
- currency
- lower_range
- upper_range
```

---

## ⚠️ NOTES

1. **Child Table DocTypes**: The child table DocTypes (`Employment History`, `Qualification`, `Job Application Reference`) **MUST** be created manually in Frappe before running migration. The custom fields reference these DocTypes, so they must exist first.

2. **Candidate ID**: This is a read-only field that will be auto-populated. The actual Candidate ID generation logic will be implemented in automation scripts (autoname or hooks).

3. **Field Names**: The actual fieldnames (`phone_number`, `resume_attachment`) remain unchanged for backward compatibility. Only labels are updated via property setters.

4. **Status Field**: The status field options are updated via patch. Existing records with old statuses may need manual update.

5. **Required Fields**: All new fields marked as `reqd=1` will be mandatory. Make sure existing workflows can handle this.

6. **Job Requisition Link**: The `job_requisition` field links to Job Requisition DocType. This enables linking applications to specific requisitions.

7. **Application Date**: Defaults to "Today" automatically.

8. **Portfolio and Expected Date of Joining**: These fields are optional (non-mandatory) as per SRS requirements.

---

## 🔄 NEXT STEPS

1. **Create Child Table DocTypes** - Create Employment History, Qualification, and Job Application Reference DocTypes
2. **Candidate ID Generation** - Implement autoname or hook to generate Candidate ID automatically
3. **File Upload Validation** - Implement validation for Resume/CV (PDF and Word files only)
4. **Status Automation** - Implement hooks for status transitions (Draft → Submitted → New Application)
5. **Email Notifications** - Create email templates and notifications for candidate and HR
6. **Web Form Creation** - Create public web form for candidate application
7. **Testing** - End-to-end testing of field validation and application flow

---

## ✅ CHECKLIST

- [x] Custom fields created
- [x] Field modification patch created
- [x] Property setters for label changes
- [x] Status field options updated
- [x] Patches.txt updated
- [ ] Child table DocTypes created (Employment History, Qualification, Job Application Reference)
- [ ] Migration tested
- [ ] Fields verified in UI
- [ ] Candidate ID generation (next phase)
- [ ] File upload validation (next phase)
- [ ] Status automation (next phase)
- [ ] Email notifications (next phase)
- [ ] Web form creation (next phase)

---

## 📝 CHILD TABLE DOCTYPE SPECIFICATIONS

### Employment History
**Purpose:** Store multiple employment records for a candidate

**Fields:**
- `company_name` - Data, Mandatory
- `designation` - Data, Mandatory
- `current_ctc` - Currency/Float, Mandatory
- `expected_ctc` - Currency/Float, Mandatory
- `reason_for_leaving` - Small Text/Text Editor, Mandatory
- `start_date` - Date, Mandatory
- `end_date` - Date, Mandatory
- `notice_period` - Int, Mandatory (unit: days)

### Qualification
**Purpose:** Store multiple qualification records for a candidate

**Fields:**
- `degree` - Data, Mandatory

**Note:** While Google Sheet shows single field, system supports multiple entries (client-approved deviation).

### Job Application Reference
**Purpose:** Store reference contacts (optional)

**Fields:**
- `name` - Data, Mandatory
- `mobile_number` - Data, Mandatory

---

**Status:** Ready for Child Table Creation, then Migration  
**Last Updated:** 2025-01-27

