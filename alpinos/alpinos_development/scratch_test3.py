"""Phase-1 verification suite for the HRMS Payroll build (rows 163-171).

Run:  bench --site alpinos.test execute alpinos.alpinos_development.scratch_test3.run
Temporary test harness — safe to delete once Phase 1 is signed off.
"""

import json

import frappe
from frappe.utils import flt

SHIFT = "ALP Day Shift"
HLIST = "ALP Test Holidays 2026"
EMP_ATT = "HR-EMP-00001"      # percentage-engine subject (HO/Admin)
EMP_CO_FULL = "HR-EMP-00002"  # comp-off full-day subject (7.5h on Sunday)
EMP_CO_HALF = "HR-EMP-00004"  # comp-off half-day subject (5h on Sunday)
SUNDAY = "2026-06-07"

PASS = []
FAIL = []


def check(label, actual, expected):
	ok = flt(actual) == flt(expected) if isinstance(expected, (int, float)) else actual == expected
	(PASS if ok else FAIL).append(f"{label}: got {actual!r}, expected {expected!r}")
	print(("  OK  " if ok else "  FAIL") + f"  {label}: {actual!r}" + ("" if ok else f"  (expected {expected!r})"))


def run():
	frappe.set_user("Administrator")
	try:
		seed()
		test_percentage_engine()
		test_comp_off()
		test_permissions()
	except Exception:
		print("\n!!! SUITE CRASHED !!!")
		print(frappe.get_traceback())
	print(f"\n===== RESULT: {len(PASS)} passed, {len(FAIL)} failed =====")
	for f in FAIL:
		print("  FAIL:", f)
	frappe.db.commit()


# ------------------------------------------------------------------------ seed

def seed():
	print("=== SEED ===")
	if not frappe.db.exists("Shift Type", SHIFT):
		frappe.get_doc(
			{"doctype": "Shift Type", "name": SHIFT, "start_time": "10:00:00", "end_time": "18:15:00"}
		).insert(ignore_permissions=True)

	if not frappe.db.exists("Holiday List", HLIST):
		hl = frappe.get_doc(
			{"doctype": "Holiday List", "holiday_list_name": HLIST, "from_date": "2026-01-01", "to_date": "2026-12-31"}
		)
		for d in ("2026-06-07", "2026-06-14", "2026-06-21", "2026-06-28"):
			hl.append("holidays", {"holiday_date": d, "description": "Sunday", "weekly_off": 1})
		hl.append("holidays", {"holiday_date": "2026-06-15", "description": "Test Festival", "weekly_off": 0})
		hl.insert(ignore_permissions=True)

	for emp in (EMP_ATT, EMP_CO_FULL, EMP_CO_HALF):
		frappe.db.set_value("Employee", emp, "holiday_list", HLIST)

	if not frappe.db.exists("Leave Period", {"from_date": "2026-01-01", "to_date": "2026-12-31"}):
		company = frappe.get_all("Company", limit=1)[0].name
		frappe.get_doc(
			{"doctype": "Leave Period", "from_date": "2026-01-01", "to_date": "2026-12-31",
			 "company": company, "is_active": 1}
		).insert(ignore_permissions=True)

	# June attendance for the percentage subject.
	frappe.db.sql(
		"DELETE FROM `tabAttendance` WHERE employee=%s AND attendance_date BETWEEN '2026-06-01' AND '2026-06-30'",
		EMP_ATT,
	)
	rows = [
		("2026-06-01", 8.20, "10:05:00"),  # 99.4% Present, grace
		("2026-06-02", 8.00, "10:10:00"),  # 96.97% Half Day (below 97 boundary)
		("2026-06-03", 5.00, "10:00:00"),  # 60.6% Half Day
		("2026-06-04", 3.00, "10:00:00"),  # 36.4% Absent
		("2026-06-05", 8.25, "10:20:00"),  # Present + tier-15 flag 1
		("2026-06-08", 8.25, "10:35:00"),  # Present + tier-30 flag 1
		("2026-06-09", 8.25, "10:20:00"),  # tier-15 flag 2
		("2026-06-10", 8.25, "10:16:00"),  # tier-15 flag 3
		("2026-06-11", 8.25, "10:29:00"),  # tier-15 flag 4 -> deduct 0.5
		("2026-06-12", 8.25, "10:01:00"),  # Present, grace
	]
	for date, hours, in_t in rows:
		att = frappe.get_doc(
			{"doctype": "Attendance", "employee": EMP_ATT, "attendance_date": date,
			 "status": "Present", "shift": SHIFT, "working_hours": hours,
			 "in_time": f"{date} {in_t}", "out_time": f"{date} 18:15:00"}
		)
		att.flags.ignore_permissions = True
		att.flags.ignore_validate = True
		att.insert()
		att.submit()

	# Sunday check-ins for the comp-off subjects.
	frappe.db.sql(
		"DELETE FROM `tabEmployee Checkin` WHERE employee IN (%s, %s) AND DATE(time)=%s",
		(EMP_CO_FULL, EMP_CO_HALF, SUNDAY),
	)
	frappe.db.sql(
		"DELETE FROM `tabAttendance` WHERE employee IN (%s, %s) AND attendance_date=%s",
		(EMP_CO_FULL, EMP_CO_HALF, SUNDAY),
	)
	for name in frappe.get_all(
		"Compensatory Leave Request", filters={"work_from_date": SUNDAY}, pluck="name"
	):
		doc = frappe.get_doc("Compensatory Leave Request", name)
		if doc.docstatus == 1:
			doc.cancel()
		frappe.delete_doc("Compensatory Leave Request", name, force=1, ignore_permissions=True)

	for emp, in_t, out_t in (
		(EMP_CO_FULL, "09:00:00", "16:30:00"),  # 7.5h > 6 -> full comp-off
		(EMP_CO_HALF, "10:00:00", "15:00:00"),  # 5.0h > 4 -> half comp-off
	):
		for t, log in ((in_t, "IN"), (out_t, "OUT")):
			frappe.get_doc(
				{"doctype": "Employee Checkin", "employee": emp, "time": f"{SUNDAY} {t}", "log_type": log}
			).insert(ignore_permissions=True)
	print("  seeded")


