"""
Quick script to send pre-onboarding email
Run: bench --site [site] console
Then: exec(open('apps/alpinos/alpinos/send_test_email.py').read())
"""

import frappe
from alpinos.employee_onboarding_automation import send_pre_onboarding_email
from alpinos.employee_onboarding_webform import get_webform_url

# Your Employee Onboarding name
onboarding_name = "HR-EMP-ONB-2026-00015"

try:
    # Get the document
    if not frappe.db.exists("Employee Onboarding", onboarding_name):
        print(f"❌ Employee Onboarding {onboarding_name} not found")
    else:
        doc = frappe.get_doc("Employee Onboarding", onboarding_name)
        
        # Get job applicant email
        if not doc.job_applicant:
            print(f"❌ No Job Applicant linked to Employee Onboarding {onboarding_name}")
        else:
            job_applicant = frappe.get_doc("Job Applicant", doc.job_applicant)
            applicant_email = job_applicant.email_id if hasattr(job_applicant, 'email_id') else None
            
            if not applicant_email:
                print(f"❌ No email ID found for Job Applicant {doc.job_applicant}")
            else:
                print(f"📧 Sending email to: {applicant_email}")
                print(f"📅 Date of Joining: {doc.date_of_joining_onboarding}")
                print(f"👤 Employee: {doc.full_name_display or doc.employee_name or 'N/A'}")
                
                # Send the email
                send_pre_onboarding_email(doc, applicant_email)
                
                # Get webform URL
                webform_url = get_webform_url(onboarding_name)
                print(f"\n✅ Email sent successfully!")
                print(f"🔗 Webform URL: {webform_url}")
                print(f"\nNote: If email fails due to server configuration, check Email Account settings.")
except Exception as e:
    print(f"❌ Error: {str(e)}")
    import traceback
    traceback.print_exc()



