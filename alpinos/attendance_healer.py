"""Attendance healer — recompute an already-marked day from ALL its punches.

HRMS marks a day once from the punches eligible at that moment, then freezes it:
once a punch is linked to an Attendance it is excluded from re-processing, so a
punch that lands later (synced late / processed in a separate run) hits the
"attendance already marked" branch, gets skip_auto_attendance=1, and NEVER updates
the in/out. On an odd-count day (IN, OUT, IN) that leaves the out-time at the last
OUT and drops the trailing IN — understating hours and the status.

`recompute_attendance` re-derives one Attendance from its day's same-shift punches
using the SHIFT'S OWN get_attendance (patched calculate_working_hours = last log is
out + the shift thresholds) and the Saturday override — never hand-rolled. It is
called by two callers so they can never diverge:
  * backfill()          — one-time fix for the historical records
  * heal_on_checkin()   — Employee Checkin after_insert, so late punches self-heal
"""

import frappe
from frappe.utils import flt, get_datetime, getdate

# Auto-attendance produces exactly these; On Leave / Holiday / Work From Home / etc.
# are intentional and must never be touched by the healer.
HEALABLE_STATUSES = {"Present", "Half Day", "Absent"}


def _day_shift_logs(employee, attendance_date, shift):
	"""Every check-in for this employee ON attendance_date for this shift, chronological.

	Same-date + same-shift scoping is what protects against cross-date mis-linked
	punches (a next-day punch attached to the wrong Attendance) — those simply are
	not in this set, so they can never push the out-time into another day."""
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
	"""Run the exact Saturday-threshold override used at marking time. Returns
	(status, half_day_status). Non-Saturday dates are returned unchanged."""
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

	Returns a change dict (old/new status, hours, out-time) or None when the record
	is out of scope. Writes via db_set only when apply=True. Idempotent: re-running
	on an already-correct record reports changed=False and writes nothing.

	`fallback_shift` supplies a shift for the calc when the Attendance itself carries
	none — the half-day-LEAVE case: HRMS marks the leave day (often shift-less) and the
	worked-other-half punches must still fold in. The leave still defines the day, so a
	leave-backed Half Day keeps its 'Half Day' status; the punches only add in/out/hours."""
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
	# Scope: only submitted, auto-marked (no Attendance Request), auto-status records.
	# Manual / regularized records are left alone. A leave-backed Half Day IS in scope so
	# the worked other half folds in — but its leave status is preserved below.
	effective_shift = att.shift or fallback_shift
	if att.docstatus != 1 or att.attendance_request or att.status not in HEALABLE_STATUSES or not effective_shift:
		return None

	logs = _day_shift_logs(att.employee, att.attendance_date, effective_shift)
	if len(logs) < 2:
		return None  # a single punch cannot yield an out-time

	# Ensure the last-log-as-out patch is bound in this process, then reuse the shift's
	# own attendance calc so hours + status match normal marking exactly.
	from alpinos.overrides.employee_checkin_override import _apply_checkout_reason_patch

	_apply_checkout_reason_patch()
	shift = frappe.get_cached_doc("Shift Type", effective_shift)
	log_objs = [frappe._dict(row) for row in logs]
	status, working_hours, late_entry, early_exit, in_time, out_time = shift.get_attendance(log_objs)
	status, half_day_status = _apply_saturday_override(
		att.attendance_date, effective_shift, status, working_hours, att.half_day_status
	)

	# A half-day LEAVE defines the day: keep 'Half Day' (never let the worked-half punches
	# flip it to Present/Absent and orphan the leave). The punches only decide whether the
	# OTHER (worked) half reads Present or Absent, via the shift's half-day threshold.
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
	"""If this punch lands on a day that already has an auto-marked Attendance,
	recompute it so the punch folds in — the fix for the 'skip - already marked'
	freeze. No-op when the day isn't marked yet (normal marking handles that) or the
	punch is from an Attendance Request."""
	if (
		doc.flags.get("skip_attendance_heal")
		or doc.get("from_attendance_request")
		or not doc.get("time")
	):
		return
	# Shift-agnostic lookup: a half-day-LEAVE Attendance is often shift-less, so filtering
	# by the punch's shift would miss it. recompute_attendance uses the punch's shift as a
	# fallback for the hours calc and preserves the leave.
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
	"""Auto-marked Attendances whose recorded out-time is EARLIER than the day's last
	same-shift punch — the true 'last log dropped' signature (independent of linking)."""
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
	"""Heal historical records. apply=0 (default) is a DRY RUN — it recomputes and
	returns exactly what WOULD change, writing nothing. apply=1 applies the fixes.

	  bench --site SITE execute alpinos.attendance_healer.backfill                  # dry run
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
	"""One-time backfill: for every Attendance in [from_date, to_date] that has BOTH an
	in_time and an out_time but NO Employee Checkin for that employee that day, create a
	matching pair of punches — an IN checkin at the attendance's in_time and an OUT checkin
	at its out_time — each linked back to that Attendance (the `attendance` field) and
	flagged skip_auto_attendance=1.

	The Attendance itself is left UNCHANGED: the heal hook is suppressed on these inserts
	(flags.skip_attendance_heal) and skip_auto_attendance=1 keeps auto-marking from
	reprocessing them, so the punches simply *back* the existing record with the same in/out
	rather than re-deriving its status/hours. HRMS's own validate can override the shift /
	drop the link, so both are force-set again after insert.

	Skips any day that already has a punch for that employee (never duplicates) and any
	attendance missing a timestamp. Each pair is committed atomically; a pair that fails
	validation is rolled back and reported in `errors`. DRY-RUN by default.

	  Preview:  bench --site SITE execute alpinos.attendance_healer.create_checkins_from_attendance --kwargs '{"from_date": "2026-07-07", "to_date": "2026-07-08"}'
	  Apply  :  bench --site SITE execute alpinos.attendance_healer.create_checkins_from_attendance --kwargs '{"from_date": "2026-07-07", "to_date": "2026-07-08", "apply": 1}'
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
		# Only backfill genuinely missing punches — skip any day that already has a
		# checkin for this employee, so we never create a duplicate.
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
					# HRMS validate/fetch_shift may override shift or drop the attendance
					# link — force the intended linkage back on.
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
