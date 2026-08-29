"""Attendance healer: recompute an already-marked day from ALL its punches.

HRMS freezes a day after marking it, so a late-synced punch never updates the in/out.
recompute_attendance re-derives one Attendance from its day's same-shift punches using the
shift's own get_attendance and the Saturday override. Shared by backfill() and heal_on_checkin().
"""

import frappe
from frappe.utils import flt, get_datetime, getdate

# Only these auto-marked statuses are healable; leave/holiday/WFH are left alone.
HEALABLE_STATUSES = {"Present", "Half Day", "Absent"}


def _day_shift_logs(employee, attendance_date, shift):
	"""Every check-in for this employee on attendance_date for this shift, chronological."""
	d = getdate(attendance_date)
	return frappe.get_all(
		"Employee Checkin",
		filters={
			"employee": employee,
			"shift": shift,
			"time": ["between", [f"{d} 00:00:00", f"{d} 23:59:59"]],
		},
		fields=[
			"name", "employee", "log_type", "time", "shift",
			"shift_start", "shift_end", "skip_auto_attendance",
		],
		order_by="time asc",
	)


def _apply_saturday_override(attendance_date, shift, status, working_hours, half_day_status):
	"""Apply the Saturday-threshold override used at marking time; returns (status, half_day_status)."""
	from alpinos.attendance_request_automation import validate_saturday_attendance_threshold

	tmp = frappe._dict(
		status=status,
		working_hours=working_hours,
		attendance_date=attendance_date,
		shift=shift,
		docstatus=1,
		half_day_status=half_day_status,
		leave_application=None,
		leave_type=None,
	)
	validate_saturday_attendance_threshold(tmp, "recompute")
	return tmp.status, tmp.get("half_day_status")


def recompute_attendance(att_name, apply=False, fallback_shift=None):
	"""Recompute one auto-marked Attendance from its day's same-shift punches.

	Returns a change dict (or None when out of scope); writes only when apply=True. Idempotent.
	fallback_shift supplies a shift for the calc when the Attendance carries none (half-day-LEAVE
	case); a leave-backed Half Day keeps its status while the punches add in/out/hours.
	"""
	att = frappe.db.get_value(
		"Attendance",
		att_name,
		[
			"name", "employee", "attendance_date", "shift", "status", "half_day_status",
			"working_hours", "in_time", "out_time", "docstatus", "attendance_request",
			"leave_application", "leave_type",
		],
		as_dict=True,
	)
	if not att:
		return None
	# Scope: submitted, auto-marked (no Attendance Request), auto-status records only.
	# A leave-backed Half Day stays in scope but keeps its leave status (preserved below).
	effective_shift = att.shift or fallback_shift
	if att.docstatus != 1 or att.attendance_request or att.status not in HEALABLE_STATUSES or not effective_shift:
		return None

	logs = _day_shift_logs(att.employee, att.attendance_date, effective_shift)
	if len(logs) < 2:
		return None  # a single punch cannot yield an out-time

	# Bind the last-log-as-out patch, then reuse the shift's own attendance calc.
	from alpinos.overrides.employee_checkin_override import _apply_checkout_reason_patch

	_apply_checkout_reason_patch()
	shift = frappe.get_cached_doc("Shift Type", effective_shift)
	log_objs = [frappe._dict(row) for row in logs]
	status, working_hours, late_entry, early_exit, in_time, out_time = shift.get_attendance(log_objs)
	status, half_day_status = _apply_saturday_override(
		att.attendance_date, effective_shift, status, working_hours, att.half_day_status
	)

	# A half-day LEAVE defines the day: keep 'Half Day'. The punches only decide whether
	# the worked half reads Present or Absent, via the shift's half-day threshold.
	if att.status == "Half Day" and (att.leave_application or att.leave_type):
		from alpinos.attendance_request_automation import half_day_status_from_threshold

		status = "Half Day"
		hs = half_day_status_from_threshold(effective_shift, "Half Day", working_hours, True)
		if hs:
			half_day_status = hs

	def _dt(value):
		return get_datetime(value) if value else None

	changed = (
		_dt(att.out_time) != _dt(out_time)
		or _dt(att.in_time) != _dt(in_time)
		or att.status != status
		or flt(att.working_hours, 2) != flt(working_hours, 2)
	)
	change = frappe._dict(
		attendance=att.name,
		employee=att.employee,
		date=str(att.attendance_date),
		old_status=att.status,
		new_status=status,
		old_hours=flt(att.working_hours, 2),
		new_hours=flt(working_hours, 2),
		old_out=str(att.out_time),
		new_out=str(out_time),
		changed=changed,
	)
	if changed and apply:
		frappe.db.set_value(
			"Attendance",
			att.name,
			{
				"in_time": in_time,
				"out_time": out_time,
				"working_hours": working_hours,
				"status": status,
				"half_day_status": half_day_status,
				"late_entry": 1 if late_entry else 0,
				"early_exit": 1 if early_exit else 0,
			},
			update_modified=True,
		)
		# Clear the stray "already marked" skips so these punches count normally again.
		for row in logs:
			if row.skip_auto_attendance:
				frappe.db.set_value(
					"Employee Checkin", row.name, "skip_auto_attendance", 0, update_modified=False
				)
	return change


