"""Server-side rules for Alpinos Quotations."""

import frappe
from frappe import _
from frappe.utils import flt

from alpinos.quotation_line_calc import recalculate_quotation_item_row


def validate_quotation_alpinos(doc, method=None):
	sync_resolved_customer(doc)
	recalculate_quotation_items(doc)
	link_obm_quotation_addresses(doc)
	validate_payment_proof(doc)


def recalculate_quotation_items(doc):
	for row in doc.get("items") or []:
		recalculate_quotation_item_row(doc, row)


def sync_resolved_customer(doc):
	t = doc.get("quotation_to") or ""
	if t == "Customer" and doc.get("party_name"):
		doc.custom_resolved_customer = doc.party_name
	elif t == "Offline Buyer Master" and doc.get("party_name"):
		cust = frappe.db.get_value("Offline Buyer Master", doc.party_name, "customer")
		doc.custom_resolved_customer = cust or None
	else:
		doc.custom_resolved_customer = None


def _address_belongs_to_customer(address_name, customer):
	if not address_name or not customer:
		return True
	return bool(
		frappe.db.exists(
			"Dynamic Link",
			{
				"link_doctype": "Customer",
				"link_name": customer,
				"parenttype": "Address",
				"parent": address_name,
			},
		)
	)


def link_obm_quotation_addresses(doc):
	"""Offline Buyer Master quotations must use addresses linked to the resolved ERP Customer."""

	if doc.get("quotation_to") != "Offline Buyer Master":
		return
	exp = doc.get("custom_resolved_customer")
	if not exp:
		return
	for label, fn in (
		(_("Customer Address"), "customer_address"),
		(_("Shipping Address"), "shipping_address_name"),
	):
		addr = doc.get(fn)
		if addr and not _address_belongs_to_customer(addr, exp):
			frappe.throw(
				_("{0} must belong to Customer {1} when Quotation To is Offline Buyer Master.").format(
					label, frappe.bold(exp)
				)
			)


def validate_payment_proof(doc, method=None):
	mode = doc.get("custom_payment_mode")
	if mode in ("Advance", "Partial"):
		if not doc.get("custom_attachment_proof"):
			frappe.throw(_("Attachment (Proof) is required for Advance and Partial payment modes"))
	if mode == "Partial" and flt(doc.get("custom_advance_amount")) <= 0:
		frappe.throw(_("Advance Amount is required when Payment Mode is Partial"))
