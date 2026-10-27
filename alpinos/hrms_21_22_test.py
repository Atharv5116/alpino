"""Changes(HP) HRMS #21 and #22: the dashboard's month, and the calendar's full day.

Run:  bench --site alpinos.test execute alpinos.hrms_21_22_test.run

#21  "The following dashboard sections should display records relevant to the current month
      only: Upcoming Birthdays, Work Anniversaries, Probation Completion, Internship
      Completion, Salary Increment ... Automatically refresh the data on the 1st of every
      month to show the records for the new month."

#22  "For employee REENA.S, attendance on 10th and 17th October (Saturdays) is marked as
      Present, and working hours are above 3.75 hours. However, the dashboard still shows
      red. Since the employee is assigned to the HO shift, the dashboard should display
      green when attendance is Present and working hours are above 3.75 hours."

"Today" is pinned to 20-10-2031 for #21 and the employees' dates are set to land around it,
so real birthdays cannot make a check pass or fail. #22 sets the thresholds on one Shift
Type and writes its fixtures in a month before the employee joined, so no real Attendance
sits on the same days. Everything rolls back.
"""

import datetime
import os

import frappe
from frappe.utils import add_months, getdate

RES = []

TODAY = datetime.datetime(2031, 10, 20, 10, 0, 0)


def check(label, fn):
	try:
		fn()
		RES.append(("PASS", label, ""))
	except AssertionError as e:
		RES.append(("FAIL", label, str(e)))
	except Exception as e:
		RES.append(("ERROR", label, f"{type(e).__name__}: {e}"))


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


def run():
	RES.clear()
	frappe.set_user("Administrator")
	real_commit = frappe.db.commit
	frappe.db.commit = lambda *a, **k: None
	import alpinos.people_events as people_events

	real_now = people_events.now_datetime
	try:
		_run_21(people_events)
		_run_22()
	finally:
		people_events.now_datetime = real_now
		frappe.db.commit = real_commit
		frappe.db.rollback()
		frappe.set_user("Administrator")

	width = max(len(r[1]) for r in RES)
	for status, label, detail in RES:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in RES if r[0] == 'PASS')}/{len(RES)} passed")
	return RES


def _app_file(*parts):
	return os.path.join(os.path.dirname(os.path.abspath(__file__)), *parts)


def _set(employee, **values):
	frappe.db.set_value("Employee", employee, values, update_modified=False)


def _run_21(people_events):
	people_events.now_datetime = lambda: TODAY
	active = frappe.get_all(
		"Employee", filters={"status": "Active"}, pluck="name", order_by="name asc", limit=20
	)
	_assert(len(active) >= 18, f"need 18 active employees, found {len(active)}")
	a, b, c, d, e, f, g = active[:7]
	many = active[7:19]

	_set(a, date_of_birth="1990-10-03")  # earlier this month: the old 30 days dropped it
	_set(b, date_of_birth="1990-11-05")  # next month: the old 30 days showed it
	_set(c, date_of_joining="2028-10-25")  # third anniversary this month
	_set(d, date_of_joining="2031-10-02")  # joined this month: no anniversary yet
	if frappe.get_meta("Employee").has_field("probation_end_date"):
		_set(e, probation_end_date="2031-10-01")
		_set(f, probation_end_date="2031-11-02")
	if frappe.get_meta("Employee").has_field("custom_internship_duration"):
		_set(g, date_of_joining="2031-07-15", custom_internship_duration=3)  # ends 15-10-2031
	for emp in many:
		_set(emp, date_of_birth="1995-10-28")

	names = {emp: frappe.db.get_value("Employee", emp, "employee_name") for emp in active}
	people = people_events.get_upcoming_birthdays_and_anniversaries()
	life = people_events.get_upcoming_employee_lifecycle()

	def listed(rows, emp, on=None):
		return any(r["employee_name"] == names[emp] and (on is None or r["date"] == on) for r in rows)

	check("a birthday earlier this month is listed",
		lambda: _assert(listed(people["birthdays"], a, "2031-10-03"), "03-10 missing"))
	check("a birthday next month is not",
		lambda: _assert(not listed(people["birthdays"], b), "05-11 listed"))
	check("every birthday and anniversary falls in the current month",
		lambda: _assert(
			all(r["date"].startswith("2031-10") for r in people["birthdays"] + people["anniversaries"]),
			[r["date"] for r in people["birthdays"] + people["anniversaries"] if not r["date"].startswith("2031-10")],
		))
	check("the month is not cut at ten rows",
		lambda: _assert(len(people["birthdays"]) >= 13, f"{len(people['birthdays'])} birthdays"))
	check("an anniversary this month is listed with its years",
		lambda: _assert(
			any(r["employee_name"] == names[c] and r["years"] == 3 for r in people["anniversaries"]),
			"third anniversary missing",
		))
	check("joining this month is not an anniversary",
		lambda: _assert(not listed(people["anniversaries"], d), "listed"))
	check("the increment follows the same anniversary",
		lambda: _assert(listed(life["increment"], c, "25/10/2031") and not listed(life["increment"], d), life["increment"]))
	if frappe.get_meta("Employee").has_field("probation_end_date"):
		check("probation ending this month is listed, next month's is not",
			lambda: _assert(listed(life["probation"], e, "01/10/2031") and not listed(life["probation"], f), life["probation"]))
	if frappe.get_meta("Employee").has_field("custom_internship_duration"):
		check("an internship ending this month is listed",
			lambda: _assert(listed(life["internship"], g, "15/10/2031"), life["internship"]))
	check("every lifecycle date falls in the current month",
		lambda: _assert(
			all(r["date"].endswith("/10/2031") for k in ("probation", "internship", "increment") for r in life[k]),
			"a row outside October",
		))

	# "Refresh on the 1st": the window is worked out on every call, so the first of the
	# next month already reads November.
	people_events.now_datetime = lambda: datetime.datetime(2031, 11, 1, 0, 5, 0)
	november = people_events.get_upcoming_birthdays_and_anniversaries()
	check("on the 1st the lists move to the new month",
		lambda: _assert(listed(november["birthdays"], b, "2031-11-05") and not listed(november["birthdays"], a), "still October"))
	people_events.now_datetime = lambda: TODAY

	check("the widgets say 'This month', not 'Next 30 days'",
		lambda: _assert(
			all("This month" in _read(p) and "Next 30 days" not in _read(p) for p in (
				("patches", "attendance_calendar.html"),
				("patches", "create_attendance_widget.py"),
				("patches", "create_hr_lifecycle_widget.py"),
			)),
			"a widget still says Next 30 days",
		))


