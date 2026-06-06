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

	# Show From/To only for "On Duty"; single date is used otherwise
	set_attendance_request_date_visibility()

	# Add custom fields to Attendance Request doctype
	add_attendance_request_custom_fields()
	
	# Add custom fields to Attendance doctype
	add_attendance_custom_fields()
	
	# Add custom fields to Employee Checkin
	add_employee_checkin_custom_fields()
	
	# Add custom fields to Shift Type
	add_shift_type_custom_fields()
	
	print("✅ Attendance Request and Attendance custom fields setup completed")


def add_attendance_request_custom_fields():
	"""Add custom fields to Attendance Request doctype"""
	custom_fields = {
		"Attendance Request": [
			dict(
				fieldname="reporting_person",
				label="Reporting Person",
				fieldtype="Link",
				options="User",
				insert_after="company",
				read_only=1,
				allow_on_submit=1,
			),
			# Single date used for non "On Duty" requests (From/To are hidden then and
			# auto-set from this). For "On Duty" the standard From/To range is shown instead.
			dict(
				fieldname="custom_request_date",
				label="Date",
				fieldtype="Date",
				insert_after="reason",
				depends_on="eval:doc.reason!='On Duty'",
				mandatory_depends_on="eval:doc.reason!='On Duty'",
				description="Single day of the request. For 'On Duty' use the From/To range instead.",
			),
			# Per-day old vs new in/out times. Edited on the draft; applied to Employee
			# Checkin + Attendance only when the request is approved (submitted).
			dict(
				fieldname="custom_attendance_details",
				label="Attendance Details (Old vs New)",
				fieldtype="Table",
				options="Attendance Request Detail",
				insert_after="explanation",
				description="Old (existing) and New (requested) in/out per day. Applied on approval.",
			),
		]
	}

	try:
		create_custom_fields(custom_fields, update=True)
		frappe.db.commit()
		print("✅ Added custom fields to Attendance Request doctype")
	except Exception as e:
		print(f"⚠️  Could not add custom fields to Attendance Request: {str(e)}")
		frappe.log_error(
			f"Error adding Attendance Request custom fields: {str(e)}\nTraceback: {frappe.get_traceback()}",
			"Add Attendance Request Custom Fields",
		)


def update_attendance_request_reason_options():
	"""Update reason field options in Attendance Request"""
	try:
		# Update the reason field options using property setter
		# First option becomes the default
		make_property_setter(
			doctype="Attendance Request",
			fieldname="reason",
			property="options",
			value="On Duty\nWork From Home\nOffice\nOther",
			property_type="Text"
		)
		
		# Set default value to "Office"
		make_property_setter(
			doctype="Attendance Request",
			fieldname="reason",
			property="default",
			value="Office",
			property_type="Text"
		)

		frappe.db.commit()
		print("✅ Updated reason field options in Attendance Request (default: Office)")
	except Exception as e:
		print(f"⚠️  Could not update reason field options: {str(e)}")
		frappe.log_error(f"Error updating reason options: {str(e)}\nTraceback: {frappe.get_traceback()}", "Update Reason Options")


def set_attendance_request_date_visibility():
	"""From Date / To Date are shown only for the 'On Duty' reason (a range).
	For every other reason a single 'Date' field (custom_request_date) is used and
	From/To are auto-set from it on the server and client.
	"""
	try:
		on_duty = "eval:doc.reason=='On Duty'"
		for fieldname in ("from_date", "to_date"):
			# Show only for On Duty.
			make_property_setter(
				doctype="Attendance Request",
				fieldname=fieldname,
				property="depends_on",
				value=on_duty,
				property_type="Data",
			)
			# Make them conditionally mandatory (only when shown), so the hidden
			# single-day case never triggers a mandatory error. The single Date field
			# drives From/To then, server- and client-side.
			make_property_setter(
				doctype="Attendance Request",
				fieldname=fieldname,
				property="reqd",
				value="0",
				property_type="Check",
			)
			make_property_setter(
				doctype="Attendance Request",
				fieldname=fieldname,
				property="mandatory_depends_on",
				value=on_duty,
				property_type="Data",
			)
		frappe.db.commit()
		print("✅ Set From/To Date visibility on Attendance Request (On Duty only)")
	except Exception as e:
		print(f"⚠️  Could not set From/To Date visibility: {str(e)}")
		frappe.log_error(
			f"Error setting AR date visibility: {str(e)}\nTraceback: {frappe.get_traceback()}",
			"AR Date Visibility",
		)


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

def add_employee_checkin_custom_fields():
	"""Add custom fields to Employee Checkin doctype"""
	custom_fields = {
		"Employee Checkin": [
			dict(
				fieldname="from_attendance_request",
				label="From Attendance Request",
				fieldtype="Check",
				insert_after="time",
				read_only=1,
				hidden=1,
				default=0
			),
			dict(
				fieldname="is_manual",
				label="Is Manual",
				fieldtype="Check",
				insert_after="from_attendance_request",
				read_only=1,
				hidden=1,
				default=0
			),
		]
	}
	
	try:
		create_custom_fields(custom_fields, update=True)
		frappe.db.commit()
		print("✅ Added custom fields to Employee Checkin doctype")
	except Exception as e:
		print(f"⚠️  Could not add custom fields to Employee Checkin: {str(e)}")
		frappe.log_error(f"Error adding Employee Checkin custom fields: {str(e)}\nTraceback: {frappe.get_traceback()}", "Add Employee Checkin Custom Fields")

def add_shift_type_custom_fields():
	"""Add custom fields to Shift Type doctype"""
	custom_fields = {
		"Shift Type": [
			dict(
				fieldname="saturday_working_hours_threshold",
				label="Saturday Working Hours Threshold for Present",
				fieldtype="Float",
				insert_after="working_hours_threshold_for_half_day",
				description="Minimum working hours required on Saturday to be marked as Present. If hours are less, Employee will be marked Absent. (Used as the Half Day threshold when the Saturday Half Day threshold below is not set.)"
			),
			# Saturday-specific thresholds. When auto-marking attendance on a Saturday,
			# these replace the standard half-day / absent thresholds.
			dict(
				fieldname="saturday_working_hours_threshold_for_half_day",
				label="Saturday Working Hours Threshold for Half Day",
				fieldtype="Float",
				insert_after="saturday_working_hours_threshold",
				description="On Saturdays: if working hours are below this (but at/above the absent threshold), the day is marked Half Day. Falls back to the Present threshold above when left 0.",
			),
			dict(
				fieldname="saturday_working_hours_threshold_for_absent",
				label="Saturday Working Hours Threshold for Absent",
				fieldtype="Float",
				insert_after="saturday_working_hours_threshold_for_half_day",
				description="On Saturdays: if working hours are below this, the day is marked Absent. Leave 0 for the legacy two-way (Present/Absent) behaviour.",
			),
		]
	}
	
	try:
		create_custom_fields(custom_fields, update=True)
		frappe.db.commit()
		print("✅ Added custom fields to Shift Type doctype")
	except Exception as e:
		print(f"⚠️  Could not add custom fields to Shift Type: {str(e)}")
		frappe.log_error(f"Error adding Shift Type custom fields: {str(e)}\nTraceback: {frappe.get_traceback()}", "Add Shift Type Custom Fields")
