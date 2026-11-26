from __future__ import annotations

from typing import Optional

import frappe
from frappe.utils import add_days, flt, get_datetime, getdate, now_datetime

from erpnext.setup.doctype.employee.employee import get_holiday_list_for_employee

from alpinos.company_scope.helpers import assert_company


def _get_employee_for_user(user):
    return frappe.db.get_value("Employee", {"user_id": user}, "name", order_by="name asc")


def _employee_no_biometric(employee):
    """True when the Employee has 'No Biometric' ticked (self check-in via the workspace dialog)."""
    if not employee:
        return False
    return bool(frappe.db.get_value("Employee", employee, "custom_no_biometric"))


def _approved_wfh_today(employee):
    """True when the employee has an approved Work From Home Request for today
    (the check-in geo-fence is skipped and a daily task update is collected on checkout)."""
    if not employee or not frappe.db.exists("DocType", "Work From Home Request"):
        return False
    return bool(
        frappe.db.exists(
            "Work From Home Request",
            {
                "employee": employee,
                "date": getdate(now_datetime()),
                "status": ["in", ["Approved", "Live"]],
            },
        )
    )


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
    """Reason must be words of letters and spaces only (no digits or special characters)."""
    import re

    if not re.fullmatch(r"[A-Za-z]+(?:\s+[A-Za-z]+)*", (value or "").strip()):
        frappe.throw(
            f"{field_label} must contain letters and spaces only (no numbers or special characters)."
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
    """Latest check-in/out today that came from the dashboard (no device_id).
    eSSL/biometric punches set device_id; dashboard logs don't. Filtered in Python so both
    NULL and empty-string device_id count as dashboard."""
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
    # company-scope: n/a (own records)
    employee = _get_employee_for_user(frappe.session.user)
    no_bio = _employee_no_biometric(employee)
    web_rules = _web_checkin_rules_active(employee)
    base = {
        "no_biometric": no_bio,
        "web_checkin_rules": web_rules,
        "approved_wfh": _approved_wfh_today(employee),
    }
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
        # biometric employee: the web timer reflects dashboard actions only; only a dashboard
        # checkout stops it, and it stays OUT for the rest of the day.
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
	"""Monthly attendance summary for the logged-in employee: per-day status, check-in/out
	times, holiday/WFH flags, worked minutes, and late/early flags vs shift."""
	# company-scope: n/a (own records)
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
	year = max(2000, min(2100, year))

	start_date = getdate(f"{year}-{month:02d}-01")
	if month == 12:
		next_month = getdate(f"{year + 1}-01-01")
	else:
		next_month = getdate(f"{year}-{month + 1:02d}-01")
	end_date = add_days(next_month, -1)

	details = _get_attendance_details(employee, start_date, end_date)
	attendance_times = _get_attendance_times_map(employee, start_date, end_date)
	checkins = _get_checkins_map(employee, start_date, end_date)
	holiday_info = _get_holiday_info(employee, start_date, end_date)
	holidays = set(holiday_info)
	regularized = _get_regularized_days(employee, start_date, end_date)
	leave_days = _get_leave_days(employee, start_date, end_date)
	wfh_days = _get_wfh_days(employee, start_date, end_date)
	outside_geo = _get_outside_geo_map(employee, start_date, end_date)

	result = {}
	threshold_cache = {}
	shift_cache = {}
	current = start_date
	while current <= end_date:
		date_str = current.strftime("%Y-%m-%d")
		att = details.get(current)
		status = (att or {}).get("status")
		lv = leave_days.get(current)
		wf = wfh_days.get(current)
		leave_type = (att or {}).get("leave_type") or None
		if not status and current in holidays:
			status = "Holiday"
		if not status and lv and not lv["half"]:
			# an approved full-day leave not marked yet (a day ahead, or today): show it
			status, leave_type = "On Leave", lv["leave_type"]

		# Both times read the PUNCH first and fall back to the Attendance record, so the
		# pair always comes from the same source. The out-time used to read Attendance
		# only, which showed a dash whenever the day had no Attendance yet, had one that
		# was never submitted, or had one whose out_time was still null because the OUT
		# punch landed after auto-attendance ran -- even though the OUT was sitting in
		# Employee Checkin the whole time. It also let the in-time come from the punch
		# while the out-time came from Attendance, so the two halves of one day could
		# disagree. worked_minutes and the day colouring key off these, so this decides
		# more than the label.
		ci = checkins.get(current, {})
		fallback = attendance_times.get(current, {})
		check_in_str = ci.get("check_in") or fallback.get("in_time")
		check_out_str = ci.get("check_out") or fallback.get("out_time")

		worked_minutes = None
		late_coming = 0
		late_minutes = None
		early_leaving = 0
		required_minutes = None
		in_min = _clock_minutes(check_in_str)
		out_min = _clock_minutes(check_out_str)
		in_sec, out_sec = _clock_seconds(check_in_str), _clock_seconds(check_out_str)
		if in_sec is not None and out_sec is not None and out_sec > in_sec:
			worked_minutes = int((out_sec - in_sec) / 60)

		# Every time on the day is read against THAT day's shift: the one its Attendance was
		# marked under, else the employee's assigned / default shift at the punch.
		shift = None
		if check_in_str or (att or {}).get("status") == "Half Day" or (lv and lv["half"]) or (wf and wf["half"]):
			shift = _day_shift(employee, current, (att or {}).get("shift"), shift_cache)
		halves = _day_halves(att, lv, wf, in_min, out_min, shift)
		if shift and in_min is not None:
			late_minutes, late_coming = _lateness(in_min, shift, halves)
		if shift and out_min is not None and in_min is not None and worked_minutes is not None:
			if _from_shift_start(out_min, shift) < shift["span"]:
				early_leaving = 1
		if worked_minutes is not None:
			required_minutes = _full_day_minutes(shift["name"] if shift else None, current, threshold_cache)

		geo = outside_geo.get(current) if not wf else None

		result[date_str] = {
			"status": status,
			"check_in": check_in_str,
			"check_out": check_out_str,
			"holiday": 1 if current in holidays else 0,
			"holiday_name": (holiday_info.get(current) or {}).get("description"),
			"weekly_off": 1 if (holiday_info.get(current) or {}).get("weekly_off") else 0,
			"regularized": 1 if current in regularized else 0,
			"wfh": 1 if wf else 0,
			"wfh_half": 1 if wf and wf["half"] else 0,
			"leave_type": leave_type or (lv["leave_type"] if lv else None),
			"halves": halves,
			"worked_minutes": worked_minutes,
			"required_minutes": required_minutes,
			"late_coming": late_coming,
			"late_minutes": late_minutes,
			"early_leaving": early_leaving,
			"shift": shift["name"] if shift else None,
			"shift_start": shift["start_label"] if shift else None,
			"shift_end": shift["end_label"] if shift else None,
			"late_grace": shift["grace"] if shift else None,
			"late_marking": 1 if shift and shift["late_on"] else 0,
			"out_of_geo": 1 if geo else 0,
			"geo_reason": (geo or {}).get("reason") if geo else None,
		}
		current = add_days(current, 1)

	return {
		"start_date": start_date.strftime("%Y-%m-%d"),
		"end_date": end_date.strftime("%Y-%m-%d"),
		"days": result,
	}


# ---------------------------------------------------------------------------------------
# Half days, shift-wise times and outside geo-fence punches for the calendar
# ---------------------------------------------------------------------------------------

HALF_LABEL = {"present": "Present", "absent": "Absent", "wfh": "WFH", "open": "Working"}


def _clock_seconds(value):
	"""'HH:MM[:SS[.ffffff]]' (or a datetime / time) to seconds after midnight."""
	if value in (None, ""):
		return None
	if hasattr(value, "hour"):
		return value.hour * 3600 + value.minute * 60 + value.second
	s = str(value).strip()
	if "T" in s:
		s = s.split("T")[-1]
	if " " in s:
		s = s.split(" ")[-1]
	parts = s.split(".")[0].split(":")
	try:
		return int(parts[0]) * 3600 + int(parts[1]) * 60 + (int(parts[2]) if len(parts) > 2 else 0)
	except (ValueError, IndexError):
		return None


def _clock_minutes(value):
	sec = _clock_seconds(value)
	return None if sec is None else sec // 60


def _td_minutes(value):
	if value is None:
		return None
	if hasattr(value, "total_seconds"):
		return int(value.total_seconds() // 60) % 1440
	return _clock_minutes(value)


def _shift_row(name, cache):
	key = ("shift", name)
	if key not in cache:
		row = frappe.db.get_value(
			"Shift Type", name,
			["name", "start_time", "end_time", "enable_late_entry_marking", "late_entry_grace_period"],
			as_dict=True,
		)
		if row:
			start, end = _td_minutes(row.start_time), _td_minutes(row.end_time)
			if start is None or end is None:
				row = None
			else:
				span = (end - start) % 1440 or 1440   # an overnight shift wraps past midnight
				row = {
					"name": row.name,
					"start": start,
					"span": span,
					"start_label": f"{start // 60:02d}:{start % 60:02d}",
					"end_label": f"{end // 60:02d}:{end % 60:02d}",
					"late_on": bool(row.enable_late_entry_marking),
					"grace": int(row.late_entry_grace_period or 0),
				}
		cache[key] = row
	return cache[key]


def _day_shift(employee, day, attendance_shift, cache):
	name = attendance_shift
	if not name:
		try:
			from hrms.hr.doctype.shift_assignment.shift_assignment import get_employee_shift

			found = get_employee_shift(employee, get_datetime(f"{day} 12:00:00"), True)
			if found and found.get("shift_type"):
				name = found["shift_type"].name
		except Exception:
			name = None
	return _shift_row(name, cache) if name else None


def _from_shift_start(minute, shift):
	"""Minutes from the shift's start to `minute`, read on the shift's own clock (so a punch
	just after midnight on a night shift is not 20 hours early)."""
	d = minute - shift["start"]
	if d < -720:
		d += 1440
	elif d > 1080 and shift["span"] < 1080:
		d -= 1440
	return d


def _lateness(in_min, shift, halves=None):
	"""(minutes late, 1/0 late) for the day's first punch.

	Counted from the shift's start, or from the middle of the shift when the first half was
	leave, WFH or absent (the employee was due in the office only for the second half).
	Late follows the Shift Type: only when HR switched late-entry marking on, and only past
	that shift's own grace period."""
	due = 0
	if halves and halves[0]["kind"] in ("leave", "wfh", "absent"):
		due = shift["span"] / 2
	minutes = int(max(_from_shift_start(in_min, shift) - due, 0))
	return minutes, (1 if shift["late_on"] and minutes > shift["grace"] else 0)


def _period(value):
	v = (value or "").strip().lower()
	if v.startswith("first"):
		return "first"
	if v.startswith("second"):
		return "second"
	return None


def _worked_half(in_min, out_min, shift):
	""""first" / "second": the half of the shift the punches cover more of; None without a
	punch or a shift. With no OUT yet, the day is read as half a shift from the IN."""
	if in_min is None or not shift:
		return None
	half = shift["span"] / 2
	a = _from_shift_start(in_min, shift)
	b = _from_shift_start(out_min, shift) if out_min is not None else a + half
	if b <= a:
		b = a + half
	first = max(0, min(b, half) - max(a, 0))
	second = max(0, min(b, shift["span"]) - max(a, half))
	return "first" if first >= second else "second"


def _day_halves(att, lv, wf, in_min, out_min, shift):
	"""[first half, second half] for a half day, each {"kind", "label"}; None for a whole day.

	A half-day Leave or WFH is placed on the half its application names (First / Second
	Half). Older applications that name none are placed by the punches against the day's
	shift: the half the employee was in for is the worked half, so the leave / WFH is the
	other. A Half Day marked for short hours (no leave) is read the same way: the half the
	employee was not there for is the Absent one.
	"""
	att = att or {}
	status = att.get("status")
	marked_half = status == "Half Day"

	leave_half = None
	if marked_half and att.get("leave_type"):
		leave_half = {"kind": "leave", "label": f"Leave ({att['leave_type']})",
			"period": _period((lv or {}).get("period"))}
	elif lv and lv["half"] and status in (None, "", "Half Day", "Present", "Work From Home"):
		leave_half = {"kind": "leave", "label": f"Leave ({lv['leave_type']})", "period": _period(lv.get("period"))}

	wfh_half = None
	if wf and wf["half"] and status not in ("On Leave", "Absent"):
		wfh_half = {"kind": "wfh", "label": HALF_LABEL["wfh"], "period": _period(wf.get("period"))}

	if not (leave_half or wfh_half or marked_half):
		return None

	worked = _worked_half(in_min, out_min, shift)

	if leave_half and wfh_half:
		special, other = leave_half, dict(wfh_half)
	elif leave_half or wfh_half:
		special = leave_half or wfh_half
		if marked_half and (att.get("half_day_status") or "") == "Absent":
			other = {"kind": "absent"}
		elif status or in_min is not None:
			other = {"kind": "present"}
		else:
			other = {"kind": "open"}       # not marked yet: the other half is still to be worked
	else:
		# Half Day for short hours: one half worked, the other Absent
		if (att.get("half_day_status") or "") == "Present":
			return None
		special, other = {"kind": "absent", "label": "Absent", "period": None}, {"kind": "present"}
		special["period"] = "first" if worked == "second" else "second"

	period = special.get("period")
	if not period and other.get("period"):
		period = "second" if other["period"] == "first" else "first"
	if not period:
		# the leave / WFH half is the one the punches do not cover; first when there are none
		period = "first" if worked != "first" else "second"
	special_out = {"kind": special["kind"], "label": special["label"]}
	other_out = {"kind": other["kind"], "label": other.get("label") or HALF_LABEL[other["kind"]]}
	return [special_out, other_out] if period == "first" else [other_out, special_out]


def _get_holiday_info(employee, from_date, to_date):
	"""{date: {description, weekly_off}} from the employee's holiday list."""
	holiday_list = get_holiday_list_for_employee(employee, raise_exception=False)
	if not holiday_list:
		return {}
	rows = frappe.get_all(
		"Holiday",
		filters={"parent": holiday_list, "holiday_date": ["between", [from_date, to_date]]},
		fields=["holiday_date", "description", "weekly_off"],
	)
	out = {}
	for r in rows:
		text = frappe.utils.strip_html(r.description or "").strip()
		out[getdate(r.holiday_date)] = {"description": text, "weekly_off": r.weekly_off}
	return out


def _get_regularized_days(employee, from_date, to_date):
	"""Dates an approved (submitted) Attendance Request corrected."""
	rows = frappe.get_all(
		"Attendance Request",
		filters={"employee": employee, "docstatus": 1, "from_date": ["<=", to_date], "to_date": [">=", from_date]},
		fields=["from_date", "to_date"],
	)
	out = set()
	for r in rows:
		day = max(getdate(r.from_date), getdate(from_date))
		while day <= min(getdate(r.to_date), getdate(to_date)):
			out.add(day)
			day = add_days(day, 1)
	return out


def _get_attendance_details(employee, from_date, to_date):
	records = frappe.get_all(
		"Attendance",
		filters={
			"employee": employee,
			"attendance_date": ["between", [from_date, to_date]],
			"docstatus": 1,
		},
		fields=["attendance_date", "status", "leave_type", "leave_application", "half_day_status", "shift"],
	)
	return {getdate(d.attendance_date): d for d in records}


def _get_leave_days(employee, from_date, to_date):
	"""Approved leave per date: {date: {leave_type, half, period}}."""
	has_period = frappe.db.has_column("Leave Application", "custom_half_day_period")
	fields = ["name", "leave_type", "from_date", "to_date", "half_day", "half_day_date"]
	if has_period:
		fields.append("custom_half_day_period")
	apps = frappe.get_all(
		"Leave Application",
		filters={
			"employee": employee,
			"docstatus": 1,
			"status": "Approved",
			"from_date": ["<=", to_date],
			"to_date": [">=", from_date],
		},
		fields=fields,
		order_by="from_date asc",
	)
	out = {}
	for a in apps:
		day = max(getdate(a.from_date), getdate(from_date))
		last = min(getdate(a.to_date), getdate(to_date))
		half_on = getdate(a.half_day_date) if a.half_day and a.half_day_date else (
			getdate(a.from_date) if a.half_day and a.from_date == a.to_date else None
		)
		while day <= last:
			out[day] = {
				"name": a.name,
				"leave_type": a.leave_type,
				"half": day == half_on,
				"period": a.get("custom_half_day_period") if day == half_on else None,
			}
			day = add_days(day, 1)
	return out


def _get_wfh_days(employee, from_date, to_date):
	"""Approved Work From Home per date, across the request's whole range: {date: {half, period}}.

	A half-day request is half on its first date (the requests carry one half-day flag and no
	separate half-day date)."""
	if not frappe.db.exists("DocType", "Work From Home Request"):
		return {}
	meta = frappe.get_meta("Work From Home Request")
	fields = ["date"] + [f for f in ("to_date", "half_day", "custom_half_day_period") if meta.has_field(f)]
	rows = frappe.get_all(
		"Work From Home Request",
		filters={
			"employee": employee,
			"status": ["in", ["Approved", "Live"]],
			"date": ["<=", to_date],
		},
		fields=fields,
	)
	out = {}
	for r in rows:
		first = getdate(r.date)
		last = getdate(r.get("to_date") or r.date)
		if last < getdate(from_date):
			continue
		day = max(first, getdate(from_date))
		while day <= min(last, getdate(to_date)):
			half = bool(r.get("half_day")) and day == first
			if day not in out or not half:
				out[day] = {"half": half, "period": r.get("custom_half_day_period") if half else None}
			day = add_days(day, 1)
	return out


def _get_outside_geo_map(employee, from_date, to_date):
	"""Punches flagged outside the shift location's geo-fence (the flag HR's
	"Outside Geo-Location Check-ins" list reads): {date: {"reason", "log_type"}}."""
	if not frappe.db.has_column("Employee Checkin", "custom_outside_location"):
		return {}
	fields = ["time", "log_type"] + [
		f for f in ("custom_outside_reason", "custom_checkin_type")
		if frappe.db.has_column("Employee Checkin", f)
	]
	rows = frappe.get_all(
		"Employee Checkin",
		filters={
			"employee": employee,
			"custom_outside_location": 1,
			"time": ["between", [from_date, add_days(to_date, 1)]],
		},
		fields=fields,
		order_by="time asc",
	)
	out = {}
	for r in rows:
		day = getdate(r.time)
		if day > getdate(to_date) or day in out:
			continue
		out[day] = {
			"reason": r.get("custom_outside_reason") or r.get("custom_checkin_type") or "",
			"log_type": r.log_type,
		}
	return out


def _full_day_minutes(shift_name, day, cache):
	"""Minutes of work that make `day` a full day under `shift_name`; None when unknown.

	Changes(HP) HRMS #22: the calendar measured every Saturday against a fixed four hours, so
	Reena Sheta's HO Saturdays (10 and 17 Oct: 3h59m, marked Present against HO's own
	3.75-hour Saturday threshold) were painted as short. The line now comes from the
	thresholds HR set on the employee's Shift Type -- the half-day and absent pair, and
	Saturday's own pair on a Saturday, read as the Attendance Summary reads them. A day is
	full at the higher of the two, as in attendance_summary_helpers._whs.

	A shift that sets no threshold gets None, and the calendar keeps its old 8h / 4h. The
	summary's other fallback, span x full-day percentage, is not used here: "Warehouse
	Production - Day" is an 08:00-22:00 window with no thresholds, and 97% of it would have
	painted ten-hour days as short.
	"""
	if not shift_name:
		return None
	from alpinos.alpinos_development.report.attendance_summary.attendance_summary_helpers import (
		_shift_thresholds,
	)

	half_t, absent_t = _shift_thresholds(shift_name, getdate(day).weekday() == 5, cache)
	hours = max(half_t, absent_t)
	return int(round(hours * 60)) if hours else None


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


@frappe.whitelist()
def check_in(latitude=None, longitude=None, image=None, checkin_type=None, checkin_reason=None):
    # company-scope: n/a (own records)
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

    # optional geolocation (coerce to float for the distance calc)
    if latitude is not None:
        values["latitude"] = flt(latitude)
    if longitude is not None:
        values["longitude"] = flt(longitude)

    # biometric + web check-in rules: restrict to the Shift Location radius and require a
    # type (+ reason for 'Other'); skipped on an approved-WFH day.
    if _web_checkin_rules_active(employee) and not _approved_wfh_today(employee):
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

        # Changes(HP) HRMS #14: "Other" was removed from the check-in reasons, and with it
        # the free-text reason that only "Other" asked for. Refused here too, so a caller
        # going straight at the endpoint cannot put it back.
        checkin_type = (checkin_type or "").strip()
        if checkin_type not in ("Client/Vendor", "Shoot", "Meeting"):
            frappe.throw("Please select a valid check-in type.")
        values["custom_checkin_type"] = checkin_type

    doc = frappe.get_doc(values)
    doc.insert()
    _save_checkin_image(doc.name, image)
    return {"status": "IN", "time": doc.time}


@frappe.whitelist()
def is_within_shift_location(latitude, longitude):
    # company-scope: n/a (own records)
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
	# company-scope: n/a (own records)
	employee = _get_employee_for_user(frappe.session.user)
	if not employee:
		return None
	today = getdate(now_datetime())
	result = frappe.db.get_value(
		"Work From Home Request",
		{"employee": employee, "date": today, "status": ["in", ["Draft", "Approved", "Live"]]},
		["name", "status"],
		as_dict=True, order_by="name asc"
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
	assert_company(doc, ptype="write")
	doc.tasks = []
	for t in tasks:
		doc.append("tasks", {"task_name": t.get("task_name"), "status": t.get("status")})
	doc.save(ignore_permissions=True)
	return True


@frappe.whitelist()
def check_out(latitude=None, longitude=None, checkout_reason=None, outside_reason=None, outside_remarks=None, image=None):
    # company-scope: n/a (own records)
    if not frappe.has_permission("Employee Checkin", "create"):
        frappe.throw("You do not have permission to Check Out.")

    employee = _get_employee_for_user(frappe.session.user)
    if not employee:
        frappe.throw("No Employee linked to this user.")
    # allow a dashboard checkout as long as there's any check-in today (the last log's
    # type is irrelevant; an eSSL OUT may be latest but the employee still checks out here).
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

    # optional geolocation (coerce to float for the distance calc)
    if latitude is not None:
        values["latitude"] = flt(latitude)
    if longitude is not None:
        values["longitude"] = flt(longitude)

    # biometric + web check-in rules: within the radius the employee must check out on the
    # device too, so the dashboard is only for outside-office checkouts. Skipped on WFH days.
    if _web_checkin_rules_active(employee) and not _approved_wfh_today(employee):
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
        "name", order_by="name asc"
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