# ---------------------------------------------------------------------------
# Prevention — heal on a late punch (Employee Checkin after_insert)
# ---------------------------------------------------------------------------
def heal_on_checkin(doc, method=None):
	"""Recompute an already-marked day when a late punch lands, so the punch folds in."""
	if (
		doc.flags.get("skip_attendance_heal")
		or doc.get("from_attendance_request")
		or not doc.get("time")
	):
		return
	# Shift-agnostic lookup: a half-day-LEAVE Attendance is often shift-less.
	att_name = frappe.db.get_value(
		"Attendance",
		{
			"employee": doc.employee,
			"attendance_date": getdate(doc.time),
			"docstatus": 1,
		},
		"name",
	)
	if not att_name:
		return
	try:
		recompute_attendance(att_name, apply=True, fallback_shift=doc.get("shift"))
	except Exception:
		frappe.log_error(
			title="Alpinos: attendance heal-on-checkin failed",
			message=frappe.get_traceback(),
		)


# ---------------------------------------------------------------------------
# Backfill — one-time fix for the historical records
# ---------------------------------------------------------------------------
def _affected_attendance_names(from_date=None, to_date=None, limit=None):
	"""Auto-marked Attendances whose out-time is earlier than the day's last same-shift punch."""
	conditions = [
		"a.docstatus = 1",
		"IFNULL(a.attendance_request, '') = ''",
		"a.status IN ('Present', 'Half Day', 'Absent')",
	]
	params = {}
	if from_date:
		conditions.append("a.attendance_date >= %(from_date)s")
		params["from_date"] = from_date
	if to_date:
		conditions.append("a.attendance_date <= %(to_date)s")
		params["to_date"] = to_date
	where = " AND ".join(conditions)
	lim = f"LIMIT {int(limit)}" if limit else ""
	return frappe.db.sql(
		f"""
		SELECT a.name
		FROM `tabAttendance` a
		JOIN `tabEmployee Checkin` ec
			ON ec.employee = a.employee AND ec.shift = a.shift
			AND DATE(ec.time) = a.attendance_date
		WHERE {where}
		GROUP BY a.name
		HAVING MAX(a.out_time) < MAX(ec.time)
		ORDER BY MIN(a.attendance_date) {lim}
		""",
		params,
		as_dict=True,
	)


@frappe.whitelist()
def backfill(apply=0, from_date=None, to_date=None, limit=None):
	"""Heal historical records. apply=0 (default) is a DRY RUN; apply=1 writes the fixes.

	  bench --site SITE execute alpinos.attendance_healer.backfill --kwargs "{'apply':1}"
	"""
	apply = int(apply)
	names = _affected_attendance_names(from_date, to_date, limit)

	changes, applied = [], 0
	for row in names:
		change = recompute_attendance(row.name, apply=bool(apply))
		if change and change.changed:
			changes.append(change)
			if apply:
				applied += 1
				if applied % 200 == 0:
					frappe.db.commit()
	if apply:
		frappe.db.commit()

	# status-transition summary (e.g. Absent -> Present) for a quick sanity read
	summary = {}
	for c in changes:
		key = f"{c.old_status} -> {c.new_status}"
		summary[key] = summary.get(key, 0) + 1

	return {
		"mode": "APPLY" if apply else "DRY-RUN",
		"scanned": len(names),
		"changed": len(changes),
		"applied": applied,
		"transitions": summary,
		"sample": changes[:25],
	}


