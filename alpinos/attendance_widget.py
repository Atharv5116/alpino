from datetime import datetime

import frappe
from frappe.utils import add_days, flt, get_datetime, getdate, now_datetime

from erpnext.setup.doctype.employee.employee import get_holiday_list_for_employee


def _get_employee_for_user(user):
    return frappe.db.get_value("Employee", {"user_id": user}, "name")


def _get_today_range():
    today = getdate(now_datetime())
    start = get_datetime(today)
    end = add_days(start, 1)
    return start, end


def _get_today_last_checkin(employee):
    start, end = _get_today_range()
    return frappe.get_all(
        "Employee Checkin",
        filters={"employee": employee, "time": ["between", [start, end]]},
        fields=["name", "log_type", "time"],
        order_by="time desc",
        limit=1,
    )


def _get_today_first_checkin(employee):
    start, end = _get_today_range()
    return frappe.get_all(
        "Employee Checkin",
        filters={"employee": employee, "log_type": "IN", "time": ["between", [start, end]]},
        fields=["name", "log_type", "time"],
        order_by="time asc",
        limit=1,
    )


def _get_today_last_checkout(employee):
    start, end = _get_today_range()
    return frappe.get_all(
        "Employee Checkin",
        filters={"employee": employee, "log_type": "OUT", "time": ["between", [start, end]]},
        fields=["name", "log_type", "time"],
        order_by="time desc",
        limit=1,
    )


@frappe.whitelist()
def get_status():
    employee = _get_employee_for_user(frappe.session.user)
    if not employee:
        return {"status": "NONE", "last_time": None, "elapsed_seconds": 0}


@frappe.whitelist()
def get_monthly_attendance(year: int | None = None, month: int | None = None):
	"""Return monthly attendance summary for the logged-in employee.

	Response format:
	{
	    "start_date": "YYYY-MM-DD",
	    "end_date": "YYYY-MM-DD",
	    "days": {
	        "YYYY-MM-DD": {
	            "status": "Present|Absent|On Leave|Half Day|Work From Home|Holiday|None",
	            "check_in": "HH:MM:SS" | null,
	            "check_out": "HH:MM:SS" | null,
	            "holiday": 1 | 0,
	            "worked_minutes": int | null,
	            "late_coming": 0 | 1,
	            "early_leaving": 0 | 1
	        },
	        ...
	    }
	}
	"""
	employee = _get_employee_for_user(frappe.session.user)
	if not employee:
		frappe.throw("No Employee linked to this user.")

	today = getdate(now_datetime())
	year = year or today.year
	month = month or today.month

	# Compute first and last day of the month
	start_date = getdate(f"{year}-{month:02d}-01")
	if month == 12:
		next_month = getdate(f"{year + 1}-01-01")
	else:
		next_month = getdate(f"{year}-{month + 1:02d}-01")
	end_date = add_days(next_month, -1)

	attendance = _get_attendance_map(employee, start_date, end_date)
	attendance_times = _get_attendance_times_map(employee, start_date, end_date)
	checkins = _get_checkins_map(employee, start_date, end_date)
	holidays = set(_get_holidays(employee, start_date, end_date))

	# Optional: late/early vs shift (requires hrms)
	try:
		from hrms.hr.doctype.shift_assignment.shift_assignment import get_employee_shift
		_has_shift = True
	except Exception:
		_has_shift = False

	result = {}
	current = start_date
	while current <= end_date:
		date_str = current.strftime("%Y-%m-%d")
		status = attendance.get(current)
		if not status and current in holidays:
			status = "Holiday"

		ci = checkins.get(current, {})
		check_in_str = ci.get("check_in")
		check_out_str = ci.get("check_out")
		if not check_in_str or not check_out_str:
			fallback = attendance_times.get(current, {})
			if not check_in_str:
				check_in_str = fallback.get("in_time")
			if not check_out_str:
				check_out_str = fallback.get("out_time")

		worked_minutes = None
		late_coming = 0
		early_leaving = 0

		if check_in_str and check_out_str:
			try:
				# Strip microseconds if present (e.g. "09:30:00.123456")
				ci_norm = str(check_in_str).strip().split(".")[0]
				co_norm = str(check_out_str).strip().split(".")[0]
				t_in = datetime.strptime(ci_norm, "%H:%M:%S").time()
				t_out = datetime.strptime(co_norm, "%H:%M:%S").time()
				dt_in = datetime.combine(current, t_in)
				dt_out = datetime.combine(current, t_out)
				if dt_out > dt_in:
					worked_minutes = int((dt_out - dt_in).total_seconds() / 60)
			except Exception:
				pass

			if _has_shift and worked_minutes is not None:
				try:
					# any time on that day to resolve shift
					ts = get_datetime(f"{date_str} 12:00:00")
					shift = get_employee_shift(employee, ts, True)
					if shift and shift.get("start_datetime") and shift.get("end_datetime"):
						s_start = shift["start_datetime"]
						s_end = shift["end_datetime"]
						# compare only time part on same date
						shift_start = datetime.combine(current, s_start.time())
						shift_end = datetime.combine(current, s_end.time())
						if dt_in > shift_start:
							late_coming = 1
						if dt_out < shift_end:
							early_leaving = 1
				except Exception:
					pass

		result[date_str] = {
			"status": status,
			"check_in": check_in_str,
			"check_out": check_out_str,
			"holiday": 1 if current in holidays else 0,
			"worked_minutes": worked_minutes,
			"late_coming": late_coming,
			"early_leaving": early_leaving,
		}
		current = add_days(current, 1)

	return {
		"start_date": start_date.strftime("%Y-%m-%d"),
		"end_date": end_date.strftime("%Y-%m-%d"),
		"days": result,
	}


