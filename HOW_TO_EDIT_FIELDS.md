# How to Edit Job Applicant Fields

**Date:** 2025-01-27

---

## 📍 WHERE TO EDIT FIELDS

### 1. **Add New Custom Fields** 
**Location:** `/apps/alpinos/alpinos/custom_fields.py`

This is where you define **new custom fields** that don't exist in the standard Job Applicant DocType.

**Example:**
```python
"Job Applicant": [
    dict(
        fieldname="new_field_name",
        label="New Field Label",
        fieldtype="Data",
        insert_after="existing_field",
        reqd=1,
    ),
]
```

**After editing:**
```bash
bench migrate
```

---

### 2. **Modify Existing Field Properties**
**Location:** `/apps/alpinos/alpinos/patches/v1_0/update_job_applicant_fields.py`

This is where you:
- Update field labels
- Hide/show fields
- Set field properties (read-only, mandatory, etc.)
- Configure field visibility

**Example:**
```python
# Hide a field
hide_field_completely("Job Applicant", "field_name")

# Update label
update_property_setter(
    "Job Applicant",
    "field_name",
    "label",
    "New Label",
    "Data"
)

# Make field read-only
update_property_setter(
    "Job Applicant",
    "field_name",
    "read_only",
    1,
    "Check"
)
```

**After editing:**
```bash
bench migrate
```

---

### 3. **Edit Field Layout via Frappe UI** (Temporary Changes)
**Location:** Frappe Desk → Customize → Customize Form

**Steps:**
1. Go to **Frappe Desk**
2. Search for **"Customize Form"**
3. Select **"Job Applicant"** DocType
4. You can:
   - Reorder fields (drag and drop)
   - Change field labels
   - Show/hide fields
   - Change field properties

**⚠️ Note:** Changes made here are stored in the database and may be overwritten by migrations. Use this for quick testing only.

---

### 4. **Edit Web Form Fields**
**Location:** 
- `/apps/alpinos/alpinos/web_form_setup.py` - Initial web form creation
- `/apps/alpinos/alpinos/web_form_update.py` - Web form updates

**Or via UI:**
- Go to **Website** → **Web Forms**
- Find **"job-application"** web form
- Edit fields directly

**⚠️ Note:** UI changes may be overwritten by code migrations.

---

### 5. **Edit Field Validation Logic**
**Location:** `/apps/alpinos/alpinos/job_applicant_automation.py`

This is where you add:
- Field validation
- Auto-population logic
- Business rules

**Example:**
```python
def validate_mandatory_fields(doc, method=None):
    """Validate all mandatory fields are filled"""
    if not doc.get("field_name"):
        frappe.throw(_("Field Name is mandatory"))
```

**After editing:**
```bash
bench restart
# No migration needed for Python code changes
```

---

## 🎯 QUICK REFERENCE GUIDE

| What to Edit | File Location | Command After Edit |
|--------------|---------------|-------------------|
| **Add new field** | `custom_fields.py` | `bench migrate` |
| **Hide/show field** | `update_job_applicant_fields.py` | `bench migrate` |
| **Change field label** | `update_job_applicant_fields.py` | `bench migrate` |
| **Change field order** | `custom_fields.py` (insert_after) | `bench migrate` |
| **Add validation** | `job_applicant_automation.py` | `bench restart` |
| **Web form fields** | `web_form_setup.py` or UI | `bench migrate` (if code) |
| **Quick UI test** | Customize Form (UI) | None (temporary) |

---

## 📝 COMMON EDITS

### Hide a Field Completely
**File:** `patches/v1_0/update_job_applicant_fields.py`

```python
# Add to the "HIDE UNWANTED FIELDS" section
hide_field_completely("Job Applicant", "field_name")
```

### Add a New Field
**File:** `custom_fields.py`

```python
dict(
    fieldname="new_field",
    label="New Field",
    fieldtype="Data",
    insert_after="existing_field",
    reqd=1,  # Optional: make mandatory
)
```

### Change Field Label
**File:** `patches/v1_0/update_job_applicant_fields.py`

```python
update_property_setter(
    "Job Applicant",
    "field_name",
    "label",
    "New Label",
    "Data"
)
```

### Make Field Read-Only
**File:** `patches/v1_0/update_job_applicant_fields.py`

```python
update_property_setter(
    "Job Applicant",
    "field_name",
    "read_only",
    1,
    "Check"
)
```

### Add Field Validation
**File:** `job_applicant_automation.py`

```python
def validate_custom_field(doc, method=None):
    if doc.field_name and len(doc.field_name) < 5:
        frappe.throw(_("Field must be at least 5 characters"))
```

Then add to `hooks.py`:
```python
"validate": [
    "alpinos.job_applicant_automation.validate_custom_field"
]
```

---

## 🔄 WORKFLOW FOR FIELD CHANGES

1. **Edit the appropriate file** (see table above)
2. **Save the file**
3. **Run the command:**
   - For field definitions: `bench migrate`
   - For Python code: `bench restart`
4. **Clear cache:**
   ```bash
   bench clear-cache
   ```
5. **Test in browser** (refresh the page)

---

## ⚠️ IMPORTANT NOTES

1. **Always use code** for permanent changes (not UI)
2. **UI changes** are temporary and may be lost
3. **Run `bench migrate`** after field definition changes
4. **Run `bench restart`** after Python code changes
5. **Clear cache** if changes don't appear immediately

---

## 🆘 TROUBLESHOOTING

### Field not appearing?
- Check if field is hidden in `update_job_applicant_fields.py`
- Run `bench migrate`
- Clear cache: `bench clear-cache`
- Check if field exists in DocType: `bench console` → `frappe.get_doc("DocField", {"parent": "Job Applicant", "fieldname": "field_name"})`

### Field changes not saving?
- Check file syntax
- Run `bench migrate` again
- Check for errors in logs: `bench --site [site-name] logs`

### Web form not updating?
- Check `web_form_update.py` for field visibility
- Update web form via UI or code
- Clear browser cache

---

**Last Updated:** 2025-01-27












