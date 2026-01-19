"""
Custom Fields for Employee Onboarding DocType
Adds all required sections and fields as per requirements
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def setup_employee_onboarding_custom_fields():
	"""Create custom fields for Employee Onboarding"""
	
	custom_fields = {
		"Employee Onboarding": [
			# ============================================
			# SECTION: Company Details
			# ============================================
			dict(
				fieldname="company_details_section",
				label="Company Details",
				fieldtype="Section Break",
				insert_after="details_section",
				collapsible=1,
				hidden=0,  # Show Company Details section with 2 columns
			),
			# Note: company field (standard field) is positioned after company_details_section via property setter (left column)
			# Only 2 columns: column_break_7 (standard) and column_break_company_unique_id
			dict(
				fieldname="column_break_company_unique_id",
				fieldtype="Column Break",
				insert_after="company_details_section",
			),
			dict(
				fieldname="candidate_id",
				label="Unique id",
				fieldtype="Link",
				options="Job Applicant",
				insert_after="column_break_company_unique_id",
				read_only=1,
				reqd=0,  # Not mandatory since it's auto-filled
				hidden=0,
				in_list_view=0,
				in_standard_filter=0,
				# Will be auto-populated from job_applicant when form is created
			),
			# Note: boarding_status is moved here via property setters
			# Removed column_break_company_details to have only 2 columns
			
			# ============================================
			# SECTION: Personal Details
			# ============================================
			dict(
				fieldname="personal_details_section",
				label="Personal Details",
				fieldtype="Section Break",
				insert_after="candidate_id",
				collapsible=1,
			),
			dict(
				fieldname="first_name",
				label="First Name",
				fieldtype="Data",
				insert_after="personal_details_section",
				reqd=1,
				read_only=1,
				fetch_from="job_applicant.applicant_name",
			),
			dict(
				fieldname="middle_name",
				label="Middle Name",
				fieldtype="Data",
				insert_after="first_name",
			),
			dict(
				fieldname="last_name",
				label="Last Name",
				fieldtype="Data",
				insert_after="middle_name",
			),
			dict(
				fieldname="full_name_display",
				label="Full Name (First, Middle, Last)",
				fieldtype="Data",
				insert_after="last_name",
				reqd=1,
				read_only=1,
				# Will be auto-populated from first_name, middle_name, last_name
			),
			dict(
				fieldname="personal_mobile_number",
				label="Personal Mobile Number",
				fieldtype="Data",
				insert_after="full_name_display",
				reqd=1,
				read_only=1,
				fetch_from="job_applicant.phone_number",
			),
			dict(
				fieldname="personal_email",
				label="Personal Email",
				fieldtype="Data",
				insert_after="personal_mobile_number",
				reqd=1,
				read_only=1,
				fetch_from="job_applicant.email_id",
			),
			dict(
				fieldname="date_of_birth",
				label="Date of Birth (DOB)",
				fieldtype="Date",
				insert_after="personal_email",
				reqd=1,
			),
			dict(
				fieldname="gender",
				label="Gender",
				fieldtype="Select",
				options="\nMale\nFemale\nOther",
				insert_after="date_of_birth",
				reqd=1,
			),
			dict(
				fieldname="marital_status_onboarding",
				label="Marital Status",
				fieldtype="Select",
				options="\nSingle\nMarried\nDivorced\nWidowed",
				insert_after="gender",
				reqd=1,
				read_only=1,
				fetch_from="job_applicant.marital_status",
			),
			dict(
				fieldname="column_break_personal_details",
				fieldtype="Column Break",
				insert_after="marital_status_onboarding",
			),
			dict(
				fieldname="blood_group",
				label="Blood Group",
				fieldtype="Select",
				options="\nA+\nA-\nB+\nB-\nAB+\nAB-\nO+\nO-",
				insert_after="column_break_personal_details",
				reqd=1,
			),
			dict(
				fieldname="physically_handicapped",
				label="Physically Handicapped",
				fieldtype="Check",
				insert_after="blood_group",
			),
			dict(
				fieldname="nationality",
				label="Nationality",
				fieldtype="Select",
				options="\nIndian\nOther",
				insert_after="physically_handicapped",
				reqd=1,
			),
			dict(
				fieldname="aadhaar_card",
				label="Aadhaar Card",
				fieldtype="Data",
				insert_after="nationality",
				reqd=1,
			),
			dict(
				fieldname="pan_card",
				label="PAN Card",
				fieldtype="Data",
				insert_after="aadhaar_card",
				reqd=1,
			),
			dict(
				fieldname="name_as_per_aadhaar",
				label="Name as per Aadhaar Card",
				fieldtype="Data",
				insert_after="pan_card",
				reqd=1,
			),
			dict(
				fieldname="name_as_per_pan",
				label="Name as per PAN Card",
				fieldtype="Data",
				insert_after="name_as_per_aadhaar",
				reqd=1,
			),
			dict(
				fieldname="passport_size_photo",
				label="Passport Size Photo",
				fieldtype="Attach",
				insert_after="name_as_per_pan",
				reqd=1,
			),
			
			# ============================================
			# SECTION: Address Details
			# ============================================
			dict(
				fieldname="address_details_section",
				label="Address Details",
				fieldtype="Section Break",
				insert_after="passport_size_photo",
				collapsible=1,
			),
			dict(
				fieldname="address_line_1",
				label="Address Line 1",
				fieldtype="Data",
				insert_after="address_details_section",
				reqd=1,
			),
			dict(
				fieldname="address_line_2",
				label="Address Line 2",
				fieldtype="Data",
				insert_after="address_line_1",
				reqd=1,
			),
			dict(
				fieldname="pincode",
				label="Pincode",
				fieldtype="Data",
				insert_after="address_line_2",
				reqd=1,
			),
			dict(
				fieldname="city_state_combined",
				label="City / State",
				fieldtype="Data",
				insert_after="pincode",
				read_only=1,
				fetch_from="job_applicant.city_state",
			),
			dict(
				fieldname="column_break_address",
				fieldtype="Column Break",
				insert_after="city_state_combined",
			),
			
			# ============================================
			# SECTION: Qualification Details
			# ============================================
			dict(
				fieldname="qualification_details_section",
				label="Qualification Details",
				fieldtype="Section Break",
				insert_after="column_break_address",
				collapsible=1,
			),
			dict(
				fieldname="degree",
				label="Degree",
				fieldtype="Data",
				insert_after="qualification_details_section",
				reqd=1,
				read_only=1,
				fetch_from="job_applicant.degree",
			),
			dict(
				fieldname="university",
				label="University",
				fieldtype="Data",
				insert_after="degree",
				reqd=1,
			),
			dict(
				fieldname="graduation_year",
				label="Graduation Year",
				fieldtype="Data",
				insert_after="university",
				reqd=1,
			),
			dict(
				fieldname="column_break_qualification",
				fieldtype="Column Break",
				insert_after="graduation_year",
			),
			dict(
				fieldname="grade",
				label="Grade",
				fieldtype="Data",
				insert_after="column_break_qualification",
				reqd=1,
			),
			dict(
				fieldname="degree_certificate_upload",
				label="Degree Certificate Upload",
				fieldtype="Attach",
				insert_after="grade",
			),
			
			# ============================================
			# SECTION: Work Experience
			# ============================================
			dict(
				fieldname="work_experience_section",
				label="Work Experience",
				fieldtype="Section Break",
				insert_after="column_break_qualification",
				collapsible=1,
			),
			dict(
				fieldname="work_experience_company_name",
				label="Company Name",
				fieldtype="Data",
				insert_after="work_experience_section",
				reqd=1,
				read_only=0,  # User must be able to enter manually
				# User must enter manually - NOT auto-filled, NO fetch_from
			),
			dict(
				fieldname="work_experience_designation",
				label="Designation",
				fieldtype="Data",
				insert_after="work_experience_company_name",
				reqd=1,
				read_only=0,  # User must be able to enter manually
				# User must enter manually - NOT auto-filled, NO fetch_from
			),
			dict(
				fieldname="work_experience_city",
				label="City",
				fieldtype="Data",
				insert_after="work_experience_designation",
				reqd=1,
				read_only=0,  # User must be able to enter manually
				# Editable by Employee
			),
			dict(
				fieldname="column_break_work_experience",
				fieldtype="Column Break",
				insert_after="work_experience_city",
			),
			dict(
				fieldname="work_experience_start_date",
				label="Start Date",
				fieldtype="Date",
				insert_after="column_break_work_experience",
				reqd=1,
				read_only=0,  # User must be able to enter manually
				# User must enter manually - NOT auto-filled, NO fetch_from
			),
			dict(
				fieldname="work_experience_end_date",
				label="End Date",
				fieldtype="Date",
				insert_after="work_experience_start_date",
				reqd=1,
				read_only=0,  # User must be able to enter manually
				# User must enter manually - NOT auto-filled, NO fetch_from
			),
			
			# ============================================
			# SECTION: Bank Details
			# ============================================
			dict(
				fieldname="bank_details_section",
				label="Bank Details",
				fieldtype="Section Break",
				insert_after="column_break_work_experience",
				collapsible=1,
			),
			dict(
				fieldname="bank_name",
				label="Bank Name",
				fieldtype="Data",
				insert_after="bank_details_section",
				reqd=1,
			),
			dict(
				fieldname="branch",
				label="Branch",
				fieldtype="Data",
				insert_after="bank_name",
				reqd=1,
			),
			dict(
				fieldname="account_number",
				label="Account Number",
				fieldtype="Data",
				insert_after="branch",
				reqd=1,
			),
			dict(
				fieldname="column_break_bank",
				fieldtype="Column Break",
				insert_after="account_number",
			),
			dict(
				fieldname="account_type",
				label="Account Type",
				fieldtype="Data",
				insert_after="column_break_bank",
				reqd=1,
			),
			dict(
				fieldname="ifsc_code",
				label="IFSC Code",
				fieldtype="Data",
				insert_after="account_type",
				reqd=1,
			),
			dict(
				fieldname="bank_account_proof",
				label="Bank Account Proof",
				fieldtype="Attach",
				insert_after="ifsc_code",
				reqd=1,
			),
			
			# ============================================
			# SECTION: Family Details
			# ============================================
			dict(
				fieldname="family_details_section",
				label="Family Details",
				fieldtype="Section Break",
				insert_after="column_break_bank",
				collapsible=1,
			),
			dict(
				fieldname="family_name",
				label="Name",
				fieldtype="Data",
				insert_after="family_details_section",
				reqd=1,
			),
			dict(
				fieldname="family_relation",
				label="Relation",
				fieldtype="Select",
				options="\nFather\nMother\nSpouse\nSibling\nOther",
				insert_after="family_name",
				reqd=1,
			),
			dict(
				fieldname="column_break_family",
				fieldtype="Column Break",
				insert_after="family_relation",
			),
			dict(
				fieldname="family_contact_number",
				label="Contact Number",
				fieldtype="Data",
				insert_after="column_break_family",
				reqd=1,
			),
			dict(
				fieldname="family_occupation",
				label="Occupation",
				fieldtype="Data",
				insert_after="family_contact_number",
				reqd=1,
			),
			
			# ============================================
			# SECTION: Emergency Contact
			# ============================================
			dict(
				fieldname="emergency_contact_section",
				label="Emergency Contact",
				fieldtype="Section Break",
				insert_after="column_break_family",
				collapsible=1,
			),
			dict(
				fieldname="emergency_contact_name",
				label="Name",
				fieldtype="Data",
				insert_after="emergency_contact_section",
				reqd=1,
			),
			dict(
				fieldname="emergency_contact_relation",
				label="Relation",
				fieldtype="Select",
				options="\nFather\nMother\nSpouse\nSibling\nFriend\nOther",
				insert_after="emergency_contact_name",
				reqd=1,
			),
			dict(
				fieldname="column_break_emergency",
				fieldtype="Column Break",
				insert_after="emergency_contact_relation",
			),
			dict(
				fieldname="emergency_contact_number",
				label="Contact Number",
				fieldtype="Data",
				insert_after="column_break_emergency",
				reqd=1,
			),
			
			# ============================================
			# SECTION: Company Profile Details
			# ============================================
			dict(
				fieldname="company_profile_details_section",
				label="Company Profile Details",
				fieldtype="Section Break",
				insert_after="column_break_emergency",
				collapsible=1,
			),
			dict(
				fieldname="company_mobile_number",
				label="Company Mobile Number",
				fieldtype="Data",
				insert_after="company_profile_details_section",
			),
			dict(
				fieldname="company_email",
				label="Company Email",
				fieldtype="Data",
				insert_after="company_mobile_number",
			),
			dict(
				fieldname="date_of_joining_onboarding",
				label="Date of Joining (DOJ)",
				fieldtype="Date",
				insert_after="company_email",
				reqd=1,
				# Will use existing date_of_joining field, but this is for HR to set
			),
			dict(
				fieldname="designation_company_profile",
				label="Designation",
				fieldtype="Data",
				insert_after="date_of_joining_onboarding",
				reqd=1,
				# Designation field in Company Profile Details section
			),
			# Note: department field (standard) is positioned after designation_company_profile via property setter
			dict(
				fieldname="location",
				label="Location",
				fieldtype="Select",
				insert_after="designation_company_profile",  # Will be after department via field_order
				reqd=1,
				read_only=0,  # Editable select field
				# Will be auto-populated from Job Applicant's job_requisition -> Job Opening -> Location
			),
			dict(
				fieldname="reporting_manager",
				label="Reporting Manager",
				fieldtype="Select",
				insert_after="location",
				reqd=1,
				read_only=0,  # Editable select field
				# Will be auto-populated from Department -> Reporting Manager
			),
			dict(
				fieldname="column_break_company_profile",
				fieldtype="Column Break",
				insert_after="reporting_manager",
			),
			dict(
				fieldname="hod",
				label="HOD",
				fieldtype="Select",
				insert_after="column_break_company_profile",
				reqd=1,
				read_only=0,  # Editable select field
				# Will be auto-populated from Department -> HOD
			),
			dict(
				fieldname="category",
				label="Category",
				fieldtype="Select",
				options="\nRegular\nContract\nIntern",
				insert_after="hod",
				reqd=1,
			),
			dict(
				fieldname="onboarding_designation",
				label="Designation",
				fieldtype="Data",
				insert_after="category",
				reqd=1,
				read_only=1,
				fetch_from="job_applicant.designation",
			),
			dict(
				fieldname="resign_date",
				label="Resign Date",
				fieldtype="Date",
				insert_after="onboarding_designation",
				reqd=1,
			),
			dict(
				fieldname="last_working_date",
				label="Last Working Date",
				fieldtype="Date",
				insert_after="resign_date",
				reqd=1,
			),
			dict(
				fieldname="employment_status",
				label="Employment Status",
				fieldtype="Select",
				options="\nActive\nInactive\nOn Leave\nTerminated",
				insert_after="last_working_date",
				reqd=1,
			),
			
			# ============================================
			# SECTION: Salary Details
			# ============================================
			dict(
				fieldname="salary_details_section",
				label="Salary Details",
				fieldtype="Section Break",
				insert_after="column_break_company_profile",
				collapsible=1,
			),
			dict(
				fieldname="ctc_monthly",
				label="CTC (Monthly)",
				fieldtype="Currency",
				insert_after="salary_details_section",
				reqd=1,
			),
			dict(
				fieldname="salary_template",
				label="Salary Template",
				fieldtype="Select",
				insert_after="ctc_monthly",
				reqd=1,
			),
			dict(
				fieldname="salary_start_date",
				label="Salary Start Date",
				fieldtype="Date",
				insert_after="salary_template",
				reqd=1,
			),
			dict(
				fieldname="salary_end_date",
				label="Salary End Date",
				fieldtype="Date",
				insert_after="salary_start_date",
				reqd=1,
			),
			dict(
				fieldname="period_in_months",
				label="Period (in months)",
				fieldtype="Int",
				insert_after="salary_end_date",
				reqd=1,
			),
			dict(
				fieldname="pay_frequency",
				label="Pay Frequency",
				fieldtype="Select",
				options="\nMonthly\nBi-weekly\nWeekly",
				insert_after="period_in_months",
				reqd=1,
			),
			dict(
				fieldname="column_break_salary",
				fieldtype="Column Break",
				insert_after="pay_frequency",
			),
			dict(
				fieldname="notice_period_salary",
				label="Notice Period",
				fieldtype="Data",
				insert_after="column_break_salary",
				reqd=1,
				# Mandatory Data field in Salary Details section
			),
			dict(
				fieldname="probation_period",
				label="Probation Period",
				fieldtype="Int",
				insert_after="notice_period_salary",
				reqd=1,
			),
			dict(
				fieldname="probation_end_date",
				label="Probation End Date",
				fieldtype="Date",
				insert_after="probation_period",
				reqd=1,
			),
			dict(
				fieldname="salary_mode",
				label="Salary Mode",
				fieldtype="Select",
				options="\nCash\nCheque\nBank Transfer",
				insert_after="probation_end_date",
				reqd=1,
			),
			dict(
				fieldname="increment_cycle",
				label="Increment Cycle",
				fieldtype="Data",
				insert_after="salary_mode",
				reqd=1,
			),
			dict(
				fieldname="tax_regime",
				label="Tax Regime",
				fieldtype="Select",
				options="\nOld Regime\nNew Regime",
				insert_after="increment_cycle",
				reqd=1,
			),
			
			# ============================================
			# SECTION: Policy
			# ============================================
			dict(
				fieldname="policy_section",
				label="Policy",
				fieldtype="Section Break",
				insert_after="column_break_salary",
				collapsible=1,
			),
			dict(
				fieldname="policy_assignment",
				label="Policy Assignment",
				fieldtype="Select",
				insert_after="policy_section",
				reqd=1,
			),
			dict(
				fieldname="leave_policy",
				label="Leave Policy",
				fieldtype="Select",
				insert_after="policy_assignment",
				reqd=1,
			),
			dict(
				fieldname="document_policy",
				label="Document Policy",
				fieldtype="Select",
				insert_after="leave_policy",
				reqd=1,
			),
			dict(
				fieldname="shift_policy",
				label="Shift Policy",
				fieldtype="Select",
				insert_after="document_policy",
				reqd=1,
			),
			dict(
				fieldname="overtime_policy",
				label="Overtime Policy",
				fieldtype="Select",
				insert_after="shift_policy",
				reqd=1,
			),
			dict(
				fieldname="holiday_policy",
				label="Holiday Policy",
				fieldtype="Select",
				insert_after="overtime_policy",
				reqd=1,
			),
			dict(
				fieldname="comp_off_policy",
				label="Comp Off Policy",
				fieldtype="Select",
				insert_after="holiday_policy",
				reqd=1,
			),
			dict(
				fieldname="column_break_policy",
				fieldtype="Column Break",
				insert_after="comp_off_policy",
			),
			dict(
				fieldname="attendance_policy",
				label="Attendance Policy",
				fieldtype="Select",
				insert_after="column_break_policy",
				reqd=1,
			),
			dict(
				fieldname="wfh_policy",
				label="Work From Home (WFH) Policy",
				fieldtype="Select",
				insert_after="attendance_policy",
				reqd=1,
			),
			dict(
				fieldname="grace_policy",
				label="Grace Policy",
				fieldtype="Select",
				insert_after="wfh_policy",
				reqd=1,
			),
			dict(
				fieldname="reimbursement_policy",
				label="Reimbursement Policy",
				fieldtype="Select",
				insert_after="grace_policy",
				reqd=1,
			),
			dict(
				fieldname="geofencing_policy",
				label="Geo-Fencing Policy",
				fieldtype="Select",
				insert_after="reimbursement_policy",
				reqd=1,
			),
			dict(
				fieldname="other_policy",
				label="Other Policy",
				fieldtype="Select",
				insert_after="geofencing_policy",
				reqd=1,
			),
			
			# ============================================
			# SECTION: Access Level
			# ============================================
			dict(
				fieldname="access_level_section",
				label="Access Level",
				fieldtype="Section Break",
				insert_after="column_break_policy",
				collapsible=1,
			),
			dict(
				fieldname="roles",
				label="Roles",
				fieldtype="Select",
				insert_after="access_level_section",
				reqd=1,
			),
			dict(
				fieldname="column_break_access",
				fieldtype="Column Break",
				insert_after="roles",
			),
			dict(
				fieldname="rights",
				label="Rights",
				fieldtype="Select",
				insert_after="column_break_access",
				reqd=1,
			),
			
			# ============================================
			# SECTION: Company Documents
			# ============================================
			dict(
				fieldname="company_documents_section",
				label="Company Documents",
				fieldtype="Section Break",
				insert_after="column_break_access",
				collapsible=1,
			),
			dict(
				fieldname="offer_letter",
				label="Offer Letter",
				fieldtype="Attach",
				insert_after="company_documents_section",
				reqd=1,
			),
			dict(
				fieldname="bond_letter",
				label="Bond Letter",
				fieldtype="Attach",
				insert_after="offer_letter",
				reqd=1,
			),
			dict(
				fieldname="exit_letter",
				label="Exit Letter",
				fieldtype="Attach",
				insert_after="bond_letter",
				reqd=1,
			),
		]
	}
	
	print("\n" + "="*50)
	print("🔍 setup_employee_onboarding_custom_fields() - START")
	print("="*50)
	print(f"Creating custom fields for Employee Onboarding...")
	print(f"Number of fields to create: {len(custom_fields.get('Employee Onboarding', []))}")
	
	create_custom_fields(custom_fields, update=True)
	print("✅ Custom fields created for Employee Onboarding")
	
	print("="*50)
	print("🔍 setup_employee_onboarding_custom_fields() - END")
	print("="*50 + "\n")

