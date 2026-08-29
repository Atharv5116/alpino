# Copyright (c) 2026, Alpinos and contributors
# License: MIT

import frappe
from frappe.utils import date_diff, flt, getdate


def get_location_details(location):
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


def _required_hours(shift_name, is_saturday, cache):
	"""Required working hours for the day: the shift span, or the Saturday threshold on Saturdays."""
	key = (shift_name, bool(is_saturday))
	if key in cache:
		return cache[key]
	req = None
	if shift_name:
		vals = frappe.db.get_value(
			"Shift Type", shift_name,
			["start_time", "end_time", "saturday_working_hours_threshold"],
		)
		if vals:
			start_t, end_t, sat_req = vals
			span = None
			if start_t is not None and end_t is not None:
				s = start_t.total_seconds() if hasattr(start_t, "total_seconds") else 0
				e = end_t.total_seconds() if hasattr(end_t, "total_seconds") else 0
				span = (e - s) / 3600.0
				if span < 0:
					span += 24.0
				span = round(span, 2)
			req = (flt(sat_req) or span) if is_saturday else span
	cache[key] = req
	return req


def calculate_attendance_stats(attendance_map, holiday_map, leave_map, wfh_map, from_date, to_date, employee):
	"""Monthly attendance statistics for the Final Format layout.

	Public Holiday vs Weekend come from the Holiday List's weekly_off flag, not a hard-coded
	Sat/Sun (Alpino works Saturdays).
	"""
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

	def _whs(att, date_str):
		"""Working-Hours-Shortage day-value from the %-of-required tiers.

		Only for a day with both a clock-in and a clock-out; holidays / weekly-offs never count.
		  >= 97% of required hours -> 0.0
		  50% - 97%                -> 0.5
		  < 50%                    -> 1.0
		"""
		if date_str in holiday_map:
			return 0.0
		if not (att.get("in_time") and att.get("out_time")):
			return 0.0
		try:
			is_sat = getdate(date_str).weekday() == 5
		except Exception:
			is_sat = False
		req = _required_hours(att.get("shift"), is_sat, shift_hours_cache)
		wh = flt(att.get("working_hours"))
		if not req or wh <= 0:
			return 0.0
		ratio = wh / req
		if ratio >= 0.97:
			return 0.0
		if ratio >= 0.50:
			return 0.5
		return 1.0

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
		has_in = bool(att.get("in_time"))
		has_out = bool(att.get("out_time"))
		wh = flt(att.get("working_hours"))
		leave_type = att.get("leave_type")
		on_holiday = date_str in holiday_map

		if status == "On Leave":
			# Full-day leave, paid or unpaid.
			if leave_type:
				_leave_amount(leave_type, 1)
			continue

		if status == "On Duty":
			# Full-day Present; no shortage and no late penalty even with no punches.
			stats.od += 1
			stats.clock_in_days += 1
			if wh:
				total_working_hours += wh
				working_days_count += 1
			continue

		if status == "Half Day":
			# 0.5 worked half (Present) + 0.5 other half.
			stats.clock_in_days += 1
			if wh:
				total_working_hours += wh
				working_days_count += 1
			if leave_type:
				# Other half is leave.
				_leave_amount(leave_type, 0.5)
			elif not on_holiday:
				# Other half is a 0.5 working-hours shortage.
				stats.working_hours_shortage += 0.5
			continue

		if status == "Work From Home":
			# WFH follows normal attendance rules: shortage and late penalty both apply.
			stats.wfh += 1
			stats.clock_in_days += 1
			if wh:
				total_working_hours += wh
				working_days_count += 1
			stats.working_hours_shortage += _whs(att, date_str)
			continue

		# Classify by punches and hours, not the stored status: a day with both a clock-in and
		# a clock-out is Present (plus a shortage tier), never Absent. Only a missing clock-out
		# or no punches at all is Absent.
		if has_in and has_out and wh > 0:
			stats.clock_in_days += 1
			total_working_hours += wh
			working_days_count += 1
			stats.working_hours_shortage += _whs(att, date_str)
		elif not on_holiday:
			stats.absent_days += 1

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
