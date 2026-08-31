"""Override Leave Application to allow submit while status is Open (for approval)."""

import frappe
from frappe import _
from frappe.utils import flt, getdate
from hrms.hr.doctype.leave_application.leave_application import LeaveApplication as HRMSLeaveApplication

SATURDAY = 5


class CustomLeaveApplication(HRMSLeaveApplication):
	"""Allow submitting Leave Application when status is Open (e.g. Send for Approval)."""

	def validate(self):
		super().validate()
		self.validate_supporting_document()
		self.validate_saturday_half_day()

	def validate_saturday_half_day(self):
		"""Saturday counts as a full working day, so it cannot be taken as a half day."""
		if not self.get("half_day"):
			return

		half_day_date = self.get("half_day_date") or self.get("from_date")
		if half_day_date and getdate(half_day_date).weekday() == SATURDAY:
			frappe.throw(
				_("Saturday is a full working day, so {0} cannot be applied as a half day.").format(
					frappe.format(getdate(half_day_date), {"fieldtype": "Date"})
				),
				title=_("Half Day Not Allowed on Saturday"),
			)

	def validate_supporting_document(self):
		"""Require a supporting document when the leave is longer than 3 days."""
		if flt(self.total_leave_days) > 3 and not self.get("custom_supporting_document"):
			frappe.throw(
				_(
					"A Supporting Document is mandatory for leave longer than 3 days "
					"(this application is {0} days)."
				).format(self.total_leave_days),
				title=_("Proof Required"),
			)

	def on_submit(self):
		self.validate_back_dated_application()
		self.update_attendance()
		# Self-approval check only when finalising approved leave, not when submitting for approval (Open)
		if self.status != "Open":
			self.validate_for_self_approval()

		if frappe.db.get_single_value("HR Settings", "send_leave_notification"):
			self.notify_employee()

		self.create_leave_ledger_entry()
		
		alloc_from, alloc_to = self.get_allocation_based_on_application_dates()
		leave_allocation = alloc_to or alloc_from
		
		if not leave_allocation:
			return
		to_date = leave_allocation.get("to_date")
		can_expire = not frappe.db.get_value("Leave Type", self.leave_type, "is_carry_forward")

		if to_date < frappe.utils.getdate() and can_expire:
			from hrms.hr.doctype.leave_ledger_entry.leave_ledger_entry import create_leave_ledger_entry

			args = frappe._dict(
				leaves=self.total_leave_days,
				from_date=to_date,
				to_date=to_date,
				is_carry_forward=0,
			)
			create_leave_ledger_entry(self, args)

		self.reload()

	def on_update_after_submit(self):
		"""Create the leave ledger when a submitted application is later approved via workflow (Open -> Approved)."""
		if self.status != "Approved":
			return

		has_ledger = frappe.db.exists(
			"Leave Ledger Entry",
			{
				"transaction_type": "Leave Application",
				"transaction_name": self.name,
				"docstatus": 1,
			},
		)
		if not has_ledger:
			self.create_leave_ledger_entry(submit=True)
