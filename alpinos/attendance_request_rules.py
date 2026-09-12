"""Attendance Request rules from Changes(HP) 6 and 7.

Regularisation is a record of what already happened, so it can never point at a moment
that has not arrived yet (#6), and Alpino works a full Saturday, so a Saturday cannot be
regularised as a half day (#7) -- the same rule Leave Application and Work From Home
Request already carry.
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
