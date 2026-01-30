"""
Patch to create sample Job Applicant entries for testing
"""

import frappe
from frappe.utils import today, add_days


def execute():
	"""Create sample Job Applicant entries"""
	
	# Get default currency
	default_currency = frappe.db.get_value("Company", {"name": ("!=", "")}, "default_currency") or "INR"
	
	# Sample data
	sample_applicants = [
		{
			"applicant_name": "John Doe",
			"email_id": "john.doe@example.com",
			"phone_number": "+1234567890",
			"resume_link": "https://example.com/resumes/john_doe.pdf",
			"degree": "Bachelor of Science in Computer Science",
			"upper_range": 500000,
			"currency": default_currency,
			"status": "Draft"
		},
		{
			"applicant_name": "Jane Smith",
			"email_id": "jane.smith@example.com",
			"phone_number": "+1234567891",
			"resume_link": "https://example.com/resumes/jane_smith.pdf",
			"degree": "Master of Business Administration",
			"upper_range": 750000,
			"currency": default_currency,
			"status": "Draft"
		},
		{
			"applicant_name": "Bob Johnson",
			"email_id": "bob.johnson@example.com",
			"phone_number": "+1234567892",
			"resume_link": "https://example.com/resumes/bob_johnson.pdf",
			"degree": "Bachelor of Engineering",
			"upper_range": 600000,
			"currency": default_currency,
			"status": "Draft"
		},
		{
			"applicant_name": "Alice Williams",
			"email_id": "alice.williams@example.com",
			"phone_number": "+1234567893",
			"resume_link": "https://example.com/resumes/alice_williams.pdf",
			"degree": "Master of Technology",
			"upper_range": 800000,
			"currency": default_currency,
			"status": "Draft"
		},
		{
			"applicant_name": "Charlie Brown",
			"email_id": "charlie.brown@example.com",
			"phone_number": "+1234567894",
			"resume_link": "https://example.com/resumes/charlie_brown.pdf",
			"degree": "Bachelor of Commerce",
			"upper_range": 450000,
			"currency": default_currency,
			"status": "Draft"
		}
	]
	
	created_count = 0
	existing_count = 0
	
	for applicant_data in sample_applicants:
		# Check if applicant already exists by email
		existing = frappe.db.exists("Job Applicant", {"email_id": applicant_data["email_id"]})
		
		if existing:
			existing_count += 1
			print(f"ℹ️  Job Applicant with email {applicant_data['email_id']} already exists, skipping...")
			continue
		
		try:
			# Create Job Applicant
			applicant = frappe.get_doc({
				"doctype": "Job Applicant",
				"applicant_name": applicant_data["applicant_name"],
				"email_id": applicant_data["email_id"],
				"phone_number": applicant_data["phone_number"],
				"resume_link": applicant_data["resume_link"],
				"degree": applicant_data["degree"],
				"upper_range": applicant_data["upper_range"],
				"currency": applicant_data["currency"],
				"status": applicant_data["status"]
			})
			
			# Insert without triggering hooks to avoid duplicate email check issues
			applicant.flags.ignore_validate = True
			applicant.flags.ignore_mandatory = True
			applicant.insert(ignore_permissions=True)
			
			# Set candidate_id = name (after insert, name is set)
			# Both will be in AHFPL0000 format (e.g., AHFPL0001, AHFPL0002)
			applicant.candidate_id = applicant.name
			applicant.save(ignore_permissions=True)
			
			frappe.db.commit()
			created_count += 1
			print(f"✅ Created Job Applicant: {applicant.name} - {applicant_data['applicant_name']}")
			
		except Exception as e:
			print(f"⚠️  Could not create Job Applicant {applicant_data['applicant_name']}: {str(e)}")
			frappe.db.rollback()
	
	print(f"\n✅ Sample Job Applicants: {created_count} created, {existing_count} already existed")

