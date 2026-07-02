"""Recover the cost of over-utilised (pro-rata excess) leave in the Full and Final Statement.

Scenario: an employee is entitled to a yearly leave quota that accrues over the year (e.g.
12 Casual Leave = 1/month). If they consume the whole quota and then leave mid-year, they
have taken MORE leave than they had earned up to their relieving date. The unearned days are
recovered from the final settlement.

Example: 12 CL/year (1/month). Employee takes all 12 and is relieved in March. By March only
3 days are earned (Jan, Feb, Mar) -> 9 days are excess -> 9 days of pay is recovered in the FnF.

Wired as Full and Final Statement `validate` (see hooks.py). For each leave type the employee
has an allocation for, we compute:

    earned (pro-rata)  = carry-forwarded leaves (already earned in a prior period)
                         + monthly accrual rate * months worked in this allocation period
    taken              = leave days consumed in this allocation period up to the relieving date
    excess             = max(taken - earned, 0)
    recovery amount    = excess * per-day salary

and add one "Excess Leave Recovery (<Leave Type>)" row to the FnF *receivables* (amounts the
company recovers from the employee). Rows are rebuilt on every validate, so editing the
relieving date / re-saving keeps them in sync and never duplicates.

A Leave Type can be opted out with the custom check `custom_recover_excess_leave_on_exit`
(added in setup_leave_type_recovery_field; default ON, NULL treated as ON). LWP leave types
are always skipped.

Per-day salary = latest Salary Structure Assignment `base` (on/before relieving) / number of
calendar days in the relieving month. Tweak PER_DAY_DIVISOR_MODE below if a different basis
(e.g. fixed 30, or 26 working days) is required.
"""

import calendar

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import add_days, cint, flt, getdate

# Marks the auto-generated receivable rows so they can be rebuilt without duplicating.
RECOVERY_COMPONENT_PREFIX = "Excess Leave Recovery"

# How the per-day rate is derived from the monthly base salary:
#   "month_days" -> base / number of calendar days in the relieving month (default)
#   "fixed_30"   -> base / 30
#   "working_26" -> base / 26
PER_DAY_DIVISOR_MODE = "month_days"


def add_excess_leave_recovery(doc, method=None):
	"""FnF `validate` hook: (re)build the excess-leave recovery rows in receivables."""
	try:
		_rebuild_recovery_rows(doc)
	except Exception:
		# Never block the FnF save because of a recovery-calculation problem.
		frappe.log_error(
			f"Excess leave recovery failed for FnF {doc.get('name')} / employee {doc.get('employee')}\n"
			f"{frappe.get_traceback()}",
			"FnF Excess Leave Recovery",
		)


def _rebuild_recovery_rows(doc):
	# Always clear our previous rows first so a re-validate stays idempotent.
	doc.set(
		"receivables",
		[
			r
			for r in (doc.get("receivables") or [])
			if not (r.component or "").startswith(RECOVERY_COMPONENT_PREFIX)
		],
	)

	if not (doc.employee and doc.relieving_date):
		return

	relieving = getdate(doc.relieving_date)
	per_day = _per_day_salary(doc.employee, relieving)

	for line in _excess_leave_by_type(doc.employee, relieving):
		amount = flt(line["excess"] * per_day, doc.precision("total_receivable_amount") or 2)
		remark = _(
			"Pro-rata excess leave on exit for {0}: taken {1}, earned {2} by {3} "
			"-> {4} day(s) recovered @ {5}/day."
		).format(
			line["leave_type"],
			line["taken"],
			line["earned"],
			frappe.utils.formatdate(relieving),
			line["excess"],
			flt(per_day, 2),
		)
		doc.append(
			"receivables",
			{
				"status": "Unsettled",
				"component": f"{RECOVERY_COMPONENT_PREFIX} ({line['leave_type']})",
				"amount": amount,
				"remark": remark,
			},
		)

	# The controller's set_totals() already ran before this hook, so recompute now that the
	# recovery rows are in place (keeps total_receivable_amount correct).
	if hasattr(doc, "set_totals"):
		doc.set_totals()


