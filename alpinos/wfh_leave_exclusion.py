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
"""

import frappe
from frappe import _
from frappe.utils import getdate

#: Leave Applications that still occupy the day.
_ACTIVE_LEAVE = ("Open", "Approved")

#: WFH Requests that still occupy the day. The doctype is not submittable, so status is all
#: there is to go on.
_ACTIVE_WFH = ("Open", "Approved", "Pending")


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


def block_wfh_when_leave_exists(doc, method=None):
	"""Work From Home Request validate: refuse a day an active Leave already holds."""
	start, end = _wfh_dates(doc)
	if not start or not doc.get("employee"):
		return
	if (doc.get("status") or "") in ("Cancelled", "Rejected"):
		return

	clash = frappe.db.sql(
		"""
		SELECT name, from_date, to_date, leave_type
		FROM `tabLeave Application`
		WHERE employee = %(emp)s AND docstatus < 2
			AND IFNULL(status, '') IN %(statuses)s
			AND from_date <= %(end)s AND to_date >= %(start)s
		LIMIT 1
		""",
		{"emp": doc.employee, "statuses": _ACTIVE_LEAVE,
		 "start": getdate(start), "end": getdate(end)},
		as_dict=True,
	)
	if clash:
		frappe.throw(
			_("A Leave application already exists for this date. Please cancel the Leave "
			  "application before applying for Work From Home."),
			title=_("Leave Already Applied"),
		)


def block_leave_when_wfh_exists(doc, method=None):
	"""Leave Application validate: refuse a day an active WFH request already holds."""
	start, end = _leave_dates(doc)
	if not start or not doc.get("employee"):
		return
	if (doc.get("status") or "") in ("Cancelled", "Rejected"):
		return
	if not frappe.db.exists("DocType", "Work From Home Request"):
		return

	clash = frappe.db.sql(
		"""
		SELECT name, `date`, to_date
		FROM `tabWork From Home Request`
		WHERE employee = %(emp)s
			AND IFNULL(status, '') IN %(statuses)s
			AND `date` <= %(end)s AND IFNULL(to_date, `date`) >= %(start)s
		LIMIT 1
		""",
		{"emp": doc.employee, "statuses": _ACTIVE_WFH,
		 "start": getdate(start), "end": getdate(end)},
		as_dict=True,
	)
	if clash:
		frappe.throw(
			_("A Work From Home request already exists for this date. Please cancel the "
			  "Work From Home request before applying for Leave."),
			title=_("Work From Home Already Applied"),
		)


@frappe.whitelist()
def find_clashes(employee, from_date, to_date=None):
	"""What already occupies these days for this employee. For a pre-submit warning."""
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
