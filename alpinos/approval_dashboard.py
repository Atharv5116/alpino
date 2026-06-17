"""Pending-approvals queue for the Approvals workspace.

get_pending_approvals returns ONLY the requests currently awaiting THIS user's action — i.e.
where the user is the approver the request is pending on right now (not requests pending
someone else, and not requests already past this user). Filtered to a date range that
defaults to the current month.

Per doctype, "pending this user" means (named approver / RM sees their own; any HR sees all):
  - Leave Application: status Pending Reporting Manager Approval -> reporting manager;
                       status Pending HR Approval -> HR
  - Expense Claim: approval_status Pending RM Approval -> reporting manager
  - Attendance Request: Pending RM Approval -> reporting_person == user; Pending HR Approval -> HR
  - Work From Home Request: Pending Reporting Manager Approval -> leave_approver == user;
                            Pending HOD Approval -> user has HOD; Pending HR Approval -> user is HR

Defensive: a doctype that is missing or errors is skipped, never blocking the others.
"""

import frappe
from frappe.utils import get_first_day, get_last_day, getdate

HR_ROLES = ("HR Manager", "HR User")


def _user_is_rm_of(employee, user):
	"""True if `user` is the reporting manager (Employee.reports_to) of `employee`."""
	if not employee:
		return False
	rm_emp = frappe.db.get_value("Employee", employee, "reports_to")
	return bool(rm_emp) and frappe.db.get_value("Employee", rm_emp, "user_id") == user


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

	# Pending items are filtered by WHEN THEY WERE APPLIED (creation), not by the leave /
	# expense / attendance event date — so a still-pending request isn't hidden just because
	# its event date falls outside the selected month.
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

	# --- Leave Application: pending the leave approver ---
	def _leave():
		if not frappe.db.exists("DocType", "Leave Application"):
			return
		for r in frappe.get_all(
			"Leave Application",
			filters=[
				["status", "in", ["Pending Reporting Manager Approval", "Pending HR Approval"]],
				["docstatus", "<", 2],
			] + created_range,
			fields=["name", "employee", "from_date", "status", "leave_approver"],
			order_by="modified desc", limit=200,
		):
			# RM stage -> the employee's OWN reporting manager: the named leave_approver
			# AND the employee's reports_to. Any HR Manager sees all (HR stage + HR-sees-all).
			pending_me = (
				(r.status == "Pending Reporting Manager Approval"
					and r.leave_approver == user and _user_is_rm_of(r.employee, user))
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
			# RM stage -> the employee's OWN reporting manager: the named expense_approver
			# AND the employee's reports_to. Any HR Manager sees all.
			if (r.expense_approver == user and _user_is_rm_of(r.employee, user)) or is_hr:
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
