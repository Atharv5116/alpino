"""HRMS: an approved Attendance Request leaves the day with the status its hours earn.

Run:  bench --site <test site> execute alpinos.attendance_request_status_test.run

Reported (Notion #25 / #26): Surendra Singh 24-10-2026 and Smit Shah 28-10-2026, requests
approved, Attendance still Half Day.

- 24-10-2026 is a Saturday. The approval worked the status out with the shift's weekday
  thresholds (Present from 8.25 h) and wrote it straight to the submitted Attendance, past
  the Saturday rule that auto-marking and the healer apply (Present from 3.75 h).
- On a one-sided edit the request's side is taken and the other side kept as the day had
  it; the hours were recomputed from those times but the status stayed the one worked out
  on the punches alone.

Fixtures are rolled back.
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
	from alpinos.overrides.attendance_request_override import CustomAttendanceRequest

	tag = "ARS" + frappe.generate_hash(length=5).upper()
	company = frappe.defaults.get_global_default("company")
	# The HO shifts: Present from 8.25 h on a weekday, from 3.75 h on a Saturday.
	shift = _insert("Shift Type", name=f"{tag}-HO", start_time="09:30:00", end_time="18:00:00",
		working_hours_threshold_for_half_day=8.25, working_hours_threshold_for_absent=4,
		saturday_working_hours_threshold=3.75, saturday_working_hours_threshold_for_absent=3.75)

	def employee(n):
		return _insert("Employee", name=f"{tag}-EMP{n}", employee_name=f"{tag} {n}", status="Active",
			company=company, date_of_joining="2026-01-01")

	def day_with(emp, day, punches, status, in_time, out_time, hours):
		for i, (log_type, t) in enumerate(punches):
			_insert("Employee Checkin", name=f"{emp}-{day}-CK{i}", employee=emp, log_type=log_type,
				time=f"{day} {t}", shift=shift)
		return _insert("Attendance", name=f"{emp}-{day}-ATT", employee=emp, attendance_date=day, docstatus=1,
			status=status, shift=shift, company=company, in_time=in_time, out_time=out_time,
			working_hours=hours, half_day_status="Absent" if status == "Half Day" else None)

	def approve(emp, day, edit_in=None, edit_out=None):
		req = frappe.new_doc("Attendance Request")
		req.employee = emp
		req.from_date = req.to_date = day
		req.reason = "Office"
		req.shift = shift
		req.company = company
		row = {"attendance_date": day}
		if edit_in:
			row.update({"edit_check_in": 1, "check_in": edit_in})
		if edit_out:
			row.update({"edit_check_out": 1, "check_out": edit_out})
		req.append("custom_attendance_details", row)
		req.__class__ = CustomAttendanceRequest
		# what on_submit does, in its order
		req._apply_requested_checkins()
		req.create_or_update_attendance(day)
		req._refresh_attendance_times()

	def status_of(att):
		return frappe.db.get_value("Attendance", att, ["status", "working_hours", "half_day_status"], as_dict=True)

	# 1. Saturday 24-10-2026: checked in, missed the check-out; the request adds 14:30.
	sat = "2026-10-24"
	e1 = employee(1)
	a1 = day_with(e1, sat, [("IN", "09:30:00")], "Absent", f"{sat} 09:30:00", None, 0)
	approve(e1, sat, edit_out="14:30:00")
	check("Saturday: an approved 5-hour day is Present (Saturday rule, not the weekday 8.25 h)",
		lambda: _assert(status_of(a1).status == "Present", status_of(a1)))
	check("...and keeps no half-day status", lambda: _assert(not status_of(a1).half_day_status, status_of(a1)))

	e2 = employee(2)
	a2 = day_with(e2, sat, [("IN", "09:30:00")], "Absent", f"{sat} 09:30:00", None, 0)
	approve(e2, sat, edit_out="12:30:00")
	check("Saturday: an approved 3-hour day is still Absent (below 3.75 h)",
		lambda: _assert(status_of(a2).status == "Absent", status_of(a2)))

	# 2. Wednesday 28-10-2026: the day's check-out was already corrected to 18:45 (no punch
	#    behind it); the request edits only the check-in. The day is 09:55 - 18:45.
	wed = "2026-10-28"
	e3 = employee(3)
	a3 = day_with(e3, wed, [("IN", "10:00:00"), ("OUT", "14:00:00")], "Half Day",
		f"{wed} 10:00:00", f"{wed} 18:45:00", 8.75)
	approve(e3, wed, edit_in="09:55:00")
	check("weekday one-sided edit: status follows the day's hours (8.83 h -> Present)",
		lambda: _assert(status_of(a3).status == "Present" and flt(status_of(a3).working_hours) > 8.25, status_of(a3)))

	# 3. The rules themselves are unchanged.
	e4 = employee(4)
	a4 = day_with(e4, wed, [("IN", "10:30:00")], "Absent", f"{wed} 10:30:00", None, 0)
	approve(e4, wed, edit_out="18:00:00")
	check("weekday: an approved 7.5-hour day is still Half Day (below 8.25 h)",
		lambda: _assert(status_of(a4).status == "Half Day", status_of(a4)))

	e5 = employee(5)
	a5 = day_with(e5, wed, [("IN", "09:30:00")], "Absent", f"{wed} 09:30:00", None, 0)
	approve(e5, wed, edit_out="18:00:00")
	check("weekday: an approved 8.5-hour day is Present", lambda: _assert(status_of(a5).status == "Present", status_of(a5)))
