"""Changes(HP) HRMS #13: correct a punch typed IN when it was an OUT, and the day with it.

eSSL types a punch by counting the day's punches and alternating (essl_sync:
"IN" if count %% 2 == 0 else "OUT"), so a manual or request punch landing first shifts every
device punch after it. Harsh Patel, 10-09-2026: his 18:33 exit was stored as an IN, the
approval then recomputed his day from the last punch typed OUT (13:58) and his day reads
3.75 hours.

This corrects one punch and re-derives the day's Attendance from the punches, the same way
alpinos.attendance_request_automation does it on approval: in = first IN, out = last OUT,
hours = the difference. Dry run by default; the write leaves an audit comment on both
documents.

	bench --site SITE execute alpinos.attendance_punch_repair.set_log_type --kwargs "{'checkin':'EMP-CKIN-09-2026-002438','log_type':'OUT'}"
	bench --site SITE execute alpinos.attendance_punch_repair.set_log_type --kwargs "{'checkin':'EMP-CKIN-09-2026-002438','log_type':'OUT','apply':1}"
"""

import frappe
from frappe.utils import flt, get_datetime, getdate


def _day_bounds(date):
	return f"{getdate(date)} 00:00:00", f"{getdate(date)} 23:59:59"


def _day_punches(employee, date):
	start, end = _day_bounds(date)
	return frappe.get_all(
		"Employee Checkin",
		filters={"employee": employee, "time": ["between", [start, end]]},
		fields=["name", "log_type", "time"],
		order_by="time asc",
	)


def _derive(employee, date):
	"""in = the day's first IN, out = its last OUT, hours = the difference."""
	punches = _day_punches(employee, date)
	ins = [p for p in punches if p.log_type == "IN"]
	outs = [p for p in punches if p.log_type == "OUT"]
	in_time = ins[0].time if ins else None
	out_time = outs[-1].time if outs else None
	hours = None
	if in_time and out_time and get_datetime(out_time) > get_datetime(in_time):
		hours = round((get_datetime(out_time) - get_datetime(in_time)).total_seconds() / 3600, 2)
	return in_time, out_time, hours, punches


@frappe.whitelist()
def set_log_type(checkin, log_type, apply=0):
	"""Retype one punch and re-derive that day's Attendance. Dry run unless apply=1."""
	apply = int(apply)
	log_type = (log_type or "").strip().upper()
	if log_type not in ("IN", "OUT"):
		frappe.throw("log_type must be IN or OUT.")

	punch = frappe.db.get_value(
		"Employee Checkin", checkin, ["name", "employee", "log_type", "time", "device_id"], as_dict=True
	)
	if not punch:
		return {"error": f"no Employee Checkin named {checkin!r}"}
	if punch.log_type == log_type:
		return {"error": f"{checkin} is already {log_type}"}

	date = getdate(punch.time)
	before_in, before_out, before_hours, punches_before = _derive(punch.employee, date)
	att = frappe.db.get_value(
		"Attendance",
		{"employee": punch.employee, "attendance_date": date, "docstatus": ["<", 2]},
		["name", "status", "in_time", "out_time", "working_hours", "docstatus"],
		as_dict=True,
	)

	result = {
		"mode": "APPLY" if apply else "DRY-RUN",
		"checkin": checkin,
		"employee": punch.employee,
		"employee_name": frappe.db.get_value("Employee", punch.employee, "employee_name"),
		"date": str(date),
		"punch": {"time": str(punch.time), "from": punch.log_type, "to": log_type,
		          "device": punch.device_id or "manual / web"},
		"day_before": {"punches": [f"{p.log_type} {str(p.time)[11:16]}" for p in punches_before],
		               "in": str(before_in), "out": str(before_out), "hours": before_hours},
		"attendance": att.name if att else None,
		"attendance_before": {
			"status": att.status, "in": str(att.in_time), "out": str(att.out_time),
			"hours": flt(att.working_hours, 2),
		} if att else None,
	}

	if not apply:
		# Show what the day WOULD become, without writing anything.
		simulated = [
			{"log_type": (log_type if p.name == checkin else p.log_type), "time": p.time, "name": p.name}
			for p in punches_before
		]
		ins = [p for p in simulated if p["log_type"] == "IN"]
		outs = [p for p in simulated if p["log_type"] == "OUT"]
		w_in = ins[0]["time"] if ins else None
		w_out = outs[-1]["time"] if outs else None
		w_hours = (
			round((get_datetime(w_out) - get_datetime(w_in)).total_seconds() / 3600, 2)
			if w_in and w_out and get_datetime(w_out) > get_datetime(w_in) else None
		)
		result["day_after"] = {
			"punches": [f"{p['log_type']} {str(p['time'])[11:16]}" for p in simulated],
			"in": str(w_in), "out": str(w_out), "hours": w_hours,
		}
		return result

	frappe.db.set_value("Employee Checkin", checkin, "log_type", log_type, update_modified=False)
	frappe.get_doc("Employee Checkin", checkin).add_comment(
		"Comment",
		f"Log type corrected {punch.log_type} -> {log_type} by {frappe.session.user} "
		"(Changes(HP) HRMS #13: the punch was typed by the device's alternating count).",
	)

	after_in, after_out, after_hours, punches_after = _derive(punch.employee, date)
	result["day_after"] = {
		"punches": [f"{p.log_type} {str(p.time)[11:16]}" for p in punches_after],
		"in": str(after_in), "out": str(after_out), "hours": after_hours,
	}

	if att and (att.in_time != after_in or att.out_time != after_out):
		updates = {"in_time": after_in, "out_time": after_out}
		if after_hours is not None:
			updates["working_hours"] = after_hours
		# Submitted Attendance: written directly, the way the approval path does, so the
		# document is not cancelled and unlinked from its request.
		frappe.db.set_value("Attendance", att.name, updates, update_modified=False)
		frappe.get_doc("Attendance", att.name).add_comment(
			"Comment",
			f"Re-derived from the day's punches after a log type correction: "
			f"in {att.in_time} -> {after_in}, out {att.out_time} -> {after_out}, "
			f"hours {flt(att.working_hours, 2)} -> {after_hours} (Changes(HP) HRMS #13).",
		)
		result["attendance_after"] = {
			"in": str(after_in), "out": str(after_out), "hours": after_hours,
		}
	else:
		result["attendance_after"] = "unchanged"

	frappe.db.commit()
	return result
