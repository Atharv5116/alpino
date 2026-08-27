"""Default Present.

An Employee ticked `custom_default_present` is marked **Present for every working
day** using the assigned shift's timing, ignoring their actual check-ins AND
overriding any leave for that day (per the client's "present always" choice),
until the box is un-ticked.

Cadence: DAILY. A day is deterministic (no punches needed), so a daily job
pre-marks today + a short look-back for each such employee. Marking the day
early means the normal auto-attendance run finds an Attendance already there and
skips it — no "Absent then Present" flicker.

  * setup_default_present_field()  -> after_migrate: the Employee checkbox
  * run_daily()                    -> scheduled: mark today + look-back
  * mark_default_present_for_day() -> the single-day marker (create OR override)
  * backfill()                     -> whitelisted one-off for a date range
"""

import datetime

import frappe
from frappe.utils import add_days, flt, get_datetime, getdate, now_datetime

LOOKBACK_DAYS = 3  # daily job also re-checks the last few days in case it was down


def setup_default_present_field():
	"""after_migrate: add the `Default Present` checkbox to Employee."""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	create_custom_fields(
		{
			"Employee": [
				dict(
					fieldname="custom_default_present",
					label="Default Present",
					fieldtype="Check",
					insert_after="default_shift",
					description=(
						"When ticked, this employee is marked Present for every WORKING day "
						"using the assigned shift timing — actual punches are ignored and any "
						"leave for the day is overridden — until this box is un-ticked."
					),
				)
			]
		},
		ignore_validate=True,
	)


def _is_holiday(holiday_list, date):
	"""True when `date` is a Public Holiday or weekly-off on the employee's Holiday List
	(i.e. NOT a working day). No holiday list -> treat every day as working."""
	if not holiday_list:
		return False
	return bool(frappe.db.exists("Holiday", {"parent": holiday_list, "holiday_date": date}))


def _shift_for(employee, date, default_shift):
	"""The Shift Type in force for the employee on `date`: an active Shift Assignment
	covering the date, else the Employee's default shift."""
	rows = frappe.db.sql(
		"""
		SELECT shift_type FROM `tabShift Assignment`
		WHERE employee = %s AND docstatus = 1 AND status = 'Active'
		  AND start_date <= %s AND (end_date IS NULL OR end_date >= %s)
		ORDER BY start_date DESC LIMIT 1
		""",
		(employee, date, date),
	)
	return (rows[0][0] if rows else None) or default_shift


def _shift_times(shift, date):
	"""(in_time, out_time, working_hours) from the Shift Type's start/end, overnight-safe."""
	vals = frappe.db.get_value("Shift Type", shift, ["start_time", "end_time"])
	if not vals or vals[0] is None or vals[1] is None:
		return None, None, None
	start_t, end_t = vals
	s = start_t.total_seconds() if hasattr(start_t, "total_seconds") else 0
	e = end_t.total_seconds() if hasattr(end_t, "total_seconds") else 0
	span = (e - s) / 3600.0
	if span <= 0:  # overnight shift -> ends the next day
		span += 24.0
		out_date = add_days(date, 1)
	else:
		out_date = date
	midnight = datetime.datetime.combine(getdate(date), datetime.time())
	out_midnight = datetime.datetime.combine(getdate(out_date), datetime.time())
	in_time = get_datetime(midnight + start_t)
	out_time = get_datetime(out_midnight + end_t)
	return in_time, out_time, round(span, 2)


