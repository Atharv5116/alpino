# Copyright (c) 2026, Alpinos and contributors
# License: MIT
"""One payment the Accounts Team recorded against a Purchase Invoice (BRD 6.1.5).

A row per payment rather than a pair of totals on the parent, because BR-UNF-05 is
explicit that Accounts pays in instalments -- "pay supplier advance today, pay logistics
tomorrow, pay supplier balance next week" -- and the two pending balances in BR-UNF-04
are derived by summing these by `payment_type`.

Who recorded it and when are stamped here rather than read from the parent's modified
stamp, which moves for every later edit.
"""

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class PurchasePaymentReference(Document):
	def before_insert(self):
		self.recorded_by = frappe.session.user
		self.recorded_on = now_datetime()
