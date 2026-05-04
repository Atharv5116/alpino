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
def get_opportunity_obm_party_data(offline_buyer_master):
	"""Offline Buyer Master name + ERPNext Customer + Customer Type for Opportunity header."""
	if not offline_buyer_master or not frappe.db.exists(
		"Offline Buyer Master", offline_buyer_master
	):
		return {}
	row = frappe.db.get_value(
		"Offline Buyer Master",
		offline_buyer_master,
		["customer", "customer_business_name", "customer_type"],
		as_dict=True,
	)
	if not row:
		return {}

	_type_map = {
		"GENERAL TRADE": "GT",
		"MODERN TRADE": "MT",
		"HORECA TRADE": "HoReCa",
		"NUTRITIONAL TRADE": "GYM & NUTRITION",
		"INSTITUTIONAL TRADE": "MT",
	}

	# Prefer the Customer's custom_order_type (matches Quotation order_type options like GT/MT).
	# Fall back to a mapped value from OBM's customer_type.
	resolved_type = ""
	if row.get("customer"):
		resolved_type = frappe.db.get_value("Customer", row["customer"], "custom_order_type") or ""
	if not resolved_type:
		resolved_type = _type_map.get((row.get("customer_type") or "").upper().strip(), "")
	if resolved_type:
		row["customer_type"] = resolved_type

	return row


@frappe.whitelist()
def get_opportunity_line_pricing(opportunity_from, party_name, item_code):
	"""MRP + margin for an Opportunity line.

	Priority when **Opportunity From** is Offline Buyer Master:
	1) Saved row on any **Offline Buyer Items** catalog for that buyer (customer)
	2) **Offline Buyer Margin** row on the selected master (`party_name`)

	Then ERPNext Customer Item MRP, else Item.standard_rate.

	``matched_buyer_sheet`` is True when pricing came from (1) or (2).
	"""
	out = {
		"customer": None,
		"mrp": 0,
		"margin_percent": 0,
		"matched_buyer_sheet": False,
		"source": None,
	}
	if not opportunity_from or not party_name or not item_code:
		return out

	if opportunity_from == "Offline Buyer Master":
		cust = frappe.db.get_value("Offline Buyer Master", party_name, "customer")
		if not cust:
			return out
		out["customer"] = cust

		catalog = frappe.db.sql(
			"""
			SELECT obil.mrp, IFNULL(obil.margin_percent, 0) AS margin_percent
			FROM `tabOffline Buyer Item` obil
			INNER JOIN `tabOffline Buyer Items` obi ON obi.name = obil.parent AND obil.parenttype = 'Offline Buyer Items'
			WHERE IFNULL(obi.docstatus, 0) < 2
				AND obil.item_code = %(item)s
				AND obi.buyer = %(cust)s
			ORDER BY obi.modified DESC
			LIMIT 1
			""",
			{"item": item_code, "cust": cust},
			as_dict=True,
		)
		std_mrp = flt(frappe.db.get_value("Item", item_code, "standard_rate"))
		if catalog:
			r = catalog[0]
			mrp = flt(r.mrp) or std_mrp
			out["mrp"] = mrp
			out["margin_percent"] = flt(r.margin_percent)
			out["matched_buyer_sheet"] = True
			out["source"] = "offline_buyer_items"
			return out

		m_pct = frappe.db.get_value(
			"Offline Buyer Margin",
			{
				"parent": party_name,
				"parenttype": "Offline Buyer Master",
				"sku": item_code,
			},
			"margin_percent",
		)
		if m_pct is not None:
			out["mrp"] = std_mrp
			out["margin_percent"] = flt(m_pct)
			out["matched_buyer_sheet"] = True
			out["source"] = "offline_buyer_margin"
			return out

		mrp = flt(
			frappe.db.get_value(
				"Customer Item MRP",
				{"parent": cust, "parenttype": "Customer", "item_code": item_code},
				"mrp",
			)
		)
		if not mrp:
			mrp = std_mrp
		out["mrp"] = mrp
		out["margin_percent"] = 0
		out["matched_buyer_sheet"] = False
		out["source"] = "fallback"
		return out

	if opportunity_from == "Customer" and party_name:
		out["customer"] = party_name
		mrp = flt(get_customer_item_mrp(party_name, item_code))
		if not mrp:
			mrp = flt(frappe.db.get_value("Item", item_code, "standard_rate"))
		out["mrp"] = mrp
		out["margin_percent"] = 0
		out["matched_buyer_sheet"] = False
		out["source"] = "customer_mrp"

	return out


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
                       additional_units_items=None,
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
	if isinstance(additional_units_items, str):
		additional_units_items = json.loads(additional_units_items)

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

		row = {
			"item_code": item_code,
			"qty": qty,
			"rate": flt(item.get("rate")),
			"delivery_date": item.get("delivery_date") or delivery_date,
			"description": item.get("description") or "",
			"custom_box": custom_box,
			"custom_customer_mrp": flt(item.get("custom_customer_mrp")),
			"custom_flat_discount": flt(item.get("custom_flat_discount")),
			"custom_offer": item.get("custom_offer") or "",
			"custom_additional_discount": flt(item.get("custom_additional_discount")),
			"custom_item_tax": flt(item.get("custom_item_tax")),
		}
		w = item.get("warehouse")
		if w:
			row["warehouse"] = w
		so.append("items", row)

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
		for scheme in scheme_items:
			so.append("custom_scheme_item_table", {
				"item_code": scheme.get("item_code"),
				"qty": flt(scheme.get("qty")),
				"scheme": scheme.get("scheme") or "",
			})

	# Additional Units - Damage items
	so.custom_additional_units_damage = int(additional_units_damage)
	if additional_units_damage and additional_units_items:
		for row in additional_units_items:
			so.append("custom_scheme_item_table", {
				"item_code": row.get("item_code"),
				"qty": flt(row.get("qty")),
				"scheme": row.get("scheme") or "",
				"previous_order_id": row.get("previous_order_id") or "",
				"remarks": row.get("remarks") or "",
			})

	so.insert(ignore_permissions=True)
	if int(submit_now):
		so.submit()
	frappe.db.commit()

	return {"name": so.name, "docstatus": so.docstatus}
