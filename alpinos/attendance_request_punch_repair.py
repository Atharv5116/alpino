"""Repair attendance left wrong by Attendance Requests approved with only one punch.

Before the Check-in/Check-out mandatory rule landed, a request with a reason other than
On Duty could be approved with (say) only a Check-in. That single punch gives zero working
hours, so auto-attendance marked the day Absent even though the request was approved.

This fills the missing side from the employee's assigned shift and re-syncs the Attendance.
"""

import frappe
from frappe.utils import getdate

SKIP_REASON = "On Duty"


def _incomplete_rows(from_date=None, to_date=None, employee=None):
	"""Request-backed Attendance (reason != On Duty) left with only one of the two punch times.

	Detection is on the Attendance itself rather than the request's child rows: an unticked
	Check-in/Check-out is blanked on validate, so the child row is not a reliable record of
	what was actually applied.
	"""
	conditions = [
		"a.docstatus = 1",
		"IFNULL(a.attendance_request, '') != ''",
		"IFNULL(ar.reason, '') != %(skip)s",
		"((a.in_time IS NOT NULL AND a.out_time IS NULL) OR (a.in_time IS NULL AND a.out_time IS NOT NULL))",
	]
	params = {"skip": SKIP_REASON}

	if from_date:
		conditions.append("a.attendance_date >= %(from_date)s")
		params["from_date"] = getdate(from_date)
	if to_date:
		conditions.append("a.attendance_date <= %(to_date)s")
		params["to_date"] = getdate(to_date)
	if employee:
		conditions.append("a.employee = %(employee)s")
		params["employee"] = employee

	where = " AND ".join(conditions)
	return frappe.db.sql(
		f"""
		SELECT
			a.attendance_request AS request, a.employee, ar.reason, ar.half_day,
			a.attendance_date, a.in_time AS check_in, a.out_time AS check_out
		FROM `tabAttendance` a
		JOIN `tabAttendance Request` ar ON ar.name = a.attendance_request
		WHERE {where}
		ORDER BY a.attendance_date, a.employee
		""",
		params,
		as_dict=True,
	)


def _resolve_shift(employee, date, att_shift=None):
	"""Shift for the day: the Attendance's own, else a punch's, else the assignment or default."""
	if att_shift:
		return att_shift

	d = getdate(date)
	for row in _day_checkins(employee, d):
		if row.shift:
			return row.shift

	assigned = frappe.db.sql(
		"""
		SELECT shift_type FROM `tabShift Assignment`
		WHERE employee = %s AND docstatus = 1 AND status = 'Active'
		  AND start_date <= %s AND (end_date IS NULL OR end_date >= %s)
		ORDER BY start_date DESC LIMIT 1
		""",
		(employee, d, d),
	)
	if assigned:
		return assigned[0][0]

	return frappe.db.get_value("Employee", employee, "default_shift")


def _day_checkins(employee, date):
	d = getdate(date)
	return frappe.get_all(
		"Employee Checkin",
		filters={"employee": employee, "time": ["between", [f"{d} 00:00:00", f"{d} 23:59:59"]]},
		fields=["name", "log_type", "time", "shift"],
		order_by="time asc",
	)


@frappe.whitelist()
def repair(from_date=None, to_date=None, employee=None, apply=0):
	"""Fill the missing punch from the assigned shift and re-sync the Attendance.

	Dry-run by default; apply=1 writes.

	  bench --site SITE execute alpinos.attendance_request_punch_repair.repair --kwargs "{'from_date':'2026-08-01','to_date':'2026-08-31'}"
	"""
	from alpinos.attendance_request_automation import get_assigned_shift_times, update_attendance_times

	apply = int(apply)
	rows = _incomplete_rows(from_date, to_date, employee)

	fixed, skipped, changes = 0, 0, []
	for row in rows:
		date = getdate(row.attendance_date)
		att = frappe.db.get_value(
			"Attendance",
			{"employee": row.employee, "attendance_date": date, "docstatus": 1},
			["name", "status", "shift", "in_time", "out_time", "working_hours"],
			as_dict=True,
		)
		if not att:
			skipped += 1
			continue

		shift = _resolve_shift(row.employee, date, att.shift)
		shift_in, shift_out = get_assigned_shift_times(row.employee, date, shift)
		if not shift_in or not shift_out:
			skipped += 1
			changes.append({"attendance": att.name, "date": str(date), "skipped": "no assigned shift"})
			continue

		# The side the request left blank is taken from the shift; the entered side stands.
		missing_side = "check_out" if row.check_in else "check_in"
		fill_time = shift_out if missing_side == "check_out" else shift_in
		log_type = "OUT" if missing_side == "check_out" else "IN"

		existing = _day_checkins(row.employee, date)
		if any(c.log_type == log_type for c in existing):
			skipped += 1
			continue

		change = {
			"request": row.request,
			"attendance": att.name,
			"employee": row.employee,
			"date": str(date),
			"old_status": att.status,
			"old_hours": att.working_hours,
			"filled": f"{log_type} @ {fill_time}",
		}

		if apply:
			try:
				checkin = frappe.new_doc("Employee Checkin")
				checkin.flags.skip_attendance_heal = True
				checkin.flags.skip_geo_validation = True
				checkin.employee = row.employee
				checkin.log_type = log_type
				checkin.time = fill_time
				checkin.shift = shift
				checkin.attendance = att.name
				checkin.insert(ignore_permissions=True)
				# HRMS validate/fetch_shift can drop the shift or the link; force both back on.
				frappe.db.set_value(
					"Employee Checkin",
					checkin.name,
					{"shift": shift, "attendance": att.name},
					update_modified=False,
				)
				# The day's other punches must carry the same shift for the recompute to see them.
				frappe.db.sql(
					"""UPDATE `tabEmployee Checkin` SET shift = %s
					   WHERE employee = %s AND DATE(`time`) = %s AND IFNULL(shift, '') = ''""",
					(shift, row.employee, date),
				)
				if not att.shift:
					frappe.db.set_value("Attendance", att.name, "shift", shift, update_modified=False)

				update_attendance_times(row.employee, date)
				_recompute(att.name, shift)
				frappe.db.commit()
			except Exception as e:
				frappe.db.rollback()
				change["error"] = str(e)
				changes.append(change)
				continue

			after = frappe.db.get_value(
				"Attendance", att.name, ["status", "working_hours", "in_time", "out_time"], as_dict=True
			)
			change["new_status"] = after.status
			change["new_hours"] = after.working_hours

		fixed += 1
		changes.append(change)

	return {
		"mode": "APPLY" if apply else "DRY-RUN",
		"rows_scanned": len(rows),
		"fixed": fixed,
		"skipped": skipped,
		"changes": changes[:50],
	}


def _recompute(attendance, shift):
	"""Re-run the healer so status and hours follow the now-complete punch pair."""
	from alpinos.attendance_healer import recompute_attendance

	# The healer ignores request-backed rows, so clear the link for the recompute and restore it.
	request = frappe.db.get_value("Attendance", attendance, "attendance_request")
	if request:
		frappe.db.set_value("Attendance", attendance, "attendance_request", None, update_modified=False)
	try:
		recompute_attendance(attendance, apply=True, fallback_shift=shift)
	finally:
		if request:
			frappe.db.set_value(
				"Attendance", attendance, "attendance_request", request, update_modified=False
			)
