"""Home leave number cards show the signed-in person's OWN balance.

The cards "Casual Leave Balance" and "Bereavement Leave" used to be Report cards on
Employee Leave Balance Summary filtered by company and a fixed date (22 Apr 2026), so every
user saw the whole company's leave added up as on that day. They are now Custom cards that
call `my_leave_balance` with the card's leave type (filters_json {"leave_type": ...}).

The figure is the same "remaining" the Leave Application form shows: this allocation's
balance, with leaves already approved later in the allocation period taken off.
"""

import frappe
from frappe.utils import flt, getdate, nowdate

METHOD = "alpinos.my_leave_cards.my_leave_balance"
REPORT = "Employee Leave Balance Summary"


def _my_employee(user=None):
	user = user or frappe.session.user
	rows = frappe.get_all(
		"Employee",
		filters={"user_id": user, "status": "Active"},
		fields=["name", "company"],
		order_by="name asc",
	)
	if not rows:
		return None
	company = frappe.defaults.get_user_default("Company")
	return next((r.name for r in rows if r.company == company), rows[0].name)


def balance_for(employee, leave_type, date=None):
	"""Remaining leave of one type for one employee on `date` (today by default)."""
	from hrms.hr.doctype.leave_application.leave_application import (
		get_leave_allocation_records,
		get_leave_balance_on,
	)

	date = getdate(date or nowdate())
	allocation = get_leave_allocation_records(employee, date, leave_type).get(leave_type)
	if not allocation:
		return 0.0
	return flt(
		get_leave_balance_on(
			employee,
			leave_type,
			date,
			to_date=allocation.to_date,
			consider_all_leaves_in_the_allocation_period=True,
		),
		2,
	)


@frappe.whitelist()
def my_leave_balance(filters=None):
	filters = frappe.parse_json(filters) or {}
	leave_type = filters.get("leave_type")
	employee = _my_employee()
	if not employee or not leave_type or not frappe.db.exists("Leave Type", leave_type):
		return {"value": None, "fieldtype": "Data"}
	return {
		# "Data" keeps 5.5 as 5.5 (a Float would show the site's 3 decimals)
		"value": balance_for(employee, leave_type),
		"fieldtype": "Data",
		"route": ["query-report", "Employee Leave Balance"],
		"route_options": {"employee": employee},
	}


def convert_cards():
	"""Turn every company-wide leave balance card into a personal one. Safe to run again."""
	changed = []
	types = {frappe.scrub(t): t for t in frappe.get_all("Leave Type", pluck="name")}
	for name in frappe.get_all(
		"Number Card", filters={"type": "Report", "report_name": REPORT}, pluck="name"
	):
		card = frappe.get_doc("Number Card", name)
		leave_type = types.get(card.report_field or "")
		if not leave_type:
			continue
		card.update(
			{
				"type": "Custom",
				"method": METHOD,
				"document_type": "Leave Application",
				"filters_json": frappe.as_json({"leave_type": leave_type}, indent=None),
				"dynamic_filters_json": "{}",
				"report_name": None,
				"report_field": None,
				"report_function": None,
				"show_percentage_stats": 0,
			}
		)
		card.flags.ignore_permissions = True
		card.save()
		changed.append((name, leave_type))
	return changed
