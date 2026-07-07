"""Percentage-based attendance calculation service (HO/Admin rule engine).

BRD ALP_HRMS_Payroll_001 §3A: each day's assigned shift hours are the 100%
baseline (Mon-Fri e.g. 8.25h, Saturday 4.0h — whatever Shift Type is assigned
that day). Worked hours are classified as:

  >= 97%            Full Day  (1.0 paid day)   — the 3% gap is the grace
  >= 50% and < 97%  Half Day  (0.5 paid day)
  <  50% / no data  Absent    (0.0 paid day)

Late flags use the Shift Type's Late Entry Threshold tiers when configured;
otherwise the BRD defaults apply (>=15 min late -> 0.5-day tier, >=30 min ->
1.0-day tier, grace below 15). Every 4 flags in a tier deduct that tier's
days; leftovers across tiers combining to 4 deduct the smallest tier again
(same engine as the Attendance Summary report).

`run_ho_adapter(batch)` fills a Monthly Attendance Batch's rows for the
HO/Admin engine: monthly calendar per BRD §4 (working days = month days -
Sundays - weekday PHs; PH on Sunday not double-counted), joining/relieving
proration, day-wise classification, WFH/OD counts and the late deduction.
"""

import json

import frappe
from frappe.utils import add_days, flt, get_datetime, get_first_day, get_last_day, getdate

FULL_DAY_PCT = 97.0
HALF_DAY_PCT = 50.0

# BRD defaults when a Shift Type has no Late Entry Threshold rows:
# (minutes late, days deducted per group of 4)
DEFAULT_LATE_TIERS = ((30, 1.0), (15, 0.5))


# ------------------------------------------------------------------ percentage

def get_shift_hours(shift_type, cache=None):
	"""Assigned hours of a Shift Type (the day's 100% baseline)."""
	if cache is not None and shift_type in cache:
		return cache[shift_type]
	hours = 0.0
	if shift_type:
		start, end = frappe.db.get_value("Shift Type", shift_type, ["start_time", "end_time"]) or (None, None)
		if start is not None and end is not None:
			seconds = (end - start).total_seconds()
			if seconds < 0:  # overnight shift
				seconds += 24 * 3600
			hours = seconds / 3600.0
	if cache is not None:
		cache[shift_type] = hours
	return hours


def classify_day(worked_hours, shift_hours):
	"""(status, paid_day, pct) for one day per the 97% / 50% percentage rules."""
	if not shift_hours:
		return ("Absent", 0.0, 0.0)
	pct = flt(worked_hours) * 100.0 / flt(shift_hours)
	if pct >= FULL_DAY_PCT:
		return ("Present", 1.0, flt(pct, 1))
	if pct >= HALF_DAY_PCT:
		return ("Half Day", 0.5, flt(pct, 1))
	return ("Absent", 0.0, flt(pct, 1))


# ------------------------------------------------------------------ late flags

def get_late_tiers(shift_type, cache):
	"""Shift's configured Late Entry Threshold tiers, else the BRD defaults.

	Returns {"start_time": time, "tiers": ((late_by_min, deduction_days), ...) desc}.
	"""
	if shift_type in cache:
		return cache[shift_type]
	cfg = None
	if shift_type:
		start_time = frappe.db.get_value("Shift Type", shift_type, "start_time")
		if start_time is not None:
			rows = frappe.get_all(
				"Late Entry Threshold",
				filters={
					"parent": shift_type,
					"parenttype": "Shift Type",
					"parentfield": "custom_late_entry_thresholds",
				},
				fields=["late_by", "deduction"],
				order_by="late_by desc",
			)
			tiers = tuple(
				(int(r.late_by), flt(r.deduction))
				for r in rows
				if int(r.late_by or 0) > 0 and flt(r.deduction) > 0
			)
			cfg = {"start_time": start_time, "tiers": tiers or DEFAULT_LATE_TIERS}
	cache[shift_type] = cfg
	return cfg


