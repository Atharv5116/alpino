# Copyright (c) 2026, Alpinos and contributors
# License: MIT

import frappe
from frappe import _
from frappe.utils import getdate, date_diff, add_days, get_first_day, get_last_day, cint, flt, formatdate, format_time, get_datetime, nowdate
from datetime import datetime, timedelta
import calendar
from alpinos.alpinos_development.report.attendance_summary.attendance_summary_helpers import (
	SUNDAY,
	calculate_attendance_stats,
)


def _display_end_date(from_date, to_date):
	"""Last day to show as a day column; an in-progress month stops at today."""
	today = getdate(nowdate())
	if today >= getdate(to_date) or today < getdate(from_date):
		return getdate(to_date)
	return today


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
	"""Report columns in Excel order."""
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
		col("Final Paids days(With Late Penalty deduction days )", "final_paid_days", "Float", 240),
		col("Final Payable days(With out Penalty deduction days)", "final_payable_days", "Float", 240),
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
	end_date = _display_end_date(from_date, to_date)
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
	"""Employees active within the report date range.

	Someone who left or was suspended during the month still appears for that month; they
	drop off from the next month onward.
	"""
	conditions = []

	if filters.get("employee"):
		conditions.append(f"name = '{filters.employee}'")

	if filters.get("company"):
		conditions.append(f"company = '{filters.company}'")

	conditions.append(f"date_of_joining IS NOT NULL AND date_of_joining <= '{getdate(to_date)}'")
	conditions.append(f"(relieving_date IS NULL OR relieving_date >= '{getdate(from_date)}')")
	conditions.append(
		f"(custom_suspension_date IS NULL OR custom_suspension_date >= '{getdate(from_date)}')"
	)

	where_clause = " AND ".join(conditions) if conditions else "1=1"

	query = f"""
		SELECT
			name as employee,
			employee_name,
			status,
			date_of_joining,
			relieving_date,
			custom_suspension_date,
			department,
			company
		FROM `tabEmployee`
		WHERE {where_clause}
		ORDER BY employee_name
	"""
	
	return frappe.db.sql(query, as_dict=True)


def get_employee_monthly_attendance(emp, from_date, to_date):
	row = frappe._dict()

	row.employee = emp.employee
	row.employee_name = emp.employee_name
	row.status = emp.status
	row.date_of_joining = emp.date_of_joining
	row.department = emp.department
	row.company = emp.company

	# Cap the calculation at the exit date for anyone relieved or suspended mid-month.
	period_end = getdate(to_date)
	for exit_date in (emp.get("relieving_date"), emp.get("custom_suspension_date")):
		if not exit_date:
			continue
		exit_date = getdate(exit_date)
		if getdate(from_date) <= exit_date < period_end:
			period_end = exit_date
	
	if emp.date_of_joining:
		row.aging = date_diff(period_end, emp.date_of_joining)
	else:
		row.aging = 0

	attendance_map = get_attendance_map(emp.employee, from_date, period_end)
	holiday_map = get_holiday_map(emp.employee, from_date, period_end)
	leave_map = get_leave_map(emp.employee, from_date, period_end)
	wfh_map = get_wfh_map(emp.employee, from_date, period_end)

	stats = calculate_attendance_stats(attendance_map, holiday_map, leave_map, wfh_map, from_date, period_end, emp.employee)
	
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

	# Days calculation:
	#   Month Working Days   = calendar days - Public Holidays - Weekends
	#   Present Working Days = Month - Paid Leave - Unpaid Leave - Absent - Working Hours Shortage
	#   Final Payable Days   = Present + Paid Leave
	#   Final Paid Days      = Payable - late penalty
	total_days = date_diff(period_end, from_date) + 1
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

	current_date = getdate(from_date)
	end_date = _display_end_date(from_date, to_date)

	while current_date <= end_date:
		day_num = current_date.day
		date_str = current_date.strftime("%Y-%m-%d")
		field_name = f"day_{day_num}"
		
		# Sundays show as WEEKEND, other Holiday List entries as the holiday name.
		if date_str in holiday_map:
			hinfo = holiday_map[date_str]
			is_sunday = current_date.weekday() == SUNDAY
			row[field_name] = "WEEKEND" if is_sunday else f"HOLIDAY - {hinfo.get('description')}"
		elif date_str in leave_map:
			leave_info = leave_map[date_str]
			row[field_name] = format_leave_info(leave_info)
		elif date_str in attendance_map:
			att_info = attendance_map[date_str]
			row[field_name] = format_attendance_info(att_info)
		else:
			row[field_name] = "-"
		
		current_date = add_days(current_date, 1)
	
	return row


def get_attendance_map(employee, from_date, to_date):
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
	"""Shift Type late-entry config, or None when there is no shift / no thresholds."""
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


def _is_first_half_leave(att, cache):
	"""True when the day's half-day leave covers the FIRST half.

	The employee is on leave until midday, so checking in for the second half is expected
	and must not be measured against the shift start.
	"""
	if att.get("status") != "Half Day":
		return False

	leave = att.get("leave_application")
	if not leave:
		return False

	if not frappe.get_meta("Leave Application").has_field("custom_half_day_period"):
		return False

	if leave not in cache:
		cache[leave] = (
			frappe.db.get_value(
				"Leave Application", leave, ["half_day", "custom_half_day_period"], as_dict=True
			)
			or {}
		)
	info = cache[leave]
	return bool(cint(info.get("half_day"))) and (
		info.get("custom_half_day_period") or ""
	).strip() == "First Half"


