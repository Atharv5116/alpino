"""Changes(HP) HRMS #15: an On Duty request may be raised for a future date.

Run:  bench --site alpinos.test execute alpinos.hrms_15_on_duty_future_test.run

    "In Attendance Request If reason Is ON DUTY then allow future date Attendance Request
     raising."  (#15, 01-10-2026)

#15 is the exception to #6, which refuses anything on a request that sits in the future.
Both rules live in attendance_request_rules.block_future_date_time, so the checks below
come in pairs: On Duty goes through, every other reason is still refused. The pairing is
the point -- an exemption written too wide would quietly undo #6.

The last check saves a real future-dated On Duty request, because the rule this fixes is
one of several validations on the way to a save and passing the rule alone proves nothing
about the document reaching the database. Fixtures roll back.
"""

import frappe
from frappe.utils import add_days, getdate, today

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


def _refused(fn):
	"""True when the rule throws, False when it lets the request through."""
	try:
		fn()
		return False
	except frappe.ValidationError:
		return True


def _req(reason, from_date, to_date=None, rows=None):
	"""A stand-in Attendance Request carrying only what the rule reads."""
	return frappe._dict(
		doctype="Attendance Request",
		reason=reason,
		from_date=from_date,
		to_date=to_date or from_date,
		half_day_date=None,
		custom_attendance_details=[frappe._dict(r) for r in (rows or [])],
	)


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
	from alpinos.attendance_request_rules import block_future_date_time

	later = add_days(today(), 5)
	earlier = add_days(today(), -2)

	def _on_duty_may_be_raised_for_a_future_date():
		doc = _req("On Duty", later)
		_assert(not _refused(lambda: block_future_date_time(doc)),
			f"an On Duty request for {later} was refused")

	check("#15 an On Duty request may carry a future From/To date",
		_on_duty_may_be_raised_for_a_future_date)

	def _the_details_row_for_that_day_is_exempt_too():
		"""The Details table carries a row per requested date.

		Exempting only From/To would still refuse the save, since the row for a future
		date is itself in the future -- which is what makes this a whole-document exemption
		rather than a two-field one.
		"""
		doc = _req("On Duty", later, rows=[{"attendance_date": later}])
		_assert(not _refused(lambda: block_future_date_time(doc)),
			"the Details row for the requested day was refused")

	check("#15 the Details row for a future On Duty day is exempt too",
		_the_details_row_for_that_day_is_exempt_too)

	def _a_future_range_is_allowed_end_to_end():
		doc = _req("On Duty", add_days(today(), 2), add_days(today(), 6))
		_assert(not _refused(lambda: block_future_date_time(doc)),
			"a multi-day future On Duty range was refused")

	check("#15 On Duty takes a future range, not only a single future day",
		_a_future_range_is_allowed_end_to_end)

	def _another_reason_is_still_refused():
		"""#6 is intact for everything that is not On Duty."""
		doc = _req("Work From Home", later)
		_assert(_refused(lambda: block_future_date_time(doc)),
			f"a Work From Home request for {later} was allowed; #6 has been undone")

	check("#6 another reason with a future date is still refused",
		_another_reason_is_still_refused)

	def _another_reasons_future_details_row_is_still_refused():
		doc = _req("Work From Home", today(), rows=[{"attendance_date": later}])
		_assert(_refused(lambda: block_future_date_time(doc)),
			"a future Details row slipped through for a non-On-Duty reason")

	check("#6 a future Details row is still refused for another reason",
		_another_reasons_future_details_row_is_still_refused)

	def _a_later_clock_today_is_still_refused():
		"""#6 compares the whole datetime, not just the date.

		A request raised this morning for this afternoon's check-out is today's date and
		still the future. Checked so the exemption cannot be read as "dates only".
		"""
		doc = _req("Work From Home", today(),
			rows=[{"attendance_date": today(), "check_out": "23:59:00"}])
		_assert(_refused(lambda: block_future_date_time(doc)),
			"a check-out later today was allowed for a non-On-Duty reason")

	check("#6 a time later today is still refused for another reason",
		_a_later_clock_today_is_still_refused)

	def _on_duty_in_the_past_is_untouched():
		doc = _req("On Duty", earlier)
		_assert(not _refused(lambda: block_future_date_time(doc)),
			"a past On Duty request was refused")

	check("#15 a past On Duty request is unaffected", _on_duty_in_the_past_is_untouched)

	def _a_future_on_duty_request_actually_saves():
		"""The rule is one of several validations between the form and the database.

		block_future_date_time passing says nothing about _enforce_request_window, the
		monthly cap or the HRMS core checks, each of which could refuse the same document.
		So the document is really inserted.
		"""
		employee = frappe.db.get_value("Employee", {"status": "Active"}, "name")
		_assert(employee, "no active Employee on this site to raise a request for")

		# A future day that is not a holiday for this employee: HRMS refuses a request whose
		# every day would be skipped, and a holiday is skipped.
		from erpnext.setup.doctype.employee.employee import is_holiday

		day = None
		for offset in range(2, 20):
			candidate = add_days(today(), offset)
			if not is_holiday(employee, candidate):
				day = candidate
				break
		_assert(day, "no non-holiday day in the next 20 days")

		doc = frappe.get_doc({
			"doctype": "Attendance Request",
			"employee": employee,
			"from_date": day,
			"to_date": day,
			"custom_request_date": day,
			"reason": "On Duty",
			"explanation": "HRMS #15 check",
		})
		doc.insert(ignore_permissions=True)
		_assert(doc.name, "the request did not get a name")
		_assert(getdate(doc.from_date) > getdate(today()),
			f"the saved request is not in the future: {doc.from_date}")

	check("#15 a future On Duty request reaches the database, not just the rule",
		_a_future_on_duty_request_actually_saves)