def classify_late(in_time, shift_type, att_date, cache):
	"""Highest late tier this check-in hits, or None (within grace / no shift)."""
	cfg = get_late_tiers(shift_type, cache)
	if not cfg or not in_time:
		return None
	try:
		shift_start = get_datetime(f"{getdate(att_date)} {cfg['start_time']}")
		minutes_late = (get_datetime(in_time) - shift_start).total_seconds() / 60.0
	except Exception:
		return None
	if minutes_late <= 0:
		return None
	return next(((lb, dd) for lb, dd in cfg["tiers"] if minutes_late >= lb), None)


def compute_late_deduction(counts, deduction_by_tier):
	"""Per-tier groups of 4 deduct that tier's days; combined leftovers reaching 4
	deduct the smallest tier's days again. Returns total days to deduct."""
	if not counts:
		return 0.0
	min_ded = min(deduction_by_tier.values())
	total, leftover = 0.0, 0
	for late_by, cnt in counts.items():
		total += (cnt // 4) * deduction_by_tier[late_by]
		leftover += cnt % 4
	total += (leftover // 4) * min_ded
	return flt(total, 2)


# ------------------------------------------------------------------ HO adapter

def run_ho_adapter(batch):
	"""Fill the batch's rows with the HO/Admin percentage-engine numbers."""
	month_start = getdate(get_first_day(batch.payroll_month))
	month_end = getdate(get_last_day(batch.payroll_month))
	shift_hours_cache, late_cfg_cache = {}, {}

	for row in batch.rows:
		_fill_ho_row(row, month_start, month_end, shift_hours_cache, late_cfg_cache)


def _fill_ho_row(row, month_start, month_end, shift_hours_cache, late_cfg_cache):
	# Lifecycle proration (BRD §2): count strictly joining -> relieving.
	start = max(month_start, getdate(row.date_of_joining)) if row.date_of_joining else month_start
	end = min(month_end, getdate(row.relieving_date)) if row.relieving_date else month_end
	if start > end:
		return

	holidays = _get_holidays(row.employee, month_start, month_end)
	attendance = _get_attendance(row.employee, month_start, month_end)
	leaves = _get_leave_days(row.employee, month_start, month_end)
	wfh_days = _get_wfh_days(row.employee, month_start, month_end)
	lwp_cache = {}

	# BRD §2 Present-by-Default: HR flag that makes the engine ignore punch data
	# entirely and mark every working day Present (zero late flags, zero absents).
	present_by_default = bool(
		frappe.db.get_value("Employee", row.employee, "custom_present_by_default")
	)

	sundays = ph = 0
	present = absent = half = 0.0
	paid_days = paid_leave = unpaid_leave = 0.0
	od_days = wfh_count = 0.0
	late_counts, late_ded_by_tier = {}, {}
	day_data = {}

	day = start
	while day <= end:
		key = day.strftime("%Y-%m-%d")
		is_sunday = day.weekday() == 6
		holiday = holidays.get(key)
		att = attendance.get(key)
		info = {}

		# Calendar (BRD §4): Sundays counted once; PH only on weekdays
		# (a holiday falling on Sunday is NOT double-counted).
		if is_sunday:
			sundays += 1
			info = {"status": "Weekend"}
		elif holiday is not None and holiday.get("weekly_off"):
			# Non-Sunday weekly off from the holiday list — treat like a weekend day.
			sundays += 1
			info = {"status": "Weekly Off"}
		elif holiday is not None:
			ph += 1
			info = {"status": "Holiday", "description": holiday.get("description") or ""}

		if present_by_default and not (is_sunday or holiday is not None):
			# Punch data is ignored outright; every working day is a full paid day.
			present += 1
			paid_days += 1.0
			info = {"status": "Present", "present_by_default": 1}
		elif att:
			status = att.status
			# OD is recorded as status Present with reason "On Duty"
			# (attendance_request_automation) — never as its own status.
			is_od = status == "On Duty" or (att.get("attendance_request_reason") == "On Duty")
			if is_od:
				od_days += 1.0
				paid_days += 1.0
				info = {"status": "On Duty"}
			elif status == "Work From Home":
				# Half-day WFH still shows a full paid day (BRD §3C); only the
				# monthly WFH count records 0.5.
				wfh = wfh_days.get(key)
				wfh_count += 0.5 if (wfh and wfh["half_day"]) else 1.0
				paid_days += 1.0
				info = {"status": "WFH", "hours": flt(att.working_hours, 2)}
				# BRD §3D scenario 2: a late WFH clock-in flags exactly like office.
				tier = classify_late(att.in_time, att.shift, day, late_cfg_cache)
				if tier:
					late_counts[tier[0]] = late_counts.get(tier[0], 0) + 1
					late_ded_by_tier[tier[0]] = tier[1]
					info["late_tier"] = tier[0]
			elif status == "On Leave":
				p, u = _leave_paid_unpaid(att.leave_type, 1.0, lwp_cache)
				paid_leave += p
				unpaid_leave += u
				paid_days += p
				info = {"status": "On Leave", "leave_type": att.leave_type}
			elif not (is_sunday or holiday is not None):
				# Regular working day with punches: apply the percentage rules.
				shift_hours = get_shift_hours(att.shift, shift_hours_cache)
				if att.working_hours and shift_hours:
					status, paid, pct = classify_day(att.working_hours, shift_hours)
				else:
					# No hours to measure — trust the recorded status.
					paid = {"Present": 1.0, "Half Day": 0.5}.get(status, 0.0)
					pct = None
				if status == "Present":
					present += 1
				elif status == "Half Day":
					half += 1
					# The other half may be an approved half-day leave on the record.
					if att.leave_type:
						p, u = _leave_paid_unpaid(att.leave_type, 0.5, lwp_cache)
						paid_leave += p
						unpaid_leave += u
						paid += p
				else:
					absent += 1
				paid_days += paid
				info = {
					"status": status,
					"in": str(att.in_time or ""),
					"out": str(att.out_time or ""),
					"hours": flt(att.working_hours, 2),
					"pct": pct,
				}
				# Late flag — skipped on holidays/weekends (above), for OD (above)
				# and on approved half-day-leave days (BRD §3D scenario 3: the
				# late penalty is off when a half-day leave covers the morning).
				if not att.leave_type:
					tier = classify_late(att.in_time, att.shift, day, late_cfg_cache)
					if tier:
						late_counts[tier[0]] = late_counts.get(tier[0], 0) + 1
						late_ded_by_tier[tier[0]] = tier[1]
						info["late_tier"] = tier[0]
			else:
				# Worked on a holiday/weekend — comp-off territory, not a paid-day change.
				info["worked_hours"] = flt(att.working_hours, 2)
		elif not info:
			leave = leaves.get(key)
			if leave:
				fraction = 0.5 if leave["half_day"] else 1.0
				p, u = _leave_paid_unpaid(leave["leave_type"], fraction, lwp_cache)
				paid_leave += p
				unpaid_leave += u
				paid_days += p
				info = {"status": "On Leave", "leave_type": leave["leave_type"], "half_day": leave["half_day"]}
			else:
				absent += 1
				info = {"status": "Absent"}

		# WFH Requests without a same-day attendance record (BRD: half = 0.5,
		# two halves sum to 1.0 in the monthly count).
		wfh = wfh_days.get(key)
		if wfh and not (att and att.status == "Work From Home"):
			wfh_count += 0.5 if wfh["half_day"] else 1.0
			info.setdefault("status", "WFH")
			info["wfh"] = "half" if wfh["half_day"] else "full"

		day_data[key] = info
		day = add_days(day, 1)

	total_days = (end - start).days + 1
	working_days = total_days - sundays - ph
	late_deduction = compute_late_deduction(late_counts, late_ded_by_tier)

	row.working_days = flt(working_days, 1)
	row.present_days = flt(present, 1)
	row.absent_days = flt(absent, 1)
	row.half_days = flt(half, 1)
	row.paid_leaves = flt(paid_leave, 1)
	row.unpaid_leaves = flt(unpaid_leave, 1)
	row.weekends = sundays
	row.public_holidays = ph
	row.od_days = flt(od_days, 1)
	row.wfh_count = flt(wfh_count, 1)
	row.late_group1_count = sum(n for lb, n in late_counts.items() if lb < 30)
	row.late_group2_count = sum(n for lb, n in late_counts.items() if lb >= 30)
	row.late_deduction_days = late_deduction
	row.payable_days = max(flt(paid_days - late_deduction, 1), 0.0)
	row.day_data = json.dumps(day_data)


# ------------------------------------------------------------------ data pulls

def _get_holidays(employee, from_date, to_date):
	holiday_list = frappe.db.get_value("Employee", employee, "holiday_list") or frappe.db.get_value(
		"Company", frappe.db.get_value("Employee", employee, "company"), "default_holiday_list"
	)
	if not holiday_list:
		return {}
	rows = frappe.get_all(
		"Holiday",
		filters={"parent": holiday_list, "holiday_date": ["between", [from_date, to_date]]},
		fields=["holiday_date", "description", "weekly_off"],
	)
	return {r.holiday_date.strftime("%Y-%m-%d"): {"description": r.description, "weekly_off": r.weekly_off} for r in rows}


def _get_attendance(employee, from_date, to_date):
	rows = frappe.get_all(
		"Attendance",
		filters={
			"employee": employee,
			"attendance_date": ["between", [from_date, to_date]],
			"docstatus": 1,
		},
		fields=[
			"attendance_date", "status", "working_hours", "shift",
			"in_time", "out_time", "leave_type", "attendance_request_reason",
		],
	)
	return {r.attendance_date.strftime("%Y-%m-%d"): r for r in rows}


def _get_leave_days(employee, from_date, to_date):
	"""Approved Leave Application days (only used when no Attendance row exists)."""
	rows = frappe.get_all(
		"Leave Application",
		filters={"employee": employee, "docstatus": 1, "status": "Approved"},
		fields=["from_date", "to_date", "leave_type", "half_day", "half_day_date"],
	)
	days = {}
	for r in rows:
		day = getdate(r.from_date)
		while day <= getdate(r.to_date):
			if getdate(from_date) <= day <= getdate(to_date):
				days[day.strftime("%Y-%m-%d")] = {
					"leave_type": r.leave_type,
					"half_day": bool(r.half_day and r.half_day_date and day == getdate(r.half_day_date)),
				}
			day = add_days(day, 1)
	return days


def _get_wfh_days(employee, from_date, to_date):
	"""Approved Work From Home Request days (half day applies to its first day)."""
	rows = frappe.db.sql(
		"""
		SELECT date AS from_date, to_date, half_day
		FROM `tabWork From Home Request`
		WHERE employee = %s AND status = 'Approved' AND date <= %s AND to_date >= %s
		""",
		(employee, to_date, from_date),
		as_dict=True,
	)
	days = {}
	for r in rows:
		day = getdate(r.from_date)
		first = True
		while day <= getdate(r.to_date):
			if getdate(from_date) <= day <= getdate(to_date):
				days[day.strftime("%Y-%m-%d")] = {"half_day": bool(r.half_day and first)}
				first = False
			day = add_days(day, 1)
	return days


def _leave_paid_unpaid(leave_type, fraction, cache):
	"""Split a leave day fraction into (paid, unpaid) by the Leave Type's LWP flag."""
	if not leave_type:
		return (fraction, 0.0)
	if leave_type not in cache:
		try:
			cache[leave_type] = bool(frappe.get_cached_value("Leave Type", leave_type, "is_lwp"))
		except Exception:
			cache[leave_type] = False
	return (0.0, fraction) if cache[leave_type] else (fraction, 0.0)