def compute_late_deduction(attendance_map):
	"""Late-entry flag counts and days to deduct, per the Shift Type late-entry tiers.

	Each late check-in falls in the highest tier its lateness meets. Per tier, every full
	group of 4 lates deducts that tier's days; leftovers across tiers combining to 4 deduct
	the smallest tier's days. Nothing deducts below a group of 4.

	A first-half leave day is exempt: the second-half check-in is not a late arrival.
	"""
	cache = {}
	leave_cache = {}
	counts = {}        # late_by: number of late entries
	ded_by_tier = {}   # late_by: deduction days for that tier

	for att in attendance_map.values():
		in_time = att.get("in_time")
		shift = att.get("shift")
		att_date = att.get("attendance_date")
		if not in_time or not shift or not att_date:
			continue
		if _is_first_half_leave(att, leave_cache):
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
		# Highest tier the lateness meets (tiers sorted desc by late_by).
		tier = next(((lb, dd) for lb, dd in cfg["tiers"] if minutes_late >= lb), None)
		if not tier:
			continue
		counts[tier[0]] = counts.get(tier[0], 0) + 1
		ded_by_tier[tier[0]] = tier[1]

	# Flag-count summary, e.g. "15m × 4, 30m × 2".
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
		leftover += cnt % 4                                     # remainder carried to the combo tier
	per_tier[min_tier] = per_tier.get(min_tier, 0.0) + (leftover // 4) * min_ded

	total = sum(per_tier.values())
	# Split by tier for the two columns: deduction < 1 is a half-day tier, >= 1 a full-day tier.
	half_ded = sum(d for lb, d in per_tier.items() if ded_by_tier[lb] < 1.0)
	full_ded = sum(d for lb, d in per_tier.items() if ded_by_tier[lb] >= 1.0)

	return {"counts": counts, "summary": summary, "deduction": flt(total, 2),
		"half_deduction": flt(half_ded, 2), "full_deduction": flt(full_ded, 2)}


def get_holiday_map(employee, from_date, to_date):
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
			# Holiday description is a rich-text field; strip HTML and collapse whitespace.
			desc = frappe.utils.strip_html_tags(holiday.description or "")
			desc = " ".join(desc.split()).strip() or "Holiday"
			holiday_map[date_str] = {
				"description": desc,
				"weekly_off": cint(holiday.weekly_off),
			}
		
		return holiday_map
	except:
		return {}


def get_leave_map(employee, from_date, to_date):
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
	try:
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
			current = getdate(wfh.from_date)
			end = getdate(wfh.to_date)
			is_half_day = wfh.get('half_day', 0)
			first_day = True

			while current <= end:
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
	leave_type = leave_info.get("leave_type", "LEAVE")
	is_half_day = leave_info.get("half_day", False)
	
	if is_half_day:
		return f"HALF DAY - {leave_type}"
	else:
		return leave_type.upper()


def format_attendance_info(att_info):
	"""Newline-separated per-day cell for the Final Format 'Details' layout."""
	status = att_info.get("status", "")
	in_time = att_info.get("in_time")
	out_time = att_info.get("out_time")
	working_hours = att_info.get("working_hours", 0)
	shift = att_info.get("shift", "")
	late_entry = att_info.get("late_entry", 0)
	early_exit = att_info.get("early_exit", 0)

	if status == "Absent":
		in_time = None
		out_time = None
		working_hours = 0

	in_str = format_time(in_time) if in_time else "-"
	out_str = format_time(out_time) if out_time else "-"

	if working_hours:
		hh = int(working_hours)
		mm = int((working_hours - hh) * 60)
		twh = f"{hh:02d} H : {mm:02d} M"
	else:
		twh = "00 H : 00 M"

	shift_name = "-"
	shift_start_str = ""
	shift_end_str = ""
	if shift:
		try:
			sd = frappe.get_cached_doc("Shift Type", shift)
			shift_name = sd.name
			if sd.start_time is not None:
				shift_start_str = format_time(sd.start_time)
			if sd.end_time is not None:
				shift_end_str = format_time(sd.end_time)
		except Exception:
			pass
	shift_time = f"{shift_start_str} To {shift_end_str}" if (shift_start_str or shift_end_str) else "-"

	# Actual late / early ranges, only when the day was flagged.
	late_str = f"{in_str} To {shift_end_str}" if late_entry else ""
	early_str = f"{shift_start_str} To {out_str}" if early_exit else ""

	tag = "WFH" if status == "Work From Home" else ("OD" if status == "On Duty" else "")
	head = "HALF DAY" if status == "Half Day" else ("ABSENT" if status == "Absent" else "Present")

	lines = []
	if tag:
		lines.append(tag)
	lines.append(f"{head} :  In: {in_str} | Out: {out_str}")
	lines.append(f"T.W.HRs : {twh}")
	lines.append(f"Shift Name : {shift_name}")
	lines.append(f"Shift Time : {shift_time}")
	lines.append(f"Early Out : {early_str}")
	lines.append(f"Late Time : {late_str}")
	return "\n".join(lines)
