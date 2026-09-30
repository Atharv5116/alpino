"""HRMS: the Attendance Summary's OD count, after an On Duty request is approved.

Run:  bench --site alpinos.test execute alpinos.attendance_od_count_test.run

Reported by Rahul: "OD count not showing after approve the ON Duty (reason) request".
The report counted OD only where the Attendance status read "On Duty" -- a status HRMS
does not offer (Present, Absent, On Leave, Half Day, Work From Home), and one nothing in
the app ever wrote, since approving an On Duty request marks the day Present. So the count
and the OD tag could never fill.

Fixtures are written straight to the tables and rolled back at the end.
"""

import frappe
from frappe.utils import flt, getdate

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
		format_attendance_info,
		get_attendance_map,
	)
	from alpinos.alpinos_development.report.attendance_summary.attendance_summary_helpers import (
		calculate_attendance_stats,
	)

	tag = "ODC" + frappe.generate_hash(length=5).upper()
	company = frappe.defaults.get_global_default("company")
	day = "2026-09-15"          # a Tuesday, no holiday
	other_day = "2026-09-16"
	month_start, month_end = "2026-09-01", "2026-09-30"

	emp = _insert("Employee", name=f"{tag}-EMP", employee_name=f"{tag} Duty Person",
		status="Active", company=company, date_of_joining="2026-01-01")
	shift = _insert("Shift Type", name=f"{tag}-SHIFT", start_time="09:00:00", end_time="18:00:00")
	_insert("Late Entry Threshold", name=f"{tag}-T", parent=shift, parenttype="Shift Type",
		parentfield="custom_late_entry_thresholds", late_by=15, deduction=0.5, idx=1)

	# The request as the approval leaves it: reason On Duty, and the day marked PRESENT.
	req = _insert("Attendance Request", name=f"{tag}-AR", employee=emp, from_date=day, to_date=day,
		docstatus=1, workflow_state="Approved", reason="On Duty", shift=shift)
	_insert("Attendance", name=f"{tag}-ATT", employee=emp, attendance_date=day, docstatus=1,
		status="Present", shift=shift, attendance_request=req,
		in_time=f"{day} 11:30:00", out_time=f"{day} 18:05:00", working_hours=6.58)
	# An ordinary LATE day that still works its full hours, so a shortage in the totals can
	# only have come from the On Duty day, and the late check still has something to count.
	_insert("Attendance", name=f"{tag}-ATT2", employee=emp, attendance_date=other_day, docstatus=1,
		status="Present", shift=shift,
		in_time=f"{other_day} 09:40:00", out_time=f"{other_day} 18:45:00", working_hours=9.08)

	def _stats():
		att_map = get_attendance_map(emp, month_start, month_end)
		return att_map, calculate_attendance_stats(att_map, {}, {}, {}, month_start, month_end, emp)

	def _the_od_count_shows_the_approved_day():
		att_map, stats = _stats()
		_assert(att_map[day].get("is_on_duty") == 1,
			f"the day was not recognised as On Duty: {att_map[day].get('is_on_duty')}")
		_assert(stats.od == 1, f"OD count is {stats.od}, expected 1")

	check("HRMS OD: an approved On Duty day is counted in OD, though its status reads Present",
		_the_od_count_shows_the_approved_day)

	def _the_day_carries_the_od_tag():
		att_map, _ = _stats()
		cell = format_attendance_info(att_map[day])
		_assert(cell.splitlines()[0].strip() == "OD", f"the cell does not open with OD: {cell[:60]!r}")

	check("HRMS OD: the day's cell is tagged OD in the report", _the_day_carries_the_od_tag)

	def _an_od_day_is_a_full_day_without_a_shortage():
		_, stats = _stats()
		# 6.58 hours against a 9 hour shift would otherwise be a shortage tier.
		_assert(flt(stats.working_hours_shortage) == 0.0,
			f"an On Duty day was charged a shortage: {stats.working_hours_shortage}")
		_assert(stats.clock_in_days == 2, f"clock-in days {stats.clock_in_days}, expected 2")
		_assert(stats.absent_days == 0, f"absent days {stats.absent_days}")

	check("HRMS OD: the day is a full working day, with no hours shortage",
		_an_od_day_is_a_full_day_without_a_shortage)

	def _an_od_day_is_not_a_late_arrival():
		from alpinos.alpinos_development.report.attendance_summary.attendance_summary import (
			compute_late_deduction,
		)

		att_map, _ = _stats()
		counts = (compute_late_deduction(att_map) or {}).get("counts") or {}
		# The ordinary day is 40 minutes late and must still count; the 11:30 On Duty must not.
		_assert(counts, "no lateness at all was counted, so the check proves nothing")
		_assert(sum(counts.values()) == 1,
			f"{sum(counts.values())} late days counted; the On Duty day should be exempt")

	check("HRMS OD: an On Duty arrival is not a late entry, an ordinary one still is",
		_an_od_day_is_not_a_late_arrival)

	def _a_day_with_another_reason_is_not_od():
		other_req = _insert("Attendance Request", name=f"{tag}-AR2", employee=emp,
			from_date=other_day, to_date=other_day, docstatus=1, workflow_state="Approved",
			reason="Office", shift=shift)
		frappe.db.set_value("Attendance", f"{tag}-ATT2", "attendance_request", other_req,
			update_modified=False)
		att_map, stats = _stats()
		_assert(att_map[other_day].get("is_on_duty") == 0,
			"a request whose reason is Office was read as On Duty")
		_assert(stats.od == 1, f"OD count is {stats.od}, expected only the On Duty day")

	check("HRMS OD: a request with another reason does not count as OD",
		_a_day_with_another_reason_is_not_od)
