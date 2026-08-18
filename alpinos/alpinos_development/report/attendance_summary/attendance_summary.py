# Copyright (c) 2026, Alpinos and contributors
# License: MIT

import frappe
from frappe import _
from frappe.utils import getdate, date_diff, add_days, get_first_day, get_last_day, cint, flt, formatdate, format_time, get_datetime
from datetime import datetime, timedelta
import calendar
from alpinos.alpinos_development.report.attendance_summary.attendance_summary_helpers import (
	calculate_attendance_stats
)


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
	"""Employee info + Final Format day-figures + per-day cells + Verify, in Excel order."""
	def col(label, fieldname, fieldtype="Float", width=110, **extra):
		c = {"label": _(label), "fieldname": fieldname, "fieldtype": fieldtype, "width": width}
		c.update(extra)
		return c

	columns = [
		col("Employee Name", "employee_name", "Data", 200, frozen=1),
		col("Employee ID", "employee", "Link", 120, options="Employee", frozen=1),
		col("Employee Status", "status", "Data", 110),
		col("Joining Date", "date_of_joining", "Date", 110),
		col("Aging", "aging", "Int", 70),
		col("Department", "department", "Link", 150, options="Department"),
		col("Company", "company", "Link", 150, options="Company"),
		# Days Calculation
		col("Month Working Days", "month_working_days", "Float", 130),
		col("Final Paid Days", "final_paid_days", "Float", 120),
		col("Final Payable Days", "final_payable_days", "Float", 130),
		col("Present Working Days", "present_working_days", "Float", 140),
		col("Clock-In Days", "clock_in_days", "Float", 110),
		# Deduction Section
		col("Absent Days", "absent_days", "Float", 100),
		col("Month Late Entries", "late_entries", "Data", 140),
		col("Half Days (Late 10:16)", "late_half_days", "Float", 140),
		col("Full Days (Late 10:31)", "late_full_days", "Float", 140),
		col("Working Hours Shortage", "working_hours_shortage", "Float", 150),
		# Leave Section
		col("Paid Leave", "paid_leave", "Float", 100),
		col("Unpaid Leave", "unpaid_leave", "Float", 110),
		col("WFH", "wfh", "Float", 80),
		col("OD", "od", "Float", 80),
		# Other
		col("Public Holiday", "public_holiday", "Int", 110),
		col("Weekend", "weekend", "Int", 90),
		col("Missing Attendance", "missing_attendance", "Int", 140),
		col("Average Working Hours", "avg_working_hours", "Float", 150),
	]

	current_date = getdate(from_date)
	end_date = getdate(to_date)
	while current_date <= end_date:
		day_num = current_date.day
		day_name = calendar.day_name[current_date.weekday()][:3]
		columns.append({
			"label": f"{day_num} {day_name}",
			"fieldname": f"day_{day_num}",
			"fieldtype": "Data",
			"width": 300,
		})
		current_date = add_days(current_date, 1)

	columns.append(col("Verify", "verify", "Data", 100))
	return columns


def get_data(filters, from_date, to_date):
	"""Get employee attendance data with daily details"""
	from_date = getdate(from_date)
	to_date = getdate(to_date)
	
	employees = get_employees(filters, from_date, to_date)

	if not employees:
		return []
	
	data = []
	
	for emp in employees:
		row = get_employee_monthly_attendance(emp, from_date, to_date)
		if row:
			data.append(row)
	
	return data


