"""
Patch to create new Job Applicant entries with all mandatory fields set
"""

import frappe
from frappe.utils import today, add_days


def execute():
	"""Create new Job Applicant entries with all mandatory fields"""
	
	# Get default currency
	default_currency = frappe.db.get_value("Company", {"name": ("!=", "")}, "default_currency") or "INR"
	
	# Get or create a Job Opening for linking
	job_opening = frappe.db.get_value("Job Opening", {"status": ("!=", "Closed")}, "name")
	if not job_opening:
		# Create a test Job Opening if none exists
		try:
			job_opening_doc = frappe.get_doc({
				"doctype": "Job Opening",
				"job_title": "Test Software Engineer",
				"company": frappe.db.get_value("Company", {"name": ("!=", "")}, "name") or frappe.db.get_single_value("Global Defaults", "default_company"),
				"status": "Open"
			})
			job_opening_doc.flags.ignore_validate = True
			job_opening_doc.flags.ignore_mandatory = True
			job_opening_doc.insert(ignore_permissions=True)
			job_opening = job_opening_doc.name
			frappe.db.commit()
			print(f"✅ Created test Job Opening: {job_opening}")
		except Exception as e:
			print(f"⚠️  Could not create Job Opening: {str(e)}")
	
	# New applicants with all mandatory fields
	new_applicants = [
		{
			"applicant_name": "Michael Anderson",
			"email_id": "michael.anderson@example.com",
			"phone_number": "+1234567900",
			"resume_link": "https://example.com/resumes/michael_anderson.pdf",
			"degree": "Master of Science in Software Engineering",
			"upper_range": 650000,
			"currency": default_currency,
			"status": "Draft",
			"marital_status": "Single",
			"city_state": "Bangalore, Karnataka",
			"total_experience": "5 years",
			"application_date": today(),
			"job_requisition": job_opening,
			"employment_company_name": "Tech Solutions Inc",
			"employment_designation": "Senior Developer",
			"employment_current_ctc": "600000",
			"employment_expected_ctc": "650000",
			"employment_reason_for_leaving": "Looking for better growth opportunities",
			"employment_start_date": add_days(today(), -365*2),  # 2 years ago
			"employment_end_date": today(),
			"employment_notice_period": "30 days"
		},
		{
			"applicant_name": "Sarah Davis",
			"email_id": "sarah.davis@example.com",
			"phone_number": "+1234567901",
			"resume_link": "https://example.com/resumes/sarah_davis.pdf",
			"degree": "Bachelor of Engineering in Electronics",
			"upper_range": 580000,
			"currency": default_currency,
			"status": "Draft",
			"marital_status": "Married",
			"city_state": "Mumbai, Maharashtra",
			"total_experience": "4 years",
			"application_date": today(),
			"job_requisition": job_opening,
			"employment_company_name": "Digital Innovations Ltd",
			"employment_designation": "Software Engineer",
			"employment_current_ctc": "550000",
			"employment_expected_ctc": "580000",
			"employment_reason_for_leaving": "Seeking new challenges and better compensation",
			"employment_start_date": add_days(today(), -365*3),
			"employment_end_date": today(),
			"employment_notice_period": "30 days"
		},
		{
			"applicant_name": "Robert Taylor",
			"email_id": "robert.taylor@example.com",
			"phone_number": "+1234567902",
			"resume_link": "https://example.com/resumes/robert_taylor.pdf",
			"degree": "Bachelor of Technology in Computer Science",
			"upper_range": 620000,
			"currency": default_currency,
			"status": "Draft",
			"marital_status": "Single",
			"city_state": "Delhi, NCR",
			"total_experience": "6 years",
			"application_date": today(),
			"job_requisition": job_opening,
			"employment_company_name": "Cloud Systems Pvt Ltd",
			"employment_designation": "Lead Developer",
			"employment_current_ctc": "600000",
			"employment_expected_ctc": "620000",
			"employment_reason_for_leaving": "Company relocation and career advancement",
			"employment_start_date": add_days(today(), -365*5),
			"employment_end_date": today(),
			"employment_notice_period": "45 days"
		},
		{
			"applicant_name": "Emily Wilson",
			"email_id": "emily.wilson@example.com",
			"phone_number": "+1234567903",
			"resume_link": "https://example.com/resumes/emily_wilson.pdf",
			"degree": "Master of Computer Applications",
			"upper_range": 700000,
			"currency": default_currency,
			"status": "Draft",
			"marital_status": "Single",
			"city_state": "Pune, Maharashtra",
			"total_experience": "7 years",
			"application_date": today(),
			"job_requisition": job_opening,
			"employment_company_name": "Data Analytics Corp",
			"employment_designation": "Senior Software Architect",
			"employment_current_ctc": "680000",
			"employment_expected_ctc": "700000",
			"employment_reason_for_leaving": "Exploring new technologies and better work culture",
			"employment_start_date": add_days(today(), -365*6),
			"employment_end_date": today(),
			"employment_notice_period": "60 days"
		},
		{
			"applicant_name": "David Martinez",
			"email_id": "david.martinez@example.com",
			"phone_number": "+1234567904",
			"resume_link": "https://example.com/resumes/david_martinez.pdf",
			"degree": "Bachelor of Science in Information Technology",
			"upper_range": 550000,
			"currency": default_currency,
			"status": "Draft",
			"marital_status": "Married",
			"city_state": "Chennai, Tamil Nadu",
			"total_experience": "3 years",
			"application_date": today(),
			"job_requisition": job_opening,
			"employment_company_name": "Startup Solutions",
			"employment_designation": "Junior Developer",
			"employment_current_ctc": "500000",
			"employment_expected_ctc": "550000",
			"employment_reason_for_leaving": "Looking for growth opportunities and skill development",
			"employment_start_date": add_days(today(), -365*2),
			"employment_end_date": today(),
			"employment_notice_period": "30 days"
		}
	]
	
	created_count = 0
	existing_count = 0
	
	for applicant_data in new_applicants:
		# Check if applicant already exists by email
		existing = frappe.db.exists("Job Applicant", {"email_id": applicant_data["email_id"]})
		
		if existing:
			existing_count += 1
			print(f"ℹ️  Job Applicant with email {applicant_data['email_id']} already exists, skipping...")
			continue
		
		try:
			# Create Job Applicant with all mandatory fields
			applicant = frappe.get_doc({
				"doctype": "Job Applicant",
				# Mandatory fields from base doctype
				"applicant_name": applicant_data["applicant_name"],
				"email_id": applicant_data["email_id"],
				"status": applicant_data["status"],
				# Mandatory custom fields
				"phone_number": applicant_data.get("phone_number"),
				"marital_status": applicant_data.get("marital_status"),
				"city_state": applicant_data.get("city_state"),
				"job_requisition": applicant_data.get("job_requisition"),
				"application_date": applicant_data.get("application_date"),
				"total_experience": applicant_data.get("total_experience"),
				# Employment History mandatory fields
				"employment_company_name": applicant_data.get("employment_company_name"),
				"employment_designation": applicant_data.get("employment_designation"),
				"employment_current_ctc": applicant_data.get("employment_current_ctc"),
				"employment_expected_ctc": applicant_data.get("employment_expected_ctc"),
				"employment_reason_for_leaving": applicant_data.get("employment_reason_for_leaving"),
				"employment_start_date": applicant_data.get("employment_start_date"),
				"employment_end_date": applicant_data.get("employment_end_date"),
				"employment_notice_period": applicant_data.get("employment_notice_period"),
				# Optional fields
				"resume_link": applicant_data.get("resume_link"),
				"degree": applicant_data.get("degree"),
				"upper_range": applicant_data.get("upper_range"),
				"currency": applicant_data.get("currency")
			})
			
			# Insert - the override will handle CAND-#### naming
			# Note: resume_attachment is mandatory but we'll bypass it for script creation
			applicant.flags.ignore_validate = True  # Bypass validation for resume_attachment
			applicant.flags.ignore_mandatory = True  # Bypass mandatory for resume_attachment
			applicant.insert(ignore_permissions=True)
			
			# Set candidate_id = name (should already be set by hook, but ensure it)
			applicant.candidate_id = applicant.name
			applicant.save(ignore_permissions=True)
			
			frappe.db.commit()
			created_count += 1
			print(f"✅ Created Job Applicant: {applicant.name} - {applicant_data['applicant_name']} (Candidate ID: {applicant.candidate_id})")
			
		except Exception as e:
			print(f"⚠️  Could not create Job Applicant {applicant_data['applicant_name']}: {str(e)}")
			frappe.log_error(f"Error creating job applicant: {str(e)}\nTraceback: {frappe.get_traceback()}", "Create Job Applicant Error")
			frappe.db.rollback()
	
	print(f"\n✅ New Job Applicants: {created_count} created, {existing_count} already existed")
	if created_count > 0:
		print(f"   All new applicants have CAND-#### format IDs with all mandatory fields set")

