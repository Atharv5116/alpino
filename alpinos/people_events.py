"""Upcoming birthdays and work anniversaries for workspace widgets."""

import frappe
from frappe.utils import add_days, getdate, now_datetime


def _format_day_label(d):
	if d is None:
		return ""
	d = getdate(d)
	return d.strftime("%a") + " " + str(d.day)


def _date_in_year(d, year):
	"""Return the same month/day in the given year. Handles Feb 29 in non-leap years (use Feb 28)."""
	try:
		return d.replace(year=year)
	except ValueError:
		# e.g. Feb 29 in a non-leap year
		return d.replace(month=2, day=28, year=year)


@frappe.whitelist()
def get_upcoming_birthdays_and_anniversaries(days=30):
	"""Return upcoming birthdays and work anniversaries for active employees."""
	try:
		days = int(days)
	except (TypeError, ValueError):
		days = 30
	today = getdate(now_datetime())
	end_date = add_days(today, days)

	employees = frappe.get_all(
		"Employee",
		filters={"status": "Active"},
		fields=["name", "employee_name", "date_of_birth", "date_of_joining", "company"],
	)

	birthdays = []
	anniversaries = []

	for emp in employees:
		dob = emp.get("date_of_birth")
		if dob:
			dob = getdate(dob)
			next_bday_year = today.year
			this_year = _date_in_year(dob, today.year)
			if this_year < today:
				next_bday_year += 1
			next_bday = _date_in_year(dob, next_bday_year)
			if today <= next_bday <= end_date:
				birthdays.append({
					"employee_name": emp.get("employee_name"),
					"date": next_bday.strftime("%Y-%m-%d"),
					"day": _format_day_label(next_bday),
					"company": emp.get("company"),
				})

		doj = emp.get("date_of_joining")
		if doj:
			doj = getdate(doj)
			if doj <= today:
				next_anniv_year = today.year
				this_year_anniv = _date_in_year(doj, today.year)
				if this_year_anniv < today:
					next_anniv_year += 1
				next_anniv = _date_in_year(doj, next_anniv_year)
				if today <= next_anniv <= end_date:
					years = max(next_anniv_year - doj.year, 1)
					anniversaries.append({
						"employee_name": emp.get("employee_name"),
						"date": next_anniv.strftime("%Y-%m-%d"),
						"years": years,
						"day": _format_day_label(next_anniv),
						"company": emp.get("company"),
					})

	birthdays = sorted(birthdays, key=lambda x: x["date"])[:10]
	anniversaries = sorted(anniversaries, key=lambda x: x["date"])[:10]
	return {"birthdays": birthdays, "anniversaries": anniversaries}


def _get_employee_for_user(user):
	"""Return Employee name for the given user, or None."""
	return frappe.db.get_value("Employee", {"user_id": user}, "name")


@frappe.whitelist()
def get_on_leave_and_wfh_today():
	"""Return employees on leave today and on WFH today.
	Visible only to HR Manager (sees all) or users who are someone's reporting manager (see only direct reports).
	"""
	today = getdate(now_datetime())
	roles = frappe.get_roles()
	is_hr_manager = "HR Manager" in roles
	employee = _get_employee_for_user(frappe.session.user)
	direct_report_ids = []
	if employee:
		direct_report_ids = frappe.get_all(
			"Employee",
			filters={"reports_to": employee, "status": "Active"},
			pluck="name",
		)
	allowed = is_hr_manager or (employee and len(direct_report_ids) > 0)
	if not allowed:
		return {"allowed": False, "on_leave": [], "on_wfh": []}

	# Employees we are allowed to see: all if HR Manager, else only direct reports
	allowed_employee_ids = None if is_hr_manager else set(direct_report_ids)

	# On leave today: Leave Application, Approved, today between from_date and to_date
	leave_filters = [
		["docstatus", "=", 1],
		["status", "=", "Approved"],
		["from_date", "<=", today],
		["to_date", ">=", today],
	]
	leave_list = frappe.get_all(
		"Leave Application",
		filters=leave_filters,
		fields=["employee", "employee_name", "leave_type", "from_date", "to_date", "half_day", "half_day_date"],
	)
	on_leave = []
	for la in leave_list:
		if allowed_employee_ids is not None and la.get("employee") not in allowed_employee_ids:
			continue
		on_leave.append({
			"employee": la.get("employee"),
			"employee_name": la.get("employee_name"),
			"leave_type": la.get("leave_type"),
			"from_date": la.get("from_date"),
			"to_date": la.get("to_date"),
			"half_day": la.get("half_day"),
			"half_day_date": la.get("half_day_date"),
		})

	# On WFH today: Attendance, Work From Home, attendance_date = today
	wfh_filters = [
		["docstatus", "=", 1],
		["attendance_date", "=", today],
		["status", "=", "Work From Home"],
	]
	wfh_list = frappe.get_all(
		"Attendance",
		filters=wfh_filters,
		fields=["employee", "employee_name", "attendance_date"],
	)
	on_wfh = []
	for att in wfh_list:
		if allowed_employee_ids is not None and att.get("employee") not in allowed_employee_ids:
			continue
		# Attendance may not have employee_name in some versions
		emp_name = att.get("employee_name") or frappe.db.get_value("Employee", att.get("employee"), "employee_name")
		on_wfh.append({
			"employee": att.get("employee"),
			"employee_name": emp_name,
			"attendance_date": str(att.get("attendance_date")) if att.get("attendance_date") else None,
		})

	return {"allowed": True, "on_leave": on_leave, "on_wfh": on_wfh}
