from __future__ import annotations

from datetime import datetime
from typing import Optional

import frappe
from frappe.utils import add_days, flt, get_datetime, getdate, now_datetime

from erpnext.setup.doctype.employee.employee import get_holiday_list_for_employee


def _get_employee_for_user(user):
    return frappe.db.get_value("Employee", {"user_id": user}, "name")


def _employee_no_biometric(employee):
    """True when the Employee has 'No Biometric' ticked → self check-in via the workspace
    dialog (live photo + location) instead of a biometric device. Preference is per-employee
    (employees of the same company can differ)."""
    if not employee:
        return False
    return bool(frappe.db.get_value("Employee", employee, "custom_no_biometric"))


def _web_checkin_config():
    """(enabled, radius_km) for the eSSL Settings web/mobile check-in rules."""
    enabled = frappe.db.get_single_value("eSSL Settings", "enable_web_checkin_rules")
    radius = flt(frappe.db.get_single_value("eSSL Settings", "web_checkin_radius_km")) or 1.0
    return bool(enabled), radius


def _web_checkin_rules_active(employee):
    """Web check-in rules apply to BIOMETRIC companies (No Biometric un-ticked) when the
    eSSL Settings toggle is on. No-Biometric employees use the photo flow instead."""
    if not employee or _employee_no_biometric(employee):
        return False
    enabled, _ = _web_checkin_config()
    return enabled


def _shift_location_coords(employee, when):
    """Latitude/longitude of the employee's active Shift Location for `when` (or None)."""
    rows = frappe.db.sql(
        """
        SELECT shift_location FROM `tabShift Assignment`
        WHERE employee = %(emp)s AND docstatus = 1 AND status = 'Active'
            AND IFNULL(shift_location, '') != ''
            AND start_date <= %(d)s AND (end_date >= %(d)s OR end_date IS NULL)
        ORDER BY start_date DESC LIMIT 1
        """,
        {"emp": employee, "d": getdate(when)},
    )
    if not rows:
        return None
    return frappe.db.get_value("Shift Location", rows[0][0], ["latitude", "longitude"], as_dict=True)


def _validate_letters_only(value, field_label="Reason"):
    """Reason must be letters only — no digits, spaces or special characters."""
    import re

    if not re.fullmatch(r"[A-Za-z]+", value or ""):
        frappe.throw(
            f"{field_label} must contain letters only (no numbers, spaces or special characters)."
        )


def _save_checkin_image(checkin_name, image):
    """Decode a base64 data-URL captured from the camera and attach it to the checkin."""
    if not image:
        return
    import base64

    data = image
    if "," in data:
        data = data.split(",", 1)[1]
    try:
        content = base64.b64decode(data)
    except Exception:
        return
    from frappe.utils.file_manager import save_file

    _file = save_file(
        f"checkin_{checkin_name}.jpg", content, "Employee Checkin", checkin_name, is_private=1
    )
    frappe.db.set_value(
        "Employee Checkin", checkin_name, "custom_checkin_image", _file.file_url, update_modified=False
    )


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


def _get_today_last_dashboard_log(employee):
    """Latest check-in/out today that originated from the DASHBOARD (no device_id).

    eSSL/biometric punches set `device_id`; dashboard logs do not. The web timer must reflect
    dashboard actions only, so stray device punches never stop or restart it — only a dashboard
    checkout does. Filtered in Python so both NULL and empty-string device_id count as dashboard.
    """
    start, end = _get_today_range()
    logs = frappe.get_all(
        "Employee Checkin",
        filters={"employee": employee, "time": ["between", [start, end]]},
        fields=["name", "log_type", "time", "device_id"],
        order_by="time desc",
    )
    for log in logs:
        if not log.get("device_id"):
            return [log]
    return []


@frappe.whitelist()
def get_status():
    employee = _get_employee_for_user(frappe.session.user)
    no_bio = _employee_no_biometric(employee)
    web_rules = _web_checkin_rules_active(employee)
    base = {"no_biometric": no_bio, "web_checkin_rules": web_rules}
    if not employee:
        return {"status": "NONE", "last_time": None, "elapsed_seconds": 0, **base}
    today_in = _get_today_first_checkin(employee)
    if not today_in:
        return {"status": "NONE", "last_time": None, "elapsed_seconds": 0, **base}

    in_time = today_in[0]["time"]
    if no_bio:
        last = _get_today_last_checkin(employee)
        last_out = _get_today_last_checkout(employee)

        if last and last[0]["log_type"] == "IN":
            return {"status": "IN", "last_time": in_time, "elapsed_seconds": None, **base}

        if last_out:
            elapsed_seconds = int((last_out[0]["time"] - in_time).total_seconds())
            return {
                "status": "OUT",
                "last_time": last_out[0]["time"],
                "elapsed_seconds": max(elapsed_seconds, 0),
                **base,
            }

        return {"status": "NONE", "last_time": None, "elapsed_seconds": 0, **base}
    else:
        # Biometric employee: the web timer reflects DASHBOARD actions only. eSSL/device
        # punches (including stray/mistaken ones) never stop or restart it. Only a dashboard
        # checkout stops the timer and flips the widget to "Checked Out". Once that happens it
        # stays OUT for the rest of the day (a later eSSL punch does not revive the web timer).
        last_dash = _get_today_last_dashboard_log(employee)
        if last_dash and last_dash[0]["log_type"] == "OUT":
            elapsed_seconds = int((last_dash[0]["time"] - in_time).total_seconds())
            return {
                "status": "OUT",
                "last_time": last_dash[0]["time"],
                "elapsed_seconds": max(elapsed_seconds, 0),
                **base,
            }
        return {"status": "IN", "last_time": in_time, "elapsed_seconds": None, **base}


