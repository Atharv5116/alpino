"""
Patch to create a complete Job Applicant with all mandatory fields including resume attachment
"""

import frappe
from frappe.utils import today, add_days
from frappe.utils.file_manager import save_file


def execute():
	"""Create a new Job Applicant with all mandatory fields including resume attachment"""
	
	# Get default currency
	default_currency = frappe.db.get_value("Company", {"name": ("!=", "")}, "default_currency") or "INR"
	
	# Get or create a Job Opening for linking
	job_opening = frappe.db.get_value("Job Opening", {"status": ("!=", "Closed")}, "name")
	if not job_opening:
		try:
			job_opening_doc = frappe.get_doc({
				"doctype": "Job Opening",
				"job_title": "Software Developer",
				"company": frappe.db.get_value("Company", {"name": ("!=", "")}, "name") or frappe.db.get_single_value("Global Defaults", "default_company"),
				"status": "Open"
			})
			job_opening_doc.flags.ignore_validate = True
			job_opening_doc.flags.ignore_mandatory = True
			job_opening_doc.insert(ignore_permissions=True)
			job_opening = job_opening_doc.name
			frappe.db.commit()
			print(f"✅ Created Job Opening: {job_opening}")
		except Exception as e:
			print(f"⚠️  Could not create Job Opening: {str(e)}")
	
	# New applicant data with all mandatory fields
	applicant_email = "complete.applicant@example.com"
	
	# Check if applicant already exists
	existing = frappe.db.exists("Job Applicant", {"email_id": applicant_email})
	if existing:
		print(f"ℹ️  Job Applicant with email {applicant_email} already exists, skipping...")
		return
	
	try:
		# Create a dummy PDF file content for resume
		pdf_content = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>endobj\n4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Times-Roman>>endobj\n5 0 obj<</Length 44>>stream\nBT\n/F1 12 Tf\n100 700 Td\n(Resume) Tj\nET\nendstream\nendobj\nxref\n0 6\ntrailer<</Size 6/Root 1 0 R>>\nstartxref\n250\n%%EOF"
		
		# Create Job Applicant first (without resume_attachment, will add it after)
		applicant = frappe.get_doc({
			"doctype": "Job Applicant",
			"applicant_name": "Complete Test Applicant",
			"email_id": applicant_email,
			"phone_number": "+1234567999",
			"status": "Draft",
			"marital_status": "Single",
			"city_state": "Hyderabad, Telangana",
			"job_requisition": job_opening,
			"application_date": today(),
			"total_experience": "4 years",
			# Employment History mandatory fields
			"employment_company_name": "Tech Corp India",
			"employment_designation": "Software Engineer",
			"employment_current_ctc": "550000",
			"employment_expected_ctc": "600000",
			"employment_reason_for_leaving": "Looking for better opportunities and career growth",
			"employment_start_date": add_days(today(), -365*3),
			"employment_end_date": today(),
			"employment_notice_period": "30 days"
		})
		
		# Insert the applicant first
		applicant.flags.ignore_validate = True
		applicant.flags.ignore_mandatory = True
		applicant.insert(ignore_permissions=True)
		
		# Set candidate_id = name (should already be set by hook, but ensure it)
		applicant.candidate_id = applicant.name
		applicant.save(ignore_permissions=True)
		frappe.db.commit()
		
		# Now create and attach the resume file
		try:
			file_doc = save_file(
				fname="resume_complete_applicant.pdf",
				content=pdf_content,
				dt="Job Applicant",
				dn=applicant.name,
				df="resume_attachment",
				is_private=0
			)
			
			# Update the applicant with the file URL
			applicant.resume_attachment = file_doc.file_url
			applicant.save(ignore_permissions=True)
			frappe.db.commit()
			
			print(f"✅ Created complete Job Applicant: {applicant.name} - Complete Test Applicant")
			print(f"   Candidate ID: {applicant.candidate_id}")
			print(f"   Resume attached: {file_doc.file_url}")
			
		except Exception as file_error:
			print(f"⚠️  Could not attach resume file: {str(file_error)}")
			# Applicant is still created, just without resume
		
	except Exception as e:
		print(f"⚠️  Could not create Job Applicant: {str(e)}")
		frappe.log_error(f"Error creating complete job applicant: {str(e)}\nTraceback: {frappe.get_traceback()}", "Create Complete Job Applicant Error")
		frappe.db.rollback()

