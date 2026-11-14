"""Server-side rules for Alpinos Quotations.

Prices, totals and the payment section follow "Opportunity to Sales Order v1.0.0", Section 5
(alpinos.offline_sales.quotation and quotation_payments): the Sales Order engine prices the
lines, the Payment Term comes from the Buyer Master only when the Quotation is created, and a
payment is recorded with its proof after Finalize, not on every save.
"""

import frappe
from frappe import _


def before_validate_quotation_alpinos(doc, method=None):
	disable_rounded_total(doc)


def validate_quotation_alpinos(doc, method=None):
	sync_resolved_customer(doc)
	disable_rounded_total(doc)
	link_obm_quotation_addresses(doc)


def disable_rounded_total(doc):
	if doc.meta.has_field("disable_rounded_total"):
		doc.disable_rounded_total = 1
		doc.rounding_adjustment = 0
		doc.base_rounding_adjustment = 0
		doc.rounded_total = 0
		doc.base_rounded_total = 0


def sync_resolved_customer(doc):
	t = doc.get("quotation_to") or ""
	if t == "Customer" and doc.get("party_name"):
		doc.custom_resolved_customer = doc.party_name
	elif t == "Buyer Master" and doc.get("party_name"):
		cust = frappe.db.get_value("Buyer Master", doc.party_name, "customer")
		doc.custom_resolved_customer = cust or None
	else:
		doc.custom_resolved_customer = None


def _address_belongs_to_customer(address_name, customer):
	"""An address of the Customer or of another Buyer in its family (parent + sites): the
	Opportunity offers the family's addresses, as the Sales Order does, and Convert to Quotation
	carries the chosen ones over."""
	if not address_name or not customer:
		return True
	from alpinos.sales_order_offline_buyer import buyer_family_customers

	return bool(
		frappe.db.exists(
			"Dynamic Link",
			{
				"link_doctype": "Customer",
				"link_name": ("in", buyer_family_customers(customer) or [customer]),
				"parenttype": "Address",
				"parent": address_name,
			},
		)
	)


def link_obm_quotation_addresses(doc):
	"""Buyer Master quotations must use addresses linked to the resolved ERP Customer."""

	if doc.get("quotation_to") != "Buyer Master" or doc.docstatus != 0:
		return
	exp = doc.get("custom_resolved_customer")
	if not exp:
		return
	for label, fn in (
		(_("Billing Address"), "customer_address"),
		(_("Shipping Address"), "shipping_address_name"),
	):
		addr = doc.get(fn)
		if addr and not _address_belongs_to_customer(addr, exp):
			frappe.throw(
				_("{0} must belong to Customer {1} when Quotation To is Buyer Master.").format(
					label, frappe.bold(exp)
				)
			)
