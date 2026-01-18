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
		update_property_setter("Job Applicant", "status", "hidden", 1, "Check")
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
		# Qualification Section Break (after notice_period or last employment field)
		dict(
			fieldname="qualification_section",
			label="Qualification",
			fieldtype="Section Break",
			insert_after="notice_period",
			collapsible=1,
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
