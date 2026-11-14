"""Server-side validation helpers for Alpinos Opportunities."""

import frappe


def validate_opportunity_alpinos(doc, method=None):
	"""Opportunity.validate hook: fill customer_name, sanitise contact_person.

	Prices, Box and totals are alpinos.offline_sales.opportunity's (Section 3, 3.2): Quantity is
	no longer rounded up to whole boxes, and the commercial values come from the Buyer Catalog."""
	if doc.opportunity_from != "Buyer Master":
		return

	if doc.party_name:
		biz_name = frappe.db.get_value(
			"Buyer Master", doc.party_name, "customer_business_name"
		)
		if biz_name:
			doc.customer_name = biz_name

	# contact_person may hold OBM plain text; clear it unless it's a real Contact.
	if doc.contact_person and not frappe.db.exists("Contact", doc.contact_person):
		doc.contact_person = ""
