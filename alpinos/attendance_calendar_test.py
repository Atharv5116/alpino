"""The calendar must show a day's OUT punch whatever state its Attendance is in.

The out-time used to be read only from a submitted Attendance record, so a dash
appeared whenever the Attendance was missing, unsubmitted, or carried a null
out_time -- while the OUT punch sat in Employee Checkin the whole time.

Run:  bench --site alpinos.test execute alpinos.attendance_calendar_test.run
"""
import frappe
from frappe.utils import getdate

from alpinos.attendance_widget import get_monthly_attendance

DATE = "2026-04-15"  # a quiet past date, so nothing real is disturbed
R = []


def _check(label, fn):
	try:
		fn()
		R.append(("PASS", label, ""))
	except AssertionError as e:
		R.append(("FAIL", label, str(e)))
	except Exception as e:
		R.append(("ERROR", label, f"{type(e).__name__}: {e}"))


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


def _employee_and_user():
	"""An active employee that has a User, so get_monthly_attendance resolves it."""
	row = frappe.db.sql(
		"""
		SELECT name, user_id FROM tabEmployee
		WHERE status = 'Active' AND IFNULL(user_id, '') != ''
		ORDER BY creation ASC LIMIT 1
		""",
		as_dict=True,
	)
	assert row, "no active employee with a user on this site"
	return row[0].name, row[0].user_id


def _day(user):
	d = getdate(DATE)
	frappe.set_user(user)
	try:
		return (get_monthly_attendance(d.year, d.month).get("days") or {}).get(DATE) or {}
	finally:
		frappe.set_user("Administrator")


def _punch(employee, log_type, stamp):
	doc = frappe.get_doc({
		"doctype": "Employee Checkin", "employee": employee,
		"log_type": log_type, "time": stamp,
	})
	doc.flags.skip_attendance_heal = True   # the healer is not what is under test
	doc.insert(ignore_permissions=True)
	return doc.name


def run():
	R.clear()
	frappe.set_user("Administrator")
	employee, user = _employee_and_user()
	made = []
	att = None
	try:
		made.append(_punch(employee, "IN", f"{DATE} 10:26:00"))
		made.append(_punch(employee, "OUT", f"{DATE} 18:40:00"))
		frappe.db.commit()

		# 1. No Attendance at all -- the old code showed a dash here.
		day = _day(user)
		_check(
			"the OUT punch shows even with no Attendance record",
			lambda: _assert(
				day.get("check_in") == "10:26:00" and day.get("check_out") == "18:40:00",
				f"{day.get('check_in')} -> {day.get('check_out')}",
			),
		)
		_check(
			"worked minutes are computed from the punches",
			lambda: _assert(day.get("worked_minutes") == 494, day.get("worked_minutes")),
		)

		# 2. A DRAFT Attendance is invisible to _get_attendance_times_map (docstatus 1).
		att = frappe.get_doc({
			"doctype": "Attendance", "employee": employee,
			"attendance_date": DATE, "status": "Half Day",
			"company": frappe.db.get_value("Employee", employee, "company"),
		})
		att.flags.ignore_validate = True
		att.insert(ignore_permissions=True)
		frappe.db.commit()
		d2 = _day(user)
		_check(
			"an unsubmitted Attendance does not hide the OUT punch",
			lambda: _assert(d2.get("check_out") == "18:40:00", d2.get("check_out")),
		)

		# 3. Submitted, but out_time never filled -- the punch still wins.
		frappe.db.set_value("Attendance", att.name, {"docstatus": 1, "in_time": f"{DATE} 10:26:00",
			"out_time": None}, update_modified=False)
		frappe.db.commit()
		frappe.clear_cache()
		d3 = _day(user)
		_check(
			"a submitted Attendance with a null out_time does not hide the OUT punch",
			lambda: _assert(d3.get("check_out") == "18:40:00", d3.get("check_out")),
		)
		_check(
			"both times come from the same source, so the pair cannot disagree",
			lambda: _assert(
				d3.get("check_in") == "10:26:00" and d3.get("check_out") == "18:40:00",
				f"{d3.get('check_in')} -> {d3.get('check_out')}",
			),
		)
	finally:
		if att:
			frappe.db.sql("DELETE FROM tabAttendance WHERE name = %s", att.name)
		for n in made:
			frappe.db.sql("DELETE FROM `tabEmployee Checkin` WHERE name = %s", n)
		frappe.db.commit()
		frappe.set_user("Administrator")

	width = max(len(r[1]) for r in R)
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	passed = sum(1 for r in R if r[0] == "PASS")
	print(f"{passed}/{len(R)} passed")
	return R
