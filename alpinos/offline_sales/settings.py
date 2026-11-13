"""Offline Sales Settings: the switch for manager scoping, default Primary POCs, escalation."""

import frappe
from frappe import _
from frappe.utils import cint

from alpinos.offline_sales import SETTINGS


def _get(field, default=None):
	if not frappe.db.table_exists("Singles") or not frappe.db.exists("DocType", SETTINGS):
		return default
	value = frappe.db.get_single_value(SETTINGS, field)
	return default if value in (None, "") else value


def scope_managers():
	"""True when buyer assignment narrows Sales Managers and Sales Admins too."""
	return bool(cint(_get("assignment_scope_for_managers", 0)))


def escalation_hours():
	return cint(_get("escalation_hours", 48)) or 48


def default_primary_pocs(eligible_only=False):
	"""Employee IDs added to every new buyer as Primary POC (4.3 / 3.3 "System Defaults").

	eligible_only drops a default whose user no longer holds Sales Manager or Sales Admin, so
	one person's role change cannot stop every new buyer from saving.
	"""
	if not frappe.db.exists("DocType", SETTINGS):
		return []
	employees = frappe.get_all(
		"Buyer Primary POC",
		filters={"parenttype": SETTINGS, "parent": SETTINGS},
		pluck="employee",
		order_by="idx asc",
	)
	if not eligible_only:
		return employees
	from alpinos.buyer_assignment import PRIMARY_POC_ROLES

	out = []
	for employee in employees:
		user = frappe.db.get_value("Employee", employee, "user_id")
		if user and set(PRIMARY_POC_ROLES) & set(frappe.get_roles(user)):
			out.append(employee)
	return out


def validate_settings(doc):
	from alpinos.buyer_assignment import PRIMARY_POC_ROLES, _validate_employee_role

	seen = set()
	for row in doc.get("default_primary_pocs") or []:
		if not row.employee or row.employee in seen:
			continue
		seen.add(row.employee)
		_validate_employee_role(row.employee, PRIMARY_POC_ROLES, _("Default Primary POC(s)"))
	if cint(doc.escalation_hours) <= 0:
		doc.escalation_hours = 48
