# Copyright (c) 2026, Alpinos and contributors
# License: MIT

import frappe
from frappe import _
from frappe.utils import getdate, date_diff, add_days, get_first_day, get_last_day, cint, flt, formatdate, format_time
from datetime import datetime, timedelta
import calendar


def execute(filters=None):
	filters = frappe._dict(filters or {})
	
	if not filters.get("month"):
		frappe.throw(_("Month is mandatory"))
	
	# Parse month (format: YYYY-MM)
	year, month = map(int, filters.month.split("-"))
	from_date = get_first_day(f"{year}-{month:02d}-01")
	to_date = get_last_day(f"{year}-{month:02d}-01")
	
	filters.from_date = from_date
	filters.to_date = to_date
	
	columns = get_columns(from_date, to_date)
	data = get_data(filters, from_date, to_date)
	
	return columns, data


def get_columns(from_date, to_date):
	"""Generate columns with employee info + dynamic date columns for the month"""
	columns = [
		{
			"label": _("Employee Name"),
			"fieldname": "employee_name",
			"fieldtype": "Data",
			"width": 200,
			"frozen": 1
		},
		{
			"label": _("Employee ID"),
			"fieldname": "employee",
			"fieldtype": "Link",
			"options": "Employee",
			"width": 120,
			"frozen": 1
		},
		{
			"label": _("Company"),
			"fieldname": "company",
			"fieldtype": "Link",
			"options": "Company",
			"width": 150
		}
	]
	
	# Add dynamic date columns
	current_date = getdate(from_date)
	end_date = getdate(to_date)
	
	while current_date <= end_date:
		day_num = current_date.day
		day_name = calendar.day_name[current_date.weekday()][:3]  # Mon, Tue, etc
		date_str = current_date.strftime("%Y-%m-%d")
		
		columns.append({
			"label": f"{day_num} {day_name}",
			"fieldname": f"day_{day_num}",
			"fieldtype": "Data",
			"width": 300
		})
		
		current_date = add_days(current_date, 1)
	
	return columns


def get_data(filters, from_date, to_date):
	"""Get employee attendance data with daily details"""
	from_date = getdate(from_date)
	to_date = getdate(to_date)
	
	employees = get_employees(filters)
	
	if not employees:
		return []
	
	data = []
	
	for emp in employees:
		row = get_employee_monthly_attendance(emp, from_date, to_date)
		if row:
			data.append(row)
	
	return data


def get_employees(filters):
	"""Get list of employees based on filters"""
	conditions = []
	
	if filters.get("employee"):
		conditions.append(f"name = '{filters.employee}'")
	
	if filters.get("company"):
		conditions.append(f"company = '{filters.company}'")
	
	where_clause = " AND ".join(conditions) if conditions else "1=1"
	
	query = f"""
		SELECT 
			name as employee,
			employee_name,
			company
		FROM `tabEmployee`
		WHERE {where_clause}
		ORDER BY employee_name
	"""
	
	return frappe.db.sql(query, as_dict=True)


def get_employee_monthly_attendance(emp, from_date, to_date):
	"""Get employee attendance data for each day of the month"""
	row = frappe._dict()
	
	# Employee basic details
	row.employee = emp.employee
	row.employee_name = emp.employee_name
	row.company = emp.company
	
	# Get all attendance records for the month
	attendance_map = get_attendance_map(emp.employee, from_date, to_date)
	
	# Get holidays for the employee
	holiday_map = get_holiday_map(emp.employee, from_date, to_date)
	
	# Get leave applications
	leave_map = get_leave_map(emp.employee, from_date, to_date)
	
	# Loop through each day of the month
	current_date = getdate(from_date)
	end_date = getdate(to_date)
	
	while current_date <= end_date:
		day_num = current_date.day
		date_str = current_date.strftime("%Y-%m-%d")
		field_name = f"day_{day_num}"
		
		# Check if it's a holiday
		if date_str in holiday_map:
			row[field_name] = f"HOLIDAY - {holiday_map[date_str]}"
		# Check if there's a leave application
		elif date_str in leave_map:
			leave_info = leave_map[date_str]
			row[field_name] = format_leave_info(leave_info)
		# Check if there's attendance
		elif date_str in attendance_map:
			att_info = attendance_map[date_str]
			row[field_name] = format_attendance_info(att_info)
		else:
			# No attendance marked
			row[field_name] = "-"
		
		current_date = add_days(current_date, 1)
	
	return row