def get_employees(filters, from_date, to_date):
	"""Get employees who were active within the report date range.

	An employee is considered active for the period if they had joined on or before the
	period end and were not relieved before the period start. This excludes employees who
	joined after the month or who left before it.
	"""
	conditions = []

	if filters.get("employee"):
		conditions.append(f"name = '{filters.employee}'")

	if filters.get("company"):
		conditions.append(f"company = '{filters.company}'")

	# Active within the date range: joined on/before period end, not relieved before its start.
	conditions.append(f"date_of_joining IS NOT NULL AND date_of_joining <= '{getdate(to_date)}'")
	conditions.append(f"(relieving_date IS NULL OR relieving_date >= '{getdate(from_date)}')")

	where_clause = " AND ".join(conditions) if conditions else "1=1"
	
	query = f"""
		SELECT 
			name as employee,
			employee_name,
			status,
			date_of_joining,
			department,
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
	row.status = emp.status
	row.date_of_joining = emp.date_of_joining
	row.department = emp.department
	row.company = emp.company
	
	# Calculate aging
	if emp.date_of_joining:
		row.aging = date_diff(to_date, emp.date_of_joining)
	else:
		row.aging = 0
	
	# Get all attendance records for the month
	attendance_map = get_attendance_map(emp.employee, from_date, to_date)
	
	# Get holidays for the employee
	holiday_map = get_holiday_map(emp.employee, from_date, to_date)
	
	# Get leave applications
	leave_map = get_leave_map(emp.employee, from_date, to_date)
	
	# Get Work From Home Requests
	wfh_map = get_wfh_map(emp.employee, from_date, to_date)
	
	# Initialize statistics
	stats = calculate_attendance_stats(attendance_map, holiday_map, leave_map, wfh_map, from_date, to_date, emp.employee)
	
	# Summary fields (Final Format layout).
	row.clock_in_days = stats["clock_in_days"]
	row.absent_days = stats["absent_days"]
	row.public_holiday = stats["public_holiday"]
	row.weekend = stats["weekend"]
	row.paid_leave = stats["paid_leave"]
	row.unpaid_leave = stats["unpaid_leave"]
	row.wfh = stats["wfh"]
	row.od = stats["od"]
	row.working_hours_shortage = stats["working_hours_shortage"]
	row.missing_attendance = stats["missing_attendance"]
	row.avg_working_hours = stats["avg_working_hours"]

	# Late-entry summary + per-tier penalty (half-day vs full-day).
	late_info = compute_late_deduction(attendance_map)
	row.late_entries = late_info["summary"]
	row.late_half_days = late_info["half_deduction"]
	row.late_full_days = late_info["full_deduction"]

	# Days Calculation:
	#   Month Working Days   = calendar days - Public Holidays - Weekends
	#   Present Working Days = Month - Paid Leave - Unpaid Leave - Absent - Working-Hours-Shortage
	#   Final Payable Days   = Present + Paid Leave            (no penalty)
	#   Final Paid Days      = Payable - late penalty          (shortage already in Present)
	total_days = date_diff(to_date, from_date) + 1
	row.month_working_days = flt(total_days - flt(stats["public_holiday"]) - flt(stats["weekend"]), 2)
	row.present_working_days = flt(
		flt(row.month_working_days)
		- flt(stats["paid_leave"]) - flt(stats["unpaid_leave"])
		- flt(stats["absent_days"]) - flt(stats["working_hours_shortage"]),
		2,
	)
	row.final_payable_days = flt(flt(row.present_working_days) + flt(stats["paid_leave"]), 2)
	row.final_paid_days = flt(flt(row.final_payable_days) - flt(late_info["deduction"]), 2)
	row.verify = ""

	# Loop through each day of the month
	current_date = getdate(from_date)
	end_date = getdate(to_date)
	
	while current_date <= end_date:
		day_num = current_date.day
		date_str = current_date.strftime("%Y-%m-%d")
		field_name = f"day_{day_num}"
		
		# Holiday List entry: weekly-off days show as WEEKEND, the rest as the holiday name.
		if date_str in holiday_map:
			hinfo = holiday_map[date_str]
			row[field_name] = "WEEKEND" if hinfo.get("weekly_off") else f"HOLIDAY - {hinfo.get('description')}"
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


def _get_shift_late_config(shift_name, cache):
	"""Return {start_time, tiers:[(late_by, deduction), ...] sorted desc} for a Shift Type,
	or None when there is no shift / no configured Late Entry Thresholds."""
	if shift_name in cache:
		return cache[shift_name]
	cfg = None
	if shift_name:
		start_time = frappe.db.get_value("Shift Type", shift_name, "start_time")
		rows = frappe.get_all(
			"Late Entry Threshold",
			filters={
				"parent": shift_name,
				"parenttype": "Shift Type",
				"parentfield": "custom_late_entry_thresholds",
			},
			fields=["late_by", "deduction"],
			order_by="late_by desc",
		)
		tiers = [
			(cint(r.late_by), flt(r.deduction))
			for r in rows
			if cint(r.late_by) > 0 and flt(r.deduction) > 0
		]
		if start_time is not None and tiers:
			cfg = {"start_time": start_time, "tiers": tiers}
	cache[shift_name] = cfg
	return cfg


def compute_late_deduction(attendance_map):
	"""Late-entry flag counts and the days to deduct, per the Shift Type late-entry tiers.

	Each late check-in is classified into the highest tier whose 'Late By' minutes it meets
	(minutes late from the shift's start_time). Then, per tier, every full group of 4 lates
	deducts that tier's days; any leftover lates across tiers that combine to 4 deduct the
	smallest tier's days (0.5). Nothing deducts below a group of 4. Computed for the report's
	period (month), so it resets each period.

	Returns {"counts": {late_by: n}, "summary": "15m × 4, 30m × 2", "deduction": days}.
	"""
	cache = {}
	counts = {}        # late_by -> number of late entries
	ded_by_tier = {}   # late_by -> deduction days for that tier

	for att in attendance_map.values():
		in_time = att.get("in_time")
		shift = att.get("shift")
		att_date = att.get("attendance_date")
		if not in_time or not shift or not att_date:
			continue
		cfg = _get_shift_late_config(shift, cache)
		if not cfg:
			continue
		try:
			shift_start = get_datetime(f"{getdate(att_date)} {cfg['start_time']}")
			minutes_late = (get_datetime(in_time) - shift_start).total_seconds() / 60.0
		except Exception:
			continue
		if minutes_late <= 0:
			continue
		# Highest tier whose threshold the lateness meets (tiers are sorted desc by late_by).
		tier = next(((lb, dd) for lb, dd in cfg["tiers"] if minutes_late >= lb), None)
		if not tier:
			continue
		counts[tier[0]] = counts.get(tier[0], 0) + 1
		ded_by_tier[tier[0]] = tier[1]

	# Flag-count summary, e.g. "15m × 4, 30m × 2" (sorted by late_by ascending).
	summary = ", ".join(
		f"{lb}m × {counts[lb]}" for lb in sorted(counts)
	)

	if not counts:
		return {"counts": {}, "summary": "", "deduction": 0.0, "half_deduction": 0.0, "full_deduction": 0.0}

	min_ded = min(ded_by_tier.values())
	min_tier = min(ded_by_tier, key=lambda k: ded_by_tier[k])
	per_tier = {}
	leftover = 0
	for late_by, cnt in counts.items():
		per_tier[late_by] = (cnt // 4) * ded_by_tier[late_by]   # full groups of 4 in this tier
		leftover += cnt % 4                                     # remainder carried to the combo
	per_tier[min_tier] = per_tier.get(min_tier, 0.0) + (leftover // 4) * min_ded

	total = sum(per_tier.values())
	# Split by tier for the two columns: a half-day tier (deduction < 1) feeds "Half Days
	# (Late 10:16)", a full-day tier (>= 1) feeds "Full Days (Late 10:31)".
	half_ded = sum(d for lb, d in per_tier.items() if ded_by_tier[lb] < 1.0)
	full_ded = sum(d for lb, d in per_tier.items() if ded_by_tier[lb] >= 1.0)

	return {"counts": counts, "summary": summary, "deduction": flt(total, 2),
		"half_deduction": flt(half_ded, 2), "full_deduction": flt(full_ded, 2)}


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
			fields=["holiday_date", "description", "weekly_off"]
		)
		
		holiday_map = {}
		for holiday in holidays:
			date_str = holiday.holiday_date.strftime("%Y-%m-%d")
			holiday_map[date_str] = {
				"description": holiday.description or "Holiday",
				"weekly_off": cint(holiday.weekly_off),
			}
		
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


def get_wfh_map(employee, from_date, to_date):
	"""Get all Work From Home Requests for the employee in the date range"""
	try:
		# Query WFH requests that overlap with the report date range
		# Field names: date (from_date), to_date, half_day
		wfh_requests = frappe.db.sql("""
			SELECT date as from_date, to_date, half_day
			FROM `tabWork From Home Request`
			WHERE employee = %s
				AND status = 'Approved'
				AND date <= %s
				AND to_date >= %s
			ORDER BY date
		""", (employee, to_date, from_date), as_dict=True)
		
		wfh_map = {}
		for wfh in wfh_requests:
			# Expand the date range into individual dates
			current = getdate(wfh.from_date)
			end = getdate(wfh.to_date)
			is_half_day = wfh.get('half_day', 0)
			first_day = True
			
			while current <= end:
				# Only include dates within the report's date range
				if current >= getdate(from_date) and current <= getdate(to_date):
					date_str = current.strftime("%Y-%m-%d")
					# Half day only applies to the first day of the WFH request
					wfh_map[date_str] = {
						"type": "Work From Home",
						"half_day": is_half_day if first_day else 0
					}
					first_day = False
				current = add_days(current, 1)
		
		return wfh_map
	except Exception as e:
		frappe.log_error(f"Error getting WFH map: {str(e)}", "WFH Map Error")
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
	
	# For absent status, clear in_time, out_time, and working_hours
	if status == "Absent":
		in_time = None
		out_time = None
		working_hours = 0
	
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
