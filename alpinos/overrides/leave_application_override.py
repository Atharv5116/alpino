"""
Override for Leave Application to allow submit when status is Open.

Standard HRMS only allows submit when status is Approved or Rejected.
We allow submit when status is Open so employees can submit for approval.
Ledger and attendance are only created when status is Approved (base class no-ops otherwise).
"""

import frappe
from frappe import _
from frappe.utils import flt
from hrms.hr.doctype.leave_application.leave_application import LeaveApplication as HRMSLeaveApplication


class CustomLeaveApplication(HRMSLeaveApplication):
	"""Allow submitting Leave Application when status is Open (e.g. Send for Approval)."""

	def validate(self):
		super().validate()
		self.validate_supporting_document()

	def validate_supporting_document(self):
		"""Require a supporting document when the leave is longer than 3 days.

		total_leave_days is set by the base validate() above, so it is reliable here.
		The same rule is mirrored on the field via mandatory_depends_on so the form
		shows the field as required; this guard blocks any path that bypasses the UI.
		"""
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
		"""
		Ensure leave ledger exists when a submitted Leave Application is later approved
		via workflow (Open -> Approved).
		"""
		# Only consume leaves for approved applications.
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
