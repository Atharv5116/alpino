"""
Custom Fields for Job Requisition and Job Applicant DocTypes
Adds required fields as per SRS requirements
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def fix_qualification_degree_field():
	"""Delete qualification_degree field if it exists"""
	try:
		custom_field = frappe.db.exists(
			"Custom Field",
			{"dt": "Job Applicant", "fieldname": "qualification_degree"}
		)
		
		if custom_field:
			print(f"⚠️  Deleting qualification_degree field")
			frappe.delete_doc("Custom Field", custom_field, force=1)
			frappe.db.commit()
			print("✅ qualification_degree field deleted")
	except Exception as e:
		print(f"⚠️  Could not delete qualification_degree field: {str(e)}")


def setup_custom_fields():
	"""Create custom fields for Job Requisition and Job Applicant"""
	
	# Fix qualification_degree field if it exists with wrong fieldtype
	fix_qualification_degree_field()
	
	custom_fields = {
		"Job Requisition": [
			# Location - Link to Branch (after department)
			dict(
				fieldname="location",
				label="Location",
				fieldtype="Link",
				options="Branch",
				insert_after="department",
				reqd=1,
			),
			
			# Min. Experience - Int (Years) (after no_of_positions)
			dict(
				fieldname="min_experience",
				label="Min. Experience (Years)",
				fieldtype="Int",
				insert_after="no_of_positions",
				reqd=1,
			),
			
			# Vacancy Type - Select (after min_experience)
			dict(
				fieldname="vacancy_type",
				label="Vacancy Type",
				fieldtype="Select",
				options="\nNew\nReplace",
				insert_after="min_experience",
				reqd=1,
			),
			
			# Priority - Select (after vacancy_type)
			dict(
				fieldname="priority",
				label="Priority",
				fieldtype="Select",
				options="\nUrgent\nHigh\nMedium\nLow",
				insert_after="vacancy_type",
				reqd=1,
			),
			
			# CTC Upper Range - Currency (after expected_compensation)
			dict(
				fieldname="ctc_upper_range",
				label="CTC Upper Range",
				fieldtype="Currency",
				options="Company:company:default_currency",
				insert_after="expected_compensation",
				reqd=1,
			),
			
			# Section Break for Requisition Details
			dict(
				fieldname="requisition_details_section",
				label="Requisition Details",
				fieldtype="Section Break",
				insert_after="status",
				collapsible=1,
			),
			
			# Approved On - Datetime (Read-only, auto-set)
			dict(
				fieldname="approved_on",
				label="Approved On",
				fieldtype="Datetime",
				read_only=1,
				insert_after="requisition_details_section",
			),
			
			# Approved By - Link to User (Read-only, auto-set)
			dict(
				fieldname="approved_by",
				label="Approved By",
				fieldtype="Link",
				options="User",
				read_only=1,
				insert_after="approved_on",
			),
			
			# Column Break
			dict(
				fieldname="column_break_approval",
				fieldtype="Column Break",
				insert_after="approved_by",
			),
			
			# Hiring Deadline - Date (in timelines section)
			dict(
				fieldname="hiring_deadline",
				label="Hiring Deadline",
				fieldtype="Date",
				insert_after="expected_by",
				reqd=1,
			),
			
			# Additional Description - Text Area (after description)
			dict(
				fieldname="additional_description",
				label="Additional Description",
				fieldtype="Text Editor",
				insert_after="description",
				reqd=1,
			),
		],
		"Job Applicant": [
			# ============================================
			# CANDIDATE DETAILS SECTION
			# ============================================
			# Note: Standard fields (applicant_name, email_id, phone_number, resume_attachment) 
			# are already in the form. We'll add our custom fields after resume_attachment.
			
			# Marital Status - Select (after phone_number)
			dict(
				fieldname="marital_status",
				label="Marital Status",
				fieldtype="Select",
				options="\nSingle\nMarried\nDivorced\nWidowed",
				insert_after="phone_number",
				reqd=1,
			),
			
			# City / State - Data (after marital_status)
			dict(
				fieldname="city_state",
				label="City / State",
				fieldtype="Data",
				insert_after="marital_status",
				reqd=1,
			),
			
			# Candidate ID - Auto Number (read-only, HR-only, visible in list view)
			# Placed after city_state in Candidate Details section
			dict(
				fieldname="candidate_id",
				label="Candidate ID",
				fieldtype="Data",
				read_only=1,
				insert_after="city_state",
				no_copy=1,
			),
			
			# Column Break after Candidate Details
			dict(
				fieldname="column_break_candidate_details",
				fieldtype="Column Break",
				insert_after="candidate_id",
			),
			
			# ============================================
			# WORK DETAILS SECTION
			# ============================================
			
			# Section Break for Work Details
			dict(
				fieldname="work_details_section",
				label="Work Details",
				fieldtype="Section Break",
				insert_after="column_break_candidate_details",
				collapsible=1,
			),
			
			# Applied Position - Data (Alphabets only)
			dict(
				fieldname="applied_position",
				label="Applied Position",
				fieldtype="Data",
				insert_after="work_details_section",
				reqd=1,
			),
			
			# Job Requisition - Link (after applied_position)
			dict(
				fieldname="job_requisition",
				label="Job Requisition",
				fieldtype="Link",
				options="Job Requisition",
				insert_after="applied_position",
				reqd=1,
			),
			
			# Application Date - Date (after job_requisition)
			dict(
				fieldname="application_date",
				label="Application Date",
				fieldtype="Date",
				insert_after="job_requisition",
				reqd=1,
				default="Today",
			),
			
			# Total Experience - Data (after application_date, Alphanumeric)
			dict(
				fieldname="total_experience",
				label="Total Experience",
				fieldtype="Data",
				insert_after="application_date",
				reqd=1,
			),
			
			# Source - Link/Select (after total_experience, move to Work Details)
			# Note: Source is a standard field, we'll position it here via property setter
			
			# Portfolio - Data (after total_experience, non-mandatory, URL)
			dict(
				fieldname="portfolio",
				label="Portfolio",
				fieldtype="Data",
				insert_after="total_experience",
			),
			
			# Expected Date of Joining - Date (after portfolio, non-mandatory)
			dict(
				fieldname="expected_date_of_joining",
				label="Expected Date of Joining",
				fieldtype="Date",
				insert_after="portfolio",
			),
			
			# Reference - Table (non-mandatory, in Work Details section)
			dict(
				fieldname="reference",
				label="Reference (If Any)",
				fieldtype="Table",
				options="Job Application Reference",
				insert_after="expected_date_of_joining",
			),
			
			# Column Break after Work Details
			dict(
				fieldname="column_break_work_details",
				fieldtype="Column Break",
				insert_after="reference",
			),
			
			# ============================================
			# EMPLOYMENT HISTORY SECTION
			# ============================================
			
			# Section Break for Employment History
			dict(
				fieldname="employment_history_section",
				label="Employment History",
				fieldtype="Section Break",
				insert_after="column_break_work_details",
				collapsible=1,
			),
			
			# Employment History - Flat Fields (Single Entry)
			dict(
				fieldname="employment_company_name",
				label="Company Name",
				fieldtype="Data",
				insert_after="employment_history_section",
				reqd=1,
			),
			dict(
				fieldname="employment_designation",
				label="Designation",
				fieldtype="Data",
				insert_after="employment_company_name",
				reqd=1,
			),
			dict(
				fieldname="employment_current_ctc",
				label="Current CTC / Annum",
				fieldtype="Data",
				insert_after="employment_designation",
				reqd=1,
			),
			dict(
				fieldname="employment_expected_ctc",
				label="Expected CTC / Annum",
				fieldtype="Data",
				insert_after="employment_current_ctc",
				reqd=1,
			),
			dict(
				fieldname="employment_reason_for_leaving",
				label="Reason for Leaving",
				fieldtype="Small Text",
				insert_after="employment_expected_ctc",
				reqd=1,
			),
			dict(
				fieldname="employment_start_date",
				label="Start Date",
				fieldtype="Date",
				insert_after="employment_reason_for_leaving",
				reqd=1,
			),
			dict(
				fieldname="employment_end_date",
				label="End Date",
				fieldtype="Date",
				insert_after="employment_start_date",
				reqd=1,
			),
			dict(
				fieldname="employment_notice_period",
				label="Notice Period",
				fieldtype="Data",
				insert_after="employment_end_date",
				reqd=1,
				description="Notice period in days",
			),
			
			# Column Break after Employment History
			dict(
				fieldname="column_break_employment_history",
				fieldtype="Column Break",
				insert_after="employment_notice_period",
			),
			
			# ============================================
			# QUALIFICATION (Simple Text Field - No Section)
			# ============================================
			
			# Degree - Simple text field (no section break, non-mandatory, hidden)
			dict(
				fieldname="degree",
				label="Degree",
				fieldtype="Data",
				insert_after="column_break_employment_history",
			),
		],
	}
	
	create_custom_fields(custom_fields, update=True)
	print("Custom fields created for Job Requisition and Job Applicant")
