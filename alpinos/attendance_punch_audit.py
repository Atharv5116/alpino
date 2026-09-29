"""Changes(HP) HRMS #13: which punches an Attendance Request approval wrote over.

Approving a request called frappe.db.set_value on the Employee Checkin and on the
Attendance, and a db.set_value writes no Version, so the ORIGINAL time is not recoverable
from this database. What is recoverable is WHICH punches an approval touched, and which
request did it, so HR can decide day by day. The fix in the override stops it happening
again; this reads what already happened.

	bench --site SITE execute alpinos.attendance_punch_audit.touched_by_requests
	bench --site SITE execute alpinos.attendance_punch_audit.touched_by_requests --kwargs "{'from_date':'2026-09-01','to_date':'2026-09-30'}"
	bench --site SITE execute alpinos.attendance_punch_audit.recoverable_history

Read-only: nothing here writes.
"""

import frappe
from frappe.utils import cint

# A row written and never touched again has modified within a second or so of creation.
# Beyond that, something came back and changed it: for these rows, the approval.
_EDIT_GAP_SECONDS = 5


@frappe.whitelist()
def touched_by_requests(from_date=None, to_date=None, limit=200):
	"""Punches carrying from_attendance_request, split into created and overwritten."""
	conds = ["IFNULL(ec.from_attendance_request, 0) = 1"]
	params = {}
	if from_date:
		conds.append("ec.time >= %(from_date)s")
		params["from_date"] = f"{from_date} 00:00:00"
	if to_date:
		conds.append("ec.time <= %(to_date)s")
		params["to_date"] = f"{to_date} 23:59:59"

	rows = frappe.db.sql(
		f"""
		SELECT ec.name, ec.employee, ec.employee_name, ec.log_type, ec.time,
		       ec.creation, ec.modified, ec.owner,
		       TIMESTAMPDIFF(SECOND, ec.creation, ec.modified) AS changed_after_seconds
		FROM `tabEmployee Checkin` ec
		WHERE {" AND ".join(conds)}
		ORDER BY ec.time DESC
		""",
		params,
		as_dict=True,
	)

	overwritten, created = [], []
	for r in rows:
		# The request that covers this employee and day, i.e. the one that wrote here.
		day = str(r.time)[:10]
		request = frappe.db.sql(
			"""
			SELECT name, reason, workflow_state, owner, modified
			FROM `tabAttendance Request`
			WHERE employee = %(emp)s AND from_date <= %(day)s AND to_date >= %(day)s
			  AND docstatus < 2
			ORDER BY modified DESC LIMIT 1
			""",
			{"emp": r.employee, "day": day},
			as_dict=True,
		)
		entry = {
			"checkin": r.name,
			"employee": r.employee,
			"employee_name": r.employee_name,
			"date": day,
			"log_type": r.log_type,
			"time_now": str(r.time),
			"request": request[0].name if request else None,
			"request_reason": request[0].reason if request else None,
			"raised_by": request[0].owner if request else None,
			"request_state": request[0].workflow_state if request else None,
		}
		if cint(r.changed_after_seconds) > _EDIT_GAP_SECONDS:
			# The row existed before the request: the device's punch, rewritten.
			entry["original_time"] = "LOST -- overwritten, no version kept"
			entry["first_written"] = str(r.creation)
			entry["changed_at"] = str(r.modified)
			overwritten.append(entry)
		else:
			created.append(entry)

	# An On Duty request should never have touched a punch already on record: those are the
	# ones the fix was for. A punch EDIT overwriting is what an edit is, so it is only wrong
	# where it landed on the wrong row -- the reason tells the two apart.
	by_reason = {}
	for e in overwritten:
		key = e.get("request_reason") or "no request found"
		by_reason[key] = by_reason.get(key, 0) + 1

	limit = cint(limit)
	return {
		"overwritten_count": len(overwritten),
		"created_count": len(created),
		"overwritten_by_reason": by_reason,
		# These are the ones to look at: a real punch was replaced.
		"overwritten": overwritten[:limit] if limit else overwritten,
		"created_sample": created[:5],
		"note": "An overwritten punch cannot be restored from this database. The biometric "
		        "device still holds the raw punch: alpinos.essl_sync.sync_essl_logs re-reads a "
		        "date range and skips timestamps already on record, so it would bring the "
		        "original back as an EXTRA row -- but the log_type it lands with is decided by "
		        "how many punches the day already has, so check a single employee first.",
	}


