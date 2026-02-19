# Employee Onboarding Webform Testing Guide

## Prerequisites

1. Ensure all migrations have been run:
   ```bash
   bench migrate
   ```

2. Ensure custom fields are set up:
   ```bash
   bench --site [your-site] console
   ```
   Then run:
   ```python
   from alpinos.employee_onboarding_custom_fields import setup_employee_onboarding_custom_fields
   setup_employee_onboarding_custom_fields()
   ```

3. Ensure email templates are created:
   ```python
   from alpinos.patches.create_hrms_email_templates import execute
   execute()
   ```

## Testing Steps

### 1. Create Test Employee Onboarding Record

1. Go to **Employee Onboarding** list
2. Create a new Employee Onboarding record:
   - Link a **Job Applicant**
   - Set **Date of Joining (DOJ)** to a date that's 7 days from today (or in the past)
   - Fill in basic required fields
   - Set **Boarding Status** to "Pre-Onboarding Initiated"
   - Save the record

3. Note down the **Employee Onboarding name** (e.g., `HR-EMP-ONB-2025-00001`)

### 2. Test Email Sending (Manual Trigger)

Since the email is sent 1 week before DOJ, you can manually trigger it:

```python
# In Frappe console (bench --site [site] console)
import frappe
from alpinos.employee_onboarding_automation import send_pre_onboarding_email

# Get your test Employee Onboarding
onboarding_name = "HR-EMP-ONB-2025-00001"  # Replace with your actual name
doc = frappe.get_doc("Employee Onboarding", onboarding_name)

# Get applicant email
job_applicant = frappe.get_doc("Job Applicant", doc.job_applicant)
applicant_email = job_applicant.email_id

# Send email
send_pre_onboarding_email(doc, applicant_email)
```

**Expected Result:**
- Email should be sent to the applicant
- Email should contain webform link with `?name={onboarding_name}` parameter
- Employee Onboarding status should change to "Document Pending"

### 3. Test Webform URL Generation

```python
# In Frappe console
from alpinos.employee_onboarding_webform import get_webform_url

onboarding_name = "HR-EMP-ONB-2025-00001"  # Replace with your actual name
url = get_webform_url(onboarding_name)
print(url)
```

**Expected Result:**
- URL should be: `http://[your-site]/webform/employee-onboarding-details?name=HR-EMP-ONB-2025-00001`

### 4. Test Webform Access

1. Open the webform URL in a browser (use the URL from step 3)
2. **Expected Behavior:**
   - Webform should load
   - Hidden field `employee_onboarding_name` should be populated with the Employee Onboarding name
   - All fields should be visible and editable

### 5. Test Webform Submission

1. Fill in the webform with test data:
   - **Personal Details:**
     - Date of Birth: Select a date
     - Gender: Select from dropdown
     - Blood Group: Select from dropdown
     - Nationality: Select from dropdown
     - Aadhaar Card: Enter test number
     - PAN Card: Enter test number
     - Names as per Aadhaar/PAN: Enter test names
     - Passport Size Photo: Upload a test image
   
   - **Address Details:**
     - Current Address: Enter test address
     - Current Accommodation Type: Select Rented/Owned
     - Permanent Address: Enter test address
     - Permanent Accommodation Type: Select Rented/Owned
   
   - **Qualification Details:**
     - Click "Add Row" in Qualifications table
     - Fill: Degree, Grade, University, Graduation Year
     - Upload Degree Certificate (optional)
   
   - **Work Experience:**
     - Click "Add Row" in Experience table
     - Fill: Company Name, Start Date, End Date, Designation, City
   
   - **Bank Details:**
     - Bank Name: Enter test bank name
     - Branch: Enter test branch
     - Account Number: Enter test account number
     - Account Type: Enter test type
     - IFSC Code: Enter test IFSC
     - Bank Account Proof: Upload test document
   
   - **Family Details:**
     - Family Member Name: Enter test name
     - Relation: Select from dropdown
     - Contact Number: Enter test number
     - Occupation: Enter test occupation
   
   - **Emergency Contact:**
     - Emergency Contact Name: Enter test name
     - Relation: Select from dropdown
     - Emergency Contact Number: Enter test number

2. Click **Submit**

**Expected Result:**
- Success message: "Thank you! Your onboarding details have been successfully submitted!"
- Redirect to success URL (homepage)

### 6. Verify Data Update in Employee Onboarding

1. Go to **Employee Onboarding** list
2. Open the test record
3. **Verify the following fields are updated:**
   - Personal Details section: All fields should be filled
   - Address Details: Both addresses should be filled
   - Qualification Child table: Should have new rows appended
   - Experience table: Should have new rows appended
   - Bank Details: All fields should be filled
   - Family Details: All fields should be filled
   - Emergency Contact: All fields should be filled
   - **Webform Tracking section (hidden):**
     - `webform_submitted` should be checked
     - `webform_submitted_on` should have timestamp

