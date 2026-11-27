"""HR list #29: Work From Home and half-day Leave on the same date, by half.
TEST sites only; everything is rolled back.

Run:  ../env/bin/python ~/alpinos-wt/mrp_work/run.py <site> alpinos.wfh_halves_test.run
"""

import frappe
from frappe.utils import add_days, getdate

R = []
TAG = "WFHH"
LEAVE_MSG = ("A Leave application already exists for this date. Please cancel the Leave "
	"application before applying for Work From Home.")
WFH_MSG = ("A Work From Home request already exists for this date. Please cancel the "
	"Work From Home request before applying for Leave.")


def check(label, fn):
	try:
		fn()
		R.append(("PASS", label, ""))
	except AssertionError as e:
		R.append(("FAIL", label, str(e)))
	except Exception as e:
		R.append(("ERR ", label, f"{type(e).__name__}: {e}"))
	finally:
		frappe.set_user("Administrator")
		frappe.clear_messages()


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


def run():
	R.clear()
	frappe.set_user("Administrator")
	real_commit = frappe.db.commit
	frappe.db.commit = lambda *a, **k: None
	try:
		_run()
	finally:
		frappe.db.commit = real_commit
		frappe.db.rollback()
		frappe.set_user("Administrator")
	width = max(len(r[1]) for r in R) if R else 10
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in R if r[0] == 'PASS')}/{len(R)} passed")
	return R


_n = [0]


def _raw(doc):
	doc.flags.ignore_mandatory = True
	doc.flags.ignore_validate = True
	doc.db_insert()
	return doc.name


def _leave(emp, lt, from_date, to_date=None, half=None, period=None, status="Approved", docstatus=1, state=None):
	"""A Leave Application already on the books."""
	_n[0] += 1
	to_date = to_date or from_date
	return _raw(frappe.get_doc({
		"doctype": "Leave Application", "name": f"{TAG}-L{_n[0]}", "employee": emp, "leave_type": lt,
		"from_date": from_date, "to_date": to_date, "status": status, "docstatus": docstatus,
		"workflow_state": state or status, "half_day": 1 if half else 0, "half_day_date": half,
		"custom_half_day_period": period, "total_leave_days": 1, "posting_date": from_date,
	}))


def _wfh(emp, day, period=None, status="Approved"):
	"""A Work From Home Request already on the books (period None = full day)."""
	_n[0] += 1
	return _raw(frappe.get_doc({
		"doctype": "Work From Home Request", "name": f"{TAG}-W{_n[0]}", "naming_series": "WFH-.YYYY.-",
		"employee": emp, "date": day,
		"to_date": day, "half_day": 1 if period else 0, "custom_half_day_period": period, "status": status,
	}))


def _new_leave(emp, lt, from_date, to_date=None, half=None, period=None):
	return frappe.get_doc({
		"doctype": "Leave Application", "employee": emp, "leave_type": lt, "from_date": from_date,
		"to_date": to_date or from_date, "half_day": 1 if half else 0, "half_day_date": half,
		"custom_half_day_period": period, "status": "Draft", "leave_approver": _approver(emp),
	})


def _approver(emp):
	return frappe.db.get_value("Employee", emp, "leave_approver") or frappe.db.get_value(
		"Has Role", {"role": "Leave Approver", "parenttype": "User", "parent": ["not in", ["Administrator", "Guest"]]},
		"parent") or "Administrator"


def _new_wfh(emp, day, period=None):
	return frappe.get_doc({
		"doctype": "Work From Home Request", "employee": emp, "date": day, "to_date": day,
		"half_day": 1 if period else 0, "custom_half_day_period": period, "status": "Draft",
	})


def _leave_refused(doc):
	from alpinos.wfh_leave_exclusion import block_leave_when_wfh_exists

	try:
		block_leave_when_wfh_exists(doc)
	except frappe.ValidationError as e:
		return frappe.utils.strip_html(str(e))
	return None


def _wfh_refused(doc):
	from alpinos.wfh_leave_exclusion import block_wfh_when_leave_exists

	try:
		block_wfh_when_leave_exists(doc)
	except frappe.ValidationError as e:
		return frappe.utils.strip_html(str(e))
	return None


