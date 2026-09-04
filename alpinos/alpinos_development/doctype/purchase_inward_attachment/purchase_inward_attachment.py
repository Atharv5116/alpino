# Copyright (c) 2026, Alpinos and contributors
# License: MIT
"""Photo or video evidence attached to a Purchase Inward at receipt (BRD 2.2.1)."""

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class PurchaseInwardAttachment(Document):
	def before_insert(self):
		self.uploaded_by = frappe.session.user
		self.uploaded_on = now_datetime()