def get_attendance_map(employee, from_date, to_date):
	"""Get all attendance records for the employee in the date range"""
	attendance_records = frappe.get_all(
		"Attendance",
		filters={
			"employee": employee,
			"attendance_date": ["between", [from_date, to_date]],
			"docstatus": ["!=", 2]
		},
		fields=[
			"attendance_date", "status", "in_time", "out_time", 
			"working_hours", "shift", "late_entry", "early_exit",
			"leave_type", "leave_application"
		]
	)
	
	attendance_map = {}
	for att in attendance_records:
		date_str = att.attendance_date.strftime("%Y-%m-%d")
		attendance_map[date_str] = att
	
	return attendance_map


def get_holiday_map(employee, from_date, to_date):
	"""Get all holidays for the employee in the date range"""
	try:
		holiday_list = frappe.db.get_value("Employee", employee, "holiday_list")
		
		if not holiday_list:
			return {}
		
		holidays = frappe.get_all(
			"Holiday",
			filters={
				"parent": holiday_list,
				"holiday_date": ["between", [from_date, to_date]]
			},
			fields=["holiday_date", "description"]
		)
		
		holiday_map = {}
		for holiday in holidays:
			date_str = holiday.holiday_date.strftime("%Y-%m-%d")
			holiday_map[date_str] = holiday.description or "Holiday"
		
		return holiday_map
	except:
		return {}


def get_leave_map(employee, from_date, to_date):
	"""Get all leave applications for the employee in the date range"""
	try:
		leave_applications = frappe.get_all(
			"Leave Application",
			filters={
				"employee": employee,
				"docstatus": 1,
				"status": "Approved"
			},
			fields=["from_date", "to_date", "leave_type", "half_day", "half_day_date"]
		)
		
		leave_map = {}
		for leave in leave_applications:
			current = getdate(leave.from_date)
			end = getdate(leave.to_date)
			
			while current <= end:
				if current >= getdate(from_date) and current <= getdate(to_date):
					date_str = current.strftime("%Y-%m-%d")
					leave_map[date_str] = {
						"leave_type": leave.leave_type,
						"half_day": leave.half_day and current == getdate(leave.half_day_date)
					}
				current = add_days(current, 1)
		
		return leave_map
	except:
		return {}


def format_leave_info(leave_info):
	"""Format leave information for display"""
	leave_type = leave_info.get("leave_type", "LEAVE")
	is_half_day = leave_info.get("half_day", False)
	
	if is_half_day:
		return f"HALF DAY - {leave_type}"
	else:
		return leave_type.upper()


def format_attendance_info(att_info):
	"""Format attendance information with all details"""
	status = att_info.get("status", "")
	in_time = att_info.get("in_time")
	out_time = att_info.get("out_time")
	working_hours = att_info.get("working_hours", 0)
	shift = att_info.get("shift", "")
	late_entry = att_info.get("late_entry", 0)
	early_exit = att_info.get("early_exit", 0)
	
	# Format times
	in_time_str = format_time(in_time) if in_time else "-"
	out_time_str = format_time(out_time) if out_time else "-"
	
	# Format working hours
	if working_hours:
		hours = int(working_hours)
		minutes = int((working_hours - hours) * 60)
		working_hours_str = f"{hours:02d} H : {minutes:02d} M"
	else:
		working_hours_str = "00 H : 00 M"
	
	# Get shift details
	shift_name = "-"
	shift_time = "-"
	if shift:
		try:
			shift_doc = frappe.get_cached_doc("Shift Type", shift)
			shift_name = shift_doc.name
			if shift_doc.start_time and shift_doc.end_time:
				shift_time = f"{format_time(shift_doc.start_time)} To {format_time(shift_doc.end_time)}"
		except:
			pass
	
	# Late/Early indicators
	late_time = "Yes" if late_entry else "-"
	early_out = "Yes" if early_exit else "-"
	
	# Get penalty if exists
	penalty = "-"  # You can query penalty doctype here if needed
	
	# Build the display string
	if status == "Half Day":
		display = f"HALF DAY | In: {in_time_str} | Out: {out_time_str}"
	else:
		display = f"{status.upper()} | In: {in_time_str} | Out: {out_time_str}"
	
	display += f" | T.W.HRs: {working_hours_str} | Shift Name: {shift_name} | Shift Time: {shift_time} | Early Out: {early_out} | Late Time: {late_time} | Penalty: {penalty}"
	
	return display