def mark_default_present_for_day(employee, date):
	"""Mark ONE working day Present with the assigned shift timing, overriding whatever
	is there (punches / leave / Absent). Skips holidays/weekly-offs and days outside the
	employee's active employment. Returns the Attendance name, or None if skipped."""
	date = getdate(date)
	emp = frappe.db.get_value(
		"Employee",
		employee,
		["date_of_joining", "relieving_date", "holiday_list", "default_shift",
		 "company", "custom_default_present"],
		as_dict=True,
	)
	if not emp or not emp.get("custom_default_present"):
		return None
	if emp.date_of_joining and date < getdate(emp.date_of_joining):
		return None
	if emp.relieving_date and date > getdate(emp.relieving_date):
		return None
	if _is_holiday(emp.holiday_list, date):
		return None

	shift = _shift_for(employee, date, emp.default_shift)
	if not shift:
		return None  # no shift -> no timing to apply
	in_time, out_time, working_hours = _shift_times(shift, date)
	if in_time is None:
		return None

	values = {
		"status": "Present",
		"shift": shift,
		"in_time": in_time,
		"out_time": out_time,
		"working_hours": working_hours,
		"leave_type": None,
		"leave_application": None,
		"half_day_status": None,
		"late_entry": 0,
		"early_exit": 0,
	}

	existing = frappe.db.get_value(
		"Attendance",
		{"employee": employee, "attendance_date": date, "docstatus": ["<", 2]},
		"name",
	)
	if existing:
		# Override in place (works for submitted rows too; bypasses validate on purpose).
		frappe.db.set_value("Attendance", existing, values, update_modified=True)
		return existing

	doc = frappe.new_doc("Attendance")
	doc.employee = employee
	doc.attendance_date = date
	doc.company = emp.company
	for k, v in values.items():
		setattr(doc, k, v)
	# "present always" — bypass the leave-overlap / duplicate guards so a leave day still
	# becomes Present.
	doc.flags.ignore_validate = True
	doc.insert(ignore_permissions=True)
	doc.submit()
	return doc.name


def run_daily():
	"""Scheduled: mark today + the last few days Present for every Default-Present employee."""
	today = getdate(now_datetime())
	employees = frappe.get_all(
		"Employee",
		filters={"custom_default_present": 1, "status": "Active"},
		pluck="name",
	)
	marked = 0
	for emp in employees:
		for i in range(0, LOOKBACK_DAYS + 1):
			d = add_days(today, -i)
			try:
				if mark_default_present_for_day(emp, d):
					marked += 1
			except Exception:
				frappe.log_error(
					title=f"Default Present daily failed: {emp} {d}",
					message=frappe.get_traceback(),
				)
	frappe.db.commit()
	return {"employees": len(employees), "marked": marked}


@frappe.whitelist()
def backfill(from_date, to_date, employee=None, apply=0):
	"""One-off backfill for a date range. DRY-RUN by default; apply=1 writes.

	  bench --site SITE execute alpinos.default_present.backfill --kwargs "{'from_date':'2026-08-01','to_date':'2026-08-31'}"
	  ... --kwargs "{'from_date':'2026-08-01','to_date':'2026-08-31','apply':1}"
	"""
	apply = int(apply)
	start, end = getdate(from_date), getdate(to_date)
	filters = {"custom_default_present": 1, "status": "Active"}
	if employee:
		filters["name"] = employee
	employees = frappe.get_all("Employee", filters=filters, pluck="name")

	would, applied, samples = 0, 0, []
	for emp in employees:
		d = start
		guard = 0
		while d <= end and guard < 400:
			guard += 1
			# preview: only count days that WOULD be marked (working day, in employment, has shift)
			row = frappe.db.get_value(
				"Employee", emp,
				["date_of_joining", "relieving_date", "holiday_list", "default_shift"],
				as_dict=True,
			) or {}
			skip = (
				(row.get("date_of_joining") and d < getdate(row.date_of_joining))
				or (row.get("relieving_date") and d > getdate(row.relieving_date))
				or _is_holiday(row.get("holiday_list"), d)
				or not _shift_for(emp, d, row.get("default_shift"))
			)
			if not skip:
				would += 1
				if apply and mark_default_present_for_day(emp, d):
					applied += 1
				if len(samples) < 25:
					samples.append({"employee": emp, "date": str(d)})
			d = add_days(d, 1)
		if apply:
			frappe.db.commit()
	return {
		"mode": "APPLY" if apply else "DRY-RUN",
		"employees": len(employees),
		"would_mark": would,
		"applied": applied,
		"sample": samples,
	}
