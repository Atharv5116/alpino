"""Upcoming birthdays and work anniversaries for workspace widgets."""

import frappe
from frappe.utils import add_days, add_months, getdate, now_datetime


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
	return frappe.db.get_value("Employee", {"user_id": user}, "name")


@frappe.whitelist()
def get_on_leave_and_wfh_today():
	"""Return employees on leave today and on WFH today, for anybody signed in.

	Changes(HP) HRMS #11: the two sections were on everybody's dashboard but only an HR
	Manager or somebody with direct reports got rows, so most people saw empty panels. The
	day's leave and work-from-home list is what the office needs to know to find each other,
	so it now reads the same for everyone. The reads ignore permissions deliberately: an
	employee cannot list other people's Leave Applications, which would otherwise filter the
	list back to nothing. Only the day's name, leave type and half-day flag go out.
	"""
	today = getdate(now_datetime())
	if frappe.session.user == "Guest":
		return {"allowed": False, "on_leave": [], "on_wfh": []}

	# Everybody sees the whole day's list, as HR does.
	allowed_employee_ids = None

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
		ignore_permissions=True,
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

	# On WFH today. Changes(HP) HRMS #18: this read only Attendance rows with status
	# "Work From Home", and an approved Work From Home Request does not become an Attendance
	# until the day is marked -- normally after it has ended. So during the working day,
	# which is the only time the panel is any use, it always said "No one on WFH today".
	# The approved request is the source of truth for the day in progress; the Attendance
	# row is the source for a day already marked, so both are read and merged.
	seen, on_wfh = set(), []

	def _add_wfh(employee, employee_name=None, source=None):
		if not employee or employee in seen:
			return
		if allowed_employee_ids is not None and employee not in allowed_employee_ids:
			return
		seen.add(employee)
		on_wfh.append({
			"employee": employee,
			"employee_name": employee_name
			or frappe.db.get_value("Employee", employee, "employee_name"),
			"attendance_date": str(today),
			"source": source,
		})

	if frappe.db.exists("DocType", "Work From Home Request"):
		for req in frappe.db.sql(
			"""
			SELECT employee, employee_name
			FROM `tabWork From Home Request`
			WHERE IFNULL(status, '') = 'Approved'
				AND `date` <= %(today)s AND IFNULL(to_date, `date`) >= %(today)s
			""",
			{"today": today}, as_dict=True,
		):
			_add_wfh(req.get("employee"), req.get("employee_name"), "request")

	for att in frappe.get_all(
		"Attendance",
		filters=[
			["docstatus", "=", 1],
			["attendance_date", "=", today],
			["status", "=", "Work From Home"],
		],
		fields=["employee", "employee_name", "attendance_date"],
		ignore_permissions=True,
	):
		_add_wfh(att.get("employee"), att.get("employee_name"), "attendance")

	return {"allowed": True, "on_leave": on_leave, "on_wfh": on_wfh}


def _format_ddmmyyyy(d):
	if not d:
		return ""
	return getdate(d).strftime("%d/%m/%Y")


@frappe.whitelist()
def get_upcoming_employee_lifecycle(days=30):
	"""Upcoming probation/internship completions and salary increments for active employees
	within the next `days` days (HR Manager only). Dates are DD/MM/YYYY in the `date` field."""
	try:
		days = int(days)
	except (TypeError, ValueError):
		days = 30

	roles = frappe.get_roles()
	if not ({"HR Manager", "System Manager", "Administrator"} & set(roles)):
		return {"allowed": False, "probation": [], "internship": [], "increment": []}

	today = getdate(now_datetime())
	end_date = add_days(today, days)

	# Only fetch custom fields that actually exist (robust across sites/migration order).
	meta = frappe.get_meta("Employee")
	has_probation = meta.has_field("probation_end_date")
	has_internship = meta.has_field("custom_internship_duration")

	fields = ["name", "employee_name", "company", "date_of_joining"]
	if has_probation:
		fields.append("probation_end_date")
	if has_internship:
		fields.append("custom_internship_duration")

	employees = frappe.get_all("Employee", filters={"status": "Active"}, fields=fields)

	probation = []
	internship = []
	increment = []

	for emp in employees:
		company = emp.get("company")
		emp_name = emp.get("employee_name")

		# probation completion: explicit probation_end_date within the window
		pend = emp.get("probation_end_date")
		if pend:
			pend = getdate(pend)
			if today <= pend <= end_date:
				probation.append({
					"employee_name": emp_name,
					"date": _format_ddmmyyyy(pend),
					"company": company,
					"_sort": pend.strftime("%Y-%m-%d"),
				})

		doj = emp.get("date_of_joining")

		# internship completion: date_of_joining + duration (months) within the window
		months = emp.get("custom_internship_duration")
		if doj and months:
			try:
				months = int(months)
			except (TypeError, ValueError):
				months = 0
			if months > 0:
				iend = getdate(add_months(getdate(doj), months))
				if today <= iend <= end_date:
					internship.append({
						"employee_name": emp_name,
						"date": _format_ddmmyyyy(iend),
						"company": company,
						"_sort": iend.strftime("%Y-%m-%d"),
					})

		# salary increment: next date_of_joining anniversary within the window
		if doj:
			doj = getdate(doj)
			if doj <= today:
				next_year = today.year
				this_year_anniv = _date_in_year(doj, today.year)
				if this_year_anniv < today:
					next_year += 1
				next_anniv = _date_in_year(doj, next_year)
				if today <= next_anniv <= end_date:
					years = max(next_year - doj.year, 1)
					increment.append({
						"employee_name": emp_name,
						"date": _format_ddmmyyyy(next_anniv),
						"years": years,
						"company": company,
						"_sort": next_anniv.strftime("%Y-%m-%d"),
					})

	def _top(rows):
		rows = sorted(rows, key=lambda x: x["_sort"])[:10]
		for r in rows:
			r.pop("_sort", None)
		return rows

	return {
		"allowed": True,
		"probation": _top(probation),
		"internship": _top(internship),
		"increment": _top(increment),
	}