# ------------------------------------------------- row 170: percentage engine

def test_percentage_engine():
	print("\n=== ROW 170: percentage engine ===")
	from alpinos.attendance_percentage import classify_day, get_shift_hours

	check("shift hours", get_shift_hours(SHIFT), 8.25)
	check("classify 8.20h", classify_day(8.20, 8.25)[0], "Present")
	check("classify 8.00h (96.97%)", classify_day(8.00, 8.25)[0], "Half Day")
	check("classify 4.13h (50.06%)", classify_day(4.13, 8.25)[0], "Half Day")
	check("classify 4.0h (48.5%)", classify_day(4.0, 8.25)[0], "Absent")
	check("Saturday 3.9h of 4h (97.5%)", classify_day(3.9, 4.0)[0], "Present")

	company = frappe.get_all("Company", limit=1)[0].name
	if frappe.db.exists("Monthly Attendance Batch", "ATT-BATCH-2026-06-HO"):
		old = frappe.get_doc("Monthly Attendance Batch", "ATT-BATCH-2026-06-HO")
		if old.docstatus == 1:
			old.cancel()
		frappe.delete_doc("Monthly Attendance Batch", "ATT-BATCH-2026-06-HO", force=1, ignore_permissions=True)
	b = frappe.get_doc(
		{"doctype": "Monthly Attendance Batch", "rule_engine": "HO/Admin",
		 "payroll_month": "2026-06-01", "company": company}
	)
	b.insert(ignore_permissions=True)
	b.populate_rows()
	b.reload()
	row = next(r for r in b.rows if r.employee == EMP_ATT)

	# Present: Jun 1, 5, 8, 9, 10, 11, 12 = 7 (a late arrival is still a full day
	# when hours are complete); Half: Jun 2, 3; Absent: Jun 4 + unmarked weekdays.
	check("working days (30-4Sun-1PH)", row.working_days, 25)
	check("present days", row.present_days, 7)
	check("half days", row.half_days, 2)
	check("weekends", row.weekends, 4)
	check("public holidays", row.public_holidays, 1)
	check("late group1 (15m)", row.late_group1_count, 4)
	check("late group2 (30m)", row.late_group2_count, 1)
	check("late deduction", row.late_deduction_days, 0.5)
	check("payable (7 + 2x0.5 - 0.5)", row.payable_days, 7.5)

	dd = json.loads(row.day_data)
	check("day_data 06-02 status", dd["2026-06-02"]["status"], "Half Day")
	check("day_data 06-15 status", dd["2026-06-15"]["status"], "Holiday")
	check("day_data 06-08 late tier", dd["2026-06-08"].get("late_tier"), 30)

	test_brd_scenarios(b)


