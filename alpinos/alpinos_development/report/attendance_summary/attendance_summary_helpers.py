# Copyright (c) 2026, Alpinos and contributors
# License: MIT

import frappe
from frappe.utils import getdate, date_diff, add_days, flt


def get_location_details(location):
	"""Get location details from Location doctype"""
	if not location:
		return {}
	
	try:
		# Adjust field names based on your Location doctype structure
		location_doc = frappe.db.get_value(
			"Location",
			location,
			["state", "country", "custom_billing_type", "custom_start_date", "custom_closing_date"],
			as_dict=True
		)
		
		if location_doc:
			return {
				"state": location_doc.get("state"),
				"country": location_doc.get("country"),
				"billing_type": location_doc.get("custom_billing_type"),
				"start_date": location_doc.get("custom_start_date"),
				"closing_date": location_doc.get("custom_closing_date")
			}
	except:
		pass
	
	return {}


def calculate_attendance_stats(attendance_map, holiday_map, leave_map, from_date, to_date, employee):
	"""Calculate attendance statistics for the month"""
	stats = frappe._dict({
		"paid_days": 0,
		"working_days": 0,
		"clock_in_days": 0,
		"absent_days": 0,
		"shift_not_started": 0,
		"holiday": len(holiday_map),
		"weekend": 0,
		"paid_leave": 0,
		"unpaid_leave": 0,
		"paid_hourly_leave": 0,
		"unpaid_hourly_leave": 0,
		"od_wfh_count": 0,
		"missing_attendance": 0,
		"penalty_count": 0,
		"avg_working_hours": 0
	})
	
	total_working_hours = 0
	working_days_count = 0
	
	# Count attendance by status
	for date_str, att in attendance_map.items():
		status = att.get("status")
		
		if status == "Present":
			stats.paid_days += 1
			stats.working_days += 1
			stats.clock_in_days += 1
			if att.get("working_hours"):
				total_working_hours += flt(att.get("working_hours"))
				working_days_count += 1
		elif status == "Absent":
			stats.absent_days += 1
		elif status == "Half Day":
			stats.paid_days += 0.5
			stats.working_days += 0.5
			stats.clock_in_days += 1
			if att.get("working_hours"):
				total_working_hours += flt(att.get("working_hours"))
				working_days_count += 1
		elif status == "On Leave":
			# Check if paid or unpaid leave
			if att.get("leave_type"):
				try:
					is_lwp = frappe.get_cached_value("Leave Type", att.get("leave_type"), "is_lwp")
					if is_lwp:
						stats.unpaid_leave += 1
					else:
						stats.paid_leave += 1
						stats.paid_days += 1
				except:
					stats.paid_leave += 1
					stats.paid_days += 1
		elif status == "Work From Home":
			stats.od_wfh_count += 1
			stats.paid_days += 1
			stats.working_days += 1
			if att.get("working_hours"):
				total_working_hours += flt(att.get("working_hours"))
				working_days_count += 1
		elif status == "On Duty":
			stats.od_wfh_count += 1
			stats.paid_days += 1
			stats.working_days += 1
			if att.get("working_hours"):
				total_working_hours += flt(att.get("working_hours"))
				working_days_count += 1
	
	# Count leaves from leave_map
	for date_str, leave_info in leave_map.items():
		if date_str not in attendance_map:  # Only count if not already in attendance
			leave_type = leave_info.get("leave_type")
			is_half_day = leave_info.get("half_day", False)
			
			try:
				is_lwp = frappe.get_cached_value("Leave Type", leave_type, "is_lwp")
				if is_lwp:
					if is_half_day:
						stats.unpaid_leave += 0.5
					else:
						stats.unpaid_leave += 1
				else:
					if is_half_day:
						stats.paid_leave += 0.5
						stats.paid_days += 0.5
					else:
						stats.paid_leave += 1
						stats.paid_days += 1
			except:
				if is_half_day:
					stats.paid_leave += 0.5
					stats.paid_days += 0.5
				else:
					stats.paid_leave += 1
					stats.paid_days += 1
	
	# Calculate weekend count
	current_date = getdate(from_date)
	end_date = getdate(to_date)
	
	while current_date <= end_date:
		weekday = current_date.weekday()
		# 5 = Saturday, 6 = Sunday
		if weekday in [5, 6]:
			stats.weekend += 1
		current_date = add_days(current_date, 1)
	
	# Calculate missing attendance
	total_days = date_diff(to_date, from_date) + 1
	marked_days = len(attendance_map) + len([d for d in leave_map if d not in attendance_map])
	stats.missing_attendance = total_days - marked_days - stats.holiday - stats.weekend
	
	# Get penalty count
	try:
		penalty_count = frappe.db.count(
			"Employee Penalty",
			filters={
				"employee": employee,
				"penalty_date": ["between", [from_date, to_date]],
				"docstatus": 1
			}
		)
		stats.penalty_count = penalty_count
	except:
		stats.penalty_count = 0
	
	# Calculate average working hours
	if working_days_count > 0:
		stats.avg_working_hours = round(total_working_hours / working_days_count, 2)
	
	return stats
