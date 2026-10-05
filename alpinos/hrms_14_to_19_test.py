"""HRMS #14, #16, #17, #18, #19.

Run:  bench --site alpinos.test execute alpinos.hrms_14_to_19_test.run

#18 is a defect in HRMS #11, which this session built: the dashboard read Attendance rows
for today, and an approved Work From Home Request does not become one until the day is
marked, so the panel was empty for the whole of the day it was meant to serve.

Fixtures are rolled back.
"""

import frappe
import io
import os
from frappe.utils import add_days, today

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


def _app_file(*parts):
	return os.path.join(os.path.dirname(os.path.abspath(__file__)), *parts)


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
	tag = "H19" + frappe.generate_hash(length=4).upper()
	company = frappe.db.get_value("Warehouse", {"is_group": 0}, "company")
	day = today()

	emp = _insert("Employee", name=f"{tag}-EMP", employee_name=f"{tag} Person", status="Active",
		company=company, date_of_joining="2026-01-01")

	# ---------------------------------------------------------------- #14
	def _other_is_gone_from_the_checkin_reasons():
		options = frappe.db.get_value(
			"Custom Field", {"dt": "Employee Checkin", "fieldname": "custom_checkin_type"},
			"options") or ""
		values = [o for o in options.split("\n") if o.strip()]
		_assert("Other" not in values, f"'Other' is still offered at check-in: {values}")
		_assert({"Client/Vendor", "Shoot", "Meeting"} <= set(values),
			f"the three real reasons must remain: {values}")

	check("#14 'Other' is gone from the check-in reasons",
		_other_is_gone_from_the_checkin_reasons)

	def _the_reason_field_no_longer_appears():
		hidden = frappe.db.get_value(
			"Custom Field", {"dt": "Employee Checkin", "fieldname": "custom_checkin_reason"},
			"hidden")
		_assert(hidden == 1,
			"the 'Enter Reason for Other' field still appears; it only existed for 'Other'")

	check("#14 the free-text reason field no longer appears",
		_the_reason_field_no_longer_appears)

	def _the_server_refuses_other_too():
		src = io.open(_app_file("attendance_widget.py"), encoding="utf-8").read()
		_assert('("Client/Vendor", "Shoot", "Meeting")' in src,
			"the endpoint still accepts 'Other'")
		_assert('A reason is required when the check-in type is' not in src,
			"the 'reason required for Other' rule is still there")

	check("#14 the check-in endpoint refuses 'Other', not just the dropdown",
		_the_server_refuses_other_too)

	# ---------------------------------------------------------------- #16
	def _wfh_is_refused_when_leave_exists():
		from alpinos.wfh_leave_exclusion import block_wfh_when_leave_exists

		_insert("Leave Application", name=f"{tag}-LV", employee=emp, docstatus=1,
			status="Approved", from_date=day, to_date=day, leave_type="Casual Leave",
			company=company)
		doc = frappe._dict(doctype="Work From Home Request", employee=emp, date=day,
			to_date=day, status="Open")
		try:
			block_wfh_when_leave_exists(doc)
		except frappe.ValidationError as e:
			msg = frappe.utils.strip_html(str(e))
			_assert("cancel the Leave application" in msg,
				f"the message is not the one the ticket gives: {msg}")
			return
		raise AssertionError("WFH was allowed on a day that already has an approved Leave")

	check("#16 WFH is refused on a day that already has Leave, with the ticket's wording",
		_wfh_is_refused_when_leave_exists)

	def _leave_is_refused_when_wfh_exists():
		from alpinos.wfh_leave_exclusion import block_leave_when_wfh_exists

		emp2 = _insert("Employee", name=f"{tag}-EMP2", employee_name=f"{tag} Two",
			status="Active", company=company, date_of_joining="2026-01-01")
		_insert("Work From Home Request", name=f"{tag}-WFH", employee=emp2, date=day,
			to_date=day, status="Approved")
		doc = frappe._dict(doctype="Leave Application", employee=emp2, from_date=day,
			to_date=day, status="Open")
		try:
			block_leave_when_wfh_exists(doc)
		except frappe.ValidationError as e:
			msg = frappe.utils.strip_html(str(e))
			_assert("cancel the Work From Home request" in msg,
				f"the reverse message does not mirror the first: {msg}")
			return
		raise AssertionError("Leave was allowed on a day that already has an approved WFH")

	check("#16 Leave is refused on a day that already has WFH, mirroring the message",
		_leave_is_refused_when_wfh_exists)

	def _a_cancelled_leave_does_not_block():
		"""Cancelling is exactly what the message asks for, so it must then work."""
		from alpinos.wfh_leave_exclusion import block_wfh_when_leave_exists

		emp3 = _insert("Employee", name=f"{tag}-EMP3", employee_name=f"{tag} Three",
			status="Active", company=company, date_of_joining="2026-01-01")
		_insert("Leave Application", name=f"{tag}-LV3", employee=emp3, docstatus=2,
			status="Cancelled", from_date=day, to_date=day, leave_type="Casual Leave",
			company=company)
		doc = frappe._dict(doctype="Work From Home Request", employee=emp3, date=day,
			to_date=day, status="Open")
		block_wfh_when_leave_exists(doc)   # must not raise

	check("#16 a cancelled Leave no longer blocks, or the instruction would be impossible",
		_a_cancelled_leave_does_not_block)

	def _a_different_day_is_unaffected():
		from alpinos.wfh_leave_exclusion import block_wfh_when_leave_exists

		doc = frappe._dict(doctype="Work From Home Request", employee=emp,
			date=add_days(day, 30), to_date=add_days(day, 30), status="Open")
		block_wfh_when_leave_exists(doc)   # the Leave above is for today only

	check("#16 a day with no clash is left alone", _a_different_day_is_unaffected)

	# ---------------------------------------------------------------- #18
	def _an_approved_request_shows_on_the_dashboard_today():
		from alpinos.people_events import get_on_leave_and_wfh_today

		emp4 = _insert("Employee", name=f"{tag}-EMP4", employee_name=f"{tag} WFH Today",
			status="Active", company=company, date_of_joining="2026-01-01")
		_insert("Work From Home Request", name=f"{tag}-WFH4", employee=emp4,
			employee_name=f"{tag} WFH Today", date=day, to_date=day, status="Approved")
		# Deliberately NO Attendance row: that is the state during the working day.
		out = get_on_leave_and_wfh_today()
		names = {w["employee"] for w in out["on_wfh"]}
		_assert(emp4 in names,
			f"an approved WFH request for today is still missing from the panel: {names}")

	check("#18 an approved WFH request shows today, before any Attendance exists",
		_an_approved_request_shows_on_the_dashboard_today)

	def _an_unapproved_request_does_not_show():
		from alpinos.people_events import get_on_leave_and_wfh_today

		emp5 = _insert("Employee", name=f"{tag}-EMP5", employee_name=f"{tag} Pending",
			status="Active", company=company, date_of_joining="2026-01-01")
		_insert("Work From Home Request", name=f"{tag}-WFH5", employee=emp5, date=day,
			to_date=day, status="Open")
		out = get_on_leave_and_wfh_today()
		_assert(emp5 not in {w["employee"] for w in out["on_wfh"]},
			"a request that is not approved was shown as working from home")

	check("#18 a request still awaiting approval is not shown",
		_an_unapproved_request_does_not_show)

	def _nobody_is_listed_twice():
		from alpinos.people_events import get_on_leave_and_wfh_today

		emp6 = _insert("Employee", name=f"{tag}-EMP6", employee_name=f"{tag} Both",
			status="Active", company=company, date_of_joining="2026-01-01")
		_insert("Work From Home Request", name=f"{tag}-WFH6", employee=emp6, date=day,
			to_date=day, status="Approved")
		_insert("Attendance", name=f"{tag}-ATT6", employee=emp6, attendance_date=day,
			docstatus=1, status="Work From Home", company=company)
		out = get_on_leave_and_wfh_today()
		listed = [w for w in out["on_wfh"] if w["employee"] == emp6]
		_assert(len(listed) == 1,
			f"somebody with both a request and an Attendance was listed {len(listed)} times")

	check("#18 somebody with both a request and an Attendance is listed once",
		_nobody_is_listed_twice)

	# ---------------------------------------------------------------- #19
	def _the_shift_percentage_decides_the_full_day():
		from alpinos.alpinos_development.report.attendance_summary.attendance_summary_helpers import (
			calculate_attendance_stats,
		)
		from frappe.utils import flt

		# 10:00-18:30 is 8.5 hours. At 97.06% a full day is 8h15m; at 100% it is 8h30m.
		lenient = _insert("Shift Type", name=f"{tag}-L", start_time="10:00:00",
			end_time="18:30:00", working_hours_percent_fulfilment_for_full_day=97.06)
		strict = _insert("Shift Type", name=f"{tag}-S", start_time="10:00:00",
			end_time="18:30:00", working_hours_percent_fulfilment_for_full_day=100)

		def _shortage(shift, hours):
			att = {f"2026-09-15": {"attendance_date": "2026-09-15", "status": "Present",
				"shift": shift, "in_time": "2026-09-15 10:00:00",
				"out_time": "2026-09-15 18:15:00", "working_hours": hours}}
			return flt(calculate_attendance_stats(
				att, {}, {}, {}, "2026-09-01", "2026-09-30", emp).working_hours_shortage)

		_assert(_shortage(lenient, 8.25) == 0.0,
			"8h15m should be a full day at 97.06% of an 8h30m shift")
		_assert(_shortage(strict, 8.25) == 0.5,
			"8h15m should NOT be a full day at 100%; the shift's own percentage must decide")

	check("#19 the shift's own percentage decides what counts as a full day",
		_the_shift_percentage_decides_the_full_day)

	def _a_shift_without_one_keeps_the_standard():
		from alpinos.alpinos_development.report.attendance_summary.attendance_summary_helpers import (
			DEFAULT_FULL_DAY_PERCENT, _full_day_percent,
		)

		plain = _insert("Shift Type", name=f"{tag}-P", start_time="10:00:00", end_time="18:30:00")
		cache = {}
		_assert(abs(_full_day_percent(plain, cache) - DEFAULT_FULL_DAY_PERCENT / 100.0) < 1e-9,
			"a shift that sets no percentage should keep the standard 97%")
		_assert(abs(_full_day_percent(f"{tag}-L", cache) - 0.9706) < 1e-9,
			"the configured percentage was not read")

	check("#19 a shift that sets no percentage keeps the standard 97%",
		_a_shift_without_one_keeps_the_standard)

	# ---------------------------------------------------------------- #17
	def _every_forced_background_also_forces_its_ink():
		js = io.open(_app_file("alpinos_development", "report", "attendance_summary",
			"attendance_summary.js"), encoding="utf-8").read()
		_assert("ATT_INK" in js, "no single ink is defined for the forced backgrounds")
		import re
		# Any inline style that sets a background must set a colour in the same style.
		for m in re.finditer(r'style="([^"]*background:[^"]*)"', js):
			style = m.group(1)
			_assert("color:" in style,
				f"a forced background with no foreground: {style[:90]}")
		_assert("var(--red-500" in js and "var(--blue-500" in js,
			"the text colours on the theme's own background do not follow the theme")

	check("#17 every forced background forces its own ink, and theme text follows the theme",
		_every_forced_background_also_forces_its_ink)
