# Field Visibility Check - Job Requisition

**Date:** 2025-01-27  
**Status:** Comparing implementation vs visible fields

---

## ✅ FIELDS VISIBLE IN FORM (From Screenshot)

### Details Tab - Left Column:
- ✅ Naming Series
- ✅ Designation *
- ✅ Department
- ✅ Location * ← **NEW FIELD (Visible)**

### Details Tab - Middle Column:
- ✅ No of. Positions *
- ✅ Min. Experience (Years) * ← **NEW FIELD (Visible)**
- ✅ Vacancy Type * ← **NEW FIELD (Visible)**
- ✅ Priority * ← **NEW FIELD (Visible)**
- ✅ Expected Compensation * (Label not updated yet)
- ✅ CTC Upper Range * ← **NEW FIELD (Visible)**

### Details Tab - Right Column:
- ✅ Company *
- ✅ Status * (Still shows "Pending" - old option)

### Requested By Section:
- ✅ Requested By *

### Timelines Section:
- ✅ Posting Date * (Label not updated to "Requested On" yet)
- ✅ Expected By
- ✅ Hiring Deadline * ← **NEW FIELD (Visible)**

---

## ❌ FIELDS NOT VISIBLE (But Should Be)

### Missing Fields:
1. ❌ **Additional Description** - Should be in "Job Description" tab (after `description`)
2. ❌ **Approved On** - Should be in "Requisition Details" section (after `status`)
3. ❌ **Approved By** - Should be in "Requisition Details" section (after `approved_on`)

### Field Modifications Not Applied:
1. ⚠️ **Expected Compensation** - Label should be "CTC Lower Range" (property setter not applied)
2. ⚠️ **Posting Date** - Label should be "Requested On" (property setter not applied)
3. ⚠️ **Status** - Options should be updated (patch not applied)

---

## 📊 SUMMARY

### New Fields Status:
- ✅ **6 out of 9 fields visible** (Location, Min Experience, Vacancy Type, Priority, CTC Upper Range, Hiring Deadline)
- ❌ **3 fields missing** (Additional Description, Approved On, Approved By)

### Field Modifications Status:
- ❌ **0 out of 3 modifications applied** (Labels and status options not updated)

---

## 🔍 POSSIBLE REASONS FOR MISSING FIELDS

### 1. Additional Description
- **Location:** Should be in "Job Description" tab
- **Check:** Open "Job Description" tab to see if it's there
- **Possible Issue:** Field might be created but in wrong position

### 2. Approved On & Approved By
- **Location:** Should be in "Requisition Details" section (after status)
- **Check:** Look for collapsible "Requisition Details" section
- **Possible Issues:**
  - Section might be collapsed
  - Section might not be created properly
  - Fields might be hidden based on status

### 3. Field Modifications (Labels & Status)
- **Possible Issues:**
  - Patch not executed yet
  - Property setters not created
  - Cache not cleared
  - Migration not run

---

## ✅ VERIFICATION STEPS

### Step 1: Check Job Description Tab
```bash
# Open Job Requisition form
# Click on "Job Description" tab
# Look for "Additional Description" field after "Job Description"
```

### Step 2: Check Requisition Details Section
```bash
# In Details tab, scroll down after "Status" field
# Look for collapsible "Requisition Details" section
# Expand it to see "Approved On" and "Approved By"
```

### Step 3: Verify Migration Ran
```bash
# Check if custom fields were created
bench console
>>> import frappe
>>> frappe.get_doc("Custom Field", {"dt": "Job Requisition", "fieldname": "additional_description"})
>>> frappe.get_doc("Custom Field", {"dt": "Job Requisition", "fieldname": "approved_on"})
>>> frappe.get_doc("Custom Field", {"dt": "Job Requisition", "fieldname": "approved_by"})
```

### Step 4: Check Property Setters
```bash
bench console
>>> import frappe
>>> frappe.get_all("Property Setter", {"doc_type": "Job Requisition", "field_name": "expected_compensation"})
>>> frappe.get_all("Property Setter", {"doc_type": "Job Requisition", "field_name": "posting_date"})
```

### Step 5: Check Status Field Options
```bash
bench console
>>> import frappe
>>> doc = frappe.get_doc("DocField", {"parent": "Job Requisition", "fieldname": "status"})
>>> print(doc.options)
```

---

## 🔧 FIXES NEEDED

### 1. Verify Custom Fields Creation
- Run migration if not done: `bench migrate`
- Clear cache: `bench clear-cache`
- Reload form in browser

### 2. Check Field Positions
- Additional Description should be in Job Description tab
- Approved On/By should be in Requisition Details section
- May need to adjust `insert_after` values

### 3. Apply Field Modifications
- Run patch manually if needed
- Verify property setters were created
- Clear cache and reload

---

## 📝 NEXT ACTIONS

1. **Check Job Description tab** for Additional Description
2. **Look for Requisition Details section** (might be collapsed)
3. **Run migration** if not done: `bench migrate`
4. **Clear cache**: `bench clear-cache`
5. **Reload form** in browser
6. **Verify patch ran** for field modifications

---

**Last Updated:** 2025-01-27
