"""Scheduled alert: employees with no check-in by 11:30 AM and no approved leave.

Runs daily at 11:30 (see scheduler_events in hooks.py). For every active employee
that has not checked in by 11:30 today and is not exempt, an alert is sent:
  - one digest email to all HR Managers (listing every flagged employee), and
  - one email to each direct manager (listing only their flagged direct reports).

Exemptions (NO alert):
  - today is a holiday / weekly-off in the employee's holiday list,
  - a full-day approved leave covering today,
  - an approved HALF-DAY leave for today whose half is the FIRST half (morning off,
    so no morning check-in is expected). A SECOND-half (or unspecified) half-day leave
    still requires a morning check-in, so it does NOT exempt.

Manual run (testing):
  bench --site <site> execute alpinos.attendance_alerts.notify_missing_checkins
"""

import frappe
from frappe.utils import escape_html, format_date, get_datetime, getdate, now_datetime

CHECKIN_CUTOFF = "11:30:00"


def get_flagged_employees(today=None):
	"""Return (today, [Employee dicts]) for active employees with no check-in by the
	11:30 cutoff today and no exemption (holiday, full-day leave, first-half half-day).
	Shared by the scheduled email and the workspace dashboard.
	"""
	if today is None:
		today = getdate(now_datetime())
	day_start = get_datetime(f"{today} 00:00:00")
	cutoff = get_datetime(f"{today} {CHECKIN_CUTOFF}")

	employees = frappe.get_all(
		"Employee",
		filters={"status": "Active"},
		fields=["name", "employee_name", "company", "department", "reports_to", "holiday_list"],
	)

	flagged = []
	for emp in employees:
		if _is_holiday(emp, today):
			continue
		if _has_checkin_by_cutoff(emp.name, day_start, cutoff):
			continue
		if _is_exempt_by_leave(emp.name, today):
			continue
		flagged.append(emp)
	return today, flagged


def notify_missing_checkins():
	today, flagged = get_flagged_employees()
	if not flagged:
		return
	_send_hr_digest(flagged, today)
	_send_manager_emails(flagged, today)


@frappe.whitelist()
def get_missing_checkins_today():
	"""Live data for the workspace widget. HR Manager sees every flagged employee; a
	reporting manager sees only their direct reports; everyone else gets allowed=False.
	"""
	from alpinos.people_events import _get_employee_for_user

	roles = frappe.get_roles()
	is_hr_manager = "HR Manager" in roles
	employee = _get_employee_for_user(frappe.session.user)
	direct_reports = []
	if employee:
		direct_reports = frappe.get_all(
			"Employee", filters={"reports_to": employee, "status": "Active"}, pluck="name"
		)

	allowed = is_hr_manager or bool(direct_reports)
	if not allowed:
		return {"allowed": False, "date": "", "employees": []}

	today, flagged = get_flagged_employees()
	allowed_ids = None if is_hr_manager else set(direct_reports)
	date_str = format_date(today)

	rows = []
	for emp in flagged:
		if allowed_ids is not None and emp.name not in allowed_ids:
			continue
		rows.append({
			"employee": emp.name,
			"employee_name": emp.employee_name,
			"department": emp.get("department") or "",
			"date": date_str,
		})
	return {"allowed": True, "date": date_str, "employees": rows}


# ---------------------------------------------------------------------------
# Exemption checks
# ---------------------------------------------------------------------------

def _has_checkin_by_cutoff(employee, day_start, cutoff):
	return bool(
		frappe.db.exists(
			"Employee Checkin",
			{"employee": employee, "time": ["between", [day_start, cutoff]]},
		)
	)


def _is_holiday(emp, today):
	holiday_list = emp.get("holiday_list")
	if not holiday_list:
		try:
			from erpnext.setup.doctype.employee.employee import get_holiday_list_for_employee

			holiday_list = get_holiday_list_for_employee(emp.name, raise_exception=False)
		except Exception:
			holiday_list = None
	if not holiday_list and emp.get("company"):
		holiday_list = frappe.db.get_value("Company", emp.company, "default_holiday_list")
	if not holiday_list:
		return False
	return bool(
		frappe.db.exists("Holiday", {"parent": holiday_list, "holiday_date": today})
	)


