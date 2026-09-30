"""HRMS: the Absent / Shortage dates, and punches shown on a worked holiday.

Run:  bench --site alpinos.test execute alpinos.attendance_summary_details_test.run

Three reports from the HRMS thread:
  * "need details for Absent count & WHS count"
  * "shows absent count 3 and on dashboard showing only 1 absent"
  * "if an employee works on a Holiday, their In Time and Out Time should be shown"

The first two are one thing: a day marked Absent WITH punches is a short-hours day and
counts under the shortage, not as an absence, and nothing said so. The fixture is a month
built the way the disputed one reads -- three days marked Absent, only one of them a real
absence -- so the counts and the new dates can be read side by side.
"""

import frappe
from frappe.utils import flt

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
	from alpinos.alpinos_development.report.attendance_summary.attendance_summary import (
		_holiday_cell,
		get_attendance_map,
	)
	from alpinos.alpinos_development.report.attendance_summary.attendance_summary_helpers import (
		calculate_attendance_stats,
	)

	tag = "ASD" + frappe.generate_hash(length=5).upper()
	company = frappe.defaults.get_global_default("company")
	start, end = "2026-09-01", "2026-09-30"

	emp = _insert("Employee", name=f"{tag}-EMP", employee_name=f"{tag} Disputed",
		status="Active", company=company, date_of_joining="2026-01-01")
	shift = _insert("Shift Type", name=f"{tag}-SHIFT", start_time="09:00:00", end_time="18:00:00")

	def _att(day, status, in_t=None, out_t=None, hours=0):
		return _insert(
			"Attendance", name=f"{tag}-ATT-{day}", employee=emp, attendance_date=f"2026-09-{day}",
			docstatus=1, status=status, shift=shift,
			in_time=f"2026-09-{day} {in_t}" if in_t else None,
			out_time=f"2026-09-{day} {out_t}" if out_t else None,
			working_hours=hours,
		)

	# Three days marked Absent: the 7th a real absence, the 8th and 9th worked but short.
	_att("07", "Absent")
	_att("08", "Absent", "10:00:00", "13:00:00", 3.0)
	_att("09", "Absent", "10:00:00", "12:30:00", 2.5)
	# A worked day with a small shortage, to show the shortage list is not only Absent days.
	_att("10", "Present", "09:05:00", "16:00:00", 6.92)

	att_map = get_attendance_map(emp, start, end)
	stats = calculate_attendance_stats(att_map, {}, {}, {}, start, end, emp)

	def _the_absent_count_holds_only_real_absences():
		_assert(stats.absent_days == 1,
			f"absent days {stats.absent_days}: only the 7th is an absence, the others were worked")
		_assert(stats.absent_dates == ["7"], f"absent dates {stats.absent_dates}, expected ['7']")

	check("HRMS: Absent counts only the day with no punches, and names it",
		_the_absent_count_holds_only_real_absences)

	def _the_worked_short_days_are_in_the_shortage_list():
		_assert("8" in stats.whs_dates and "9" in stats.whs_dates,
			f"the worked-short days are missing from the shortage dates: {stats.whs_dates}")
		_assert(flt(stats.working_hours_shortage) >= 2.0,
			f"shortage {stats.working_hours_shortage}, expected at least the two full days")

	check("HRMS: a day marked Absent but worked short is listed under the shortage, not Absent",
		_the_worked_short_days_are_in_the_shortage_list)

	def _a_half_day_absence_is_named_as_half():
		"""Faiz Raja read Absent 1.5 with one date: the half day was counted, never listed."""
		_att("11", "Half Day")          # half day, no punch -> 0.5 Absent
		att_map2 = get_attendance_map(emp, start, end)
		s2 = calculate_attendance_stats(att_map2, {}, {}, {}, start, end, emp)
		_assert(flt(s2.absent_days) == 1.5, f"absent days {s2.absent_days}, expected 1.5")
		_assert("11 (half)" in s2.absent_dates,
			f"the half-day absence is not in the dates: {s2.absent_dates}")
		_assert(len(s2.absent_dates) == 2, f"dates {s2.absent_dates} do not account for 1.5")

	check("HRMS: a half-day absence is listed as (half), so the dates account for the count",
		_a_half_day_absence_is_named_as_half)

	def _the_dispute_is_explained_by_the_two_lists():
		"""3 marked Absent, 1 real: the dates say which is which."""
		marked_absent = [d for d in ("7", "8", "9")]
		_assert(len(marked_absent) == 3, "fixture")
		_assert(stats.absent_days == 1 and len(stats.absent_dates) == 1,
			"the report should show 1 absence, as the dashboard does")
		_assert(set(stats.whs_dates) >= {"8", "9"},
			f"the other two days must be accounted for in the shortage: {stats.whs_dates}")

	check("HRMS: report and dashboard agree once the dates are shown (3 marked, 1 absence)",
		_the_dispute_is_explained_by_the_two_lists)

	def _a_worked_holiday_shows_its_punches():
		worked = {"in_time": "2026-09-14 09:10:00", "out_time": "2026-09-14 17:40:00",
		          "working_hours": 8.5, "shift": shift}
		cell = _holiday_cell("HOLIDAY - Ganesh Chaturthi", worked)
		_assert(cell.startswith("HOLIDAY - Ganesh Chaturthi"), f"the holiday name was lost: {cell[:40]!r}")
		_assert("09:10" in cell and "17:40" in cell, f"the punches are not shown: {cell!r}")
		_assert("08 H : 30 M" in cell, f"the hours worked are not shown: {cell!r}")

	check("HRMS: a holiday somebody worked shows In, Out and the hours",
		_a_worked_holiday_shows_its_punches)

	def _an_ordinary_holiday_is_unchanged():
		_assert(_holiday_cell("WEEKEND", None) == "WEEKEND", "a plain weekend gained something")
		_assert(_holiday_cell("HOLIDAY - Diwali", {"in_time": None, "out_time": None}) ==
			"HOLIDAY - Diwali", "a holiday with no punches gained something")

	check("HRMS: a holiday nobody worked reads exactly as before",
		_an_ordinary_holiday_is_unchanged)