def _weekdays(start, count):
	"""`count` Monday-to-Friday dates from `start` (Saturday cannot be a half day here)."""
	out, day = [], getdate(start)
	while len(out) < count:
		if day.weekday() < 5:
			out.append(str(day))
		day = getdate(add_days(day, 1))
	return out


def _run():
	emp = frappe.db.get_value("Employee", {"status": "Active"}, "name", order_by="name")
	lt = frappe.db.get_value("Leave Type", {}, "name", order_by="name")
	D = _weekdays("2031-11-03", 16)
	frappe.db.delete("Leave Application", {"employee": emp, "from_date": [">=", "2031-01-01"]})
	frappe.db.delete("Work From Home Request", {"employee": emp, "date": [">=", "2031-01-01"]})

	def _different_halves():
		_wfh(emp, D[0], "First Half")
		_assert(_leave_refused(_new_leave(emp, lt, D[0], half=D[0], period="Second Half")) is None,
			"Leave Second Half refused after WFH First Half")
		_wfh(emp, D[1], "Second Half")
		_assert(_leave_refused(_new_leave(emp, lt, D[1], half=D[1], period="First Half")) is None,
			"Leave First Half refused after WFH Second Half")
		_leave(emp, lt, D[2], half=D[2], period="First Half")
		_assert(_wfh_refused(_new_wfh(emp, D[2], "Second Half")) is None, "WFH Second Half refused after Leave First Half")
		_leave(emp, lt, D[3], half=D[3], period="Second Half")
		_assert(_wfh_refused(_new_wfh(emp, D[3], "First Half")) is None, "WFH First Half refused after Leave Second Half")

	check("Different halves: WFH one half + Leave the other half, both ways, no error", _different_halves)

	def _same_half():
		_wfh(emp, D[4], "First Half")
		_assert(_leave_refused(_new_leave(emp, lt, D[4], half=D[4], period="First Half")) == WFH_MSG,
			"Leave First Half on a WFH First Half not refused with the existing message")
		_leave(emp, lt, D[5], half=D[5], period="Second Half")
		_assert(_wfh_refused(_new_wfh(emp, D[5], "Second Half")) == LEAVE_MSG,
			"WFH Second Half on a Leave Second Half not refused with the existing message")

	check("Same half: refused both ways, with the existing messages word for word", _same_half)

	def _full_day():
		_wfh(emp, D[6])
		for period in ("First Half", "Second Half"):
			_assert(_leave_refused(_new_leave(emp, lt, D[6], half=D[6], period=period)) == WFH_MSG,
				f"Leave {period} allowed on a full-day WFH")
		_assert(_leave_refused(_new_leave(emp, lt, D[6])) == WFH_MSG, "full Leave allowed on a full-day WFH")
		_leave(emp, lt, D[7])
		for period in ("First Half", "Second Half"):
			_assert(_wfh_refused(_new_wfh(emp, D[7], period)) == LEAVE_MSG, f"WFH {period} allowed on a full-day Leave")
		_assert(_wfh_refused(_new_wfh(emp, D[7])) == LEAVE_MSG, "full WFH allowed on a full-day Leave")
		_leave(emp, lt, D[8], half=D[8], period="First Half")
		_assert(_wfh_refused(_new_wfh(emp, D[8])) == LEAVE_MSG, "full WFH allowed on a half-day Leave")

	check("Full day: a full-day WFH or Leave leaves no half for the other", _full_day)

	def _pending_holds():
		_leave(emp, lt, D[9], half=D[9], period="First Half", status="Draft", docstatus=0,
			state="Pending Reporting Manager Approval")
		_assert(_wfh_refused(_new_wfh(emp, D[9], "First Half")) == LEAVE_MSG, "a pending Leave did not hold its half")
		_assert(_wfh_refused(_new_wfh(emp, D[9], "Second Half")) is None, "a pending Leave blocked the other half")
		_wfh(emp, D[10], "Second Half", status="Pending Reporting Manager Approval")
		_assert(_leave_refused(_new_leave(emp, lt, D[10], half=D[10], period="Second Half")) == WFH_MSG,
			"a pending WFH did not hold its half")
		_assert(_leave_refused(_new_leave(emp, lt, D[10], half=D[10], period="First Half")) is None,
			"a pending WFH blocked the other half")

	check("Requests pending approval hold their half too (Leave at Draft / Pending, WFH Pending)", _pending_holds)

	def _rejected_cancelled_free():
		_wfh(emp, D[11], status="Rejected")
		_assert(_leave_refused(_new_leave(emp, lt, D[11])) is None, "a rejected WFH still blocks")
		_leave(emp, lt, D[12], status="Cancelled", docstatus=2)
		_leave(emp, lt, D[12], status="Draft", docstatus=0, state="Rejected")
		_assert(_wfh_refused(_new_wfh(emp, D[12])) is None, "a cancelled or rejected Leave still blocks")

	check("Rejected and cancelled requests free the day", _rejected_cancelled_free)

	def _multi_day_leave():
		# a 3-day Leave whose last day is a Second Half
		_leave(emp, lt, D[13], D[15], half=D[15], period="Second Half")
		_assert(_wfh_refused(_new_wfh(emp, D[15], "First Half")) is None, "WFH First Half refused on the leave's half day")
		_assert(_wfh_refused(_new_wfh(emp, D[15], "Second Half")) == LEAVE_MSG, "WFH Second Half allowed on the leave's half")
		_assert(_wfh_refused(_new_wfh(emp, D[13], "First Half")) == LEAVE_MSG, "WFH allowed on a full day of the leave")

	check("A multi-day Leave: only its half day has a free half", _multi_day_leave)

	def _no_half_named():
		day = _weekdays("2031-12-01", 1)[0]
		_leave(emp, lt, day, half=day, period=None)
		_assert(_wfh_refused(_new_wfh(emp, day, "Second Half")) == LEAVE_MSG,
			"an older half day with no half named let a WFH half through")

	check("An older half-day Leave with no half named still blocks (the half is unknown)", _no_half_named)

	def _save_paths():
		days = _weekdays("2031-12-08", 4)
		_leave(emp, lt, days[0], half=days[0], period="First Half")
		same = _new_wfh(emp, days[0], "First Half")
		try:
			same.insert(ignore_permissions=True)
		except frappe.ValidationError as e:
			_assert(frappe.utils.strip_html(str(e)) == LEAVE_MSG, str(e))
		else:
			raise AssertionError("saving a WFH on the leave's half went through")
		frappe.clear_messages()
		other = _new_wfh(emp, days[0], "Second Half")
		other.insert(ignore_permissions=True)
		_assert(frappe.db.exists("Work From Home Request", other.name), "WFH for the other half not saved")

		lwp = frappe.db.get_value("Leave Type", {"is_lwp": 1}, "name") or lt
		_wfh(emp, days[1], "Second Half")
		leave = _new_leave(emp, lwp, days[1], half=days[1], period="Second Half")
		try:
			leave.insert(ignore_permissions=True)
		except frappe.ValidationError as e:
			_assert(frappe.utils.strip_html(str(e)) == WFH_MSG, f"stopped on something else: {e}")
		else:
			raise AssertionError("saving a Leave on the WFH's half went through")
		frappe.clear_messages()
		leave = _new_leave(emp, lwp, days[1], half=days[1], period="First Half")
		try:
			leave.insert(ignore_permissions=True)
		except frappe.ValidationError as e:
			_assert(WFH_MSG not in str(e), "Leave for the other half refused by the WFH rule")

	check("Saving the forms runs the rule (WFH and Leave)", _save_paths)

	def _unchanged_resave():
		day, other_day = _weekdays("2031-12-15", 2)
		name = _wfh(emp, day, "First Half")
		_leave(emp, lt, day, half=day, period="First Half")  # an older clash already on the books
		doc = frappe.get_doc("Work From Home Request", name)
		doc.reason = "task update at checkout"
		doc.save(ignore_permissions=True)  # must not raise: nothing about its day changed
		moved = frappe.get_doc("Work From Home Request", _wfh(emp, other_day, "First Half"))
		moved.date = moved.to_date = day
		try:
			moved.save(ignore_permissions=True)
		except frappe.ValidationError as e:
			_assert(frappe.utils.strip_html(str(e)) == LEAVE_MSG, str(e))
		else:
			raise AssertionError("moving a WFH onto the leave's half went through")

	check("Re-saving an unchanged request is not refused; moving it onto a taken half is", _unchanged_resave)
