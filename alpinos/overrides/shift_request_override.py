import frappe
from frappe import _
from frappe.utils import add_days, add_months, formatdate, getdate

from hrms.hr.doctype.shift_request.shift_request import ShiftRequest as HRMSShiftRequest

# BRD ALP_HRMS_Payroll_001 §4B: an employee may raise at most 4 Shift Change
# Requests per month. Rejected/cancelled requests give the slot back.
MONTHLY_SHIFT_REQUEST_LIMIT = 4


class CustomShiftRequest(HRMSShiftRequest):
	"""
	Allow submitting a Shift Request in any workflow status.

	- HRMS default behavior blocks submit unless status is Approved/Rejected.
	- We allow submit for any status to support custom workflows.
	- We only create Shift Assignment when status is Approved (same as HRMS intent).
	- Enforces the 4-per-month request cap (HR Managers exempt).
	"""

	def validate(self):
		if hasattr(super(), "validate"):
			super().validate()
		self._enforce_monthly_limit()

	def _enforce_monthly_limit(self):
		if "HR Manager" in frappe.get_roles():
			return
		month_start = getdate(self.from_date).replace(day=1)
		month_end = add_days(add_months(month_start, 1), -1)
		filters = {
			"employee": self.employee,
			"from_date": ["between", [month_start, month_end]],
			"docstatus": ["!=", 2],
			"status": ["!=", "Rejected"],
		}
		# `name != NULL` matches nothing in SQL — only exclude self once named.
		if self.name:
			filters["name"] = ["!=", self.name]
		used = frappe.db.count("Shift Request", filters)
		if used >= MONTHLY_SHIFT_REQUEST_LIMIT:
			frappe.throw(
				_(
					"Limit reached: at most {0} Shift Change Requests per month. "
					"{1} already raised in {2}."
				).format(MONTHLY_SHIFT_REQUEST_LIMIT, used, formatdate(month_start, "MMMM yyyy")),
				title=_("Monthly Shift Change Limit Reached"),
			)

	def on_submit(self):
		# Only create Shift Assignment when Approved; otherwise allow submit without side effects
		if self.status == "Approved":
			return super().on_submit()
		return None
