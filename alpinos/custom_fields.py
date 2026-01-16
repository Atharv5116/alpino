"""
Custom Fields for Job Requisition DocType
Adds required fields as per SRS requirements
"""

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def setup_custom_fields():
	"""Create custom fields for Job Requisition"""
	
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
	}
	
	create_custom_fields(custom_fields, update=True)
	print("Custom fields created for Job Requisition")
