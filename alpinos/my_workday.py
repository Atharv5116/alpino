"""My Workday: the employee's dashboard at the top of Home.

One Custom HTML Block ("My Workday", from patches/my_workday.{html,js,css}) laid out as the
approved design: Today's Attendance and Days This Month, the attendance calendar across the
whole width, Attendance Regularization and Leave Balances, Moments at Alpino and Team Pulse.
It replaces the "Employee Check In / Out" and "My Attendance Calendar" blocks on Home (and
the separate birthdays block, which Moments covers); HR's own blocks stay below it.

The calendar and Days This Month read alpinos.attendance_widget.get_monthly_attendance;
check-in and check-out still go through attendance_widget (camera, geo-fence, check-in type,
WFH tasks, outside-office checkout reason all unchanged). Everything else comes from
`get_workday` here, for the signed-in employee only.
"""

import os

import frappe
from frappe.utils import add_days, add_months, cint, flt, formatdate, getdate, now_datetime

from alpinos.attendance_widget import (
	_day_halves,
	_day_shift,
	_lateness,
	_get_employee_for_user,
	_get_leave_days,
	_get_wfh_days,
	_clock_minutes,
)

BLOCK = "My Workday"
WORKSPACE = "Home"
#: Blocks the dashboard replaces on Home. Their records stay, only the layout drops them.
REPLACES = ("Employee Check In / Out", "My Attendance Calendar", "Upcoming Birthdays & Anniversaries")
EDIT_CAP = 4  # attendance_request_override: at most 4 check-in/out edits a month


@frappe.whitelist()
def get_workday():
	employee = _get_employee_for_user(frappe.session.user)
	out = {
		"employee": employee,
		"today": None,
		"regularization": None,
		"leave_balances": [],
		"moments": _moments(),
		"pulse": _pulse(),
	}
	if employee:
		out["employee_name"] = frappe.db.get_value("Employee", employee, "employee_name")
		out["today"] = _today(employee)
		out["regularization"] = _regularization(employee)
		out["leave_balances"] = _leave_balances(employee)
	return out


# ---------------------------------------------------------------------------------- today
def _today(employee):
	today = getdate(now_datetime())
	cols = ["time", "log_type", "device_id"] + [
		f for f in ("custom_outside_location", "custom_outside_reason", "custom_checkin_type")
		if frappe.db.has_column("Employee Checkin", f)
	]
	logs = frappe.get_all(
		"Employee Checkin",
		filters={"employee": employee, "time": ["between", [f"{today} 00:00:00", f"{today} 23:59:59"]]},
		fields=cols,
		order_by="time asc",
	)
	first_in = next((l for l in logs if l.log_type == "IN"), None)
	last_out = None
	if first_in:
		outs = [l for l in logs if l.log_type == "OUT" and l.time >= first_in.time]
		last_out = outs[-1] if outs else None

	att = frappe.db.get_value(
		"Attendance", {"employee": employee, "attendance_date": today, "docstatus": 1},
		["status", "shift", "leave_type"], as_dict=True,
	) or {}
	shift = _day_shift(employee, today, att.get("shift"), {})
	leave = _get_leave_days(employee, today, today).get(today)
	wfh = _get_wfh_days(employee, today, today).get(today)

	def _punch(log):
		if not log:
			return None
		return {
			"time": str(log.time),
			"source": "Biometric" if log.get("device_id") else "Web",
			"outside": cint(log.get("custom_outside_location")),
			"reason": log.get("custom_outside_reason") or log.get("custom_checkin_type") or "",
		}

	late_minutes = late = None
	if shift and first_in:
		in_min = _clock_minutes(first_in.time)
		halves = _day_halves(att, leave, wfh, in_min, None, shift)
		late_minutes, late = _lateness(in_min, shift, halves)

	return {
		"date": str(today),
		"status": att.get("status"),
		"shift": shift["name"] if shift else None,
		"shift_start": shift["start_label"] if shift else None,
		"shift_end": shift["end_label"] if shift else None,
		"first_in": _punch(first_in),
		"last_out": _punch(last_out),
		"late_minutes": late_minutes,
		"late": late,
		"leave": {"leave_type": leave["leave_type"], "half": leave["half"], "period": leave.get("period")} if leave else None,
		"wfh": {"half": wfh["half"], "period": wfh.get("period")} if wfh else None,
	}


# ------------------------------------------------------------------------- regularization
def _regularization(employee):
	"""Check-in / check-out edits used this month against the monthly limit of 4."""
	from alpinos.attendance_request_automation import (
		count_attendance_request_edits,
		get_reserved_request_names,
	)

	today = getdate(now_datetime())
	month_start = today.replace(day=1)
	used = count_attendance_request_edits(
		get_reserved_request_names(employee, month_start, add_months(month_start, 1))
	)
	exempt = "HR Manager" in frappe.get_roles()
	return {
		"month": formatdate(month_start, "MMMM yyyy"),
		"used": cint(used),
		"cap": EDIT_CAP,
		"left": max(EDIT_CAP - cint(used), 0),
		"exempt": 1 if exempt else 0,
	}


