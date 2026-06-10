"""Pending-approvals queue for the Approvals workspace.

get_pending_approvals returns the requests awaiting the current user's action:
  - HR (HR Manager / HR User): everything pending approval.
  - Reporting Manager: pending requests of their direct reports only.

Covers Leave Application, Attendance Request, Work From Home Request and Expense Claim.
Defensive: a doctype that is missing or errors is skipped, never blocking the others.
"""

import frappe


HR_ROLES = ("HR Manager", "HR User")

# (doctype, label, pending filters, employee field, date field)
SOURCES = (
	("Leave Application", "Leave", {"status": "Open", "docstatus": ["<", 2]}, "employee", "from_date"),
	("Attendance Request", "Attendance", {"docstatus": 0}, "employee", "from_date"),
	(
		"Work From Home Request",
		"WFH",
		{"status": ["in", ["Pending Reporting Manager Approval", "Pending HOD Approval", "Pending HR Approval"]]},
		"employee",
		"date",
	),
	("Expense Claim", "Expense", {"approval_status": "Draft", "docstatus": 0}, "employee", "posting_date"),
)


@frappe.whitelist()
def get_pending_approvals():
	user = frappe.session.user
	is_hr = user == "Administrator" or bool(set(HR_ROLES) & set(frappe.get_roles(user)))

	reports = None
	if not is_hr:
		rm_emp = frappe.db.get_value("Employee", {"user_id": user}, "name")
		if not rm_emp:
			return {"allowed": False, "items": [], "total": 0}
		reports = frappe.get_all("Employee", filters={"reports_to": rm_emp}, pluck="name")
		if not reports:
			return {"allowed": True, "items": [], "total": 0}

	items = []
	for doctype, label, filt, emp_field, date_field in SOURCES:
		if not frappe.db.exists("DocType", doctype):
			continue
		filters = dict(filt)
		if not is_hr:
			filters[emp_field] = ["in", reports]
		try:
			rows = frappe.get_all(
				doctype,
				filters=filters,
				fields=["name", f"{emp_field} as employee", f"{date_field} as date"],
				order_by="modified desc",
				limit=200,
			)
		except Exception:
			continue
		for r in rows:
			items.append(
				{
					"type": label,
					"doctype": doctype,
					"name": r.name,
					"employee": r.get("employee"),
					"employee_name": frappe.db.get_value("Employee", r.get("employee"), "employee_name")
					if r.get("employee")
					else "",
					"date": str(r.get("date")) if r.get("date") else "",
					"route": doctype.lower().replace(" ", "-"),
				}
			)
	return {"allowed": True, "items": items, "total": len(items)}
