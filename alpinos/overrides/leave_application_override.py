"""Override Leave Application to allow submit while status is Open (for approval)."""

import frappe
from frappe import _
from frappe.utils import cint, flt, formatdate, get_link_to_form, getdate
from hrms.hr.doctype.leave_application.leave_application import LeaveApplication as HRMSLeaveApplication
from hrms.hr.doctype.leave_application.leave_application import OverlapError

SATURDAY = 5
#: Applications in these states no longer hold their dates.
INACTIVE = ("Rejected", "Cancelled")
OVERLAP_MESSAGE = "Leave application already exists for the selected overlapping dates."


class CustomLeaveApplication(HRMSLeaveApplication):
	"""Allow submitting Leave Application when status is Open (e.g. Send for Approval)."""

	def validate(self):
		super().validate()
		self.validate_supporting_document()
		self.validate_saturday_half_day()

	def validate_leave_overlap(self):
		"""One employee cannot hold two leave applications on the same dates, whatever the
		leave types (HRMS #27).

		HRMS only looks at applications whose status is Open or Approved. Alpino's approval
		workflow keeps a waiting application at status Draft (or a Pending ... status), so a
		leave still waiting for approval never blocked a second one on the same dates.
		Every application counts here except Rejected and Cancelled ones. Runs on save, on
		submit and on every approval step, since HRMS calls it from validate.

		Two half days on one date stay allowed, as in HRMS, when together they make one day
		and they are not the same half.
		"""
		LA = frappe.qb.DocType("Leave Application")
		has_state = frappe.get_meta("Leave Application").has_field("workflow_state")
		has_period = frappe.get_meta("Leave Application").has_field("custom_half_day_period")
		fields = [LA.name, LA.leave_type, LA.from_date, LA.to_date, LA.status, LA.half_day, LA.half_day_date]
		if has_state:
			fields.append(LA.workflow_state)
		if has_period:
			fields.append(LA.custom_half_day_period)
		query = (
			frappe.qb.from_(LA)
			.select(*fields)
			.where(
				(LA.employee == self.employee)
				& (LA.docstatus < 2)
				& (LA.status.notin(INACTIVE))
				& (LA.to_date >= self.from_date)
				& (LA.from_date <= self.to_date)
				& (LA.name != (self.name or ""))
			)
			.orderby(LA.from_date)
		)
		others = [
			d for d in query.run(as_dict=True)
			if not (has_state and d.get("workflow_state") in INACTIVE)
		]

		for d in others:
			if self._halves_share_the_day(d, others, has_period):
				continue
			self._throw_overlap(d)

	def _halves_share_the_day(self, d, others, has_period):
		"""Both are half days on the same date, the other ends or starts there (or this one is
		that half day alone), they name different halves, and no other half day takes the
		date already."""
		if not (cint(self.half_day) and cint(d.half_day)):
			return False
		if not (self.half_day_date and d.half_day_date and getdate(self.half_day_date) == getdate(d.half_day_date)):
			return False
		if not (
			flt(self.total_leave_days) == 0.5
			or getdate(self.from_date) == getdate(d.to_date)
			or getdate(self.to_date) == getdate(d.from_date)
		):
			return False
		if has_period and self.get("custom_half_day_period") and self.get("custom_half_day_period") == d.get("custom_half_day_period"):
			return False
		same_date = [
			o for o in others
			if cint(o.half_day) and o.half_day_date and getdate(o.half_day_date) == getdate(self.half_day_date)
		]
		return len(same_date) < 2

	def _throw_overlap(self, d):
		state = d.get("workflow_state") or d.status
		frappe.throw(
			_(OVERLAP_MESSAGE)
			+ "<br><br>"
			+ _("Existing: {0}, {1}, {2} to {3} ({4})").format(
				get_link_to_form("Leave Application", d.name),
				d.leave_type,
				formatdate(d.from_date),
				formatdate(d.to_date),
				state,
			),
			OverlapError,
			title=_("Overlapping Leave"),
		)

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