# -------------------------------------------------------------------------- leave balances
def _leave_balances(employee):
	"""Each leave type allocated for today: what is left, out of what was allocated."""
	from hrms.hr.doctype.leave_application.leave_application import (
		get_leave_allocation_records,
		get_leave_balance_on,
	)

	today = getdate(now_datetime())
	rows = []
	for leave_type, a in (get_leave_allocation_records(employee, today) or {}).items():
		left = get_leave_balance_on(
			employee, leave_type, today, to_date=a.to_date, consider_all_leaves_in_the_allocation_period=True
		)
		rows.append({
			"leave_type": leave_type,
			"left": flt(left, 2),
			"allocated": flt(a.total_leaves_allocated, 2),
			"to_date": str(a.to_date),
			"to_label": formatdate(a.to_date, "dd MMM yyyy"),
		})
	rows.sort(key=lambda r: (-r["allocated"], r["leave_type"]))
	return rows


# --------------------------------------------------------------------- moments and pulse
def _designations(employees):
	employees = [e for e in set(employees) if e]
	if not employees:
		return {}
	return {
		r.name: r
		for r in frappe.get_all(
			"Employee",
			filters={"name": ["in", employees]},
			fields=["name", "designation", "department", "branch"],
			ignore_permissions=True,
		)
	}


def _moments():
	from alpinos.people_events import get_upcoming_birthdays_and_anniversaries

	data = get_upcoming_birthdays_and_anniversaries() or {}
	return {"birthdays": data.get("birthdays") or [], "anniversaries": data.get("anniversaries") or []}


def _pulse():
	"""Who is on leave or working from home today, with which half for a half day."""
	from alpinos.people_events import get_on_leave_and_wfh_today

	data = get_on_leave_and_wfh_today() or {}
	if not data.get("allowed"):
		return {"on_leave": [], "on_wfh": []}
	today = getdate(now_datetime())
	on_leave, on_wfh = data.get("on_leave") or [], data.get("on_wfh") or []
	info = _designations([r.get("employee") for r in on_leave + on_wfh])

	has_period = frappe.db.has_column("Leave Application", "custom_half_day_period")
	for r in on_leave:
		half_today = cint(r.get("half_day")) and (
			(r.get("half_day_date") and getdate(r["half_day_date"]) == today)
			or getdate(r.get("from_date")) == getdate(r.get("to_date"))
		)
		period = None
		if half_today and has_period:
			period = frappe.db.get_value(
				"Leave Application",
				{"employee": r["employee"], "docstatus": 1, "status": "Approved", "half_day": 1,
				 "from_date": ["<=", today], "to_date": [">=", today]},
				"custom_half_day_period",
			)
		r["part"] = (period or "Half Day") if half_today else "Full Day"
		r.update(_where(info.get(r.get("employee"))))
		for k in ("from_date", "to_date", "half_day_date"):
			if r.get(k):
				r[k] = str(r[k])
	for r in on_wfh:
		wfh = _get_wfh_days(r["employee"], today, today).get(today) if r.get("employee") else None
		r["part"] = ((wfh.get("period") or "Half Day") if wfh and wfh["half"] else "Full Day")
		r.update(_where(info.get(r.get("employee"))))
	return {"on_leave": on_leave, "on_wfh": on_wfh}


def _where(row):
	row = row or {}
	return {"designation": row.get("designation"), "department": row.get("department"), "branch": row.get("branch")}


# --------------------------------------------------------------------------- the block
def _files():
	d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "patches")
	parts = []
	for ext in ("html", "js", "css"):
		with open(os.path.join(d, f"my_workday.{ext}"), encoding="utf-8") as f:
			parts.append(f.read())
	return parts


def place_on_home():
	"""Ship the block's content (only when the app's files changed, like the calendar) and put
	it first on Home in place of the blocks it replaces. Safe to run on every migrate."""
	import json

	from alpinos.widget_content import write_if_shipped_changed

	html, script, style = _files()
	write_if_shipped_changed(BLOCK, html=html, script=script, style=style)

	if not frappe.db.exists("Workspace", WORKSPACE):
		return
	ws = frappe.get_doc("Workspace", WORKSPACE)
	blocks = json.loads(ws.content or "[]")

	def name_of(b):
		return (b.get("data") or {}).get("custom_block_name") if b.get("type") == "custom_block" else None

	kept = [b for b in blocks if name_of(b) not in REPLACES]
	ours = [b for b in kept if name_of(b) == BLOCK]
	if ours:
		kept.remove(ours[0])
		item = ours[0]
	else:
		item = {"id": frappe.generate_hash(length=10), "type": "custom_block", "data": {"custom_block_name": BLOCK, "col": 12}}
	item["data"]["col"] = 12
	kept.insert(0, item)

	ws.content = json.dumps(kept)
	ws.set("custom_blocks", [r for r in ws.custom_blocks if r.custom_block_name not in REPLACES])
	if not any(r.custom_block_name == BLOCK for r in ws.custom_blocks):
		ws.append("custom_blocks", {"custom_block_name": BLOCK, "label": BLOCK})
	ws.flags.ignore_permissions = True
	ws.flags.ignore_links = True
	ws.save()
