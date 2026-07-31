"""Server-side validation helpers for Alpinos Opportunities."""

import frappe
from frappe import _
from frappe.utils import flt
from math import ceil


def validate_opportunity_alpinos(doc, method=None):
	"""Runs on Opportunity.validate via hooks.doc_events.

	1. Rounds SKU quantities up to full boxes when a Box UOM conversion exists.
	2. Sets customer_name from OBM's customer_business_name when opportunity_from == 'Buyer Master'.
	3. Clears contact_person if ERPNext's map_fields() copied OBM's plain-text value into the
	   Link-to-Contact field (which would cause a link-validation error on save).
	"""
	apply_box_conversion_to_items(doc)
	recalculate_opportunity_totals(doc)

	if doc.opportunity_from != "Buyer Master":
		return

	# --- 1. customer_name --------------------------------------------------
	if doc.party_name:
		biz_name = frappe.db.get_value(
			"Buyer Master", doc.party_name, "customer_business_name"
		)
		if biz_name:
			doc.customer_name = biz_name

	# --- 2. contact_person Link sanity ------------------------------------
	# ERPNext map_fields() may have copied OBM's plain-text contact_person (e.g. "Ramesh Kumar")
	# into Opportunity.contact_person which is a Link to Contact.  Clear it unless it is a
	# valid Contact name.
	if doc.contact_person and not frappe.db.exists("Contact", doc.contact_person):
		doc.contact_person = ""


def recalculate_opportunity_totals(doc):
	sub_total = 0.0
	over_discount_total = 0.0
	additional_discount_total = 0.0
	gst_total = 0.0
	total_incl = 0.0

	for row in doc.get("items") or []:
		qty = flt(row.qty)
		mrp = flt(row.custom_mrp)
		if not qty or not mrp:
			continue

		flat_discount = flt(row.custom_flat_discount)
		if not flat_discount:
			flat_discount = flt(row.get("custom_buyer_margin_percent"))

		offer_pct = flt(row.custom_offer)
		additional_discount_pct = flt(row.custom_additional_discount)

		gst_pct = flt(row.get("custom_gst_percent") or row.get("gst_percent") or 0)
		if not gst_pct and row.item_code:
			gst_pct = flt(frappe.db.get_value("Item", row.item_code, "custom_gst_percent"))

		# MRP is GST-inclusive
		gross_incl = mrp * qty
		after_flat = gross_incl - (gross_incl * flat_discount / 100.0)
		after_offer = after_flat - (after_flat * offer_pct / 100.0)
		final_incl = after_offer - (after_offer * additional_discount_pct / 100.0)
		final_incl = max(final_incl, 0)

		div = 1 + (gst_pct / 100.0)
		net_amount = (final_incl / div) if div else final_incl
		gst_amount = max(final_incl - net_amount, 0)

		row.rate = flt(net_amount / qty, 2) if qty else 0.0
		row.amount = flt(net_amount, 2)
		row.base_rate = row.rate
		row.base_amount = row.amount
		row.custom_item_tax = flt(gst_amount, 2)
		if flat_discount and not flt(row.custom_flat_discount):
			row.custom_flat_discount = flat_discount

		# Running totals
		sub_total += gross_incl
		over_discount_total += (gross_incl - after_flat)
		additional_discount_total += (after_offer - final_incl)
		gst_total += gst_amount
		total_incl += final_incl

	cash_discount_pct = flt(doc.get("custom_cash_discount"))
	cash_discount_amount = total_incl * (cash_discount_pct / 100.0) if total_incl > 0 else 0
	final_total = max(total_incl - cash_discount_amount, 0)

	doc.custom_over_discount = flt(over_discount_total, 2)
	doc.custom_additional_discount_total = flt(additional_discount_total, 2)
	doc.custom_gst_total = flt(gst_total, 2)
	doc.total = flt(final_total, 2)
	doc.opportunity_amount = flt(final_total, 2)


def apply_box_conversion_to_items(doc):
	for row in doc.get("items") or []:
		apply_box_conversion(row)


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