def _get_attendance_map(employee, from_date, to_date):
	records = frappe.get_all(
		"Attendance",
		filters={
			"employee": employee,
			"attendance_date": ["between", [from_date, to_date]],
			"docstatus": 1,
		},
		fields=["attendance_date", "status"],
	)
	return {getdate(d["attendance_date"]): d["status"] for d in records}


def _get_attendance_times_map(employee, from_date, to_date):
	"""Fallback: in_time/out_time from Attendance when Employee Checkin has no data."""
	records = frappe.get_all(
		"Attendance",
		filters={
			"employee": employee,
			"attendance_date": ["between", [from_date, to_date]],
			"docstatus": 1,
		},
		fields=["attendance_date", "in_time", "out_time"],
	)
	out = {}
	for d in records:
		dt = getdate(d["attendance_date"])
		in_t, out_t = d.get("in_time"), d.get("out_time")
		if in_t is not None or out_t is not None:
			out[dt] = {
				"in_time": in_t.strftime("%H:%M:%S") if hasattr(in_t, "strftime") else (str(in_t).split(" ")[-1][:8] if in_t else None),
				"out_time": out_t.strftime("%H:%M:%S") if hasattr(out_t, "strftime") else (str(out_t).split(" ")[-1][:8] if out_t else None),
			}
	return out


def _get_checkins_map(employee, from_date, to_date):
	records = frappe.get_all(
		"Employee Checkin",
		filters={"employee": employee, "time": ["between", [from_date, add_days(to_date, 1)]]},
		fields=["time", "log_type"],
		order_by="time asc",
	)

	result = {}
	for log in records:
		t = log.get("time")
		if t is None:
			continue
		log_date = getdate(t)
		# Handle both datetime and string (e.g. ISO from JSON)
		if hasattr(t, "strftime"):
			log_time = t.strftime("%H:%M:%S")
		else:
			t_str = str(t).strip()
			if " " in t_str:
				log_time = t_str.split(" ")[-1][:8]  # "HH:MM:SS" or "HH:MM:SS.ffffff"
			elif "T" in t_str:
				log_time = t_str.split("T")[-1][:8]
			else:
				log_time = t_str[:8] if len(t_str) >= 8 else t_str
		if ":" not in log_time:
			continue
		if log_date not in result:
			result[log_date] = {"check_in": None, "check_out": None}

		if log["log_type"] == "IN":
			if not result[log_date]["check_in"]:
				result[log_date]["check_in"] = log_time
		else:
			result[log_date]["check_out"] = log_time

	return result


