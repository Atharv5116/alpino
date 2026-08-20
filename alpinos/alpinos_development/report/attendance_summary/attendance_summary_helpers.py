# Copyright (c) 2026, Alpinos and contributors
# License: MIT

import frappe
from frappe.utils import date_diff, flt


def get_location_details(location):
	"""Get location details from Location doctype"""
	if not location:
		return {}

	try:
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
	except Exception:
		pass

	return {}


def _get_shift_hours(shift_name, cache):
	"""Expected worked hours for a shift = (end_time - start_time) MINUS the shift's Late
	Entry Grace Period (handles overnight). Benchmark for the Working-Hours-Shortage count:
	a worked day whose `working_hours` fall below this is a shortage day. The grace period
	is deducted so someone who arrives within grace and works the rest of the shift is not
	flagged short (e.g. an 8.5h shift with 15m grace expects 8.25h)."""
	if shift_name in cache:
		return cache[shift_name]
	hours = None
	if shift_name:
		vals = frappe.db.get_value(
			"Shift Type", shift_name, ["start_time", "end_time", "late_entry_grace_period"]
		)
		if vals and vals[0] is not None and vals[1] is not None:
			start_t, end_t, grace = vals
			s = start_t.total_seconds() if hasattr(start_t, "total_seconds") else 0
			e = end_t.total_seconds() if hasattr(end_t, "total_seconds") else 0
			dur = (e - s) / 3600.0
			if dur < 0:
				dur += 24.0
			dur -= (int(grace or 0)) / 60.0  # deduct the Late Entry Grace Period (minutes)
			hours = round(max(dur, 0.0), 2)
	cache[shift_name] = hours
	return hours


def calculate_attendance_stats(attendance_map, holiday_map, leave_map, wfh_map, from_date, to_date, employee):
	"""Attendance statistics for the month, aligned to the Final Format layout.

	`holiday_map` values are {"description", "weekly_off"} so Public Holiday (weekly_off=0)
	and Weekend (weekly_off=1) come straight from the employee's Holiday List — no hard-coded
	Sat/Sun (Alpino works Saturdays; only the Holiday List's weekly-offs are weekend days)."""
	stats = frappe._dict({
		"clock_in_days": 0,
		"absent_days": 0,
		"public_holiday": 0,
		"weekend": 0,
		"paid_leave": 0,
		"unpaid_leave": 0,
		"wfh": 0,
		"od": 0,
		"working_hours_shortage": 0,
		"missing_attendance": 0,
		"avg_working_hours": 0,
	})

	# Public Holiday vs Weekend from the Holiday List's weekly_off flag.
	for info in holiday_map.values():
		if info.get("weekly_off"):
			stats.weekend += 1
		else:
			stats.public_holiday += 1

	total_working_hours = 0
	working_days_count = 0
	shift_hours_cache = {}

	def _short(att):
		"""1 when a worked day's hours fell below its shift's expected span, else 0."""
		wh = flt(att.get("working_hours"))
		sh = _get_shift_hours(att.get("shift"), shift_hours_cache)
		return 1 if (sh and wh and wh < sh) else 0

	def _leave_amount(leave_type, amt):
		try:
			is_lwp = frappe.get_cached_value("Leave Type", leave_type, "is_lwp")
		except Exception:
			is_lwp = 0
		if is_lwp:
			stats.unpaid_leave += amt
		else:
			stats.paid_leave += amt

	for date_str, att in attendance_map.items():
		status = att.get("status")
		if status == "Present":
			stats.clock_in_days += 1
			if att.get("working_hours"):
				total_working_hours += flt(att.get("working_hours"))
				working_days_count += 1
			stats.working_hours_shortage += _short(att)
		elif status == "Absent":
			stats.absent_days += 1
		elif status == "Half Day":
			# Worked half counts as a clock-in; the other half may be leave (leave_type on the row).
			stats.clock_in_days += 1
			if att.get("working_hours"):
				total_working_hours += flt(att.get("working_hours"))
				working_days_count += 1
			if att.get("leave_type"):
				_leave_amount(att.get("leave_type"), 0.5)
		elif status == "On Leave":
			if att.get("leave_type"):
				_leave_amount(att.get("leave_type"), 1)
		elif status == "Work From Home":
			stats.wfh += 1
			stats.clock_in_days += 1
			if att.get("working_hours"):
				total_working_hours += flt(att.get("working_hours"))
				working_days_count += 1
			stats.working_hours_shortage += _short(att)
		elif status == "On Duty":
			stats.od += 1
			stats.clock_in_days += 1
			if att.get("working_hours"):
				total_working_hours += flt(att.get("working_hours"))
				working_days_count += 1
			stats.working_hours_shortage += _short(att)

	# Leaves not already covered by an attendance row.
	for date_str, leave_info in leave_map.items():
		if date_str not in attendance_map:
			amt = 0.5 if leave_info.get("half_day", False) else 1
			_leave_amount(leave_info.get("leave_type"), amt)

	# WFH requests not already captured as attendance.
	for date_str, wfh_info in wfh_map.items():
		if date_str not in attendance_map or attendance_map[date_str].get("status") != "Work From Home":
			stats.wfh += 0.5 if wfh_info.get("half_day", 0) else 1

	# Missing attendance = days with nothing marked (not attendance, leave, holiday or weekend).
	total_days = date_diff(to_date, from_date) + 1
	marked_days = len(attendance_map) + len([d for d in leave_map if d not in attendance_map])
	stats.missing_attendance = total_days - marked_days - stats.public_holiday - stats.weekend

	if working_days_count > 0:
		stats.avg_working_hours = round(total_working_hours / working_days_count, 2)

	return stats
