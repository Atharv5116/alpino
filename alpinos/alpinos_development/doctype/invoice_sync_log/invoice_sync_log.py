# Copyright (c) 2026, Alpinos and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class InvoiceSyncLog(Document):
	pass


def log_invoice_sync(order_id, invoice_no, status, reason="", sync_type="Bulk Excel"):
	"""Record one invoice-sync outcome. Never let a logging failure break the sync."""
	try:
		frappe.get_doc(
			{
				"doctype": "Invoice Sync Log",
				"order_id": order_id or "",
				"invoice_no": invoice_no or "",
				"sync_type": sync_type,
				"sync_status": status,
				"reason": (reason or "")[:1000],
				"synced_on": frappe.utils.now_datetime(),
			}
		).insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(title="Invoice Sync Log write failed")