def _get_holidays(employee, from_date, to_date):
	holiday_list = get_holiday_list_for_employee(employee, raise_exception=False)
	if not holiday_list:
		return []

	return frappe.get_all(
		"Holiday",
		filters={"parent": holiday_list, "holiday_date": ["between", [from_date, to_date]]},
		pluck="holiday_date",
	)


@frappe.whitelist()
def check_in(latitude=None, longitude=None):
    if not frappe.has_permission("Employee Checkin", "create"):
        frappe.throw("You do not have permission to Check In.")

    employee = _get_employee_for_user(frappe.session.user)
    if not employee:
        frappe.throw("No Employee linked to this user.")
    today_last = _get_today_last_checkin(employee)
    if today_last:
        frappe.throw("You can only Check In once per day.")

    values = {"doctype": "Employee Checkin", "employee": employee, "log_type": "IN"}

    # Pass optional geolocation data if provided (coerce to float to avoid str/float TypeError in distance calc)
    if latitude is not None:
        values["latitude"] = flt(latitude)
    if longitude is not None:
        values["longitude"] = flt(longitude)

    doc = frappe.get_doc(values)
    doc.insert()
    return {"status": "IN", "time": doc.time}


@frappe.whitelist()
def get_today_wfh_request():
	employee = _get_employee_for_user(frappe.session.user)
	if not employee:
		return None
	today = getdate(now_datetime())
	result = frappe.db.get_value(
		"Work From Home Request",
		{"employee": employee, "date": today, "status": ["in", ["Draft", "Approved"]]},
		["name", "status"],
		as_dict=True,
	)
	if not result:
		return None
	tasks = frappe.get_all(
		"Work From Home Task",
		filters={"parent": result.name},
		fields=["task_name", "status"],
		order_by="idx asc",
	)
	result["tasks"] = tasks
	return result


@frappe.whitelist()
def save_wfh_tasks(wfh_request, tasks):
	tasks = frappe.parse_json(tasks)
	doc = frappe.get_doc("Work From Home Request", wfh_request)
	doc.tasks = []
	for t in tasks:
		doc.append("tasks", {"task_name": t.get("task_name"), "status": t.get("status")})
	doc.save(ignore_permissions=True)
	return True


@frappe.whitelist()
def check_out(latitude=None, longitude=None, checkout_reason=None):
    if not frappe.has_permission("Employee Checkin", "create"):
        frappe.throw("You do not have permission to Check Out.")

    employee = _get_employee_for_user(frappe.session.user)
    if not employee:
        frappe.throw("No Employee linked to this user.")
    today_last = _get_today_last_checkin(employee)
    if not today_last or today_last[0]["log_type"] != "IN":
        frappe.throw("You must Check In today before Check Out.")

    last_out = _get_today_last_checkout(employee)
    if last_out:
        frappe.throw("You have already Checked Out today.")

    values = {"doctype": "Employee Checkin", "employee": employee, "log_type": "OUT"}

    # Pass optional geolocation data if provided (coerce to float to avoid str/float TypeError in distance calc)
    if latitude is not None:
        values["latitude"] = flt(latitude)
    if longitude is not None:
        values["longitude"] = flt(longitude)
    if checkout_reason is not None and str(checkout_reason).strip():
        values["checkout_reason"] = str(checkout_reason).strip()

    doc = frappe.get_doc(values)
    doc.insert()
    in_time = _get_today_first_checkin(employee)[0]["time"]
    elapsed_seconds = int((doc.time - in_time).total_seconds())
    
    # Check if there's a Work From Home Request for today (Approved or Draft)
    today = getdate(now_datetime())
    wfh_request = frappe.db.get_value(
        "Work From Home Request",
        {
            "employee": employee,
            "date": today,
            "status": ["in", ["Draft", "Approved"]]
        },
        "name"
    )
    
    return {
        "status": "OUT", 
        "time": doc.time, 
        "elapsed_seconds": max(elapsed_seconds, 0),
        "wfh_request": wfh_request,
        "show_task_dialog": bool(wfh_request)
    }

