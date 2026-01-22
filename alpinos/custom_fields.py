"""
Custom Fields for Job Requisition and Job Applicant DocTypes
Adds required fields as per SRS requirements
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def delete_qualification_field():
	"""Delete qualification table field if it exists (references non-existent Qualification DocType)"""
	try:
		qual_field = frappe.db.get_value(
			"Custom Field",
			{"dt": "Job Applicant", "fieldname": "qualification"},
			"name"
		)
		if qual_field:
			frappe.delete_doc("Custom Field", qual_field, force=1, ignore_permissions=True)
			frappe.db.commit()
			print("✅ Deleted qualification table field (references non-existent Qualification DocType)")
	except Exception as e:
		print(f"⚠️  Could not delete qualification field: {str(e)}")


def update_degree_field_position():
	"""Update degree field to be in qualification section"""
	try:
		# Update degree custom field's insert_after to qualification_section
		custom_field = frappe.db.get_value(
			"Custom Field",
			{"dt": "Job Applicant", "fieldname": "degree"},
			"name"
		)
		if custom_field:
			cf = frappe.get_doc("Custom Field", custom_field)
			cf.insert_after = "qualification_section"
			cf.save(ignore_permissions=True)
			frappe.db.commit()
			print("✅ Updated degree field position to qualification section")
	except Exception as e:
		print(f"⚠️  Could not update degree field position: {str(e)}")


def hide_status_field():
	"""Hide status field in Job Applicant"""
	try:
		update_property_setter("Job Applicant", "status", "hidden", "1", "Check")
		print("✅ Hidden status field in Job Applicant")
	except Exception as e:
		print(f"⚠️  Could not hide status field: {str(e)}")


def update_property_setter(doctype, fieldname, property_name, value, property_type="Data"):
	"""Create or update a property setter"""
	existing = frappe.db.exists(
		"Property Setter",
		{
			"doc_type": doctype,
			"field_name": fieldname,
			"property": property_name,
		}
	)
	
	if existing:
		ps = frappe.get_doc("Property Setter", existing)
		ps.value = value
		ps.save(ignore_permissions=True)
	else:
		ps = frappe.get_doc({
			"doctype": "Property Setter",
			"doctype_or_field": "DocField",
			"doc_type": doctype,
			"field_name": fieldname,
			"property": property_name,
			"value": value,
			"property_type": property_type,
		})
		ps.insert(ignore_permissions=True)
	
	frappe.db.commit()


def setup_custom_fields():
	"""Create custom fields for Job Requisition and Job Applicant"""
	
	custom_fields = {
		"Job Requisition": [
			# Section Break for Requisition Details (only shown in Edit view)
			dict(
				fieldname="requisition_details_section",
				label="Requisition Details",
				fieldtype="Section Break",
				insert_after="naming_series",
				collapsible=1,
				depends_on="eval:!doc.__islocal",  # Only show in Edit view (when saved)
			),
			
			# Column Break for Status and Approval
			dict(
				fieldname="column_break_requisition",
				fieldtype="Column Break",
				insert_after="requisition_details_section",
			),
			
			# Approved On - Datetime (Read-only, auto-set)
			dict(
				fieldname="approved_on",
				label="Approved On",
				fieldtype="Datetime",
				read_only=1,
				insert_after="column_break_requisition",
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
			
			# Profile Details Section
			dict(
				fieldname="profile_details_section",
				label="Profile Details",
				fieldtype="Section Break",
				insert_after="approved_by",
				collapsible=0,
			),
			
			
			# Location - Link to Branch (after additional_description)
			dict(
				fieldname="location",
				label="Location",
				fieldtype="Link",
				options="Branch",
				insert_after="no_of_positions",
				reqd=1,
			),
			
			# Hiring Deadline - Date
			dict(
				fieldname="hiring_deadline",
				label="Hiring Deadline",
				fieldtype="Date",
				insert_after="location",
				reqd=1,
			),
			
			# Min. Experience - Int (Years)
			dict(
				fieldname="min_experience",
				label="Min. Experience (Years)",
				fieldtype="Int",
				insert_after="hiring_deadline",
				reqd=1,
			),
			
			# Priority - Select
			dict(
				fieldname="priority",
				label="Priority",
				fieldtype="Select",
				options="\nUrgent\nHigh\nMedium\nLow",
				insert_after="min_experience",
				reqd=1,
			),
			
			# Vacancy Type - Select
			dict(
				fieldname="vacancy_type",
				label="Vacancy Type",
				fieldtype="Select",
				options="\nNew\nReplace",
				insert_after="priority",
				reqd=1,
			),
			
			# Employee Details Section (for replacement positions)
			dict(
				fieldname="employee_details_section",
				label="Employee Details",
				fieldtype="Section Break",
				insert_after="vacancy_type",
				collapsible=1,
				depends_on='eval:doc.vacancy_type=="Replace"',
			),
			
			# Linked Employee - Link to Employee (for replacement)
			dict(
				fieldname="linked_employee",
				label="Linked Employee",
				fieldtype="Link",
				options="Employee",
				insert_after="employee_details_section",
				description="Select the employee being replaced (for replacement positions)",
				ignore_user_permissions=1,
			),
			
			# Column Break
			dict(
				fieldname="column_break_employee",
				fieldtype="Column Break",
				insert_after="linked_employee",
			),
			
			# Reporting Manager - Link to Employee (fetched from linked employee)
			dict(
				fieldname="reporting_manager",
				label="Reporting Manager",
				fieldtype="Link",
				options="Employee",
				insert_after="column_break_employee",
				read_only=1,
				fetch_from="linked_employee.reports_to",
				description="Auto-fetched from linked employee's reporting structure",
				ignore_user_permissions=1,
			),
			
			# Reporting Manager User - Link to User (hidden, for workflow)
			dict(
				fieldname="reporting_manager_user",
				label="Reporting Manager User",
				fieldtype="Link",
				options="User",
				insert_after="reporting_manager",
				read_only=1,
				hidden=1,
				description="User ID of reporting manager (for workflow)",
			),
			
			# Company Details Section
			dict(
				fieldname="company_details_section",
				label="Company Details",
				fieldtype="Section Break",
				insert_after="reporting_manager",
				collapsible=0,
			),
			
			# Salary Details Section
			dict(
				fieldname="salary_details_section",
				label="Salary Details",
				fieldtype="Section Break",
				insert_after="company_details_section",
				collapsible=0,
			),
			
			# CTC Upper Range - Currency (after salary section)
			dict(
				fieldname="ctc_upper_range",
				label="CTC Upper Range / Monthly",
				fieldtype="Currency",
				options="Company:company:default_currency",
				insert_after="salary_details_section",
				reqd=1,
			),
			
			# Requested By (in Timelines, after posting_date/Requested On)
			dict(
				fieldname="custom_requested_by",
				label="Requested By",
				fieldtype="Link",
				options="User",
				insert_after="posting_date",
				read_only=1,
				reqd=1,
				default="user",
			),
			
			# Column Break for Employee Info
			dict(
				fieldname="column_break_requestor",
				fieldtype="Column Break",
				insert_after="custom_requested_by",
			),
			
			# Requested By Employee - Link to Employee (fetched from user)
			dict(
				fieldname="requested_by_employee",
				label="Requested By Employee",
				fieldtype="Link",
				options="Employee",
				insert_after="column_break_requestor",
				read_only=1,
				description="Employee record of the person requesting",
				ignore_user_permissions=1,
			),
			
			# Requestor's Reporting Manager - Link to Employee
			dict(
				fieldname="requestor_reporting_manager",
				label="Requestor's Manager",
				fieldtype="Link",
				options="Employee",
				insert_after="requested_by_employee",
				read_only=1,
				description="Reporting manager of the requesting employee",
				ignore_user_permissions=1,
			),
			
			# Requestor's Manager User - Link to User (hidden, for workflow)
			dict(
				fieldname="requestor_manager_user",
				label="Requestor Manager User",
				fieldtype="Link",
				options="User",
				insert_after="requestor_reporting_manager",
				read_only=1,
				hidden=1,
				description="User ID of requestor's manager (for workflow)",
			),
		],
	"Job Applicant": [
		# Qualification Section Break (after notice_period or last employment field)
		dict(
			fieldname="qualification_section",
			label="Qualification",
			fieldtype="Section Break",
			insert_after="notice_period",
			collapsible=1,
		),
		
		# Screening Section Break
		dict(
			fieldname="screening_section",
			label="Screening",
			fieldtype="Section Break",
			insert_after="applicant_rating",
			collapsible=1,
		),
		
		# Candidate Category - Select (White/Hold/Black)
		dict(
			fieldname="candidate_category",
			label="Candidate Category",
			fieldtype="Select",
			options="\nWhite\nHold\nBlack",
			insert_after="screening_section",
		),
		
		# Screening Status - Select (Read-only, auto-updated)
		dict(
			fieldname="screening_status",
			label="Screening Status",
			fieldtype="Select",
			options="\nPending Screening\nShortlisted\nScreening Call Scheduled\nOn Hold\nNot Eligible\nInterview Scheduled\nAccepted\nRejected\nHired",
			insert_after="candidate_category",
			read_only=1,
		),
	],
	
	# Delete qualification table field if it exists (references non-existent Qualification DocType)
	# This is handled separately to avoid validation errors
	}
	
	create_custom_fields(custom_fields, update=True)
	print("Custom fields created for Job Requisition and Job Applicant")
	
	# Delete qualification table field if it exists (it references non-existent Qualification DocType)
	delete_qualification_field()
	
	# Update degree field to be in qualification section
	update_degree_field_position()
	
	# Hide status field
	hide_status_field()
	
	print("✅ Job Requisition custom fields created (property setters loaded from fixtures/property_setter.json)")
