"""Changes(HP) HRMS #20: an On Duty request is a full day, never a half one.

Run:  bench --site alpinos.test execute alpinos.hrms_20_on_duty_half_day_test.run

    "Add a validation/conditional rule in the Attendance Request: Reason = On Duty -> Half
     Day selection should be disabled/not allowed. Users should only be able to submit the
     request for a Full Day when the reason is On Duty."  (#20)

Two halves, checked separately because either on its own would be a half-built rule: the
server refuses it for the paths that never load a form, and the form itself disables and
clears the box so nobody reaches the refusal by accident.

The checks come in pairs so the rule cannot be read wider than the ticket -- On Duty is
refused, every other reason keeps its Half Day. #7 (no half day on a Saturday) is still
in force alongside it and is checked too, since both rules read the same field. Fixtures
roll back.
"""

import frappe
import io
import os
from frappe.utils import add_days, getdate, today

RES = []

#: Python's weekday(): Saturday is 5. #7 refuses a Saturday half day whatever the reason,
#: so a check about #20 must stand on a day #7 has no opinion about.
SATURDAY = 5


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
	try:
		fn()
		return False
	except frappe.ValidationError:
		return True


def _a_weekday():
	"""A recent day that is not a Saturday, so #7 stays out of the way."""
	for offset in range(0, 10):
		day = add_days(today(), -offset)
		if getdate(day).weekday() != SATURDAY:
			return day
	raise AssertionError("no non-Saturday in the last 10 days")


def _req(reason, day, half_day=1):
	return frappe._dict(
		doctype="Attendance Request",
		reason=reason,
		from_date=day,
		to_date=day,
		half_day=half_day,
		half_day_date=day,
		custom_attendance_details=[],
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


def _app_file(*parts):
	return os.path.join(os.path.dirname(os.path.abspath(__file__)), *parts)


def _run():
	from alpinos.attendance_request_rules import (
		block_half_day_when_on_duty,
		block_saturday_half_day,
	)

	day = _a_weekday()

	def _on_duty_with_half_day_is_refused():
		doc = _req("On Duty", day, half_day=1)
		_assert(_refused(lambda: block_half_day_when_on_duty(doc)),
			f"an On Duty half-day request for {day} was accepted")

	check("#20 an On Duty request with Half Day ticked is refused",
		_on_duty_with_half_day_is_refused)

	def _on_duty_full_day_goes_through():
		doc = _req("On Duty", day, half_day=0)
		_assert(not _refused(lambda: block_half_day_when_on_duty(doc)),
			"a full-day On Duty request was refused")

	check("#20 a full-day On Duty request goes through", _on_duty_full_day_goes_through)

	def _another_reason_keeps_its_half_day():
		"""The rule is about On Duty and must leave the other reasons alone."""
		for reason in ("Work From Home", "Penalty"):
			doc = _req(reason, day, half_day=1)
			_assert(not _refused(lambda: block_half_day_when_on_duty(doc)),
				f"a {reason} half-day request was refused; the rule is too wide")

	check("#20 another reason keeps its Half Day", _another_reason_keeps_its_half_day)

	def _the_message_says_what_to_do_about_it():
		doc = _req("On Duty", day, half_day=1)
		try:
			block_half_day_when_on_duty(doc)
			raise AssertionError("not refused at all")
		except frappe.ValidationError:
			msg = frappe.message_log[-1] if frappe.message_log else {}
			text = (msg.get("message") if isinstance(msg, dict) else str(msg)) or ""
			_assert("Half Day" in text and "Reason" in text,
				f"the refusal does not tell the person what to change: {text!r}")
		finally:
			frappe.clear_messages()

	check("#20 the refusal names the two ways out of it",
		_the_message_says_what_to_do_about_it)

	def _saturday_is_still_refused_for_every_reason():
		"""#7 is untouched: it refuses a Saturday half day whatever the reason."""
		saturday = None
		for offset in range(0, 10):
			candidate = add_days(today(), -offset)
			if getdate(candidate).weekday() == SATURDAY:
				saturday = candidate
				break
		_assert(saturday, "no Saturday in the last 10 days")
		doc = _req("Work From Home", saturday, half_day=1)
		_assert(_refused(lambda: block_saturday_half_day(doc)),
			f"#7 no longer refuses a Saturday half day ({saturday})")

	check("#7 a Saturday half day is still refused for every reason",
		_saturday_is_still_refused_for_every_reason)

	def _the_rule_is_actually_wired_up():
		"""A validate rule nobody calls is not a rule.

		The three Attendance Request rules live in one module and are registered by hand, so
		a new one is exactly the kind of thing that gets written and never hooked.
		"""
		hooks = frappe.get_hooks("doc_events") or {}
		events = (hooks.get("Attendance Request") or {}).get("validate") or []
		flat = events if isinstance(events, list) else [events]
		_assert("alpinos.attendance_request_rules.block_half_day_when_on_duty" in flat,
			f"the rule is not in the Attendance Request validate chain: {flat}")

	check("#20 the rule is registered on Attendance Request validate",
		_the_rule_is_actually_wired_up)

	def _the_form_disables_the_box_rather_than_only_refusing_it():
		"""#20 asks for the selection to be DISABLED, which is a form change.

		Checked by reading the script, since there is no browser here. What is asserted is
		the behaviour the ticket names -- read_only driven by the reason -- and the clearing
		of a tick that is no longer allowed, which is the half a depends_on cannot do.
		"""
		js = io.open(_app_file("public", "js", "attendance_request_on_duty.js"),
			encoding="utf-8").read()
		_assert("'Attendance Request'" in js, "the script is not bound to the doctype")
		_assert("reason(frm)" in js, "nothing reacts to the Reason changing")
		_assert("set_df_property('half_day', 'read_only'" in js,
			"the Half Day box is never disabled")
		_assert("set_value('half_day', 0)" in js,
			"a Half Day already ticked is not cleared when On Duty is chosen")

	check("#20 the form disables Half Day and clears a tick already made",
		_the_form_disables_the_box_rather_than_only_refusing_it)

	def _the_script_is_registered_for_the_doctype():
		js_hooks = frappe.get_hooks("doctype_js") or {}
		entry = js_hooks.get("Attendance Request") or []
		flat = entry if isinstance(entry, list) else [entry]
		_assert(any("attendance_request_on_duty.js" in e for e in flat),
			f"the form script is not registered: {flat}")

	check("#20 the form script is registered in doctype_js",
		_the_script_is_registered_for_the_doctype)

	def _a_real_on_duty_half_day_request_cannot_be_saved():
		"""The rule in the chain, on a real document, not a stand-in."""
		employee = frappe.db.get_value("Employee", {"status": "Active"}, "name")
		_assert(employee, "no active Employee on this site")

		doc = frappe.get_doc({
			"doctype": "Attendance Request",
			"employee": employee,
			"from_date": day,
			"to_date": day,
			"custom_request_date": day,
			"reason": "On Duty",
			"half_day": 1,
			"half_day_date": day,
			"explanation": "HRMS #20 check",
		})
		_assert(_refused(lambda: doc.insert(ignore_permissions=True)),
			"an On Duty half-day request saved to the database")

	check("#20 a real On Duty half-day request cannot be saved",
		_a_real_on_duty_half_day_request_cannot_be_saved)
