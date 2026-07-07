# Copyright (c) 2026, Alpinos and contributors
# License: MIT

"""Monthly Attendance Batch — the shared shell for all three attendance modules.

One batch = one rule engine x one payroll month x one company. The employee rows
and their calculated numbers live in the child table; the per-day detail behind
each row is stored in the row's day_data JSON and rendered by the batch entry page.

Data enters per engine (populate_rows dispatches):
  - HO/Admin      : generated from Attendance / check-in records already in ERPNext
  - WH ESSL       : fetched punches (eSSL sync) aggregated into OT/EL
  - Offline Sales : parsed from the Excel HR uploads onto the batch

Status lifecycle (workflow on `workflow_state`): Draft -> Pending Approval ->
Approved (submit) -> Locked. After Approved no fetch/upload/edit is allowed.
"""

import calendar

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_first_day, getdate, now_datetime

ENGINE_ABBR = {
	"HO/Admin": "HO",
	"WH ESSL": "WH",
	"Offline Sales": "OS",
}


class MonthlyAttendanceBatch(Document):
	def autoname(self):
		"""ATT-BATCH-YYYY-MM-<engine>, e.g. ATT-BATCH-2026-07-HO."""
		month = getdate(self.payroll_month)
		abbr = ENGINE_ABBR.get(self.rule_engine, "XX")
		self.name = f"ATT-BATCH-{month.year}-{month.month:02d}-{abbr}"

	def validate(self):
		self._normalize_month()
		self._check_duplicate()
		self._block_edits_after_approval()

	def _normalize_month(self):
		self.payroll_month = get_first_day(self.payroll_month)
		month = getdate(self.payroll_month)
		self.month_title = f"{calendar.month_name[month.month]} {month.year} — {self.rule_engine}"

	def _check_duplicate(self):
		"""One live batch per engine + month + company."""
		dup = frappe.db.exists(
			"Monthly Attendance Batch",
			{
				"rule_engine": self.rule_engine,
				"payroll_month": self.payroll_month,
				"company": self.company,
				"docstatus": ["!=", 2],
				"name": ["!=", self.name],
			},
		)
		if dup:
			frappe.throw(
				_("Batch {0} already exists for {1} — {2}. Edit that batch instead.").format(
					frappe.bold(dup), self.rule_engine, self.month_title
				)
			)

	def _block_edits_after_approval(self):
		"""No changes once the workflow has moved past Pending (task: read-only after approval).

		Submitted docs are already immutable via docstatus; this guards the Draft-side
		states so nothing edits a batch under approval except HR Manager moving it.
		"""
		if self.is_new() or self.docstatus != 0:
			return
		old_state = frappe.db.get_value(self.doctype, self.name, "workflow_state")
		if old_state in ("Approved", "Locked"):
			frappe.throw(_("This batch is {0} and can no longer be edited.").format(old_state))

	def on_submit(self):
		self.db_set("approved_by", frappe.session.user, update_modified=False)
		self.db_set("approved_on", now_datetime(), update_modified=False)

	# ------------------------------------------------------------------ data in

	@frappe.whitelist()
	def populate_rows(self):
		"""(Re)build the employee rows for this batch's engine and month.

		Dispatches to the engine adapter. Fails fast if any active employee in the
		company is not categorized (Salary Category with a rule engine) — nobody may
		silently fall out of payroll.
		"""
		if self.docstatus != 0 or (self.workflow_state or "Draft") not in ("Draft",):
			frappe.throw(_("Rows can only be generated while the batch is in Draft."))

		validate_all_employees_categorized(self.company)

		employees = get_employees_for_engine(self.rule_engine, self.company, self.payroll_month)
		if not employees:
			frappe.throw(
				_("No active employees found for rule engine {0} in {1}.").format(
					self.rule_engine, self.company
				)
			)

		self.set("rows", [])
		for emp in employees:
			self.append(
				"rows",
				{
					"employee": emp.name,
					"employee_name": emp.employee_name,
					"department": emp.department,
					"salary_category": emp.salary_category,
					"date_of_joining": emp.date_of_joining,
					"relieving_date": emp.relieving_date,
				},
			)

		# Engine adapters fill in the numbers (built module by module).
		adapter = ENGINE_ADAPTERS.get(self.rule_engine)
		if adapter:
			adapter(self)

		self.db_set("fetched_by", frappe.session.user, update_modified=False)
		self.db_set("fetched_on", now_datetime(), update_modified=False)
		self.save()
		return {"rows": len(self.rows)}


# ---------------------------------------------------------------- categorization

def validate_all_employees_categorized(company):
	"""Throw (listing offenders) if any active employee lacks a Salary Category
	with an Attendance Rule Engine. Runs before every batch generation."""
	uncategorized = frappe.db.sql(
		"""
		SELECT e.name, e.employee_name
		FROM `tabEmployee` e
		LEFT JOIN `tabSalary Category` sc ON sc.name = e.salary_category
		WHERE e.status = 'Active'
		  AND e.company = %s
		  AND (e.salary_category IS NULL OR e.salary_category = ''
		       OR sc.attendance_rule_engine IS NULL OR sc.attendance_rule_engine = '')
		ORDER BY e.employee_name
		""",
		(company,),
		as_dict=True,
	)
	if uncategorized:
		names = ", ".join(f"{u.employee_name} ({u.name})" for u in uncategorized[:15])
		more = _(" and {0} more").format(len(uncategorized) - 15) if len(uncategorized) > 15 else ""
		frappe.throw(
			_(
				"Cannot generate the batch — {0} active employee(s) have no Salary Category "
				"with an Attendance Rule Engine: {1}{2}. Set it on the Employee record first."
			).format(len(uncategorized), names, more),
			title=_("Uncategorized Employees"),
		)


def get_employees_for_engine(rule_engine, company, payroll_month):
	"""Active-in-month employees whose Salary Category maps to this rule engine.

	Same lifecycle window as the Attendance Summary report: joined on/before month
	end, not relieved before month start (leaver stays visible in the exit month).
	"""
	from frappe.utils import get_last_day

	month_start = get_first_day(payroll_month)
	month_end = get_last_day(payroll_month)

	return frappe.db.sql(
		"""
		SELECT e.name, e.employee_name, e.department, e.salary_category,
		       e.date_of_joining, e.relieving_date
		FROM `tabEmployee` e
		INNER JOIN `tabSalary Category` sc ON sc.name = e.salary_category
		WHERE sc.attendance_rule_engine = %s
		  AND e.company = %s
		  AND e.date_of_joining IS NOT NULL AND e.date_of_joining <= %s
		  AND (e.relieving_date IS NULL OR e.relieving_date >= %s)
		ORDER BY e.employee_name
		""",
		(rule_engine, company, month_end, month_start),
		as_dict=True,
	)


# ---------------------------------------------------------------- engine adapters
# Each adapter fills the batch's rows with its engine's numbers. Implemented in
# their own modules as those tasks land; keys must match the rule_engine options.

def _ho_admin_adapter(batch):
	"""HO/Admin — 97%/50% percentage rules, late tiers, WFH/OD counts."""
	from alpinos.attendance_percentage import run_ho_adapter

	run_ho_adapter(batch)


def _wh_essl_adapter(batch):
	"""WH ESSL — OT/EL minute rules. Built with the ESSL module tasks."""
	pass


def _offline_sales_adapter(batch):
	"""Offline Sales — Excel upload. Built with the Offline Sales module tasks."""
	pass


ENGINE_ADAPTERS = {
	"HO/Admin": _ho_admin_adapter,
	"WH ESSL": _wh_essl_adapter,
	"Offline Sales": _offline_sales_adapter,
}
