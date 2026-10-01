# Copyright (c) 2026, Alpinos and contributors
# License: MIT

import frappe
from frappe.utils import cint, date_diff, flt, getdate

SUNDAY = 6


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


def _shift_thresholds(shift_name, is_saturday, cache):
	"""(half_day_threshold, absent_threshold) from the Shift Type, 0 when not configured.

	These are HR's own policy: below the half-day threshold the day is half, below the
	absent threshold it is absent. The report used to ignore them entirely and measure
	every day against the shift span, so a shift configured to accept a shorter day still
	collected a shortage.

	Saturday has its own pair, and they are the ones that count on a Saturday -- Alpino
	works a short Saturday, so measuring it against the weekday thresholds charged a
	shortage for every Saturday of the month. The Saturday half-day threshold falls back to
	the Saturday Present threshold, exactly as the marking rule does
	(attendance_request_automation.validate_saturday_attendance_threshold).
	"""
	key = ("thresholds", shift_name, bool(is_saturday))
	if key in cache:
		return cache[key]
	half = absent = 0.0
	if shift_name:
		if is_saturday:
			vals = frappe.db.get_value(
				"Shift Type", shift_name,
				[
					"saturday_working_hours_threshold_for_half_day",
					"saturday_working_hours_threshold_for_absent",
					"saturday_working_hours_threshold",
				],
			)
			if vals:
				half, absent = flt(vals[0]), flt(vals[1])
				if not half:
					half = flt(vals[2])
		else:
			vals = frappe.db.get_value(
				"Shift Type", shift_name,
				["working_hours_threshold_for_half_day", "working_hours_threshold_for_absent"],
			)
			if vals:
				half, absent = flt(vals[0]), flt(vals[1])
	cache[key] = (half, absent)
	return cache[key]


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

	Weekend counts Sundays only (Alpino works Saturdays); every other Holiday List entry
	counts as a public holiday.
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
		# HRMS asked for the detail behind the two figures people dispute: which days make
		# up Absent, and which make up the shortage. A day rejected for short hours counts
		# as a shortage and NOT as an absence, which is what makes the totals look wrong.
		"absent_dates": [],
		"whs_dates": [],
		"missing_attendance": 0,
		"avg_working_hours": 0,
	})

	# Sundays are the weekend; anything else on the Holiday List is a public holiday.
	for holiday_date in holiday_map:
		if getdate(holiday_date).weekday() == SUNDAY:
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
		wh = flt(att.get("working_hours"))
		if wh <= 0:
			return 0.0

		# The Shift Type's own thresholds come first: they are the policy HR configured.
		# Below the absent threshold the day is a full shortage, below the half-day one a
		# half, and at or above it nothing is owed -- a shift that accepts a shorter day
		# stops collecting a shortage for every day of the month.
		half_t, absent_t = _shift_thresholds(att.get("shift"), is_sat, shift_hours_cache)
		if is_sat and half_t and not absent_t:
			# Legacy two-way Saturday, the way the marking reads it: below the Saturday
			# Present threshold the day is Absent outright, at or above it nothing is owed.
			return 0.0 if wh >= half_t else 1.0
		if absent_t and wh < absent_t:
			return 1.0
		if half_t and wh < half_t:
			return 0.5
		if half_t or absent_t:
			return 0.0

		# Neither threshold configured: fall back to the shift span and its tiers.
		req = _required_hours(att.get("shift"), is_sat, shift_hours_cache)
		if not req:
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
			# Changes(HP) #9: a leave range swallows the Sundays and Public Holidays inside
			# it, but those days were never working days -- charging them as Paid Leave
			# would bill the employee twice for a day nobody was expected to work.
			if on_holiday:
				continue
			# Full-day leave, paid or unpaid.
			if leave_type:
				_leave_amount(leave_type, 1)
			continue

		# An approved On Duty request marks the day Present, since HRMS has no On Duty
		# status, so the day is recognised by the request behind it (is_on_duty, set in
		# get_attendance_map). The OD count stayed at nought until this read it.
		if status == "On Duty" or cint(att.get("is_on_duty")):
			# Full-day Present; no shortage and no late penalty even with no punches.
			stats.od += 1
			stats.clock_in_days += 1
			if wh:
				total_working_hours += wh
				working_days_count += 1
			continue

		if status == "Half Day":
			# 0.5 worked half + 0.5 other half.
			#
			# Changes(HP) #8: the worked half is only credited when there is a real
			# clock-in. Approving a half-day leave writes the Attendance up front, so a
			# FUTURE half day used to hand out a Clock-In Day for a shift nobody had
			# worked yet. No punch means the half was not worked -- 0.5 Absent.
			if has_in:
				stats.clock_in_days += 1
				if wh:
					total_working_hours += wh
					working_days_count += 1
			elif not on_holiday:
				stats.absent_days += 0.5
				# Half of a day, so the dates must say so too -- otherwise a 1.5 count
				# lists one date and the detail reads as wrong all over again.
				stats.absent_dates.append(f"{getdate(date_str).day} (half)")
			if leave_type:
				# Other half is leave -- unless the day was never a working day (#9).
				if not on_holiday:
					_leave_amount(leave_type, 0.5)
			elif not on_holiday:
				# Other half is a 0.5 working-hours shortage.
				stats.working_hours_shortage += 0.5
				stats.whs_dates.append(f"{getdate(date_str).day} (half)")
			continue

		if status == "Work From Home":
			# WFH follows normal attendance rules: shortage and late penalty both apply.
			stats.wfh += 1
			stats.clock_in_days += 1
			if wh:
				total_working_hours += wh
				working_days_count += 1
			_amount = _whs(att, date_str)
			stats.working_hours_shortage += _amount
			if _amount:
				stats.whs_dates.append(
					f"{getdate(date_str).day}" if _amount >= 1 else f"{getdate(date_str).day} (half)"
				)
			continue

		# A day marked Absent still costs a full day, but how it is reported depends on
		# whether the employee actually worked. With both punches the day was rejected for
		# short hours, so it counts as a full working-hours shortage rather than an
		# absence; with no punches it is a genuine absence. Either way the deduction is
		# 1.0, so paid days are the same.
		if status == "Absent":
			if on_holiday:
				continue
			if has_in and has_out and wh > 0:
				stats.clock_in_days += 1
				total_working_hours += wh
				working_days_count += 1
				stats.working_hours_shortage += 1.0
				stats.whs_dates.append(f"{getdate(date_str).day}")
			else:
				stats.absent_days += 1
				stats.absent_dates.append(f"{getdate(date_str).day}")
			continue

		# Otherwise classify by punches and hours rather than the stored status: a day with
		# both a clock-in and a clock-out is a worked day plus a shortage tier. Only a missing
		# clock-out or no punches at all is Absent.
		if has_in and has_out and wh > 0:
			stats.clock_in_days += 1
			total_working_hours += wh
			working_days_count += 1
			_amount = _whs(att, date_str)
			stats.working_hours_shortage += _amount
			if _amount:
				stats.whs_dates.append(
					f"{getdate(date_str).day}" if _amount >= 1 else f"{getdate(date_str).day} (half)"
				)
		elif not on_holiday:
			stats.absent_days += 1
			stats.absent_dates.append(f"{getdate(date_str).day}")

	# Leaves not already covered by an attendance row.
	for date_str, leave_info in leave_map.items():
		if date_str in attendance_map:
			continue
		# Changes(HP) #9: get_leave_map walks every date from -> to, so a Sunday or a
		# Public Holiday inside the range lands here too. Only working days are Paid Leave.
		if date_str in holiday_map:
			continue
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
