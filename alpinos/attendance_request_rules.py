"""Attendance Request rules from Changes(HP) 6 and 7.

Regularisation is a record of what already happened, so it can never point at a moment
that has not arrived yet (#6), and Alpino works a full Saturday, so a Saturday cannot be
regularised as a half day (#7) -- the same rule Leave Application and Work From Home
Request already carry.

#15 carves On Duty out of #6: an On Duty request is raised ahead of the duty, so it is the
one reason that may carry a future date. #20 adds the other half of the On Duty shape: it is
a full day or it is nothing.
"""

import frappe
from frappe import _
from frappe.utils import get_datetime, getdate, now_datetime

#: Python's weekday(): Monday is 0, so Saturday is 5.
SATURDAY = 5

FUTURE_MESSAGE = "Future date and time are not allowed for attendance regularization."


def _combine(date, time_value):
	"""date + a Time field into one datetime, or None when either side is missing."""
	if not date or time_value in (None, ""):
		return None
	try:
		return get_datetime(f"{getdate(date)} {time_value}")
	except Exception:
		return None


def block_future_date_time(doc, method=None):
	"""Changes(HP) #6 - nothing on the request may sit in the future.

	Checked against the whole datetime, not just the date: a request raised this morning
	for this afternoon's check-out is a future time on today's date, and is exactly the
	case the rule is aimed at. Dates with no time are compared as dates, so a request for
	today is never blocked just because midnight has passed.
	"""
	if doc.doctype != "Attendance Request":
		return

	# Changes(HP) #15 (01-10-2026) supersedes #6 for this one reason: "If reason is ON DUTY
	# then allow future date Attendance Request raising." On Duty is a duty assignment made
	# in advance, not a record of a day already worked, so the premise of #6 does not hold.
	# The whole request is exempt, not just From/To: the Details table carries a row per
	# requested date, so exempting the header alone would still refuse the save.
	if doc.get("reason") == "On Duty":
		return

	now = now_datetime()
	today = getdate(now)
	offenders = []

	for fieldname, label in (("from_date", _("From Date")), ("to_date", _("To Date")),
	                         ("half_day_date", _("Half Day Date"))):
		value = doc.get(fieldname)
		if value and getdate(value) > today:
			offenders.append("{0}: {1}".format(label, frappe.format(getdate(value), {"fieldtype": "Date"})))

	for row in doc.get("custom_attendance_details") or []:
		date = row.get("attendance_date")
		if date and getdate(date) > today:
			offenders.append("{0}: {1}".format(
				_("Attendance Date"), frappe.format(getdate(date), {"fieldtype": "Date"})))
			continue
		# Same day, later clock: still the future.
		for time_field, time_label in (("check_in", _("Check-in")), ("check_out", _("Check-out"))):
			stamp = _combine(date, row.get(time_field))
			if stamp and stamp > now:
				offenders.append("{0} {1}: {2}".format(
					time_label, _("on"), frappe.format(stamp, {"fieldtype": "Datetime"})))

	if not offenders:
		return

	frappe.throw(
		_(FUTURE_MESSAGE) + "<br><br>" + "<br>".join(dict.fromkeys(offenders)),
		title=_("Future Date / Time Not Allowed"),
	)


def block_half_day_when_on_duty(doc, method=None):
	"""Changes(HP) #20 - On Duty is a full day; Half Day is not offered for it.

	    "Reason = On Duty -> Half Day selection should be disabled/not allowed. Users should
	     only be able to submit the request for a Full Day when the reason is On Duty."

	The form hides and clears the box (attendance_request_on_duty.js), so in practice nobody
	reaches this. It is here because that is a convenience, not a rule: an import, an API
	call or a script can set half_day without the form ever loading, and #20 asks for a
	validation. Half Day Date is cleared with it rather than left behind pointing at a day
	that is no longer half.
	"""
	if doc.doctype != "Attendance Request":
		return
	if doc.get("reason") != "On Duty":
		return
	if not doc.get("half_day"):
		return

	frappe.throw(
		_("An On Duty request is raised for a full day, so Half Day cannot be selected. "
		  "Untick Half Day, or choose a different Reason."),
		title=_("Half Day Not Allowed for On Duty"),
	)


def block_saturday_half_day(doc, method=None):
	"""Changes(HP) #7 - Saturday is a full working day, so it cannot be regularised as half."""
	if doc.doctype != "Attendance Request":
		return
	if not doc.get("half_day"):
		return

	# half_day_date is the one day of a range that is actually halved; a single-day
	# request usually carries the same value in from_date, so fall back to it.
	date = doc.get("half_day_date") or doc.get("from_date")
	if not date or getdate(date).weekday() != SATURDAY:
		return

	frappe.throw(
		_("Saturday is a full working day, so {0} cannot be requested as a half day.").format(
			frappe.format(getdate(date), {"fieldtype": "Date"})
		),
		title=_("Half Day Not Allowed on Saturday"),
	)
