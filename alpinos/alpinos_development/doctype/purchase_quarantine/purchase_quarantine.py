# Copyright (c) 2026, Alpinos and contributors
# License: MIT
"""Purchase Quarantine — the items held out of a Purchase Inward, together.

Raised by the system when Store hands an inward over (alpinos.purchase.quarantine): one
document per inward holds every quarantined line and ONE reminder for all of them.
Released lines leave through quarantine.release_items, which raises their Purchase QC;
from there they follow the normal QC -> GRN -> Purchase Invoice path.

Totals, the status and the next reminder date are derived here on every save, never
typed.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, flt, get_datetime, getdate

from alpinos.purchase import constants as C


class PurchaseQuarantine(Document):
	def validate(self):
		self._roll_up()
		self._schedule_reminder()

	def _roll_up(self):
		rows = self.get("items") or []
		self.total_qty = sum(flt(r.qty) for r in rows)
		self.released_qty = sum(flt(r.qty) for r in rows if r.status == C.QUARANTINE_RELEASED)
		self.held_qty = self.total_qty - self.released_qty
		released = [r for r in rows if r.status == C.QUARANTINE_RELEASED]
		if rows and len(released) == len(rows):
			self.status = C.QRN_RELEASED
		elif released:
			self.status = C.QRN_PARTIALLY_RELEASED
		else:
			self.status = C.QRN_QUARANTINED

	def _schedule_reminder(self):
		"""Next reminder = the last one (or the quarantine date) + the reminder days."""
		if cint(self.reminder_days) < 0:
			frappe.throw(_("Remind After (Days) cannot be negative."))
		if self.status == C.QRN_RELEASED or cint(self.reminder_days) <= 0:
			self.next_reminder_on = None
			return
		before = self.get_doc_before_save()
		changed = not before or cint(before.reminder_days) != cint(self.reminder_days)
		if self.next_reminder_on and not changed:
			return
		base = self.last_reminder_on or self.quarantine_date
		base = getdate(get_datetime(base)) if base else getdate()
		self.next_reminder_on = add_days(base, cint(self.reminder_days))