@frappe.whitelist()
def get_monthly_attendance(year: Optional[int] = None, month: Optional[int] = None):
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
		return {"days": {}}

	today = getdate(now_datetime())
	try:
		year = int(year) if year not in (None, "") else today.year
		month = int(month) if month not in (None, "") else today.month
	except (TypeError, ValueError):
		year, month = today.year, today.month

	# Validate to avoid "day is out of range for month"
	year = max(2000, min(2100, year))
	# Clamp month to valid range (frontend or API might send 0 or 13)
	if month < 1:
		month += 12
		year -= 1
	if month > 12:
		year += (month - 1) // 12
		month = ((month - 1) % 12) + 1
	year = max(2000, min(2100, year))  # Re-clamp year after month rollover

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
	wfh_dates = _get_wfh_dates(employee, start_date, end_date)

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
		fallback = attendance_times.get(current, {})
		if not check_in_str:
			check_in_str = fallback.get("in_time")
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
			"wfh": 1 if current in wfh_dates else 0,
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


def _get_wfh_dates(employee, from_date, to_date):
	"""Dates the employee has an applied/approved Work From Home Request for. Used to flag a
	day as WFH on the calendar even when its attendance status is Present (check-ins from home)."""
	if not frappe.db.exists("DocType", "Work From Home Request"):
		return set()
	rows = frappe.get_all(
		"Work From Home Request",
		filters={
			"employee": employee,
			"date": ["between", [from_date, to_date]],
			"status": ["in", ["Approved", "Live"]],
		},
		pluck="date",
	)
	return {getdate(d) for d in rows}


@frappe.whitelist()
def check_in(latitude=None, longitude=None, image=None, checkin_type=None, checkin_reason=None):
    if not frappe.has_permission("Employee Checkin", "create"):
        frappe.throw("You do not have permission to Check In.")

    employee = _get_employee_for_user(frappe.session.user)
    if not employee:
        frappe.throw("No Employee linked to this user.")
    today_last = _get_today_last_checkin(employee)
    if _employee_no_biometric(employee):
        if today_last:
            frappe.throw("You can only Check In once per day.")
    else:
        if today_last and today_last[0]["log_type"] == "IN":
            frappe.throw("You are already Checked In.")

    # No-Biometric companies must capture a live photo at check-in.
    if _employee_no_biometric(employee) and not image:
        frappe.throw("A live photo is required to Check In.")

    values = {"doctype": "Employee Checkin", "employee": employee, "log_type": "IN"}

    # Pass optional geolocation data if provided (coerce to float to avoid str/float TypeError in distance calc)
    if latitude is not None:
        values["latitude"] = flt(latitude)
    if longitude is not None:
        values["longitude"] = flt(longitude)

    # Biometric companies with web check-in rules enabled: restrict to Shift Location radius
    # and require a type (+ reason for 'Other').
    if _web_checkin_rules_active(employee):
        enabled, radius_km = _web_checkin_config()
        coords = _shift_location_coords(employee, now_datetime())
        if coords and coords.get("latitude") is not None and (latitude is not None and longitude is not None):
            from hrms.hr.utils import get_distance_between_coordinates

            distance_m = get_distance_between_coordinates(
                flt(coords.latitude), flt(coords.longitude), flt(latitude), flt(longitude)
            )
            if distance_m <= radius_km * 1000.0:
                frappe.throw(
                    "Please use biometric device to checkin"
                )

        checkin_type = (checkin_type or "").strip()
        if checkin_type not in ("Client/Vendor", "Shoot", "Meeting", "Other"):
            frappe.throw("Please select a valid check-in type.")
        values["custom_checkin_type"] = checkin_type
        if checkin_type == "Other":
            checkin_reason = (checkin_reason or "").strip()
            if not checkin_reason:
                frappe.throw("A reason is required when the check-in type is 'Other'.")
            _validate_letters_only(checkin_reason, "Reason")
            values["custom_checkin_reason"] = checkin_reason

    doc = frappe.get_doc(values)
    doc.insert()
    _save_checkin_image(doc.name, image)
    return {"status": "IN", "time": doc.time}