def _is_exempt_by_leave(employee, today):
	"""Approved leave covering today exempts the employee, EXCEPT a second-half (or
	unspecified) half-day leave for today, which still requires a morning check-in.
	"""
	has_period = frappe.get_meta("Leave Application").has_field("custom_half_day_period")
	fields = ["name", "half_day", "half_day_date"]
	if has_period:
		fields.append("custom_half_day_period")

	leaves = frappe.get_all(
		"Leave Application",
		filters={
			"employee": employee,
			"docstatus": 1,
			"status": "Approved",
			"from_date": ["<=", today],
			"to_date": [">=", today],
		},
		fields=fields,
	)

	for lv in leaves:
		is_half_today = lv.get("half_day") and lv.get("half_day_date") and getdate(lv.half_day_date) == today
		if not is_half_today:
			# Full-day leave covering today -> exempt.
			return True
		# Half-day leave on today: exempt only when the FIRST half is the leave.
		period = (lv.get("custom_half_day_period") or "").strip() if has_period else ""
		if period == "First Half":
			return True
	return False


# ---------------------------------------------------------------------------
# Email building / sending
# ---------------------------------------------------------------------------

def _valid_user_emails(users):
	emails, seen = [], set()
	for u in users:
		if not u or u in seen or u in ("Administrator", "Guest"):
			continue
		seen.add(u)
		row = frappe.db.get_value("User", u, ["enabled", "email"], as_dict=True)
		if row and row.enabled and row.email:
			emails.append(row.email)
	return emails


def _get_hr_manager_recipients():
	users = frappe.get_all(
		"Has Role",
		filters={"role": "HR Manager", "parenttype": "User"},
		pluck="parent",
	)
	return _valid_user_emails(users)


def _table_html(flagged, today):
	th = "padding:6px 10px;border:1px solid #e5e7eb;text-align:left;background:#f9fafb;"
	td = "padding:6px 10px;border:1px solid #e5e7eb;"
	head = (
		f"<th style='{th}'>Sr No.</th>"
		f"<th style='{th}'>Employee ID/Name</th>"
		f"<th style='{th}'>Date</th>"
		f"<th style='{th}'>Department</th>"
	)
	date_str = escape_html(format_date(today))

	rows = ""
	for idx, emp in enumerate(flagged, start=1):
		emp_id_name = f"{emp.name} — {emp.employee_name}" if emp.get("employee_name") else emp.name
		rows += (
			"<tr>"
			f"<td style='{td}'>{idx}</td>"
			f"<td style='{td}'>{escape_html(emp_id_name)}</td>"
			f"<td style='{td}'>{date_str}</td>"
			f"<td style='{td}'>{escape_html(emp.get('department') or '')}</td>"
			"</tr>"
		)

	return (
		"<table style='border-collapse:collapse;font-size:13px;'>"
		f"<thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>"
	)


def _footer():
	return (
		"<p style='color:#6b7280;font-size:12px;margin-top:12px;'>"
		"Automated attendance alert from Alpinos.</p>"
	)


def _send(recipients, subject, message):
	if not recipients:
		return
	try:
		frappe.sendmail(recipients=recipients, subject=subject, message=message)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Missing Check-in Alert Email")


def _send_hr_digest(flagged, today):
	msg = (
		f"<p>The following <b>{len(flagged)}</b> employee(s) had <b>no check-in by 11:30 AM</b> "
		f"on <b>{format_date(today)}</b> and have no approved leave for the day:</p>"
		+ _table_html(flagged, today)
		+ _footer()
	)
	_send(
		_get_hr_manager_recipients(),
		f"Attendance Alert: {len(flagged)} employee(s) with no check-in by 11:30 AM ({format_date(today)})",
		msg,
	)


def _send_manager_emails(flagged, today):
	by_manager = {}
	for emp in flagged:
		if emp.get("reports_to"):
			by_manager.setdefault(emp.reports_to, []).append(emp)

	for manager_emp, team in by_manager.items():
		manager_user = frappe.db.get_value("Employee", manager_emp, "user_id")
		recipients = _valid_user_emails([manager_user]) if manager_user else []
		if not recipients:
			continue
		msg = (
			f"<p>The following member(s) of your team had <b>no check-in by 11:30 AM</b> "
			f"on <b>{format_date(today)}</b> and have no approved leave for the day:</p>"
			+ _table_html(team, today)
			+ _footer()
		)
		_send(
			recipients,
			f"Attendance Alert: your team — no check-in by 11:30 AM ({format_date(today)})",
			msg,
		)