def _excess_leave_by_type(employee, relieving):
	"""Yield {leave_type, taken, earned, excess} for each leave type with positive excess."""
	allocations = frappe.get_all(
		"Leave Allocation",
		filters={
			"employee": employee,
			"docstatus": 1,
			"from_date": ["<=", relieving],
			"to_date": [">=", relieving],
		},
		fields=[
			"name",
			"leave_type",
			"from_date",
			"to_date",
			"new_leaves_allocated",
			"total_leaves_allocated",
		],
	)

	results = []
	for alloc in allocations:
		if not _leave_type_recoverable(alloc.leave_type):
			continue

		alloc_from = getdate(alloc.from_date)
		alloc_to = getdate(alloc.to_date)
		period_months = _month_span(alloc_from, alloc_to)
		if period_months <= 0:
			continue

		new_grant = flt(alloc.new_leaves_allocated)
		# Anything beyond the fresh grant is carry-forward from a prior period = already earned.
		carry_forward_earned = max(flt(alloc.total_leaves_allocated) - new_grant, 0)

		monthly_rate = new_grant / period_months
		worked_months = min(_month_span(alloc_from, relieving), period_months)
		earned = flt(carry_forward_earned + monthly_rate * worked_months, 2)

		taken = _leaves_taken(employee, alloc.leave_type, alloc_from, relieving)
		excess = flt(taken - earned, 2)
		if excess > 0:
			results.append(
				{
					"leave_type": alloc.leave_type,
					"taken": flt(taken, 2),
					"earned": earned,
					"excess": excess,
				}
			)
	return results


def _leave_type_recoverable(leave_type):
	"""Skip LWP types; honour the per-type opt-out (NULL/missing -> recover)."""
	row = frappe.db.get_value(
		"Leave Type", leave_type, ["is_lwp", "custom_recover_excess_leave_on_exit"], as_dict=True
	)
	if not row:
		return False
	if cint(row.is_lwp):
		return False
	# Field may not exist yet (pre-migrate) -> default to enabled.
	val = row.get("custom_recover_excess_leave_on_exit")
	return True if val is None else bool(cint(val))


def _leaves_taken(employee, leave_type, period_from, relieving):
	"""Leave days consumed (from the Leave Ledger) in [period_from, relieving] for this type.

	Leave Application ledger entries store consumed leave as NEGATIVE `leaves`; we sum those and
	flip the sign. Carry-forward/allocation/expiry entries are excluded by transaction_type.
	"""
	taken = frappe.db.sql(
		"""
		SELECT COALESCE(SUM(leaves), 0)
		FROM `tabLeave Ledger Entry`
		WHERE employee = %(employee)s
		  AND leave_type = %(leave_type)s
		  AND transaction_type = 'Leave Application'
		  AND docstatus = 1
		  AND leaves < 0
		  AND from_date >= %(period_from)s
		  AND from_date <= %(relieving)s
		""",
		{
			"employee": employee,
			"leave_type": leave_type,
			"period_from": period_from,
			"relieving": relieving,
		},
	)[0][0]
	return flt(-flt(taken), 2)


def _month_span(start, end):
	"""Inclusive count of calendar months touched between start and end (>=0).

	Jan->Mar = 3; Jan->Jan = 1; end before start = 0. A partial month counts as a whole month,
	matching the monthly-accrual model (any day worked in a month earns that month's quota).
	"""
	start, end = getdate(start), getdate(end)
	if end < start:
		return 0
	return (end.year - start.year) * 12 + (end.month - start.month) + 1


def _per_day_salary(employee, on_date):
	"""Latest Salary Structure Assignment base (on/before on_date) divided by the chosen basis."""
	base = frappe.db.get_value(
		"Salary Structure Assignment",
		filters={"employee": employee, "docstatus": 1, "from_date": ["<=", on_date]},
		fieldname="base",
		order_by="from_date desc",
	)
	base = flt(base)
	if base <= 0:
		return 0.0

	if PER_DAY_DIVISOR_MODE == "fixed_30":
		divisor = 30
	elif PER_DAY_DIVISOR_MODE == "working_26":
		divisor = 26
	else:  # "month_days"
		divisor = calendar.monthrange(getdate(on_date).year, getdate(on_date).month)[1]

	return flt(base / divisor, 4) if divisor else 0.0


def setup_leave_type_recovery_field():
	"""Add the per-Leave-Type opt-out check. Runs on after_migrate (idempotent)."""
	create_custom_fields(
		{
			"Leave Type": [
				dict(
					fieldname="custom_recover_excess_leave_on_exit",
					label="Recover Excess Leave on Exit",
					fieldtype="Check",
					insert_after="is_lwp",
					default="1",
					description=(
						"When set, pro-rata over-utilised leave of this type is recovered in the "
						"employee's Full and Final Statement. Ignored for LWP types."
					),
				),
			]
		},
		update=True,
	)
	frappe.db.commit()
	print("✅ Added 'Recover Excess Leave on Exit' field to Leave Type")
