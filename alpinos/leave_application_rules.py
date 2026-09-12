"""Leave Application rules that are Alpino's rather than HRMS's.

HRMS is happy to half-day any date. Alpino works a full Saturday, so a Saturday half day
would credit half a day the employee was expected to work in full -- the same rule Work
From Home Request already carries in block_saturday_half_day.
"""

import frappe
from frappe import _
from frappe.utils import getdate

#: Python's weekday(): Monday is 0, so Saturday is 5.
SATURDAY = 5


def block_saturday_half_day(doc, method=None):
	"""Saturday counts as a full working day, so it cannot be taken as a half day.

	The date checked is half_day_date, which is the one day of a multi-day application
	that is actually halved -- not from_date. A single-day application usually carries
	the same value in both, but a leave from Thursday to Saturday halved on the Thursday
	must stay allowed, and one halved on the Saturday must not.
	"""
	if doc.doctype != "Leave Application":
		return
	if not doc.get("half_day"):
		return

	# half_day_date is blank until HRMS defaults it, and on a one-day application the
	# only candidate is from_date; fall back rather than skip the check entirely.
	date = doc.get("half_day_date") or doc.get("from_date")
	if not date:
		return

	if getdate(date).weekday() != SATURDAY:
		return

	frappe.throw(
		_("Saturday is a full working day, so {0} cannot be applied as a half day.").format(
			frappe.format(getdate(date), {"fieldtype": "Date"})
		),
		title=_("Half Day Not Allowed on Saturday"),
	)
