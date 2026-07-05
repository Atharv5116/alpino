"""Comp-Off auto-generation (BRD ALP_HRMS_Payroll_001 §3E).

When an HO/Admin employee works on a Public Holiday or Weekly Off:

  worked > 4.0 hours  ->  0.5 comp-off request
  worked > 6.0 hours  ->  1.0 comp-off request

The daily job scans recent holiday check-ins, marks the holiday Attendance
(Half Day / Present — HRMS's Compensatory Leave Request validation requires
it), creates the Compensatory Leave Request and parks it with the employee's
Reporting Manager for approval (workflow in comp_off_workflow_setup.py).
On submit HRMS allocates the leave, so it shows on the employee's leave
screen; on Approve/Reject the employee is notified (notify_comp_off_outcome).

Late penalties never apply to these days (BRD §3D scenario 4) — only total
hours matter, which is exactly what this module measures.
"""

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate, nowdate, time_diff_in_hours

COMP_LEAVE_TYPE = "Compensatory Off"
HALF_DAY_HOURS = 4.0
FULL_DAY_HOURS = 6.0
LOOKBACK_DAYS = 3  # catch late biometric syncs


def setup_comp_off_leave_type():
	"""Ensure the compensatory Leave Type exists (run on migrate)."""
	if frappe.db.exists("Leave Type", COMP_LEAVE_TYPE):
		frappe.db.set_value("Leave Type", COMP_LEAVE_TYPE, "is_compensatory", 1)
		return
	frappe.get_doc(
		{
			"doctype": "Leave Type",
			"leave_type_name": COMP_LEAVE_TYPE,
			"is_compensatory": 1,
			"allow_negative": 0,
			"include_holiday": 0,
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()


def process_comp_off_detection(for_date=None):
	"""Daily job: raise comp-off requests for holiday work in the lookback window."""
	dates = (
		[getdate(for_date)]
		if for_date
		else [add_days(getdate(nowdate()), -offset) for offset in range(1, LOOKBACK_DAYS + 1)]
	)
	created = []
	for day in dates:
		created += _process_day(day)
	return created


def _process_day(day):
	created = []
	# Employees with at least 2 punches that day (need an in AND an out).
	rows = frappe.db.sql(
		"""
		SELECT employee, MIN(time) AS first_in, MAX(time) AS last_out, COUNT(*) AS punches
		FROM `tabEmployee Checkin`
		WHERE DATE(time) = %s
		GROUP BY employee
		HAVING punches >= 2
		""",
		(day,),
		as_dict=True,
	)
	for r in rows:
		try:
			name = _process_employee_day(r, day)
			if name:
				created.append(name)
		except Exception:
			frappe.log_error(
				title="Comp-Off detection",
				message=f"{r.employee} {day}\n{frappe.get_traceback()}",
			)
	return created


def _process_employee_day(row, day):
	employee = row.employee
	if frappe.db.get_value("Employee", employee, "status") != "Active":
		return None
	if not _is_holiday_for(employee, day):
		return None

	worked = flt(time_diff_in_hours(row.last_out, row.first_in), 2)
	if worked <= HALF_DAY_HOURS:
		return None
	is_full = worked > FULL_DAY_HOURS

	# One request per employee per worked day.
	if frappe.db.exists(
		"Compensatory Leave Request",
		{"employee": employee, "work_from_date": day, "docstatus": ["!=", 2]},
	):
		return None

	_ensure_attendance(employee, day, worked, "Present" if is_full else "Half Day")

	request = frappe.get_doc(
		{
			"doctype": "Compensatory Leave Request",
			"employee": employee,
			"leave_type": COMP_LEAVE_TYPE,
			"work_from_date": day,
			"work_end_date": day,
			"half_day": 0 if is_full else 1,
			"half_day_date": None if is_full else day,
			"reason": _(
				"Auto-generated: worked {0} hours on holiday/weekly off {1}."
			).format(worked, day),
		}
	)
	request.flags.ignore_permissions = True
	request.insert()
	# Straight to the RM step — the request is system-raised, nothing to draft.
	if frappe.db.has_column("Compensatory Leave Request", "workflow_state"):
		frappe.db.set_value(
			"Compensatory Leave Request", request.name, "workflow_state", "Pending RM Approval"
		)
	_notify_rm(request, worked)
	return request.name


def _is_holiday_for(employee, day):
	from hrms.hr.utils import get_holiday_dates_for_employee

	try:
		return bool(get_holiday_dates_for_employee(employee, day, day))
	except Exception:
		return False


def _ensure_attendance(employee, day, worked, status):
	"""HRMS's request validation needs a submitted Attendance for the day."""
	existing = frappe.db.get_value(
		"Attendance",
		{"employee": employee, "attendance_date": day, "docstatus": ["!=", 2]},
		["name", "status", "docstatus"],
		as_dict=True,
	)
	if existing:
		if existing.docstatus == 0:
			att = frappe.get_doc("Attendance", existing.name)
			att.status = status
			att.working_hours = worked
			att.flags.ignore_permissions = True
			att.save()
			att.submit()
		return
	att = frappe.get_doc(
		{
			"doctype": "Attendance",
			"employee": employee,
			"attendance_date": day,
			"status": status,
			"working_hours": worked,
		}
	)
	att.flags.ignore_permissions = True
	att.flags.ignore_validate = True
	att.insert()
	att.submit()


def _notify_rm(request, worked):
	"""Notification Log + ToDo for the employee's reporting manager."""
	rm_user = _reporting_manager_user(request.employee)
	if not rm_user:
		return
	subject = _("Comp-Off approval: {0} worked {1}h on {2}").format(
		request.employee_name or request.employee, worked, request.work_from_date
	)
	_notification(rm_user, subject, request)
	try:
		from frappe.desk.form.assign_to import add as assign_to

		assign_to(
			{
				"assign_to": [rm_user],
				"doctype": request.doctype,
				"name": request.name,
				"description": subject,
			},
			ignore_permissions=True,
		)
	except Exception:
		pass  # duplicate assignment etc. — the notification already went out


def _reporting_manager_user(employee):
	reports_to = frappe.db.get_value("Employee", employee, "reports_to")
	if not reports_to:
		return None
	return frappe.db.get_value("Employee", reports_to, "user_id")


def _notification(user, subject, doc):
	try:
		frappe.get_doc(
			{
				"doctype": "Notification Log",
				"for_user": user,
				"type": "Alert",
				"subject": subject,
				"document_type": doc.doctype,
				"document_name": doc.name,
			}
		).insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(title="Comp-Off notification", message=frappe.get_traceback())


def notify_comp_off_outcome(doc, method=None):
	"""doc_events on_change: tell the employee when their request is decided."""
	state = doc.get("workflow_state")
	if state not in ("Approved", "Rejected"):
		return
	if not doc.has_value_changed("workflow_state"):
		return
	user = frappe.db.get_value("Employee", doc.employee, "user_id")
	if not user:
		return
	if state == "Approved":
		subject = _("Your Comp-Off for {0} was approved — leave credited.").format(doc.work_from_date)
	else:
		subject = _("Your Comp-Off for {0} was rejected.").format(doc.work_from_date)
	_notification(user, subject, doc)