def _seed_attendance(emp, date, status, hours, in_t, **extra):
	att = frappe.get_doc(
		{"doctype": "Attendance", "employee": emp, "attendance_date": date,
		 "status": status, "shift": SHIFT, "working_hours": hours,
		 "in_time": f"{date} {in_t}", "out_time": f"{date} 18:15:00", **extra}
	)
	att.flags.ignore_permissions = True
	att.flags.ignore_validate = True
	att.insert()
	att.submit()


def test_brd_scenarios(batch):
	"""BRD §1-§3D edge scenarios: OD, Present-by-Default, WFH late, half-day leave."""
	print("\n=== BRD SCENARIOS (§2, §3D sc.2/3/6) ===")
	emp_od = EMP_CO_FULL   # reuse: give them scenario attendance in June
	emp_pbd = EMP_CO_HALF  # Present-by-Default subject

	frappe.db.sql(
		"DELETE FROM `tabAttendance` WHERE employee IN (%s,%s) AND attendance_date BETWEEN '2026-06-01' AND '2026-06-06'",
		(emp_od, emp_pbd),
	)
	# OD day recorded the way the app records it: Present + reason On Duty, late in_time.
	_seed_attendance(emp_od, "2026-06-01", "Present", 8.25, "10:40:00", attendance_request_reason="On Duty")
	# WFH day with a late clock-in (scenario 2: must flag).
	_seed_attendance(emp_od, "2026-06-02", "Work From Home", 8.25, "10:20:00")
	# Approved half-day leave on record with a "late" in-time (scenario 3: must NOT flag).
	_seed_attendance(emp_od, "2026-06-03", "Half Day", 4.13, "14:10:00", leave_type="Casual Leave")

	# Present-by-Default employee: flag on, and an Absent punch record that must be ignored.
	frappe.db.set_value("Employee", emp_pbd, "custom_present_by_default", 1)
	_seed_attendance(emp_pbd, "2026-06-01", "Absent", 0, "10:00:00")

	batch.populate_rows()
	batch.reload()
	row_od = next(r for r in batch.rows if r.employee == emp_od)
	row_pbd = next(r for r in batch.rows if r.employee == emp_pbd)
	dd_od = json.loads(row_od.day_data)

	check("OD day counted (via reason field)", row_od.od_days, 1)
	check("OD late 10:40 gives NO flag (sc.6)", dd_od["2026-06-01"].get("late_tier"), None)
	check("WFH late 10:20 DOES flag (sc.2)", dd_od["2026-06-02"].get("late_tier"), 15)
	check("WFH still full paid day", dd_od["2026-06-02"]["status"], "WFH")
	check("half-day-leave day: no late flag (sc.3)", dd_od["2026-06-03"].get("late_tier"), None)

	check("PbD: present = all working days", row_pbd.present_days, row_pbd.working_days)
	check("PbD: zero absents", row_pbd.absent_days, 0)
	check("PbD: zero late flags", (row_pbd.late_group1_count or 0) + (row_pbd.late_group2_count or 0), 0)
	check("PbD: payable = working days", row_pbd.payable_days, row_pbd.working_days)

	frappe.db.set_value("Employee", emp_pbd, "custom_present_by_default", 0)

	test_wfh_two_halves(batch)
	test_shift_change_cap()