### 7. Test Duplicate Submission Prevention

1. Try to access the webform URL again (same Employee Onboarding)
2. **Expected Behavior:**
   - JavaScript should detect already submitted status
   - Error message: "This form has already been submitted. Please contact HR if you need to make changes."
   - Submit button should be disabled

3. Try to submit anyway (if you bypass the JavaScript check)
4. **Expected Behavior:**
   - Server-side validation should prevent submission
   - Error: "This form has already been submitted. Please contact HR if you need to make changes."

### 8. Test Invalid Reference

1. Access webform with invalid Employee Onboarding name:
   ```
   /webform/employee-onboarding-details?name=INVALID-NAME
   ```

2. **Expected Behavior:**
   - Error message: "Invalid Employee Onboarding reference. Please contact HR."

### 9. Test Missing Reference

1. Access webform without name parameter:
   ```
   /webform/employee-onboarding-details
   ```

2. **Expected Behavior:**
   - JavaScript should show error: "Employee Onboarding reference is missing. Please use the link provided in your email."

### 10. Test Scheduled Email (Daily Job)

The scheduled job runs daily to send emails 1 week before DOJ:

```python
# In Frappe console
from alpinos.employee_onboarding_automation import send_scheduled_pre_onboarding_emails

# Run the scheduled job manually
send_scheduled_pre_onboarding_emails()
```

**Expected Result:**
- Should find Employee Onboarding records where:
  - `date_of_joining_onboarding` is exactly 7 days from today
  - `boarding_status` is "Pre-Onboarding Initiated"
  - `docstatus` is not cancelled
- Should send emails to all matching records

### 11. Test Table Data Appending

1. Create a new Employee Onboarding record
2. Manually add some qualification/experience rows in the Employee Onboarding form
3. Submit webform with additional qualification/experience rows
4. **Expected Result:**
   - New rows should be **appended** to existing rows (not replaced)
   - Both old and new rows should be present

## Troubleshooting

### Issue: Webform not loading
- Check if webform is published: Go to **Web Form** list, find "employee-onboarding-details", ensure `published = 1`
- Check route: Should be "employee-onboarding-details"

### Issue: Hidden field not populated
- Check browser console for JavaScript errors
- Verify URL parameter is present: `?name=...`
- Check if `employee_onboarding_details.js` is loaded

### Issue: Data not updating
- Check Frappe error log: **Error Log** list
- Verify Employee Onboarding name exists
- Check if `webform_submitted` is already set (prevents duplicate)

### Issue: Email not sending
- Check email queue: **Email Queue** list
- Verify email template exists: "Onboarding - Document Reminder"
- Check email account settings

### Issue: Handler not executing
- Verify hook is registered in `hooks.py`
- Check if function is imported correctly
- Check Frappe error log for import errors

## Test Checklist

- [ ] Email sent with webform link
- [ ] Webform URL contains correct Employee Onboarding name
- [ ] Webform loads successfully
- [ ] Hidden field populated from URL
- [ ] All form fields are visible and editable
- [ ] Form submission successful
- [ ] Data updated in Employee Onboarding
- [ ] Qualification rows appended (not replaced)
- [ ] Experience rows appended (not replaced)
- [ ] `webform_submitted` flag set
- [ ] `webform_submitted_on` timestamp set
- [ ] Duplicate submission prevented
- [ ] Invalid reference handled
- [ ] Missing reference handled
- [ ] Temporary document deleted after processing

## Quick Test Script

Run this in Frappe console for quick testing:

```python
import frappe
from alpinos.employee_onboarding_automation import send_pre_onboarding_email
from alpinos.employee_onboarding_webform import get_webform_url

# Get a test Employee Onboarding
onboarding_name = "HR-EMP-ONB-2025-00001"  # Replace with actual name

# Check if exists
if frappe.db.exists("Employee Onboarding", onboarding_name):
    doc = frappe.get_doc("Employee Onboarding", onboarding_name)
    
    # Get webform URL
    webform_url = get_webform_url(onboarding_name)
    print(f"Webform URL: {webform_url}")
    
    # Check if already submitted
    if doc.get('webform_submitted'):
        print("⚠️  Webform already submitted")
        print(f"Submitted on: {doc.get('webform_submitted_on')}")
    else:
        print("✅ Webform not yet submitted")
        
        # Get applicant email
        if doc.job_applicant:
            job_applicant = frappe.get_doc("Job Applicant", doc.job_applicant)
            applicant_email = job_applicant.email_id
            print(f"Applicant Email: {applicant_email}")
            
            # Send test email
            send_pre_onboarding_email(doc, applicant_email)
            print("✅ Test email sent")
        else:
            print("⚠️  No Job Applicant linked")
else:
    print(f"❌ Employee Onboarding {onboarding_name} not found")
```



