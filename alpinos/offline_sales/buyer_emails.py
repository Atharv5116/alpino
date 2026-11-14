"""Buyer emails of the Offline Sales flow (doc Section 2, 5.1, "Confirmed - Downstream Integration").

Order dispatched: when an Offline order's Delivery Note is submitted, the buyer (Buyer Master
email) gets "Your Order {SO} has been dispatched via {Transporter Name}. Tracking ID: {LR NO.}."
with the Sales Order PDF and, when the order has one, the Invoice PDF. Sent after the commit and
never in the way of the dispatch itself; the warehouse / Delivery Note flow is not changed.
(The request acknowledgement is sent by order_link; the Quotation-finalized email by the
Quotation's Finalize.)
"""

import frappe
from frappe import _

from alpinos.offline_sales import is_offline


def delivery_note_on_submit(doc, method=None):
	if doc.get("is_return"):
		return
	so = doc.get("custom_sales_order_id")
	if not so:
		return
	frappe.enqueue(
		"alpinos.offline_sales.buyer_emails.send_dispatch_email", queue="short", enqueue_after_commit=True,
		delivery_note=doc.name, sales_order=so,
	)


def dispatch_message(sales_order, transporter, lr_no):
	return _("Your Order {0} has been dispatched via {1}. Tracking ID: {2}.").format(sales_order, transporter or "-", lr_no or "-")


def _buyer_email(so):
	buyer = so.get("custom_offline_buyer_master") or frappe.db.get_value("Buyer Master", {"customer": so.customer}, "name")
	return frappe.db.get_value("Buyer Master", buyer, "email") if buyer else None


def _invoice_attachment(so):
	url = (so.get("custom_invoice_pdf") or "").strip()
	if not url:
		return None
	name = frappe.db.get_value("File", {"file_url": url}, "name")
	if not name:
		return None
	f = frappe.get_doc("File", name)
	return {"fname": f.file_name, "fcontent": f.get_content()}


def send_dispatch_email(delivery_note, sales_order):
	"""Never raises: the dispatch is already done."""
	try:
		so = frappe.get_doc("Sales Order", sales_order)
		if not is_offline(so.get("custom_channel")):
			return
		email = _buyer_email(so)
		if not email:
			return
		dn = frappe.db.get_value("Delivery Note", delivery_note, ["custom_transporter_name", "custom_lr_gr_no"], as_dict=True) or {}
		attachments = [{"fname": f"{so.name}.pdf", "fcontent": frappe.get_print("Sales Order", so.name, as_pdf=True)}]
		invoice = _invoice_attachment(so)
		if invoice:
			attachments.append(invoice)
		frappe.sendmail(
			recipients=[email],
			subject=_("Order {0} dispatched").format(so.name),
			message=dispatch_message(so.name, dn.get("custom_transporter_name"), dn.get("custom_lr_gr_no")),
			attachments=attachments,
			reference_doctype="Sales Order",
			reference_name=so.name,
		)
	except Exception:
		frappe.log_error(title=f"Dispatch email to the buyer failed for {sales_order}")