def test_wfh_two_halves(batch):
	"""BRD §3C: two separate half-day WFH requests sum to 1.0 in the monthly count."""
	print("\n=== BRD §3C: two WFH halves sum to 1.0 ===")
	frappe.db.sql(
		"DELETE FROM `tabWork From Home Request` WHERE employee=%s AND date BETWEEN '2026-06-01' AND '2026-06-30'",
		EMP_ATT,
	)
	for i, d in enumerate(("2026-06-16", "2026-06-18"), 1):
		frappe.db.sql(
			"""
			INSERT INTO `tabWork From Home Request`
				(name, employee, date, to_date, half_day, status, owner, creation, modified, modified_by, docstatus, idx)
			VALUES (%s, %s, %s, %s, 1, 'Approved', 'Administrator', NOW(), NOW(), 'Administrator', 0, 0)
			""",
			(f"WFH-TEST-{i}", EMP_ATT, d, d),
		)
	batch.populate_rows()
	batch.reload()
	row = next(r for r in batch.rows if r.employee == EMP_ATT)
	check("two half-day WFH -> count 1.0", row.wfh_count, 1.0)
	frappe.db.sql("DELETE FROM `tabWork From Home Request` WHERE name IN ('WFH-TEST-1','WFH-TEST-2')")


def test_shift_change_cap():
	"""BRD §4B: max 4 Shift Change Requests per employee per month (HR Manager exempt)."""
	print("\n=== BRD §4B: shift change 4/month cap ===")
	frappe.db.sql(
		"DELETE FROM `tabShift Request` WHERE employee=%s AND from_date BETWEEN '2026-07-01' AND '2026-07-31'",
		EMP_ATT,
	)
	for i in range(4):
		sr = frappe.get_doc(
			{"doctype": "Shift Request", "employee": EMP_ATT, "shift_type": SHIFT,
			 "from_date": f"2026-07-{6 + i:02d}", "to_date": f"2026-07-{6 + i:02d}", "status": "Draft"}
		)
		sr.flags.ignore_permissions = True
		sr.flags.ignore_validate = True  # skip HRMS approver checks; cap is tested below
		sr.flags.ignore_mandatory = True
		sr.insert()

	# 5th request in the same month, checked as a non-HR-Manager user.
	frappe.set_user("accounts.test@alpinos.test")
	fifth = frappe.get_doc(
		{"doctype": "Shift Request", "employee": EMP_ATT, "shift_type": SHIFT,
		 "from_date": "2026-07-20", "to_date": "2026-07-20", "status": "Draft"}
	)
	try:
		fifth._enforce_monthly_limit()
		check("5th shift request blocked", "allowed", "blocked")
	except frappe.ValidationError:
		check("5th shift request blocked", "blocked", "blocked")
	frappe.set_user("Administrator")

	# HR Manager is exempt.
	frappe.set_user("hr.test@alpinos.test")
	try:
		fifth._enforce_monthly_limit()
		check("HR Manager exempt from cap", "allowed", "allowed")
	except frappe.ValidationError:
		check("HR Manager exempt from cap", "blocked", "allowed")
	frappe.set_user("Administrator")

	frappe.db.sql(
		"DELETE FROM `tabShift Request` WHERE employee=%s AND from_date BETWEEN '2026-07-01' AND '2026-07-31'",
		EMP_ATT,
	)


# ------------------------------------------------------- row 171: comp-off

