"""Changes(HP) HRMS #16: a day is either Leave or Work From Home, never both.

    "Do not allow an employee to apply for WFH for a date/period that already has an active
     Leave application... Apply the same rule in reverse: if WFH already exists, the employee
     must cancel it before applying for Leave."

The ticket gives the wording for one direction; the other is written to match it, because a
person who hits the rule from the Leave side should not be told something different from the
person who hits it from the WFH side.

"Active" means not cancelled and not rejected. A cancelled Leave is exactly what the message
asks the person to produce, so treating it as blocking would make the instruction impossible
to follow.

HR list #29 (26 Nov 2026): halves of a day.

  * Different halves: WFH for the First Half and Leave for the Second Half (or the other way
    round) on the same date are both allowed.
  * Same half: refused, with the message above.
  * Full day: a full-day WFH leaves no half for Leave, and a full-day Leave none for WFH.

A pending request holds its day too. Alpino's workflow keeps a Leave waiting for approval at
status Draft (workflow state "Pending ... Approval") and a WFH at "Pending ... Approval", so
only Rejected and Cancelled free a day, the same as the leave overlap rule (HR list #27).
A half day with no half named (older records) cannot be told apart from the other half, so it
is treated as clashing.

The check runs when a request is created, or when its employee, dates, half day or half change
(or a rejected one comes back), so saving an unchanged request (a WFH task update at checkout,
an approval step) is never refused by a record that was already there.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, getdate

from alpinos.company_scope.helpers import assert_company

#: Leave Applications that still occupy the day (find_clashes only).
_ACTIVE_LEAVE = ("Open", "Approved")

#: WFH Requests that still occupy the day (find_clashes only).
_ACTIVE_WFH = ("Open", "Approved", "Pending")

#: HR list #29: only these free a day; a request pending approval still holds it.
_INACTIVE = ("Rejected", "Cancelled")

_HALVES = ("First Half", "Second Half")

_LEAVE_FIELDS = ("employee", "from_date", "to_date", "half_day", "half_day_date", "custom_half_day_period")
_WFH_FIELDS = ("employee", "date", "to_date", "half_day", "custom_half_day_period")


def _overlap(a_from, a_to, b_from, b_to):
	return getdate(a_from) <= getdate(b_to) and getdate(b_from) <= getdate(a_to)


def _wfh_dates(doc):
	start = doc.get("date")
	end = doc.get("to_date") or start
	return (start, end) if start else (None, None)


def _leave_dates(doc):
	start = doc.get("from_date")
	end = doc.get("to_date") or start
	return (start, end) if start else (None, None)


def _inactive(doc):
	return (doc.get("status") or "") in _INACTIVE or (doc.get("workflow_state") or "") in _INACTIVE


def _needs_check(doc, fields):
	"""New, or the employee / dates / halves changed, or a rejected request is back in play."""
	if not isinstance(doc, Document) or doc.is_new():
		return True
	before = doc.get_doc_before_save()
	if not before:
		return True
	if any(str(before.get(f) or "") != str(doc.get(f) or "") for f in fields):
		return True
	return _inactive(before)


def _leave_half(leave, day):
	"""The half a Leave takes on `day`: "First Half" / "Second Half", "?" for a half day with
	no half named, None when it takes the whole day."""
	if not cint(leave.get("half_day")):
		return None
	half_date = leave.get("half_day_date")
	start, end = _leave_dates(leave)
	if not half_date and start and getdate(start) == getdate(end):
		half_date = start
	if not half_date or getdate(half_date) != getdate(day):
		return None
	return leave.get("custom_half_day_period") or "?"


def _wfh_half(wfh, day):
	"""The half a WFH request takes (it is single-day); None for the whole day."""
	if not cint(wfh.get("half_day")):
		return None
	return wfh.get("custom_half_day_period") or "?"


def _first_shared_half(leave, wfh):
	"""The first date on which the Leave and the WFH want the same half (or a whole day);
	None when every shared date is split First / Second Half between them."""
	l_start, l_end = _leave_dates(leave)
	w_start, w_end = _wfh_dates(wfh)
	day = max(getdate(l_start), getdate(w_start))
	last = min(getdate(l_end), getdate(w_end))
	while day <= last:
		a, b = _leave_half(leave, day), _wfh_half(wfh, day)
		if not (a in _HALVES and b in _HALVES and a != b):
			return day
		day = getdate(add_days(day, 1))
	return None


def _active_leaves(employee, start, end):
	period = "custom_half_day_period" if frappe.db.has_column("Leave Application", "custom_half_day_period") else "''"
	wf = ("AND IFNULL(workflow_state, '') NOT IN %(inactive)s"
		if frappe.db.has_column("Leave Application", "workflow_state") else "")
	return frappe.db.sql(
		f"""
		SELECT name, from_date, to_date, half_day, half_day_date, {period} AS custom_half_day_period
		FROM `tabLeave Application`
		WHERE employee = %(emp)s AND docstatus < 2
			AND IFNULL(status, '') NOT IN %(inactive)s {wf}
			AND from_date <= %(end)s AND to_date >= %(start)s
		""",
		{"emp": employee, "inactive": _INACTIVE, "start": getdate(start), "end": getdate(end)},
		as_dict=True,
	)


def _active_wfh(employee, start, end):
	period = ("custom_half_day_period"
		if frappe.db.has_column("Work From Home Request", "custom_half_day_period") else "''")
	return frappe.db.sql(
		f"""
		SELECT name, `date`, to_date, half_day, {period} AS custom_half_day_period
		FROM `tabWork From Home Request`
		WHERE employee = %(emp)s
			AND IFNULL(status, '') NOT IN %(inactive)s
			AND `date` <= %(end)s AND IFNULL(to_date, `date`) >= %(start)s
		""",
		{"emp": employee, "inactive": _INACTIVE, "start": getdate(start), "end": getdate(end)},
		as_dict=True,
	)


def block_wfh_when_leave_exists(doc, method=None):
	"""Work From Home Request validate: refuse a half (or day) an active Leave already holds."""
	start, end = _wfh_dates(doc)
	if not start or not doc.get("employee"):
		return
	if _inactive(doc) or not _needs_check(doc, _WFH_FIELDS):
		return

	if any(_first_shared_half(leave, doc) for leave in _active_leaves(doc.employee, start, end)):
		frappe.throw(
			_("A Leave application already exists for this date. Please cancel the Leave "
			  "application before applying for Work From Home."),
			title=_("Leave Already Applied"),
		)


def block_leave_when_wfh_exists(doc, method=None):
	"""Leave Application validate: refuse a half (or day) an active WFH request already holds."""
	start, end = _leave_dates(doc)
	if not start or not doc.get("employee"):
		return
	if _inactive(doc) or not _needs_check(doc, _LEAVE_FIELDS):
		return
	if not frappe.db.exists("DocType", "Work From Home Request"):
		return

	if any(_first_shared_half(doc, wfh) for wfh in _active_wfh(doc.employee, start, end)):
		frappe.throw(
			_("A Work From Home request already exists for this date. Please cancel the "
			  "Work From Home request before applying for Leave."),
			title=_("Work From Home Already Applied"),
		)


@frappe.whitelist()
def find_clashes(employee, from_date, to_date=None):
	"""What already occupies these days for this employee. For a pre-submit warning."""
	emp = frappe.db.get_value("Employee", employee, ["company", "user_id"], as_dict=True) if employee else None
	# Somebody else's leave follows their company; the user's own does not.
	if emp and emp.user_id != frappe.session.user:
		assert_company(emp.company, "Leave Application", "read")
	to_date = to_date or from_date
	leaves = frappe.db.sql(
		"""
		SELECT name, from_date, to_date, leave_type, status
		FROM `tabLeave Application`
		WHERE employee = %(emp)s AND docstatus < 2 AND IFNULL(status, '') IN %(st)s
			AND from_date <= %(end)s AND to_date >= %(start)s
		""",
		{"emp": employee, "st": _ACTIVE_LEAVE,
		 "start": getdate(from_date), "end": getdate(to_date)},
		as_dict=True,
	)
	wfh = []
	if frappe.db.exists("DocType", "Work From Home Request"):
		wfh = frappe.db.sql(
			"""
			SELECT name, `date`, to_date, status
			FROM `tabWork From Home Request`
			WHERE employee = %(emp)s AND IFNULL(status, '') IN %(st)s
				AND `date` <= %(end)s AND IFNULL(to_date, `date`) >= %(start)s
			""",
			{"emp": employee, "st": _ACTIVE_WFH,
			 "start": getdate(from_date), "end": getdate(to_date)},
			as_dict=True,
		)
	return {"leave": leaves, "wfh": wfh, "clash": bool(leaves or wfh)}
