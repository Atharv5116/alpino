# Final Structure Verification - Job Applicant

**Date:** 2025-01-27  
**Status:** ✅ All Requirements Met

---

## ✅ REMOVED (As Per Requirements)

### 1. All Child Tables - REMOVED ✅
- ❌ **Employment History** child table - **DELETED** (converted to flat fields)
- ❌ **Qualification** child table - **DELETED** (converted to single field)
- ❌ **Job Application Reference** child table - **DELETED** (converted to 2 flat fields)

### 2. Duplicate/Unwanted Fields - REMOVED ✅
- ❌ **Duplicate Designation** - Main `designation` field is hidden from web form (auto-populated, HR-only)
- ❌ **Resume Link** - Hidden from web form and regular form (only `resume_attachment` used)
- ❌ **Salary Expectation Section** - All fields hidden:
  - `currency` - Hidden
  - `lower_range` - Hidden
  - `upper_range` - Hidden

---

## ✅ CONVERTED TO FLAT FIELDS

### Employment History (8 Flat Fields)
| Field | Type | Mandatory |
|-------|------|-----------|
| `employment_company_name` | Data | Yes |
| `employment_designation` | Data | Yes |
| `employment_current_ctc` | Data | Yes |
| `employment_expected_ctc` | Data | Yes |
| `employment_reason_for_leaving` | Small Text | Yes |
| `employment_start_date` | Date | Yes |
| `employment_end_date` | Date | Yes |
| `employment_notice_period` | Data | Yes |

### Qualification (Single Field)
| Field | Type | Mandatory |
|-------|------|-----------|
| `degree` | Data | Yes |

### Reference (2 Optional Fields)
| Field | Type | Mandatory |
|-------|------|-----------|
| `reference_name` | Data | No |
| `reference_mobile_number` | Data | No |

---

## ✅ ADDED FIELDS

### Candidate ID
- **Field:** `candidate_id`
- **Type:** Data (read-only)
- **Auto-generated:** Yes (format: CAND-YYYY-#####)
- **Mandatory:** Yes
- **Visible:** HR-only (Edit view)
- **Web Form:** Hidden

### Applied Position
- **Field:** `applied_position`
- **Type:** Data
- **Mandatory:** Yes
- **User-entered:** Yes (Alphabets)

### Job Requisition
- **Field:** `job_requisition`
- **Type:** Link (Job Requisition)
- **Mandatory:** Yes
- **Validation:** Must be open/active

---

## 📋 FINAL FIELD STRUCTURE

### Candidate Details Section
1. **Candidate ID** (auto, read-only, HR-only)
2. **Full Name** (`applicant_name`) - Mandatory
3. **Email** (`email_id`) - Mandatory
4. **Mobile Number** (`phone_number`) - Mandatory
5. **Resume/CV** (`resume_attachment`) - Mandatory (PDF/DOC/DOCX only)
6. **Marital Status** (`marital_status`) - Mandatory (Dropdown)
7. **City / State** (`city_state`) - Mandatory

### Work Details Section
1. **Applied Position** (`applied_position`) - Mandatory (Data, user-entered)
2. **Job Requisition** (`job_requisition`) - Mandatory (Link, validates open status)
3. **Job Opening** (`job_title`) - Auto-populated, read-only, hidden from web form
4. **Designation** (`designation`) - Auto-populated, read-only, hidden from web form
5. **Application Date** (`application_date`) - Mandatory (default: Today)
6. **Source** (`source`) - Mandatory (Link/Select)
7. **Total Experience** (`total_experience`) - Mandatory (Alphanumeric)
8. **Portfolio** (`portfolio`) - Optional (URL)
9. **Expected Date of Joining** (`expected_date_of_joining`) - Optional
10. **Reference Name** (`reference_name`) - Optional
11. **Reference Mobile Number** (`reference_mobile_number`) - Optional

### Employment History Section (Flat Fields)
1. **Company Name** (`employment_company_name`) - Mandatory
2. **Designation** (`employment_designation`) - Mandatory
3. **Current CTC / Annum** (`employment_current_ctc`) - Mandatory
4. **Expected CTC / Annum** (`employment_expected_ctc`) - Mandatory
5. **Reason for Leaving** (`employment_reason_for_leaving`) - Mandatory
6. **Start Date** (`employment_start_date`) - Mandatory
7. **End Date** (`employment_end_date`) - Mandatory
8. **Notice Period** (`employment_notice_period`) - Mandatory

### Qualification Section (Single Field)
1. **Degree** (`degree`) - Mandatory

---

## 🔍 FIELD VISIBILITY RULES

### Hidden from Web Form:
- `candidate_id` (HR-only)
- `status` (HR-only)
- `designation` (main field - auto-populated, HR-only)
- `job_title` (Job Opening - auto-populated)
- `country` (not in SRS)
- `resume_link` (duplicate - only use `resume_attachment`)
- `currency` (Salary section - not in SRS)
- `lower_range` (Salary section - not in SRS)
- `upper_range` (Salary section - not in SRS)

### Visible in Web Form:
- All Candidate Details fields (except Candidate ID)
- All Work Details fields (except Job Opening, Designation)
- All Employment History flat fields
- Qualification (Degree)
- Reference fields (optional)

---

## ⚠️ IMPORTANT NOTES

1. **Two Designation Fields:**
   - **Main `designation`** - Auto-populated from Job Opening/Requisition (read-only, HR-only)
   - **`employment_designation`** - User-entered in Employment History section (mandatory)

2. **Resume Fields:**
   - **`resume_attachment`** - Used (mandatory, PDF/DOC/DOCX only)
   - **`resume_link`** - Hidden (not used)

3. **Salary Fields:**
   - All salary expectation fields are hidden (`currency`, `lower_range`, `upper_range`)
   - Employment History has CTC fields (`employment_current_ctc`, `employment_expected_ctc`)

4. **No Child Tables:**
   - Everything is flat fields
   - No "Add Row" buttons
   - Single entry for Employment History
   - Single field for Qualification

---

## ✅ VERIFICATION CHECKLIST

- [x] All child tables removed
- [x] Employment History converted to 8 flat fields
- [x] Qualification converted to single field
- [x] Reference converted to 2 optional fields
- [x] Duplicate Designation handled (main field hidden from web form)
- [x] Resume Link hidden
- [x] Salary Expectation section hidden
- [x] Candidate ID added (auto-generated, read-only)
- [x] Applied Position added (user-entered, mandatory)
- [x] Job Requisition confirmed mandatory
- [x] All fields match Google Sheet specification

---

**Status:** ✅ Complete - Ready for Migration  
**Last Updated:** 2025-01-27




