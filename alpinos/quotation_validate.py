"""Server-side rules for Alpinos Quotations."""

import frappe
from frappe import _
from frappe.utils import flt
from math import ceil

from alpinos.quotation_line_calc import recalculate_quotation_item_row


def before_validate_quotation_alpinos(doc, method=None):
	disable_rounded_total(doc)


def validate_quotation_alpinos(doc, method=None):
	sync_resolved_customer(doc)
	disable_rounded_total(doc)
	sync_obm_payment_mode(doc)
	recalculate_quotation_items(doc)
	recalculate_quotation_totals(doc)
	link_obm_quotation_addresses(doc)
	validate_payment_proof(doc)


def disable_rounded_total(doc):
	if doc.meta.has_field("disable_rounded_total"):
		doc.disable_rounded_total = 1
		doc.rounding_adjustment = 0
		doc.base_rounding_adjustment = 0
		doc.rounded_total = 0
		doc.base_rounded_total = 0


def recalculate_quotation_items(doc):
	for row in doc.get("items") or []:
		apply_box_conversion(row)
		sync_obm_item_pricing(doc, row)
		recalculate_quotation_item_row(doc, row)


def apply_box_conversion(row):
	if not row.get("item_code"):
		return

	from alpinos.sales_order_api import get_box_conversion_factor

	factor = flt(get_box_conversion_factor(row.item_code))
	if not factor:
		return

	if flt(row.get("qty")):
		boxes = ceil(flt(row.qty) / factor)
	elif flt(row.get("custom_boxes")):
		boxes = ceil(flt(row.custom_boxes))
	else:
		return

	row.custom_boxes = boxes
	row.qty = flt(boxes * factor, 2)


def sync_obm_payment_mode(doc):
	if doc.get("quotation_to") != "Offline Buyer Master" or not doc.get("party_name"):
		return
	payment_term = frappe.db.get_value("Offline Buyer Master", doc.party_name, "payment_term")
	if not payment_term:
		return
	doc.custom_payment_mode = {
		"Credit": "Debit",
		"Partial": "Partial",
		"Advance": "Advance",
	}.get(payment_term, "Advance")


def sync_obm_item_pricing(doc, row):
	if doc.get("quotation_to") != "Offline Buyer Master" or not doc.get("party_name") or not row.get("item_code"):
		return
	if flt(row.get("custom_mrp")) and flt(row.get("custom_flat_discount")):
		return

	from alpinos.sales_order_api import get_opportunity_line_pricing

	pricing = get_opportunity_line_pricing("Offline Buyer Master", doc.party_name, row.item_code)
	margin = flt(pricing.get("margin_percent"))
	if pricing.get("mrp") and not flt(row.get("custom_mrp")):
		row.custom_mrp = flt(pricing.get("mrp"))
	if margin:
		row.custom_buyer_margin_percent = margin
		if not flt(row.get("custom_flat_discount")):
			row.custom_flat_discount = margin


def recalculate_quotation_totals(doc):
	sub_total = 0.0
	over_discount = 0.0
	additional_discount = 0.0
	gst_total = 0.0
	total_incl = 0.0

	for row in doc.get("items") or []:
		qty = flt(row.get("qty"))
		mrp = flt(row.get("custom_mrp"))
		if not qty or not mrp:
			continue

		flat_discount = flt(row.get("custom_flat_discount"))
		if not flat_discount:
			flat_discount = flt(row.get("custom_buyer_margin_percent"))

		offer_pct = flt(row.get("custom_offer"))
		additional_discount_pct = flt(row.get("custom_additional_discount"))
		gst_pct = flt(row.get("custom_item_tax_percent") or row.get("custom_gst_percent") or row.get("gst_percent") or 0)
		if not gst_pct and row.get("item_code"):
			gst_pct = flt(frappe.db.get_value("Item", row.get("item_code"), "custom_gst_percent"))

		gross_incl = qty * mrp
		after_flat = gross_incl - (gross_incl * flat_discount / 100.0)
		after_offer = after_flat - (after_flat * offer_pct / 100.0)
		final_incl = after_offer - (after_offer * additional_discount_pct / 100.0)
		final_incl = max(final_incl, 0)

		div = 1 + (gst_pct / 100.0)
		net_amount = (final_incl / div) if div else final_incl
		gst_amount = max(final_incl - net_amount, 0)

		sub_total += gross_incl
		over_discount += (gross_incl - after_flat)
		additional_discount += (after_offer - final_incl)
		gst_total += gst_amount
		total_incl += final_incl

	cash_discount_pct = flt(doc.get("custom_cash_discount"))
	cash_discount_amount = total_incl * (cash_discount_pct / 100.0) if total_incl > 0 else 0
	total_payable = max(total_incl - cash_discount_amount, 0)

	doc.custom_sub_total = flt(sub_total, 2)
	doc.custom_over_discount = flt(over_discount, 2)
	doc.custom_additional_discount_total = flt(additional_discount, 2)
	doc.custom_gst_total = flt(gst_total, 2)
	doc.custom_total_payable = flt(total_payable, 2)
	doc.custom_remaining_amount = flt(total_payable - flt(doc.get("custom_advance_amount")), 2)
	doc.total = flt(total_payable, 2)
	doc.base_total = flt(total_payable, 2)
	doc.grand_total = flt(total_payable, 2)
	doc.base_grand_total = flt(total_payable, 2)


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
