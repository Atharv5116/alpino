"""Server-side validation helpers for Alpinos Opportunities."""

import frappe
from frappe import _
from frappe.utils import flt
from math import ceil


def validate_opportunity_alpinos(doc, method=None):
	"""Runs on Opportunity.validate via hooks.doc_events.

	1. Rounds SKU quantities up to full boxes when a Box UOM conversion exists.
	2. Sets customer_name from OBM's customer_business_name when opportunity_from == 'Offline Buyer Master'.
	3. Clears contact_person if ERPNext's map_fields() copied OBM's plain-text value into the
	   Link-to-Contact field (which would cause a link-validation error on save).
	"""
	apply_box_conversion_to_items(doc)

	if doc.opportunity_from != "Offline Buyer Master":
		return

	# --- 1. customer_name --------------------------------------------------
	if doc.party_name:
		biz_name = frappe.db.get_value(
			"Offline Buyer Master", doc.party_name, "customer_business_name"
		)
		if biz_name:
			doc.customer_name = biz_name

	# --- 2. contact_person Link sanity ------------------------------------
	# ERPNext map_fields() may have copied OBM's plain-text contact_person (e.g. "Ramesh Kumar")
	# into Opportunity.contact_person which is a Link to Contact.  Clear it unless it is a
	# valid Contact name.
	if doc.contact_person and not frappe.db.exists("Contact", doc.contact_person):
		doc.contact_person = ""


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
