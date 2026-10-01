"""HRMS: a one-sided edit, and a day measured first log to last log.

Run:  bench --site alpinos.test execute alpinos.attendance_one_sided_edit_test.run

Harshil Gajjar, 29-09-2026, seven punches:
    IN 10:00:00 (set by the approved request), OUT 11:49:08, IN 15:09:03, OUT 15:33:55,
    IN 15:39:43, OUT 17:45:21, IN 19:09:50
His request ticked Edit Check-in only, yet the Attendance came out 10:00 to 17:45, 7.76
hours: the check-out moved as well, and it stopped at the last punch TYPED out rather than
his last punch of the day.

Two rules are checked here: the unedited side is left alone, and the day runs first log to
last log whatever the types -- which is how the scheduler and the healer already measure it.
Fixtures are rolled back.
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
	from alpinos.overrides.attendance_request_override import CustomAttendanceRequest

	tag = "OSE" + frappe.generate_hash(length=5).upper()
	company = frappe.defaults.get_global_default("company")
	day = "2026-09-29"

	emp = _insert("Employee", name=f"{tag}-EMP", employee_name=f"{tag} Many Punches",
		status="Active", company=company, date_of_joining="2026-01-01")
	shift = _insert("Shift Type", name=f"{tag}-HO", start_time="10:00:00", end_time="18:30:00",
		working_hours_threshold_for_half_day=8.25, working_hours_threshold_for_absent=4)

	# His day, exactly: the last punch is typed IN.
	punches = [
		("IN", "10:00:00"), ("OUT", "11:49:08"), ("IN", "15:09:03"), ("OUT", "15:33:55"),
		("IN", "15:39:43"), ("OUT", "17:45:21"), ("IN", "19:09:50"),
	]
	for i, (lt, t) in enumerate(punches):
		_insert("Employee Checkin", name=f"{tag}-CK{i}", employee=emp, log_type=lt,
			time=f"{day} {t}", shift=shift)

	att = _insert("Attendance", name=f"{tag}-ATT", employee=emp, attendance_date=day, docstatus=1,
		status="Present", shift=shift, company=company,
		in_time=f"{day} 10:12:00", out_time=f"{day} 19:09:50", working_hours=8.96)

	def _request(edit_in=False, edit_out=False, in_t=None, out_t=None):
		doc = frappe.new_doc("Attendance Request")
		doc.employee = emp
		doc.from_date = doc.to_date = day
		doc.reason = "Office"
		doc.shift = shift
		doc.company = company
		row = {"attendance_date": day}
		if edit_in:
			row.update({"edit_check_in": 1, "check_in": in_t})
		if edit_out:
			row.update({"edit_check_out": 1, "check_out": out_t})
		doc.append("custom_attendance_details", row)
		doc.__class__ = CustomAttendanceRequest
		return doc

	def _editing_the_check_in_leaves_the_check_out_alone():
		req = _request(edit_in=True, in_t="10:00:00")
		req.create_or_update_attendance(day)
		req._refresh_attendance_times()
		row = frappe.db.get_value("Attendance", att, ["in_time", "out_time", "working_hours"], as_dict=True)
		_assert(str(row.in_time).endswith("10:00:00"), f"the check-in was not applied: {row.in_time}")
		_assert(str(row.out_time).endswith("19:09:50"),
			f"the check-out moved to {row.out_time}; the request never asked about it")

	check("HRMS: editing only the check-in leaves the check-out as the day had it",
		_editing_the_check_in_leaves_the_check_out_alone)

	def _the_day_runs_to_the_last_log_whatever_its_type():
		"""With no stored out to preserve, the day must still reach his 19:09 punch."""
		frappe.db.set_value("Attendance", att, {"in_time": None, "out_time": None,
			"working_hours": 0}, update_modified=False)
		req = _request(edit_in=True, in_t="10:00:00")
		req.create_or_update_attendance(day)
		req._refresh_attendance_times()
		row = frappe.db.get_value("Attendance", att, ["in_time", "out_time", "working_hours"], as_dict=True)
		_assert(str(row.out_time).endswith("19:09:50"),
			f"the day stopped at {row.out_time}, not his last punch")
		_assert(flt(row.working_hours, 2) > 9.0,
			f"hours {row.working_hours}: the day should run 10:00 to 19:09")

	check("HRMS: the day runs to the last log even when that log is typed IN",
		_the_day_runs_to_the_last_log_whatever_its_type)

	def _editing_the_check_out_still_applies():
		req = _request(edit_out=True, out_t="18:30:00")
		req.create_or_update_attendance(day)
		req._refresh_attendance_times()
		row = frappe.db.get_value("Attendance", att, ["out_time"], as_dict=True)
		_assert(str(row.out_time).endswith("18:30:00"),
			f"the requested check-out was not applied: {row.out_time}")

	check("HRMS: editing the check-out still changes the check-out",
		_editing_the_check_out_still_applies)

	def _a_stray_skipped_punch_does_not_become_the_check_out():
		"""A punch the healer flagged Skip Auto Attendance is not the employee's exit.

		The marking leaves such a punch out, but the times sync that runs after it does not
		filter the flag, so it used to drag the check-out onto a 23:50 backfill punch on a
		day the request only touched the check-in.
		"""
		frappe.db.set_value("Attendance", att, {"in_time": f"{day} 10:00:00",
			"out_time": f"{day} 19:09:50", "working_hours": 9.16}, update_modified=False)
		_insert("Employee Checkin", name=f"{tag}-STRAY", employee=emp, log_type="OUT",
			time=f"{day} 23:50:00", shift=shift, skip_auto_attendance=1)
		req = _request(edit_in=True, in_t="10:00:00")
		req.create_or_update_attendance(day)
		req._refresh_attendance_times()
		row = frappe.db.get_value("Attendance", att, ["out_time"], as_dict=True)
		_assert(str(row.out_time).endswith("19:09:50"),
			f"the check-out was dragged to {row.out_time} by a skipped backfill punch")

	check("HRMS: a skipped backfill punch does not become the check-out of an edited day",
		_a_stray_skipped_punch_does_not_become_the_check_out)
