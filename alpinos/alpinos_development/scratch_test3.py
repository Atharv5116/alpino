"""Verification suite for the attendance batch shell (timesheet rows 163-169).

Run:  bench --site alpinos.test execute alpinos.alpinos_development.scratch_test3.run
Temporary test harness — safe to delete once signed off.

The calculation engines (percentage, comp-off, shift cap) and their tests are
parked on branch `attendance-phase2`; merging that branch restores them.
"""

import frappe
from frappe.utils import flt

PASS = []
FAIL = []


def check(label, actual, expected):
	ok = flt(actual) == flt(expected) if isinstance(expected, (int, float)) else actual == expected
	(PASS if ok else FAIL).append(label)
	print(("  OK  " if ok else "  FAIL") + f"  {label}: {actual!r}" + ("" if ok else f"  (expected {expected!r})"))


def run():
	frappe.set_user("Administrator")
	try:
		test_shell()
		test_permissions()
	except Exception:
		print("\n!!! SUITE CRASHED !!!")
		print(frappe.get_traceback())
	print(f"\n===== RESULT: {len(PASS)} passed, {len(FAIL)} failed =====")
	frappe.db.commit()


def _drop_batch(name):
	if frappe.db.exists("Monthly Attendance Batch", name):
		doc = frappe.get_doc("Monthly Attendance Batch", name)
		if doc.docstatus == 1:
			doc.cancel()
		frappe.delete_doc("Monthly Attendance Batch", name, force=1, ignore_permissions=True)


def test_shell():
	print("=== ROWS 163-165: categorization, batch, workflow ===")
	check("Salary Category engine field", bool(
		frappe.get_meta("Salary Category").get_field("attendance_rule_engine")), True)
	check("default categories seeded", frappe.db.count(
		"Salary Category", {"attendance_rule_engine": ["!=", ""]}) >= 3, True)
	check("workflow exists", bool(frappe.db.exists("Workflow", "Monthly Attendance Batch Approval")), True)

	company = frappe.get_all("Company", limit=1)[0].name
	_drop_batch("ATT-BATCH-2026-06-HO")
	b = frappe.get_doc(
		{"doctype": "Monthly Attendance Batch", "rule_engine": "HO/Admin",
		 "payroll_month": "2026-06-10", "company": company}
	)
	b.insert(ignore_permissions=True)
	check("name normalized", b.name, "ATT-BATCH-2026-06-HO")
	check("month normalized", str(b.payroll_month), "2026-06-01")
	check("initial state", b.workflow_state or "Draft", "Draft")

	r = b.populate_rows()
	check("rows generated", r["rows"] > 0, True)

	try:
		frappe.get_doc(
			{"doctype": "Monthly Attendance Batch", "rule_engine": "HO/Admin",
			 "payroll_month": "2026-06-01", "company": company}
		).insert(ignore_permissions=True)
		check("duplicate blocked", "allowed", "blocked")
	except Exception:
		check("duplicate blocked", "blocked", "blocked")

	from frappe.model.workflow import apply_workflow

	apply_workflow(b, "Submit for Approval")
	apply_workflow(frappe.get_doc("Monthly Attendance Batch", b.name), "Approve")
	b = frappe.get_doc("Monthly Attendance Batch", b.name)
	check("approved (submitted)", b.docstatus, 1)

	print("\n=== ROW 168: read-only after approval ===")
	try:
		b.populate_rows()
		check("populate blocked after approve", "allowed", "blocked")
	except Exception:
		check("populate blocked after approve", "blocked", "blocked")

	apply_workflow(b, "Lock")
	check("locked", frappe.db.get_value("Monthly Attendance Batch", b.name, "workflow_state"), "Locked")
	# leave the batch on the site for browser inspection


def test_permissions():
	print("\n=== ROW 169: roles & permissions ===")
	from alpinos.attendance_batch_api import create_batch, get_batches

	for email, role in (("hr.test@alpinos.test", "HR Manager"), ("accounts.test@alpinos.test", "Accounts User")):
		if not frappe.db.exists("User", email):
			u = frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": email.split(".")[0].title(), "send_welcome_email": 0}
			)
			u.append("roles", {"role": role})
			u.insert(ignore_permissions=True)

	frappe.set_user("accounts.test@alpinos.test")
	check("accounts can list", isinstance(get_batches(), dict), True)
	try:
		create_batch("WH ESSL", "2026-06-01")
		check("accounts create blocked", "allowed", "blocked")
	except Exception:
		check("accounts create blocked", "blocked", "blocked")

	frappe.set_user("hr.test@alpinos.test")
	try:
		name = create_batch("WH ESSL", "2026-06-01")
		check("HR can create", bool(name), True)
	except Exception:
		check("HR can create", "error", True)
		name = None
	frappe.set_user("Administrator")
	if name:
		frappe.delete_doc("Monthly Attendance Batch", name, force=1, ignore_permissions=True)
