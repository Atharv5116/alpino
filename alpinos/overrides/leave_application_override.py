"""
Override for Leave Application to allow submit when status is Open.

Standard HRMS only allows submit when status is Approved or Rejected.
We allow submit when status is Open so employees can submit for approval.
Ledger and attendance are only created when status is Approved (base class no-ops otherwise).
"""

import frappe
from frappe import _
from hrms.hr.doctype.leave_application.leave_application import LeaveApplication as HRMSLeaveApplication


class CustomLeaveApplication(HRMSLeaveApplication):
	"""Allow submitting Leave Application when status is Open (e.g. Send for Approval)."""

	def on_submit(self):
		if self.status == "Cancelled":
			frappe.throw(
				_("Only Leave Applications with status 'Approved' and 'Rejected' can be submitted")
			)

		self.validate_back_dated_application()
		self.update_attendance()
		# Self-approval check only when finalising approved leave, not when submitting for approval (Open)
		if self.status != "Open":
			self.validate_for_self_approval()

		if frappe.db.get_single_value("HR Settings", "send_leave_notification"):
			self.notify_employee()

		self.create_leave_ledger_entry()
		leave_allocation = self.get_leave_allocation()
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
