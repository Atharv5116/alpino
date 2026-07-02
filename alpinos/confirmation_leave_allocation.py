"""Leave allocation when an employee is confirmed (employment type leaves "Probation").

On confirmation we allocate, for the current calendar year:
  - Casual Leave    : 1 per month from the CONFIRMATION month through December
                      (confirmed in Dec -> 1, Nov -> 2, ... Jan -> 12).
  - Bereavement Leave: 7 (flat, no proration)
  - Restricted Leave : 1 (flat, no proration)

The transition is detected in alpinos.employee_confirmation.on_employee_update, which
calls allocate_confirmation_leaves(employee). A guard Check on Employee
(custom_confirmation_leaves_allocated, added in alpinos.employee_custom_fields) plus a
per-(employee, leave_type, period) existence check make this idempotent.

ensure_leave_setup() creates the three Leave Types and a calendar-year Leave Period if
missing; it runs on every migrate via the after_migrate hook.
"""

import frappe
from frappe.utils import getdate, nowdate

# leave_type_name -> count rule. "prorate_to_year_end" => 12 - month + 1; int => flat.
CONFIRMATION_LEAVES = [
	{"leave_type": "Casual Leave", "rule": "prorate_to_year_end"},
	{"leave_type": "Bereavement Leave", "rule": 7},
	{"leave_type": "Restricted Leave", "rule": 1},
]


def _default_company():
	company = frappe.db.get_single_value("Global Defaults", "default_company")
	if company:
		return company
	names = frappe.get_all("Company", limit=1, pluck="name")
	return names[0] if names else None


def _get_or_create_leave_period(company, on_date):
	"""Return a Leave Period covering `on_date` for `company`, creating a calendar-year one if needed."""
	on_date = getdate(on_date)
	existing = frappe.get_all(
		"Leave Period",
		filters={
			"company": company,
			"from_date": ["<=", on_date],
			"to_date": [">=", on_date],
		},
		limit=1,
	)
	if existing:
		return frappe.get_doc("Leave Period", existing[0].name)

	lp = frappe.get_doc(
		{
			"doctype": "Leave Period",
			"from_date": getdate(f"{on_date.year}-01-01"),
			"to_date": getdate(f"{on_date.year}-12-31"),
			"company": company,
			"is_active": 1,
		}
	)
	lp.insert(ignore_permissions=True)
	return lp


def ensure_leave_setup(company=None):
	"""Idempotently create the three Leave Types and a calendar-year Leave Period.

	Safe to run repeatedly (after_migrate / `bench execute`).
	"""
	for cfg in CONFIRMATION_LEAVES:
		name = cfg["leave_type"]
		if not frappe.db.exists("Leave Type", name):
			frappe.get_doc(
				{
					"doctype": "Leave Type",
					"leave_type_name": name,
					"is_lwp": 0,
					"include_holiday": 0,
					"is_carry_forward": 0,
					"allow_negative": 0,
				}
			).insert(ignore_permissions=True)
			print(f"✅ Created Leave Type '{name}'")

	company = company or _default_company()
	if company:
		_get_or_create_leave_period(company, getdate(nowdate()))

	frappe.db.commit()


def _count_for_rule(rule, confirmation_date):
	if rule == "prorate_to_year_end":
		return 12 - getdate(confirmation_date).month + 1
	try:
		return int(rule)
	except (TypeError, ValueError):
		return 0


def allocate_confirmation_leaves(employee, confirmation_date=None):
	"""Create submitted Leave Allocations for a just-confirmed employee.

	`employee` may be an Employee doc or its name. Returns the list of
	(leave_type, count) actually allocated. Idempotent: skips if the guard flag
	is set or an allocation already exists for the (employee, leave_type, period).
	"""
	emp = employee if hasattr(employee, "doctype") else frappe.get_doc("Employee", employee)

	if emp.get("custom_confirmation_leaves_allocated"):
		return []

	company = emp.get("company") or _default_company()
	if not company:
		frappe.log_error(
			f"No company found for employee {emp.name}; cannot allocate confirmation leaves.",
			"Confirmation Leave Allocation",
		)
		return []

	ensure_leave_setup(company=company)

	on_date = getdate(confirmation_date or nowdate())
	leave_period = _get_or_create_leave_period(company, on_date)
	from_date = on_date
	to_date = getdate(leave_period.to_date) if leave_period else getdate(f"{on_date.year}-12-31")

	created = []
	for cfg in CONFIRMATION_LEAVES:
		leave_type = cfg["leave_type"]
		count = _count_for_rule(cfg["rule"], on_date)
		if count <= 0 or not frappe.db.exists("Leave Type", leave_type):
			continue

		# Skip if an allocation already covers this leave type for this period.
		if frappe.db.exists(
			"Leave Allocation",
			{
				"employee": emp.name,
				"leave_type": leave_type,
				"from_date": from_date,
				"to_date": to_date,
				"docstatus": 1,
			},
		):
			continue

		try:
			alloc = frappe.get_doc(
				{
					"doctype": "Leave Allocation",
					"employee": emp.name,
					"employee_name": emp.get("employee_name"),
					"leave_type": leave_type,
					"from_date": from_date,
					"to_date": to_date,
					"new_leaves_allocated": count,
					"carry_forward": 0,
					"company": company,
				}
			)
			if leave_period:
				alloc.leave_period = leave_period.name
			alloc.insert(ignore_permissions=True)
			alloc.submit()
			created.append((leave_type, count))
		except Exception:
			frappe.log_error(
				f"Failed allocating {count} x {leave_type} for {emp.name}\n{frappe.get_traceback()}",
				"Confirmation Leave Allocation",
			)

	# Mark done so we never re-allocate (direct db write -> no recursive Employee on_update).
	frappe.db.set_value(
		"Employee", emp.name, "custom_confirmation_leaves_allocated", 1, update_modified=False
	)
	frappe.db.commit()
	return created