def test_comp_off():
	print("\n=== ROW 171: comp-off ===")
	from alpinos.comp_off_automation import COMP_LEAVE_TYPE, process_comp_off_detection

	check("leave type exists", bool(frappe.db.exists("Leave Type", COMP_LEAVE_TYPE)), True)
	check("workflow exists", bool(frappe.db.exists("Workflow", "Comp-Off Approval")), True)

	created = process_comp_off_detection(for_date=SUNDAY)
	check("requests created", len(created), 2)

	full = frappe.db.get_value(
		"Compensatory Leave Request", {"employee": EMP_CO_FULL, "work_from_date": SUNDAY},
		["name", "half_day", "workflow_state"], as_dict=True,
	)
	half = frappe.db.get_value(
		"Compensatory Leave Request", {"employee": EMP_CO_HALF, "work_from_date": SUNDAY},
		["name", "half_day", "workflow_state"], as_dict=True,
	)
	check("7.5h -> full day request", full and full.half_day, 0)
	check("5.0h -> half day request", half and half.half_day, 1)
	check("parked at RM step", full and full.workflow_state, "Pending RM Approval")

	# Idempotency: running again must not duplicate.
	check("rerun creates none", len(process_comp_off_detection(for_date=SUNDAY)), 0)

	# Approve the full one -> submit -> HRMS allocates the leave.
	from frappe.model.workflow import apply_workflow

	doc = frappe.get_doc("Compensatory Leave Request", full.name)
	apply_workflow(doc, "Approve")
	doc.reload()
	check("approved docstatus", doc.docstatus, 1)
	check("leave allocated", bool(doc.leave_allocation), True)
	if doc.leave_allocation:
		alloc = frappe.db.get_value(
			"Leave Allocation", doc.leave_allocation, ["leave_type", "total_leaves_allocated"], as_dict=True
		)
		check("allocation leave type", alloc.leave_type, COMP_LEAVE_TYPE)
		check("allocated days", alloc.total_leaves_allocated, 1.0)


# --------------------------------------------- rows 168/169: perms + read-only

def test_permissions():
	print("\n=== ROWS 168/169: permissions & read-only ===")
	from alpinos.attendance_batch_api import create_batch, get_batches, populate_batch_rows

	for email, role in (("hr.test@alpinos.test", "HR Manager"), ("accounts.test@alpinos.test", "Accounts User")):
		if not frappe.db.exists("User", email):
			u = frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": email.split(".")[0].title(), "send_welcome_email": 0}
			)
			u.append("roles", {"role": role})
			u.insert(ignore_permissions=True)
		else:
			u = frappe.get_doc("User", email)
			if role not in [r.role for r in u.roles]:
				u.append("roles", {"role": role})
				u.save(ignore_permissions=True)

	# Accounts: read yes, create no.
	frappe.set_user("accounts.test@alpinos.test")
	try:
		r = get_batches()
		check("accounts can list", isinstance(r, dict), True)
	except Exception:
		check("accounts can list", "PermissionError", True)
	try:
		create_batch("WH ESSL", "2026-06-01")
		check("accounts create blocked", "allowed", "blocked")
	except frappe.PermissionError:
		check("accounts create blocked", "blocked", "blocked")
	except Exception as e:
		check("accounts create blocked", type(e).__name__, "blocked")

	# HR Manager: create yes.
	frappe.set_user("hr.test@alpinos.test")
	try:
		name = create_batch("WH ESSL", "2026-06-01")
		check("HR can create", bool(name), True)
	except Exception as e:
		check("HR can create", f"error {type(e).__name__}", True)
		name = None

	frappe.set_user("Administrator")

	# Read-only after approval: approve the June HO batch, then try to repopulate.
	from frappe.model.workflow import apply_workflow

	b = frappe.get_doc("Monthly Attendance Batch", "ATT-BATCH-2026-06-HO")
	apply_workflow(b, "Submit for Approval")
	apply_workflow(frappe.get_doc("Monthly Attendance Batch", b.name), "Approve")
	try:
		populate_batch_rows(b.name)
		check("populate blocked after approve", "allowed", "blocked")
	except Exception:
		check("populate blocked after approve", "blocked", "blocked")
	# leave it Approved on the site for browser inspection

	if name:
		frappe.delete_doc("Monthly Attendance Batch", name, force=1, ignore_permissions=True)
