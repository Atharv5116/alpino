# Field Sections Organization - Job Applicant

**Date:** 2025-01-27  
**Status:** ✅ Organized with Section Breaks and Column Breaks

---

## 📋 FIELD ORGANIZATION STRUCTURE

The Job Applicant form is now organized into clear sections with column breaks between each section:

### 1. **Candidate Details Section**
Contains all candidate personal information:

| Field | Type | Mandatory | Notes |
|-------|------|-----------|-------|
| Full Name | Data | Yes | Standard field (applicant_name) |
| Email | Data (Email) | Yes | Standard field (email_id) |
| Mobile Number | Data | Yes | Standard field (phone_number) |
| Resume/CV | Attach | Yes | Standard field (resume_attachment) |
| Marital Status | Select | Yes | Custom field |
| City / State | Data | Yes | Custom field |
| Candidate ID | Data (read-only) | Yes | Auto-generated, HR-only |

**Column Break** ⬇️

---

### 2. **Work Details Section**
Contains all work-related and application information:

| Field | Type | Mandatory | Notes |
|-------|------|-----------|-------|
| Applied Position | Data | Yes | User-entered |
| Job Requisition | Link | Yes | Validates open status |
| Application Date | Date | Yes | Default: Today |
| Source | Link/Select | Yes | Standard field |
| Total Experience | Data | Yes | Alphanumeric |
| Portfolio | Data | No | Optional URL |
| Expected Date of Joining | Date | No | Optional |
| Reference Name | Data | No | Optional |
| Reference Mobile Number | Data | No | Optional |

**Column Break** ⬇️

---

### 3. **Employment History Section**
Contains employment information (flat fields, single entry):

| Field | Type | Mandatory | Notes |
|-------|------|-----------|-------|
| Company Name | Data | Yes | |
| Designation | Data | Yes | |
| Current CTC / Annum | Data | Yes | |
| Expected CTC / Annum | Data | Yes | |
| Reason for Leaving | Small Text | Yes | |
| Start Date | Date | Yes | |
| End Date | Date | Yes | |
| Notice Period | Data | Yes | Days |

**Column Break** ⬇️

---

### 4. **Qualification Section**
Contains qualification information:

| Field | Type | Mandatory | Notes |
|-------|------|-----------|-------|
| Degree | Data | Yes | Single field |

---

## 🎨 VISUAL LAYOUT

```
┌─────────────────────────────────────────────────────────┐
│                    CANDIDATE DETAILS                     │
├─────────────────────────────────────────────────────────┤
│ Full Name          │ Email                               │
│ Mobile Number      │ Resume/CV                           │
│ Marital Status     │ City / State                        │
│ Candidate ID       │                                     │
└─────────────────────────────────────────────────────────┘
                        ⬇️ Column Break
┌─────────────────────────────────────────────────────────┐
│                      WORK DETAILS                         │
├─────────────────────────────────────────────────────────┤
│ Applied Position   │ Job Requisition                     │
│ Application Date    │ Source                             │
│ Total Experience    │ Portfolio                          │
│ Expected DOJ       │ Reference Name                     │
│                     │ Reference Mobile Number             │
└─────────────────────────────────────────────────────────┘
                        ⬇️ Column Break
┌─────────────────────────────────────────────────────────┐
│                  EMPLOYMENT HISTORY                      │
├─────────────────────────────────────────────────────────┤
│ Company Name        │ Designation                         │
│ Current CTC         │ Expected CTC                       │
│ Reason for Leaving  │                                    │
│ Start Date          │ End Date                           │
│ Notice Period       │                                    │
└─────────────────────────────────────────────────────────┘
                        ⬇️ Column Break
┌─────────────────────────────────────────────────────────┐
│                     QUALIFICATION                        │
├─────────────────────────────────────────────────────────┤
│ Degree              │                                    │
└─────────────────────────────────────────────────────────┘
```

---

## 📁 FILES MODIFIED

### `/apps/alpinos/alpinos/custom_fields.py`
- ✅ Added proper section organization
- ✅ Added column breaks between each major section
- ✅ Fields organized in logical groups matching Google Sheet

---

## ✅ BENEFITS

1. **Clear Organization:** Fields are grouped logically by category
2. **Better UX:** Column breaks create visual separation between sections
3. **Easy Navigation:** Collapsible sections allow users to focus on relevant areas
4. **Matches Specification:** Structure aligns with Google Sheet requirements

---

## 🚀 DEPLOYMENT

Run migration to apply the new field organization:

```bash
cd /home/hetvi/frappe-bench
bench migrate
```

After migration, the form will display with:
- Clear section breaks for each category
- Column breaks between sections for better layout
- All fields properly organized

---

**Status:** ✅ Complete - Ready for Migration  
**Last Updated:** 2025-01-27