@frappe.whitelist()
def create_checkins_from_attendance(from_date=None, to_date=None, apply=0):
	"""Backfill Employee Checkins for Attendances that have in/out times but no punches that day.

	Creates an IN + OUT pair linked back to the Attendance (skip_auto_attendance=1); the
	Attendance itself is left unchanged. Skips days that already have a punch. DRY-RUN by default.

	  bench --site SITE execute alpinos.attendance_healer.create_checkins_from_attendance --kwargs '{"from_date": "2026-07-07", "to_date": "2026-07-08", "apply": 1}'
	"""
	apply = int(apply)

	conditions = [
		"a.docstatus < 2",
		"a.in_time IS NOT NULL",
		"a.out_time IS NOT NULL",
		"IFNULL(a.shift, '') <> ''",
	]
	params = {}
	if from_date:
		conditions.append("a.attendance_date >= %(from_date)s")
		params["from_date"] = from_date
	if to_date:
		conditions.append("a.attendance_date <= %(to_date)s")
		params["to_date"] = to_date

	rows = frappe.db.sql(
		"""
		SELECT a.name, a.employee, a.attendance_date, a.shift, a.in_time, a.out_time
		FROM `tabAttendance` a
		WHERE {where}
		ORDER BY a.attendance_date, a.employee
		""".format(where=" AND ".join(conditions)),
		params,
		as_dict=True,
	)

	created_pairs = 0
	skipped_has_checkin = 0
	errors = []
	samples = []

	for att in rows:
		# Skip any day that already has a checkin for this employee (never duplicate).
		if frappe.db.sql(
			"SELECT name FROM `tabEmployee Checkin` WHERE employee=%s AND DATE(`time`)=%s LIMIT 1",
			(att.employee, att.attendance_date),
		):
			skipped_has_checkin += 1
			continue

		if apply:
			try:
				for log_type, ts in (("IN", att.in_time), ("OUT", att.out_time)):
					ci = frappe.new_doc("Employee Checkin")
					ci.flags.skip_attendance_heal = True  # leave the Attendance untouched
					ci.flags.skip_geo_validation = True   # historical reconstruction, no live geo-fence
					ci.employee = att.employee
					ci.log_type = log_type
					ci.time = ts
					ci.shift = att.shift
					ci.attendance = att.name
					ci.skip_auto_attendance = 1
					ci.insert(ignore_permissions=True)
					# HRMS validate/fetch_shift may override shift or drop the link; force it back on.
					frappe.db.set_value(
						"Employee Checkin",
						ci.name,
						{"shift": att.shift, "attendance": att.name, "skip_auto_attendance": 1},
						update_modified=False,
					)
				frappe.db.commit()  # each IN+OUT pair is atomic
				created_pairs += 1
			except Exception as e:
				frappe.db.rollback()
				errors.append({"attendance": att.name, "error": str(e)})
				continue
		else:
			created_pairs += 1

		if len(samples) < 25:
			samples.append(
				{
					"attendance": att.name,
					"employee": att.employee,
					"date": str(att.attendance_date),
					"shift": att.shift,
					"IN": str(att.in_time),
					"OUT": str(att.out_time),
				}
			)

	return {
		"mode": "APPLY" if apply else "DRY-RUN",
		"attendances_matched": len(rows),
		"pairs": created_pairs,  # IN+OUT pairs created (or would-create in dry-run)
		"checkins_total": created_pairs * 2,
		"skipped_already_has_checkin": skipped_has_checkin,
		"error_count": len(errors),
		"errors": errors[:25],
		"sample": samples,
	}
