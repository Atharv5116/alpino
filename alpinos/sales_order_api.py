"""
Whitelisted API methods for Sales Order customizations.
These bypass child table permission issues when called from client scripts.
"""

import frappe
from frappe.utils import flt
from math import ceil


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


@frappe.whitelist()
def create_sales_order(customer, order_type, company, items, cash_discount=0,
                       delivery_date=None, freebies=None, scheme_items=None,
                       additional_units_damage=0, billing_address=None, shipping_address=None,
                       submit_now=1):
	"""Create a Sales Order from the custom entry page"""
	import json

	if isinstance(items, str):
		items = json.loads(items)
	if isinstance(freebies, str):
		freebies = json.loads(freebies)
	if isinstance(scheme_items, str):
		scheme_items = json.loads(scheme_items)

	so = frappe.new_doc("Sales Order")
	so.customer = customer
	so.order_type = order_type
	so.company = company or frappe.defaults.get_user_default("Company")
	so.delivery_date = delivery_date
	so.custom_cash_discount = flt(cash_discount)
	if billing_address:
		so.customer_address = billing_address
	if shipping_address:
		so.shipping_address_name = shipping_address

	for item in items:
		item_code = item.get("item_code")
		qty = flt(item.get("qty"))
		custom_box = flt(item.get("custom_box"))
		factor = get_box_conversion_factor(item_code)
		if factor:
			# Always round to next whole box and keep qty aligned to full boxes.
			boxes = ceil(qty / factor) if qty else ceil(custom_box) if custom_box else 0
			qty = flt(boxes * factor) if boxes else qty
			custom_box = boxes

		so.append("items", {
			"item_code": item_code,
			"qty": qty,
			"rate": flt(item.get("rate")),
			"delivery_date": item.get("delivery_date") or delivery_date,
			"custom_box": custom_box,
			"custom_customer_mrp": flt(item.get("custom_customer_mrp")),
			"custom_flat_discount": flt(item.get("custom_flat_discount")),
			"custom_offer": item.get("custom_offer") or "",
			"custom_additional_discount": flt(item.get("custom_additional_discount")),
			"custom_item_tax": flt(item.get("custom_item_tax")),
		})

	# Marketing Freebies
	if freebies:
		for freebie in freebies:
			so.append("custom_marketing_freebies", {
				"item_code": freebie.get("item_code"),
				"qty": flt(freebie.get("qty")),
				"remarks": freebie.get("remarks") or "",
			})

	# Scheme Items
	if scheme_items:
		so.custom_additional_units_damage = 1
		for scheme in scheme_items:
			so.append("custom_scheme_item_table", {
				"item_code": scheme.get("item_code"),
				"qty": flt(scheme.get("qty")),
				"scheme": scheme.get("scheme") or "",
				"previous_order_id": scheme.get("previous_order_id") or "",
			})
	else:
		so.custom_additional_units_damage = int(additional_units_damage)

	so.insert(ignore_permissions=True)
	if int(submit_now):
		so.submit()
	frappe.db.commit()

	return {"name": so.name, "docstatus": so.docstatus}
