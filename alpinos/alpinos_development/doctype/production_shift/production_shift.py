"""Production Shift -- a named working shift (e.g. Shift A 06:00-14:00).

The current shift is resolved by alpinos.production.shifts.current_shift(). An end time
earlier than the start time is an overnight shift.
# default pending BA confirmation: shift names and timings are configured by the plant.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class ProductionShift(Document):
	def validate(self):
		self.shift_name = (self.shift_name or "").strip()
		if not self.shift_name:
			frappe.throw(_("Shift Name is required."), title=_("Missing Shift Name"))
		if self.start_time and self.end_time and str(self.start_time) == str(self.end_time):
			frappe.throw(_("Start Time and End Time cannot be the same."), title=_("Invalid Shift"))
