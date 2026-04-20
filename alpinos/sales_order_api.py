"""
Whitelisted API methods for Sales Order customizations.
These bypass child table permission issues when called from client scripts.
"""

import frappe
from frappe.utils import flt


@frappe.whitelist()
def get_customer_item_mrp(customer, item_code):
	"""Fetch MRP for an item from Customer's Item MRP table"""
	if not customer or not item_code:
		return None

	mrp = frappe.db.get_value(
		"Customer Item MRP",
		{"parent": customer, "parenttype": "Customer", "item_code": item_code},
		"mrp"
	)
	return flt(mrp)


@frappe.whitelist()
def get_box_conversion_factor(item_code):
	"""Fetch Box UOM conversion factor from Item's UOM table"""
	if not item_code:
		return None

	conversion_factor = frappe.db.get_value(
		"UOM Conversion Detail",
		{"parent": item_code, "parenttype": "Item", "uom": "Box"},
		"conversion_factor"
	)
	return flt(conversion_factor) if conversion_factor else None
