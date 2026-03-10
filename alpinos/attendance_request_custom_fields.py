"""
Custom Fields for Attendance Request and Attendance DocTypes
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def setup_attendance_request_custom_fields():
	"""Update reason field options and add custom fields to Attendance and Attendance Request"""
	
	# Update reason field options in Attendance Request
	update_attendance_request_reason_options()
	
	# Add custom fields to Attendance doctype
	add_attendance_custom_fields()
	
	print("✅ Attendance Request and Attendance custom fields setup completed")


def update_attendance_request_reason_options():
	"""Update reason field options in Attendance Request"""
	try:
		# Update the reason field options using property setter
		make_property_setter(
			doctype="Attendance Request",
			fieldname="reason",
			property="options",
			value="Work From Home\nOffice\nOther",
			property_type="Text"
		)
		frappe.db.commit()
		print("✅ Updated reason field options in Attendance Request")
	except Exception as e:
		print(f"⚠️  Could not update reason field options: {str(e)}")
		frappe.log_error(f"Error updating reason options: {str(e)}\nTraceback: {frappe.get_traceback()}", "Update Reason Options")


def add_attendance_custom_fields():
	"""Add custom fields to Attendance doctype"""
	# Delete the checkbox field if it exists
	try:
		checkbox_field = frappe.db.get_value(
			"Custom Field",
			{"dt": "Attendance", "fieldname": "from_attendance_request"},
			"name"
		)
		if checkbox_field:
			frappe.delete_doc("Custom Field", checkbox_field, force=1, ignore_permissions=True)
			frappe.db.commit()
			print("✅ Deleted from_attendance_request checkbox field from Attendance")
	except Exception as e:
		print(f"⚠️  Could not delete checkbox field: {str(e)}")
	
	# Add only the text field
	custom_fields = {
		"Attendance": [
			dict(
				fieldname="attendance_request_reason",
				label="Attendance Request Reason",
				fieldtype="Small Text",
				insert_after="attendance_request",
				read_only=0,
				hidden=0,
				description=""
			),
		]
	}
	
	try:
		create_custom_fields(custom_fields, update=True)
		frappe.db.commit()
		print("✅ Added custom fields to Attendance doctype")
	except Exception as e:
		print(f"⚠️  Could not add custom fields to Attendance: {str(e)}")
		frappe.log_error(f"Error adding Attendance custom fields: {str(e)}\nTraceback: {frappe.get_traceback()}", "Add Attendance Custom Fields")

