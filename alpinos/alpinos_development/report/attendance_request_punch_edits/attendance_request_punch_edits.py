# Copyright (c) 2026, Alpinos and contributors
# License: MIT

"""Attendance Request Punch Edits report.

Lists the punch *edits* made through approved Attendance Requests: for each date where an
existing check-in was present and got changed, it shows the old vs new check-in/check-out.

Only genuine edits are listed — dates that had no prior check-in (On Duty / missing-punch
requests) are excluded, because there is no "old" punch to compare against.
"""

import frappe
from frappe import _
from frappe.utils import getdate, get_first_day, get_last_day, get_datetime, get_time


def execute(filters=None):
	filters = frappe._dict(filters or {})

	# Default the date range to the current month when not supplied.
	if not filters.get("from_date"):
		filters.from_date = get_first_day(getdate())
	if not filters.get("to_date"):
		filters.to_date = get_last_day(getdate())

	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns():
	return [
		{"label": _("Employee"), "fieldname": "employee", "fieldtype": "Link", "options": "Employee", "width": 120},
		{"label": _("Employee Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 160},
		{"label": _("Department"), "fieldname": "department", "fieldtype": "Link", "options": "Department", "width": 150},
		{"label": _("Attendance Request"), "fieldname": "attendance_request", "fieldtype": "Link", "options": "Attendance Request", "width": 170},
		{"label": _("Reason"), "fieldname": "reason", "fieldtype": "Data", "width": 110},
		{"label": _("Date"), "fieldname": "attendance_date", "fieldtype": "Date", "width": 100},
		{"label": _("Old Check-in"), "fieldname": "old_check_in", "fieldtype": "Datetime", "width": 165},
		{"label": _("New Check-in"), "fieldname": "new_check_in", "fieldtype": "Datetime", "width": 165},
		{"label": _("Old Check-out"), "fieldname": "old_check_out", "fieldtype": "Datetime", "width": 165},
		{"label": _("New Check-out"), "fieldname": "new_check_out", "fieldtype": "Datetime", "width": 165},
	]


def _combine(date, text_time):
	"""Combine a date with a typed time-of-day (the new punches are stored as text, e.g.
	'09:00') into a datetime, so old and new punches are comparable. Blank/invalid -> None."""
	if text_time in (None, ""):
		return None
	try:
		return get_datetime(f"{getdate(date)} {get_time(text_time)}")
	except Exception:
		return None


def get_data(filters):
	conditions = ["ar.docstatus = 1", "log.parenttype = 'Attendance Request'", "log.check_in IS NOT NULL"]
	params = {"from_date": getdate(filters.from_date), "to_date": getdate(filters.to_date)}

	conditions.append("log.attendance_date BETWEEN %(from_date)s AND %(to_date)s")
	if filters.get("employee"):
		conditions.append("ar.employee = %(employee)s")
		params["employee"] = filters.employee
	if filters.get("company"):
		conditions.append("ar.company = %(company)s")
		params["company"] = filters.company

	where_clause = " AND ".join(conditions)

	rows = frappe.db.sql(
		f"""
		SELECT
			ar.name AS attendance_request,
			ar.employee, ar.employee_name, ar.department, ar.reason,
			log.attendance_date,
			log.check_in AS old_check_in,
			log.check_out AS old_check_out,
			det.check_in AS new_check_in_text,
			det.check_out AS new_check_out_text
		FROM `tabAttendance Request Log` log
		INNER JOIN `tabAttendance Request` ar ON ar.name = log.parent
		LEFT JOIN `tabAttendance Request Detail` det
			ON det.parent = ar.name
			AND det.parenttype = 'Attendance Request'
			AND det.attendance_date = log.attendance_date
		WHERE {where_clause}
		ORDER BY ar.employee, log.attendance_date, ar.name
		""",
		params,
		as_dict=True,
	)

	data = []
	for r in rows:
		data.append(
			{
				"employee": r.employee,
				"employee_name": r.employee_name,
				"department": r.department,
				"attendance_request": r.attendance_request,
				"reason": r.reason,
				"attendance_date": r.attendance_date,
				"old_check_in": r.old_check_in,
				"new_check_in": _combine(r.attendance_date, r.new_check_in_text),
				"old_check_out": r.old_check_out,
				"new_check_out": _combine(r.attendance_date, r.new_check_out_text),
			}
		)
	return data
