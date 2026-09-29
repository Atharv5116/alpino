"""Changes(HP) HRMS #10 late penalty on half days, #11 dashboard leave / WFH sections,
#12 HR's requests do not spend the employee's limit, #13 an approval keeps real punches.

Run:  bench --site alpinos.test execute alpinos.hrms_10_to_13_test.run

Fixtures are written straight to the tables (H1013-<run>) inside one transaction that is
ROLLED BACK at the end, so the site keeps its own employees, punches and requests.
"""

import frappe
from frappe.utils import getdate, today

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
	tag = "H1013" + frappe.generate_hash(length=4).upper()
	day = getdate(today())

	# ---------------------------------------------------------------- HRMS #10
	from alpinos.alpinos_development.report.attendance_summary.attendance_summary import (
		compute_late_deduction,
	)

	shift = _insert("Shift Type", name=f"{tag}-SHIFT", start_time="09:00:00", end_time="18:00:00")
	# One tier: 15 minutes late or more. Four lates make a deduction, so the counts are what
	# these checks read -- a single late shows up as one flag in that tier.
	_insert(
		"Late Entry Threshold", name=f"{tag}-T1", parent=shift, parenttype="Shift Type",
		parentfield="custom_late_entry_thresholds", late_by=15, deduction=0.5, idx=1,
	)

	def _leave(period):
		return _insert(
			"Leave Application", name=f"{tag}-LV-{period[:5].replace(' ', '')}", docstatus=1,
			status="Approved", employee=f"{tag}-EMP", from_date=day, to_date=day,
			half_day=1, half_day_date=day, custom_half_day_period=period, leave_type="Casual Leave",
		)

	first_half = _leave("First Half")
	second_half = _leave("Second Half")

	def _att(in_time, status="Half Day", leave=None):
		return {"x": {
			"attendance_date": day, "shift": shift, "in_time": f"{day} {in_time}",
			"status": status, "leave_application": leave,
		}}

	def _late_counts(att_map):
		"""Flags per tier, e.g. {15: 1}: the empty dict means nothing was counted late."""
		out = compute_late_deduction(att_map)
		return (out or {}).get("counts") or {}

	def _first_half_leave_is_late_against_the_second_half():
		# Shift 09:00-18:00, so the second half starts 13:30. In at 14:00 is 30 minutes late.
		late = _late_counts(_att("14:00:00", leave=first_half))
		_assert(late, f"a late second-half arrival was not counted at all: {late!r}")

	check("#10 a half day is late when the employee arrives late for the half they are due",
		_first_half_leave_is_late_against_the_second_half)

	def _on_time_for_the_second_half_is_not_late():
		# 13:00 is before the 13:30 midpoint: early for that half, not late.
		late = _late_counts(_att("13:00:00", leave=first_half))
		_assert(not late, f"an on-time second-half arrival was counted late: {late!r}")
		# and it must not be measured against the 09:00 shift start any more
		_assert("15" not in str(late), f"measured against the shift start: {late!r}")

	check("#10 arriving on time for the second half is not a late entry",
		_on_time_for_the_second_half_is_not_late)

	def _second_half_leave_still_measures_the_shift_start():
		# On leave AFTER lunch, so the morning is a normal shift start: 09:30 is 30 late.
		late = _late_counts(_att("09:30:00", leave=second_half))
		_assert(late, f"a late morning on a second-half leave day was not counted: {late!r}")

	check("#10 a second-half leave day still measures lateness from the shift start",
		_second_half_leave_still_measures_the_shift_start)

	# ---------------------------------------------------------------- HRMS #11
	from alpinos import people_events as PE

	emp_user = f"{tag.lower()}.plain@example.com"
	_insert("User", name=emp_user, email=emp_user, first_name="Plain", user_type="System User", enabled=1)
	_insert(
		"Employee", name=f"{tag}-EMP", employee_name=f"{tag} Plain Person", user_id=emp_user,
		status="Active", company=frappe.defaults.get_global_default("company"), date_of_joining=day,
	)
	other = _insert(
		"Employee", name=f"{tag}-EMP2", employee_name=f"{tag} On Leave Person", status="Active",
		company=frappe.defaults.get_global_default("company"), date_of_joining=day,
	)
	_insert(
		"Leave Application", name=f"{tag}-LV-TODAY", docstatus=1, status="Approved",
		employee=other, employee_name=f"{tag} On Leave Person", from_date=day, to_date=day,
		leave_type="Casual Leave",
	)
	wfh_emp = _insert(
		"Employee", name=f"{tag}-EMP3", employee_name=f"{tag} WFH Person", status="Active",
		company=frappe.defaults.get_global_default("company"), date_of_joining=day,
	)
	_insert(
		"Attendance", name=f"{tag}-ATT-WFH", docstatus=1, employee=wfh_emp,
		employee_name=f"{tag} WFH Person", attendance_date=day, status="Work From Home",
	)

	def _as(user, fn):
		frappe.set_user(user)
		try:
			return fn()
		finally:
			frappe.set_user("Administrator")

	def _a_plain_employee_sees_both_lists():
		out = _as(emp_user, PE.get_on_leave_and_wfh_today)
		_assert(out["allowed"], "a plain employee is still refused the sections")
		leave_names = [r["employee"] for r in out["on_leave"]]
		wfh_names = [r["employee"] for r in out["on_wfh"]]
		_assert(other in leave_names, f"today's leave is missing for a plain employee: {leave_names}")
		_assert(wfh_emp in wfh_names, f"today's WFH is missing for a plain employee: {wfh_names}")

	check("#11 a plain employee sees today's leave and work-from-home lists",
		_a_plain_employee_sees_both_lists)

	def _an_hr_manager_sees_the_same_rows():
		admin = PE.get_on_leave_and_wfh_today()
		plain = _as(emp_user, PE.get_on_leave_and_wfh_today)
		_assert([r["employee"] for r in admin["on_leave"]] == [r["employee"] for r in plain["on_leave"]],
			"the plain employee's leave list differs from HR's")
		_assert([r["employee"] for r in admin["on_wfh"]] == [r["employee"] for r in plain["on_wfh"]],
			"the plain employee's WFH list differs from HR's")

	check("#11 the lists match what HR sees, which is what the sheet asks for",
		_an_hr_manager_sees_the_same_rows)

	# ---------------------------------------------------------------- HRMS #12
	from alpinos.attendance_request_automation import (
		count_attendance_request_edits,
		get_reserved_request_names,
	)

	month_start = day.replace(day=1)
	next_month = frappe.utils.add_months(month_start, 1)

	def _request(n, raised_by_hr, edits=2):
		name = f"{tag}-AR-{n}"
		_insert(
			"Attendance Request", name=name, employee=f"{tag}-EMP", from_date=day, to_date=day,
			docstatus=1, workflow_state="Approved", reason="Office",
			custom_raised_by_hr=raised_by_hr,
		)
		for i in range(edits):
			_insert(
				"Attendance Request Detail", name=f"{name}-D{i}", parent=name,
				parenttype="Attendance Request", parentfield="custom_attendance_details",
				attendance_date=day, edit_check_in=1, edit_check_out=1, idx=i + 1,
			)
		return name

	own = _request("OWN", raised_by_hr=0, edits=1)     # 2 edits: in + out
	by_hr = _request("HR", raised_by_hr=1, edits=1)    # 2 edits, raised by HR

	def _hr_raised_requests_do_not_spend_the_balance():
		reserved = get_reserved_request_names(f"{tag}-EMP", month_start, next_month, None)
		_assert(own in reserved, f"the employee's own request stopped counting: {reserved}")
		_assert(by_hr not in reserved, f"HR's request still counts against the employee: {reserved}")
		_assert(count_attendance_request_edits(reserved) == 2,
			f"the balance used is {count_attendance_request_edits(reserved)}, expected the 2 of their own")

	check("#12 a request HR raised for the employee does not use the employee's four edits",
		_hr_raised_requests_do_not_spend_the_balance)

	def _mutation_the_check_reads_the_flag():
		frappe.db.set_value("Attendance Request", by_hr, "custom_raised_by_hr", 0, update_modified=False)
		reserved = get_reserved_request_names(f"{tag}-EMP", month_start, next_month, None)
		_assert(by_hr in reserved, "clearing the flag did not bring the request back into the count")
		frappe.db.set_value("Attendance Request", by_hr, "custom_raised_by_hr", 1, update_modified=False)

	check("#12 MUTATION: clearing the flag puts the request back in the balance",
		_mutation_the_check_reads_the_flag)

	def _the_backfill_finds_requests_raised_before_the_flag_existed():
		from alpinos.attendance_request_automation import backfill_raised_by_hr

		hr_user = f"{tag.lower()}.hr@example.com"
		_insert("User", name=hr_user, email=hr_user, first_name="Hr", user_type="System User", enabled=1)
		_insert("Has Role", name=f"{tag}-ROLE", parent=hr_user, parenttype="User",
			parentfield="roles", role="HR Manager")
		# Two requests from before the flag: one HR raised for the employee, one the
		# employee raised themselves. Only the first is HR's to carry.
		old_hr = _request("OLDHR", raised_by_hr=0, edits=1)
		old_own = _request("OLDOWN", raised_by_hr=0, edits=1)
		frappe.db.set_value("Attendance Request", old_hr, "owner", hr_user, update_modified=False)
		frappe.db.set_value("Attendance Request", old_own, "owner", emp_user, update_modified=False)

		dry = backfill_raised_by_hr(apply=0, sample=0)
		listed = [t["request"] for t in dry["sample"]]
		_assert(old_hr in listed, f"the HR-raised request was not found: {listed}")
		_assert(old_own not in listed, f"the employee's own request was picked up too: {listed}")
		_assert(frappe.db.get_value("Attendance Request", old_hr, "custom_raised_by_hr") in (0, None),
			"the dry run wrote the flag")

		backfill_raised_by_hr(apply=1, sample=0)
		_assert(frappe.db.get_value("Attendance Request", old_hr, "custom_raised_by_hr") == 1,
			"the backfill did not stamp HR's request")
		_assert(frappe.db.get_value("Attendance Request", old_own, "custom_raised_by_hr") in (0, None),
			"the backfill stamped the employee's own request")

	check("#12 the backfill stamps the HR-raised requests already on record, and only those",
		_the_backfill_finds_requests_raised_before_the_flag_existed)

	# ---------------------------------------------------------------- HRMS #13
	from alpinos.overrides.attendance_request_override import CustomAttendanceRequest

	def _punches(emp):
		rows = frappe.get_all(
			"Employee Checkin", filters={"employee": emp}, fields=["log_type", "time"], order_by="time asc"
		)
		return [(r.log_type, str(r.time)[11:16]) for r in rows]

	def _real_day(emp):
		"""The day as the device recorded it: in 13:10, out 18:33, plus an earlier stray IN."""
		for log_type, t in (("IN", "13:10:00"), ("OUT", "18:33:00")):
			_insert("Employee Checkin", name=f"{emp}-{log_type}", employee=emp, log_type=log_type,
				time=f"{day} {t}", shift=shift)

	def _doc(emp, reason, rows):
		doc = frappe.new_doc("Attendance Request")
		doc.employee = emp
		doc.from_date = doc.to_date = day
		doc.reason = reason
		doc.shift = shift
		for r in rows:
			doc.append("custom_attendance_details", dict(attendance_date=day, **r))
		doc.__class__ = CustomAttendanceRequest
		return doc

	def _on_duty_keeps_the_punches_that_exist():
		emp = _insert("Employee", name=f"{tag}-EMP-OD", employee_name="On Duty Person", status="Active",
			company=frappe.defaults.get_global_default("company"), date_of_joining=day)
		_real_day(emp)
		before = _punches(emp)
		_doc(emp, "On Duty", [{}])._apply_requested_checkins()
		after = _punches(emp)
		_assert(after == before,
			f"On Duty rewrote the day's real punches: {before} became {after}")

	check("#13 an On Duty approval leaves punches already on record alone",
		_on_duty_keeps_the_punches_that_exist)

	def _on_duty_still_fills_a_missing_punch():
		emp = _insert("Employee", name=f"{tag}-EMP-OD2", employee_name="Half Punched", status="Active",
			company=frappe.defaults.get_global_default("company"), date_of_joining=day)
		_insert("Employee Checkin", name=f"{emp}-IN", employee=emp, log_type="IN",
			time=f"{day} 13:10:00", shift=shift)
		_doc(emp, "On Duty", [{}])._apply_requested_checkins()
		out = [p for p in _punches(emp) if p[0] == "OUT"]
		_assert(out, "On Duty did not fill the missing check-out")
		_assert(("IN", "13:10") in _punches(emp), "the real check-in was overwritten anyway")

	check("#13 an On Duty approval still fills a punch that is missing",
		_on_duty_still_fills_a_missing_punch)

	def _an_edit_lands_on_the_punch_the_dashboard_shows():
		emp = _insert("Employee", name=f"{tag}-EMP-ED", employee_name="Edit Person", status="Active",
			company=frappe.defaults.get_global_default("company"), date_of_joining=day)
		_real_day(emp)
		# a second, later IN: the edit must still land on the day's FIRST one
		_insert("Employee Checkin", name=f"{emp}-IN2", employee=emp, log_type="IN",
			time=f"{day} 15:45:00", shift=shift)
		_doc(emp, "Office", [{"edit_check_in": 1, "check_in": "10:10:00"}])._apply_requested_checkins()
		ins = sorted(t for lt, t in _punches(emp) if lt == "IN")
		_assert("10:10" in ins, f"the requested check-in was not written: {ins}")
		_assert("15:45" in ins, f"the edit landed on the wrong punch: {ins}")
		_assert("13:10" not in ins, f"the first check-in was left behind: {ins}")

	check("#13 a punch edit rewrites the day's first check-in, not whichever row came back first",
		_an_edit_lands_on_the_punch_the_dashboard_shows)
