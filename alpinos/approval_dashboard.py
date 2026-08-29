"""Pending-approvals queue for the Approvals workspace (only requests awaiting this user)."""

import frappe
from frappe.utils import get_first_day, get_last_day, getdate

HR_ROLES = ("HR Manager", "HR User")


def _user_is_rm_of(employee, user):
	"""True if `user` is the reporting manager (Employee.reports_to) of `employee`."""
	if not employee:
		return False
	rm_emp = frappe.db.get_value("Employee", employee, "reports_to")
	return bool(rm_emp) and frappe.db.get_value("Employee", rm_emp, "user_id") == user


def _wf_state_field(doctype):
	"""Field an active Workflow stores its state in for `doctype` (None if no workflow)."""
	return frappe.db.get_value("Workflow", {"document_type": doctype, "is_active": 1}, "workflow_state_field")


@frappe.whitelist()
def get_pending_approvals(from_date=None, to_date=None):
	user = frappe.session.user
	roles = set(frappe.get_roles(user))
	is_hr = user == "Administrator" or bool(set(HR_ROLES) & roles)
	is_hod = "HOD" in roles
	emp = frappe.db.get_value("Employee", {"user_id": user}, "name")
	is_rm = bool(emp) and bool(frappe.db.exists("Employee", {"reports_to": emp}))

	today = getdate()
	from_date = getdate(from_date) if from_date else get_first_day(today)
	to_date = getdate(to_date) if to_date else get_last_day(today)

	# Filter by creation date, not the event date, so a still-pending request isn't hidden.
	created_range = [["creation", ">=", str(from_date)], ["creation", "<=", str(to_date) + " 23:59:59"]]

	allowed = is_hr or is_hod or is_rm
	result = {
		"allowed": allowed,
		"items": [],
		"total": 0,
		"from_date": str(from_date),
		"to_date": str(to_date),
	}
	if not allowed:
		return result

	items = []

	def add(doctype, label, name, employee, date, route):
		items.append({
			"type": label,
			"doctype": doctype,
			"name": name,
			"employee": employee,
			"employee_name": frappe.db.get_value("Employee", employee, "employee_name") if employee else "",
			"date": str(date) if date else "",
			"route": route,
		})

	def safe(fn):
		try:
			fn()
		except Exception:
			frappe.log_error(frappe.get_traceback(), "Approvals dashboard")

	# --- Leave Application: pending the reporting manager / HR ---
	def _leave():
		if not frappe.db.exists("DocType", "Leave Application"):
			return
		# The workflow keeps its state in its own field; read that rather than assuming status.
		sf = _wf_state_field("Leave Application") or "status"
		for r in frappe.get_all(
			"Leave Application",
			filters=[
				[sf, "in", ["Pending Reporting Manager Approval", "Pending HR Approval"]],
				["docstatus", "<", 2],
			] + created_range,
			fields=["name", "employee", "from_date", sf],
			order_by="modified desc", limit=200,
		):
			state = r.get(sf)
			# RM stage: the employee's own reporting manager (reports_to) with the Reporting
			# Manager role, not the leave_approver field. Any HR Manager sees all.
			pending_me = (
				(state == "Pending Reporting Manager Approval"
					and _user_is_rm_of(r.employee, user)
					and "Reporting Manager" in roles)
				or is_hr
			)
			if pending_me:
				add("Leave Application", "Leave", r.name, r.employee, r.from_date, "leave-application")

	# --- Expense Claim: pending the expense approver ---
	def _expense():
		if not frappe.db.exists("DocType", "Expense Claim"):
			return
		for r in frappe.get_all(
			"Expense Claim",
			filters=[["approval_status", "=", "Pending RM Approval"], ["docstatus", "<", 2]] + created_range,
			fields=["name", "employee", "posting_date", "expense_approver"],
			order_by="modified desc", limit=200,
		):
			# RM stage: the employee's own reporting manager with the Reporting Manager role.
			if (_user_is_rm_of(r.employee, user) and "Reporting Manager" in roles) or is_hr:
				add("Expense Claim", "Expense", r.name, r.employee, r.posting_date, "expense-claim")

	# --- Attendance Request: RM step -> reporting_person; HR step -> HR ---
	def _attendance():
		if not frappe.db.exists("DocType", "Attendance Request"):
			return
		for r in frappe.get_all(
			"Attendance Request",
			filters=[
				["docstatus", "=", 0],
				["workflow_state", "in", ["Pending RM Approval", "Pending HR Approval"]],
			] + created_range,
			fields=["name", "employee", "from_date", "workflow_state", "reporting_person"],
			order_by="modified desc", limit=200,
		):
			pending_me = (
				(r.workflow_state == "Pending RM Approval" and r.reporting_person == user)
				or (r.workflow_state == "Pending HR Approval" and is_hr)
			)
			if pending_me:
				add("Attendance Request", "Attendance", r.name, r.employee, r.from_date, "attendance-request")

	# --- Work From Home Request: RM step -> leave_approver; HOD -> HOD role; HR -> HR ---
	def _wfh():
		if not frappe.db.exists("DocType", "Work From Home Request"):
			return
		for r in frappe.get_all(
			"Work From Home Request",
			filters=[
				["status", "in", ["Pending Reporting Manager Approval", "Pending HOD Approval", "Pending HR Approval"]],
			] + created_range,
			fields=["name", "employee", "date", "status", "leave_approver"],
			order_by="modified desc", limit=200,
		):
			pending_me = (
				(r.status == "Pending Reporting Manager Approval" and r.leave_approver == user)
				or (r.status == "Pending HOD Approval" and is_hod)
				or (r.status == "Pending HR Approval" and is_hr)
			)
			if pending_me:
				add("Work From Home Request", "WFH", r.name, r.employee, r.date, "work-from-home-request")

	for fn in (_leave, _expense, _attendance, _wfh):
		safe(fn)

	result["items"] = items
	result["total"] = len(items)
	return result