def _read(parts):
	with open(_app_file(*parts), encoding="utf-8") as fh:
		return fh.read()


def _run_22():
	from alpinos.attendance_widget import _full_day_minutes, get_monthly_attendance

	shift = frappe.get_all("Shift Type", pluck="name", order_by="name asc", limit=1)
	_assert(shift, "no Shift Type on this site")
	shift = shift[0]
	# HO's own numbers on 27-10-2026.
	frappe.db.set_value("Shift Type", shift, {
		"working_hours_threshold_for_half_day": 8.25,
		"working_hours_threshold_for_absent": 4.0,
		"saturday_working_hours_threshold": 3.75,
		"saturday_working_hours_threshold_for_half_day": 0,
		"saturday_working_hours_threshold_for_absent": 3.75,
	}, update_modified=False)

	saturday, weekday = getdate("2026-10-17"), getdate("2026-10-16")
	check("a Saturday's full day is the shift's Saturday threshold",
		lambda: _assert(_full_day_minutes(shift, saturday, {}) == 225, _full_day_minutes(shift, saturday, {})))
	check("a weekday's full day is the shift's half-day threshold",
		lambda: _assert(_full_day_minutes(shift, weekday, {}) == 495, _full_day_minutes(shift, weekday, {})))
	check("a day with no shift has no full-day line, so the calendar keeps 8h/4h",
		lambda: _assert(_full_day_minutes(None, saturday, {}) is None))

	frappe.db.set_value("Shift Type", shift, {
		"working_hours_threshold_for_half_day": 0,
		"working_hours_threshold_for_absent": 0,
		"saturday_working_hours_threshold": 0,
		"saturday_working_hours_threshold_for_half_day": 0,
		"saturday_working_hours_threshold_for_absent": 0,
	}, update_modified=False)
	check("a shift with no thresholds also keeps 8h/4h (not 97% of its span)",
		lambda: _assert(_full_day_minutes(shift, weekday, {}) is None))
	frappe.db.set_value("Shift Type", shift, {
		"working_hours_threshold_for_half_day": 8.25,
		"working_hours_threshold_for_absent": 4.0,
		"saturday_working_hours_threshold": 3.75,
		"saturday_working_hours_threshold_for_absent": 3.75,
	}, update_modified=False)

	# End to end: Reena's Saturday -- Present, 10:08 to 14:07 -- on a day with nothing real.
	emp = frappe.db.sql(
		"""
		SELECT name, user_id, company, employee_name, date_of_joining FROM tabEmployee
		WHERE status = 'Active' AND IFNULL(user_id, '') != '' AND date_of_joining >= '2024-01-01'
		ORDER BY date_of_joining DESC LIMIT 1
		""",
		as_dict=True,
	)
	_assert(emp, "no active employee with a user who joined after 2024")
	emp = emp[0]
	month_start = getdate(add_months(getdate(emp.date_of_joining).replace(day=1), -2))
	sat = month_start
	while sat.weekday() != 5:
		sat = frappe.utils.add_days(sat, 1)
	sat = getdate(sat)
	_assert(
		not frappe.db.exists("Attendance", {"employee": emp.name, "attendance_date": sat}),
		f"{emp.name} already has an Attendance on {sat}",
	)
	att = frappe.get_doc({
		"doctype": "Attendance",
		"name": "HRMS22-TEST-SAT",
		"employee": emp.name,
		"employee_name": emp.employee_name,
		"company": emp.company,
		"attendance_date": sat,
		"status": "Present",
		"shift": shift,
		"in_time": f"{sat} 10:08:00",
		"out_time": f"{sat} 14:07:27",
		"working_hours": 3.99,
		"docstatus": 1,
	})
	att.db_insert()

	frappe.set_user(emp.user_id)
	try:
		day = (get_monthly_attendance(sat.year, sat.month).get("days") or {}).get(str(sat)) or {}
	finally:
		frappe.set_user("Administrator")
	check("the calendar sends the Saturday's full day from the Attendance's shift",
		lambda: _assert(day.get("required_minutes") == 225, day))
	check("3h59m on that Saturday is not short (the 4h rule called it short)",
		lambda: _assert(
			day.get("worked_minutes") == 239 and day["worked_minutes"] + 1 >= day["required_minutes"]
			and day["worked_minutes"] < 240,
			day,
		))

	script = _read(("patches", "attendance_calendar.js"))
	check("the calendar script reads required_minutes for the colour and the Early tag",
		lambda: _assert(
			"function isShortHours" in script
			and script.count("isShortHours(item, dateKey)") >= 3
			and "fallsShort(duration, item.required_minutes)" in script,
			"wiring missing",
		))
