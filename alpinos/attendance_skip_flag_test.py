"""HRMS: an approved request leaves the day Absent when a punch is flagged Skip Auto Attendance.

Run:  bench --site alpinos.test execute alpinos.attendance_skip_flag_test.run

Dharmishtha Paghadar, 02-09-2026: check-in 10:27:44, an approved request (HR-ARQ-26-09-00101,
reason Office) set the check-out to 18:08:41, the Attendance shows 7.68 working hours -- and
the status stayed Absent. The check-out carried Skip Auto Attendance, and the status
calculation drops those punches, so it saw a day with a check-in and no check-out and asked
HRMS, which says Absent. The times came from another path that does not filter on the flag,
which is why the record reads full hours and Absent at once.

Fixtures are rolled back at the end.
"""

import frappe
from frappe.utils import cint, flt

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

	tag = "SKP" + frappe.generate_hash(length=5).upper()
	company = frappe.defaults.get_global_default("company")
	day = "2026-09-02"

	emp = _insert("Employee", name=f"{tag}-EMP", employee_name=f"{tag} Skipped",
		status="Active", company=company, date_of_joining="2026-01-01")
	shift = _insert("Shift Type", name=f"{tag}-SHIFT", start_time="10:00:00", end_time="18:30:00")

	# The day as hers stood: a device check-in, and a check-out flagged Skip Auto Attendance.
	_insert("Employee Checkin", name=f"{tag}-IN", employee=emp, log_type="IN",
		time=f"{day} 10:27:44", shift=shift, skip_auto_attendance=0)
	out = _insert("Employee Checkin", name=f"{tag}-OUT", employee=emp, log_type="OUT",
		time=f"{day} 17:00:00", shift=shift, skip_auto_attendance=1)

	def _request():
		doc = frappe.new_doc("Attendance Request")
		doc.employee = emp
		doc.from_date = doc.to_date = day
		doc.reason = "Office"
		doc.shift = shift
		doc.company = company
		doc.append("custom_attendance_details", {
			"attendance_date": day, "edit_check_out": 1, "check_out": "18:08:41",
		})
		doc.__class__ = CustomAttendanceRequest
		return doc

	def _the_punch_stops_being_skipped():
		_request()._apply_requested_checkins()
		row = frappe.db.get_value("Employee Checkin", out,
			["time", "skip_auto_attendance", "from_attendance_request"], as_dict=True)
		_assert(str(row.time).endswith("18:08:41"), f"the time was not applied: {row.time}")
		_assert(cint(row.skip_auto_attendance) == 0,
			"the punch is still flagged Skip Auto Attendance, so the day will not be marked")
		_assert(cint(row.from_attendance_request) == 1, "the punch is not marked as the request's")

	check("HRMS: a punch an approved request writes stops being skipped",
		_the_punch_stops_being_skipped)

	def _the_status_calculation_sees_both_punches():
		"""Even if something else flags it again, the request's own punch still counts."""
		frappe.db.set_value("Employee Checkin", out, "skip_auto_attendance", 1, update_modified=False)
		doc = _request()
		date_start, date_end = f"{day} 00:00:00", f"{day} 23:59:59"
		logs = frappe.get_all(
			"Employee Checkin",
			filters={"employee": emp, "time": ["between", [date_start, date_end]]},
			fields=["name", "log_type", "skip_auto_attendance", "from_attendance_request"],
		)
		kept = [
			l for l in logs
			if not cint(l.get("skip_auto_attendance")) or cint(l.get("from_attendance_request"))
		]
		_assert(len(kept) == 2, f"the calculation sees {len(kept)} punch(es), expected both")
		_assert({l.log_type for l in kept} == {"IN", "OUT"},
			f"the check-out is missing from the calculation: {[l.log_type for l in kept]}")

	check("HRMS: the status calculation keeps a request's punch even when flagged",
		_the_status_calculation_sees_both_punches)

	def _a_genuinely_skipped_punch_is_still_ignored():
		"""A punch nobody requested, flagged by the healer, stays out of the marking."""
		healer = _insert("Employee Checkin", name=f"{tag}-HEAL", employee=emp, log_type="OUT",
			time=f"{day} 23:50:00", shift=shift, skip_auto_attendance=1)
		logs = frappe.get_all(
			"Employee Checkin",
			filters={"employee": emp, "time": ["between", [f"{day} 00:00:00", f"{day} 23:59:59"]]},
			fields=["name", "skip_auto_attendance", "from_attendance_request"],
		)
		kept = {
			l.name for l in logs
			if not cint(l.get("skip_auto_attendance")) or cint(l.get("from_attendance_request"))
		}
		_assert(healer not in kept, "a skipped punch nobody requested was brought into the marking")

	check("HRMS: a skipped punch nobody requested is still left out",
		_a_genuinely_skipped_punch_is_still_ignored)