@frappe.whitelist()
def is_within_shift_location(latitude, longitude):
    employee = _get_employee_for_user(frappe.session.user)
    if not employee:
        return {"within_location": False}

    if _employee_no_biometric(employee):
        return {"within_location": False}

    if _web_checkin_rules_active(employee):
        enabled, radius_km = _web_checkin_config()
        coords = _shift_location_coords(employee, now_datetime())
        if coords and coords.get("latitude") is not None and (latitude is not None and longitude is not None):
            from hrms.hr.utils import get_distance_between_coordinates

            distance_m = get_distance_between_coordinates(
                flt(coords.latitude), flt(coords.longitude), flt(latitude), flt(longitude)
            )
            if distance_m <= radius_km * 1000.0:
                return {"within_location": True}

    return {"within_location": False}


@frappe.whitelist()
def get_today_wfh_request():
	employee = _get_employee_for_user(frappe.session.user)
	if not employee:
		return None
	today = getdate(now_datetime())
	result = frappe.db.get_value(
		"Work From Home Request",
		{"employee": employee, "date": today, "status": ["in", ["Draft", "Approved", "Live"]]},
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
def check_out(latitude=None, longitude=None, checkout_reason=None, outside_reason=None, outside_remarks=None, image=None):
    if not frappe.has_permission("Employee Checkin", "create"):
        frappe.throw("You do not have permission to Check Out.")

    employee = _get_employee_for_user(frappe.session.user)
    if not employee:
        frappe.throw("No Employee linked to this user.")
    # Allow a dashboard checkout as long as there is ANY check-in today. We deliberately do
    # NOT require the *last* log to be an IN: an eSSL device OUT (e.g. a mistaken punch near
    # the biometric machine) may be the latest log, yet the employee still needs to check out
    # from the dashboard. The last log's type is irrelevant here.
    if not _get_today_first_checkin(employee):
        frappe.throw("You must Check In today before Check Out.")

    # No-Biometric companies must capture a live photo at check-out and can only check out once.
    if _employee_no_biometric(employee):
        if not image:
            frappe.throw("A live photo is required to Check Out.")
        last_out = _get_today_last_checkout(employee)
        if last_out:
            frappe.throw("You have already Checked Out today.")

    values = {"doctype": "Employee Checkin", "employee": employee, "log_type": "OUT"}

    # Pass optional geolocation data if provided (coerce to float to avoid str/float TypeError in distance calc)
    if latitude is not None:
        values["latitude"] = flt(latitude)
    if longitude is not None:
        values["longitude"] = flt(longitude)

    # Biometric companies with web check-in rules enabled: within the Shift Location radius the
    # employee must check OUT on the biometric device too (mirrors the check-in rule), so the
    # dashboard is only for genuine outside-office checkouts.
    if _web_checkin_rules_active(employee):
        enabled, radius_km = _web_checkin_config()
        coords = _shift_location_coords(employee, now_datetime())
        if coords and coords.get("latitude") is not None and (latitude is not None and longitude is not None):
            from hrms.hr.utils import get_distance_between_coordinates

            distance_m = get_distance_between_coordinates(
                flt(coords.latitude), flt(coords.longitude), flt(latitude), flt(longitude)
            )
            if distance_m <= radius_km * 1000.0:
                frappe.throw(
                    "Please use biometric device to check out"
                )

    # Structured outside-location reason (Client/Vendor, Shoot, Meeting, Other + remarks).
    reason = (str(outside_reason).strip() if outside_reason else "")
    remarks = (str(outside_remarks).strip() if outside_remarks else "")
    if reason:
        values["custom_outside_reason"] = reason
        if remarks:
            values["custom_outside_remarks"] = remarks
        # Also satisfy the geofence override's "reason required" check + keep a readable trail.
        values["checkout_reason"] = f"{reason}: {remarks}" if (reason == "Other" and remarks) else reason
    elif checkout_reason is not None and str(checkout_reason).strip():
        values["checkout_reason"] = str(checkout_reason).strip()

    doc = frappe.get_doc(values)
    doc.insert()
    _save_checkin_image(doc.name, image)
    in_time = _get_today_first_checkin(employee)[0]["time"]
    elapsed_seconds = int((doc.time - in_time).total_seconds())
    
    # Check if there's a Work From Home Request for today (Approved or Draft)
    today = getdate(now_datetime())
    wfh_request = frappe.db.get_value(
        "Work From Home Request",
        {
            "employee": employee,
            "date": today,
            "status": ["in", ["Draft", "Approved", "Live"]]
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

@frappe.whitelist()
def log_frontend_action(action, log_type=None, details=None):
    employee = _get_employee_for_user(frappe.session.user)
    try:
        frappe.get_doc({
            "doctype": "Employee Checkin Log",
            "employee": employee,
            "user": frappe.session.user,
            "action": action,
            "log_type": log_type,
            "details": details,
            "ip_address": getattr(frappe.request, "remote_addr", ""),
            "request_path": getattr(frappe.request, "path", "")
        }).insert(ignore_permissions=True)
    except Exception:
        pass
