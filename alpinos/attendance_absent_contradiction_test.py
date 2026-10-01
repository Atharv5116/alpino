"""HRMS: the healer repairs a day marked Absent that its own punches contradict.

Run:  bench --site alpinos.test execute alpinos.attendance_absent_contradiction_test.run

On prod, 35 days in 2026 are marked Absent while carrying both punches and real hours --
Lakshay Singh Rajpurohit 9.82 on 25 Sep, Jeet Patel 9.64 on 21 Apr, Mohitkumar Pandhi 9.00
on six days in May, and a cluster of 8.50 hour days on 12 Mar whose punches came from the
backfill and carry Skip Auto Attendance.

The healer could always repair such a day -- it recomputes from the punches and clears
stray skip flags -- but its selector only looked for an out-time sitting behind the day's
last punch, so it never picked these up. Fixtures are rolled back at the end.
"""

import frappe
from frappe.utils import cint

RES = []


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


def _insert(doctype, **values):
	doc = frappe.get_doc(dict(doctype=doctype, **values))
	doc.flags.ignore_mandatory = True
	doc.flags.ignore_validate = True
	doc.db_insert()
	return doc.name


def run():
	RES.clear()
	frappe.set_user("Administrator")
	real_commit = frappe.db.commit
	frappe.db.commit = lambda *a, **k: None
	try:
		_run()
	finally:
		frappe.db.commit = real_commit
		frappe.db.rollback()
		frappe.set_user("Administrator")

	width = max(len(r[1]) for r in RES)
	for status, label, detail in RES:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in RES if r[0] == 'PASS')}/{len(RES)} passed")
	return RES


def _run():
	from alpinos.attendance_healer import _contradictory_absent_names, backfill

	tag = "ABC" + frappe.generate_hash(length=5).upper()
	company = frappe.defaults.get_global_default("company")
	day, short_day = "2026-05-07", "2026-05-08"

	emp = _insert("Employee", name=f"{tag}-EMP", employee_name=f"{tag} Full Day", status="Active",
		company=company, date_of_joining="2026-01-01")
	# HO as prod has it: 8.5 hour span, absent below 4, half below 8.25.
	shift = _insert("Shift Type", name=f"{tag}-HO", start_time="10:00:00", end_time="18:30:00",
		working_hours_threshold_for_half_day=8.25, working_hours_threshold_for_absent=4)

	def _day(date, in_t, out_t, hours, skip=0):
		_insert("Employee Checkin", name=f"{tag}-IN-{date}", employee=emp, log_type="IN",
			time=f"{date} {in_t}", shift=shift, skip_auto_attendance=skip)
		_insert("Employee Checkin", name=f"{tag}-OUT-{date}", employee=emp, log_type="OUT",
			time=f"{date} {out_t}", shift=shift, skip_auto_attendance=skip)
		return _insert("Attendance", name=f"{tag}-ATT-{date}", employee=emp, attendance_date=date,
			docstatus=1, status="Absent", shift=shift, company=company,
			in_time=f"{date} {in_t}", out_time=f"{date} {out_t}", working_hours=hours)

	# A nine-hour day marked Absent, its punches flagged like the 12 Mar cluster.
	full = _day(day, "09:30:00", "18:30:00", 9.0, skip=1)
	# A genuinely short day: 2 hours, below the absent threshold, correctly Absent.
	short = _day(short_day, "10:00:00", "12:00:00", 2.0)

	def _the_full_day_is_selected():
		names = {r.name for r in _contradictory_absent_names(from_date="2026-05-01", to_date="2026-05-31")}
		_assert(full in names, f"the nine-hour Absent day was not picked up: {names}")

	check("HRMS: a day marked Absent with hours above the shift's bar is picked up",
		_the_full_day_is_selected)

	def _a_genuinely_short_day_is_left_alone():
		names = {r.name for r in _contradictory_absent_names(from_date="2026-05-01", to_date="2026-05-31")}
		_assert(short not in names,
			"a two-hour day, correctly Absent under the shift's threshold, was picked up")

	check("HRMS: a genuinely short day stays Absent and is not touched",
		_a_genuinely_short_day_is_left_alone)

	def _the_dry_run_changes_nothing():
		out = backfill(apply=0, from_date="2026-05-01", to_date="2026-05-31")
		_assert(out["mode"] == "DRY-RUN", out["mode"])
		_assert(frappe.db.get_value("Attendance", full, "status") == "Absent",
			"the dry run wrote the status")

	check("HRMS: the dry run reports without writing", _the_dry_run_changes_nothing)

	def _applying_repairs_the_day():
		backfill(apply=1, from_date="2026-05-01", to_date="2026-05-31")
		status = frappe.db.get_value("Attendance", full, "status")
		_assert(status != "Absent", f"the nine-hour day is still {status}")
		_assert(frappe.db.get_value("Attendance", short, "status") == "Absent",
			"the genuinely short day was changed")
		# and the stray flags are cleared, so the day marks normally from now on
		flags = frappe.get_all("Employee Checkin",
			filters={"employee": emp, "time": ["between", [f"{day} 00:00:00", f"{day} 23:59:59"]]},
			pluck="skip_auto_attendance")
		_assert(not any(cint(f) for f in flags), f"punches are still flagged skipped: {flags}")

	check("HRMS: applying re-marks the day from its punches and clears the stray flags",
		_applying_repairs_the_day)