@frappe.whitelist()
def recoverable_history(from_date=None, to_date=None):
	"""Whether any Version rows exist for the punches / attendance in the range.

	frappe.db.set_value writes no Version, so this is expected to be empty -- it is worth
	confirming on the site itself before telling anybody the old times are gone.
	"""
	conds = ["v.ref_doctype IN ('Employee Checkin', 'Attendance')"]
	params = {}
	if from_date:
		conds.append("v.creation >= %(from_date)s")
		params["from_date"] = f"{from_date} 00:00:00"
	if to_date:
		conds.append("v.creation <= %(to_date)s")
		params["to_date"] = f"{to_date} 23:59:59"

	rows = frappe.db.sql(
		f"""
		SELECT v.ref_doctype,
		       COUNT(*) AS versions,
		       SUM(v.data LIKE '%%in_time%%' OR v.data LIKE '%%out_time%%') AS with_punch_times
		FROM `tabVersion` v
		WHERE {" AND ".join(conds)}
		GROUP BY v.ref_doctype
		""",
		params,
		as_dict=True,
	)
	recoverable = sum(cint(r.get("with_punch_times")) for r in rows)
	return {
		"versions": rows,
		"punch_times_recoverable_from_versions": recoverable,
		"note": (
			"with_punch_times 0 means no old check-in or check-out value was kept anywhere -- "
			"versions of Attendance record the status only -- so a punch an approval overwrote "
			"can come back from the biometric device or not at all."
			if not recoverable else
			"Some versions DO carry an old in_time / out_time: read their data field for the "
			"value as it was before the approval."
		),
	}


@frappe.whitelist()
def explain_day(employee, date):
	"""One employee, one date: the punches, the requests, and what touched what.

	For a complaint like "before approval it read 13:10 / 18:33, after approval 10:10 /
	13:38". employee takes an id (AHFPL1144) or part of a name (Harsh).

	  bench --site SITE execute alpinos.attendance_punch_audit.explain_day --kwargs "{'employee':'Harsh','date':'2026-09-10'}"
	"""
	emp = employee if frappe.db.exists("Employee", employee) else None
	if not emp:
		matches = frappe.get_all(
			"Employee",
			filters=[["employee_name", "like", f"%{employee}%"]],
			fields=["name", "employee_name"],
			limit=10,
		)
		if not matches:
			return {"error": f"no Employee matches {employee!r}"}
		if len(matches) > 1:
			return {"error": "more than one Employee matches; pass the id", "matches": matches}
		emp = matches[0].name

	day_start, day_end = f"{date} 00:00:00", f"{date} 23:59:59"
	punches = frappe.db.sql(
		"""
		SELECT name, log_type, time, IFNULL(from_attendance_request, 0) AS from_request,
		       IFNULL(is_manual, 0) AS is_manual, device_id, creation, modified, owner,
		       TIMESTAMPDIFF(SECOND, creation, modified) AS changed_after_seconds
		FROM `tabEmployee Checkin`
		WHERE employee = %(emp)s AND time BETWEEN %(s)s AND %(e)s
		ORDER BY time
		""",
		{"emp": emp, "s": day_start, "e": day_end},
		as_dict=True,
	)
	rows = []
	for p in punches:
		overwritten = cint(p.from_request) and cint(p.changed_after_seconds) > _EDIT_GAP_SECONDS
		rows.append({
			"checkin": p.name,
			"log_type": p.log_type,
			"time_now": str(p.time),
			"came_from": "attendance request" if cint(p.from_request) else (p.device_id or "manual / web"),
			"first_written": str(p.creation),
			"changed_at": str(p.modified),
			"verdict": (
				"OVERWRITTEN by an approval -- the original time is not recoverable here"
				if overwritten else
				"written by an approval (the punch was missing)" if cint(p.from_request) else
				"as recorded, never rewritten"
			),
		})

	requests = frappe.db.sql(
		"""
		SELECT name, reason, workflow_state, docstatus, owner AS raised_by, shift,
		       IFNULL(custom_is_punch_edit, 0) AS is_punch_edit,
		       IFNULL(custom_raised_by_hr, 0) AS raised_by_hr, modified
		FROM `tabAttendance Request`
		WHERE employee = %(emp)s AND from_date <= %(d)s AND to_date >= %(d)s AND docstatus < 2
		ORDER BY modified
		""",
		{"emp": emp, "d": date},
		as_dict=True,
	)
	for r in requests:
		r["modified"] = str(r["modified"])
		r["details"] = frappe.db.sql(
			"""
			SELECT attendance_date, IFNULL(edit_check_in, 0) AS edit_check_in, check_in,
			       IFNULL(edit_check_out, 0) AS edit_check_out, check_out
			FROM `tabAttendance Request Detail`
			WHERE parent = %(p)s AND attendance_date = %(d)s
			""",
			{"p": r["name"], "d": date},
			as_dict=True,
		)
		# What the fixed code would do with this request today.
		if r["reason"] == "On Duty":
			r["under_the_fix"] = "fills only a MISSING punch; a recorded one is left alone"
		else:
			r["under_the_fix"] = "still overwrites, but lands on the day's first IN / last OUT"

	attendance = frappe.db.sql(
		"""
		SELECT name, status, in_time, out_time, working_hours, attendance_request, docstatus
		FROM `tabAttendance` WHERE employee = %(emp)s AND attendance_date = %(d)s
		""",
		{"emp": emp, "d": date},
		as_dict=True,
	)
	for a in attendance:
		a["in_time"] = str(a["in_time"]) if a["in_time"] else None
		a["out_time"] = str(a["out_time"]) if a["out_time"] else None

	return {
		"employee": emp,
		"employee_name": frappe.db.get_value("Employee", emp, "employee_name"),
		"date": date,
		"punches": rows,
		"requests": requests,
		"attendance": attendance,
	}
