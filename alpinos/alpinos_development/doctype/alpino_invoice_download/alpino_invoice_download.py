# Copyright (c) 2026, Alpinos and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class AlpinoInvoiceDownload(Document):
	pass


def log(sales_order: str, user: str | None = None) -> None:
	"""Record that `user` has downloaded this Sales Order's invoice.

	Idempotent — a second download by the same user doesn't add a row, and a
	failure here must never break the download itself."""
	user = user or frappe.session.user
	if not sales_order or not user or user == "Guest":
		return
	try:
		if frappe.db.exists("Alpino Invoice Download", {"sales_order": sales_order, "user": user}):
			return
		doc = frappe.get_doc({
			"doctype": "Alpino Invoice Download",
			"sales_order": sales_order,
			"user": user,
			"downloaded_on": frappe.utils.now_datetime(),
		})
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "alpinos.invoice_download_log")
