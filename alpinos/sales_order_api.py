"""
Whitelisted API methods for Sales Order customizations.
These bypass child table permission issues when called from client scripts.
"""

import frappe
from frappe.utils import flt
from math import ceil


DEFAULT_SO_COMPANY = "Alpino Health Foods Pvt. Ltd."


def _so_tax_logger():
	return frappe.logger("alpinos_so_tax", allow_site=True, file_count=20)


def _norm_state(value):
	return (value or "").strip().lower().replace(" ", "")


def _resolve_company(preferred=None):
	company = (preferred or "").strip()
	if company:
		return company
	if DEFAULT_SO_COMPANY and frappe.db.exists("Company", DEFAULT_SO_COMPANY):
		return DEFAULT_SO_COMPANY
	company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
		"Global Defaults", "default_company"
	)
	if company:
		return company
	return frappe.db.get_value("Company", {"name": ("!=", "")}, "name", order_by="creation asc")


def _pick_tax_category(inter_state):
	"""Pick best-fit Tax Category name for intra/inter-state GST."""
	names = frappe.get_all("Tax Category", pluck="name") or []
	if not names:
		return None

	intra_keys = ("instate", "in-state", "withinstate", "cgst", "sgst", "intrastate")
	inter_keys = ("outstate", "out-state", "interstate", "inter-state", "igst")
	keys = inter_keys if inter_state else intra_keys

	for name in names:
		n = (name or "").strip().lower()
		if any(k in n for k in keys):
			return name
	return None


def _apply_tax_mode_from_billing(doc):
	"""
	Use IGST when billing state is outside Gujarat, else CGST/SGST.
	Implemented by setting tax_category so ERPNext tax rules/templates can resolve correctly.
	"""
	if doc.doctype != "Sales Order":
		return
	if not doc.get("customer"):
		return

	billing = doc.get("customer_address")
	if not billing:
		_so_tax_logger().warning(
			"[tax_mode] no billing address | so=%s customer=%s",
			doc.get("name") or "(new)",
			doc.get("customer"),
		)
		return

	billing_state = frappe.db.get_value("Address", billing, "state")
	if not billing_state:
		_so_tax_logger().warning(
			"[tax_mode] billing state missing | so=%s billing=%s",
			doc.get("name") or "(new)",
			billing,
		)
		return

	inter_state = _norm_state(billing_state) != _norm_state("Gujarat")
	tax_category = _pick_tax_category(inter_state)
	if tax_category:
		doc.tax_category = tax_category
		_so_tax_logger().info(
			"[tax_mode] resolved category=%s | so=%s billing_state=%s",
			tax_category,
			doc.get("name") or "(new)",
			billing_state,
		)


def _fallback_tax_template(company, inter_state):
	"""Fallback template pick when tax rules don't return one."""
	if not company:
		return None
	templates = frappe.get_all(
		"Sales Taxes and Charges Template",
		filters={"company": company, "disabled": 0},
		fields=["name"],
		order_by="modified desc",
	)
	if not templates:
		return None

	keys = ("igst", "inter-state", "interstate") if inter_state else ("cgst", "sgst", "intra", "within")
	for row in templates:
		n = (row.name or "").lower()
		if any(k in n for k in keys):
			return row.name
	return templates[0].name


def _template_from_tax_category(company, tax_category):
	if not tax_category:
		return None
	# 1) strict match: company + tax category
	if company:
		row = frappe.db.get_value(
			"Sales Taxes and Charges Template",
			{"company": company, "tax_category": tax_category, "disabled": 0},
			"name",
			order_by="modified desc",
		)
		if row:
			return row

	# 2) fallback: any active template with this tax category
	row = frappe.db.get_value(
		"Sales Taxes and Charges Template",
		{"tax_category": tax_category, "disabled": 0},
		"name",
		order_by="modified desc",
	)
	return row


def _ensure_gst_setup_for_company(company):
	"""Create default GST categories/templates/rules if missing for company."""
	if not company:
		return
	try:
		from alpinos.patches.v1_0.create_gst_5_sales_tax_setup import _setup_for_company

		_setup_for_company(company)
	except Exception as e:
		_so_tax_logger().warning("[tax_setup] bootstrap failed company=%s err=%s", company, e)


def _apply_tax_template_from_party(doc):
	"""Resolve and apply Sales Taxes template from party/tax rule context."""
	if doc.doctype != "Sales Order" or not doc.get("customer") or not doc.get("company"):
		return

	billing = doc.get("customer_address")
	shipping = doc.get("shipping_address_name")
	if not billing and not shipping:
		return

	from erpnext.accounts.party import set_taxes as erpnext_set_taxes

	# 1) First, try explicit template by tax_category + company (deterministic).
	template = _template_from_tax_category(doc.company, doc.get("tax_category"))

	# 2) Then ERPNext tax-rule resolution.
	if not template:
		template = erpnext_set_taxes(
		party=doc.customer,
		party_type="Customer",
		posting_date=doc.get("transaction_date"),
		company=doc.company,
		customer_group=frappe.db.get_value("Customer", doc.customer, "customer_group"),
		tax_category=doc.get("tax_category"),
		billing_address=billing,
		shipping_address=shipping,
		)

	if not template and billing:
		billing_state = frappe.db.get_value("Address", billing, "state")
		inter_state = _norm_state(billing_state) != _norm_state("Gujarat")
		template = _fallback_tax_template(doc.company, inter_state)

	# 4) Bootstrap tax setup for company once, then retry.
	if not template:
		_ensure_gst_setup_for_company(doc.company)
		template = _template_from_tax_category(doc.company, doc.get("tax_category"))
		if not template and billing:
			billing_state = frappe.db.get_value("Address", billing, "state")
			inter_state = _norm_state(billing_state) != _norm_state("Gujarat")
			template = _fallback_tax_template(doc.company, inter_state)

	if not template:
		_so_tax_logger().error(
			"[tax_template] not found | so=%s customer=%s company=%s tax_category=%s billing=%s shipping=%s",
			doc.get("name") or "(new)",
			doc.get("customer"),
			doc.get("company"),
			doc.get("tax_category"),
			billing,
			shipping,
		)
		try:
			frappe.log_error(
				title="Alpinos SO Tax Template Missing",
				message=(
					f"SO: {doc.get('name') or '(new)'}\n"
					f"Customer: {doc.get('customer')}\n"
					f"Company: {doc.get('company')}\n"
					f"Tax Category: {doc.get('tax_category')}\n"
					f"Billing: {billing}\n"
					f"Shipping: {shipping}\n"
				),
			)
		except Exception:
			pass
		return

	if doc.get("taxes_and_charges") != template:
		doc.taxes_and_charges = template

	if hasattr(doc, "set"):
		doc.set("taxes", [])
	if hasattr(doc, "append_taxes_from_master"):
		doc.append_taxes_from_master("Sales Taxes and Charges Template")
	_so_tax_logger().info(
		"[tax_template] applied template=%s rows=%s | so=%s",
		doc.get("taxes_and_charges"),
		len(doc.get("taxes") or []),
		doc.get("name") or "(new)",
	)


@frappe.whitelist()
def get_tax_template_for_sales_order(customer, company=None, billing_address=None, shipping_address=None):
	"""Resolve tax category + taxes template for Sales Order Entry page."""
	out = {"company": None, "tax_category": None, "taxes_and_charges": None}
	if not customer:
		return out

	company = _resolve_company(company)
	out["company"] = company

	doc = frappe._dict(
		{
			"doctype": "Sales Order",
			"customer": customer,
			"company": company,
			"customer_address": billing_address,
			"shipping_address_name": shipping_address,
			"transaction_date": frappe.utils.nowdate(),
		}
	)
	doc.get = lambda key, default=None: doc[key] if key in doc else default
	doc.set = lambda key, value: doc.__setitem__(key, value)

	_apply_tax_mode_from_billing(doc)
	_apply_tax_template_from_party(doc)
	out["tax_category"] = doc.get("tax_category")
	out["taxes_and_charges"] = doc.get("taxes_and_charges")
	_so_tax_logger().info(
		"[page_resolve] customer=%s company=%s billing=%s shipping=%s -> category=%s template=%s",
		customer,
		company,
		billing_address,
		shipping_address,
		out["tax_category"],
		out["taxes_and_charges"],
	)
	return out


def _line_flat_discount(item):
	flat = flt(item.get("custom_flat_discount"))
	if flat:
		return flat
	return flt(item.get("buyer_margin_percent") or item.get("custom_buyer_margin_percent"))


def _calculate_sales_order_line_values(item):
	qty = flt(item.get("qty"))
	mrp = flt(item.get("custom_customer_mrp"))
	flat_discount = _line_flat_discount(item)
	offer_pct = flt(item.get("custom_offer"))
	additional_discount_pct = flt(item.get("custom_additional_discount"))
	gst_pct = flt(item.get("custom_gst_percent") or item.get("gst_percent") or 0)

	if not qty or not mrp:
		return {
			"rate": flt(item.get("rate")),
			"amount": flt(item.get("amount")),
			"flat_discount": flat_discount,
			"gst_amount": flt(item.get("custom_item_tax")),
		}

	# MRP is GST-inclusive
	gross_incl = mrp * qty
	after_flat = gross_incl - (gross_incl * flat_discount / 100.0)
	after_offer = after_flat - (after_flat * offer_pct / 100.0)
	final_incl = after_offer - (after_offer * additional_discount_pct / 100.0)
	final_incl = max(final_incl, 0)

	div = 1 + (gst_pct / 100.0)
	net_amount = (final_incl / div) if div else final_incl
	gst_amount = max(final_incl - net_amount, 0)

	return {
		# Store net values in rate/amount; GST can be calculated by Taxes & Charges template.
		"rate": flt(net_amount / qty, 2),
		"amount": flt(net_amount, 2),
		"flat_discount": flat_discount,
		"gst_amount": flt(gst_amount, 2),
	}


def _apply_calculated_item_values(row, calc):
	row.rate = calc["rate"]
	row.amount = calc["amount"]
	row.base_rate = calc["rate"]
	row.base_amount = calc["amount"]
	row.net_rate = calc["rate"]
	row.net_amount = calc["amount"]
	row.base_net_rate = calc["rate"]
	row.base_net_amount = calc["amount"]


def _apply_cash_discount(doc):
	cash_discount = flt(doc.get("custom_cash_discount"))
	doc.custom_cash_discount_amount = 0
	if cash_discount <= 0:
		doc.additional_discount_percentage = 0
		doc.discount_amount = 0
		return

	doc.apply_discount_on = "Grand Total"
	doc.additional_discount_percentage = cash_discount


def validate_sales_order_pricing(doc, method=None):
	"""Keep saved Sales Order rows aligned with the custom entry-page calculation."""
	_so_tax_logger().info(
		"[validate] start so=%s customer=%s company=%s billing=%s shipping=%s",
		doc.get("name") or "(new)",
		doc.get("customer"),
		doc.get("company"),
		doc.get("customer_address"),
		doc.get("shipping_address_name"),
	)
	if not doc.get("company"):
		doc.company = _resolve_company()
	doc.ignore_pricing_rule = 1
	_apply_tax_mode_from_billing(doc)
	_apply_tax_template_from_party(doc)
	_apply_cash_discount(doc)

	for row in doc.get("items") or []:
		calc = _calculate_sales_order_line_values(row)
		if not calc["rate"] and not calc["amount"]:
			continue
		if calc["flat_discount"] and not flt(row.get("custom_flat_discount")):
			row.custom_flat_discount = calc["flat_discount"]
		if calc.get("gst_amount") is not None:
			row.custom_item_tax = flt(calc.get("gst_amount"))
		_apply_calculated_item_values(row, calc)

	if hasattr(doc, "calculate_taxes_and_totals"):
		doc.calculate_taxes_and_totals()
	doc.custom_cash_discount_amount = flt(doc.get("discount_amount"))
	_so_tax_logger().info(
		"[validate] done so=%s template=%s tax_rows=%s total_taxes=%s grand_total=%s",
		doc.get("name") or "(new)",
		doc.get("taxes_and_charges"),
		len(doc.get("taxes") or []),
		doc.get("total_taxes_and_charges"),
		doc.get("grand_total"),
	)


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
		["customer", "customer_business_name", "customer_type", "payment_term"],
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
                       taxes_and_charges=None,
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
	so.company = _resolve_company(company)
	so.delivery_date = delivery_date
	so.ignore_pricing_rule = 1
	so.custom_cash_discount = flt(cash_discount)
	_so_tax_logger().info(
		"[create] payload customer=%s in_company=%s resolved_company=%s billing=%s shipping=%s explicit_template=%s items=%s",
		customer,
		company,
		so.company,
		billing_address,
		shipping_address,
		taxes_and_charges,
		len(items or []),
	)
	if billing_address:
		so.customer_address = billing_address
	if shipping_address:
		so.shipping_address_name = shipping_address
	_apply_tax_mode_from_billing(so)
	if taxes_and_charges:
		so.taxes_and_charges = taxes_and_charges
		so.set("taxes", [])
		so.append_taxes_from_master("Sales Taxes and Charges Template")
	else:
		_apply_tax_template_from_party(so)
	_so_tax_logger().info(
		"[create] resolved category=%s template=%s tax_rows=%s",
		so.get("tax_category"),
		so.get("taxes_and_charges"),
		len(so.get("taxes") or []),
	)

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

		calc = _calculate_sales_order_line_values(
			{
				**item,
				"qty": qty,
				"custom_box": custom_box,
				"custom_customer_mrp": item.get("custom_customer_mrp"),
			}
		)
		row = {
			"item_code": item_code,
			"qty": qty,
			"rate": calc["rate"],
			"delivery_date": item.get("delivery_date") or delivery_date,
			"description": item.get("description") or "",
			"custom_box": custom_box,
			"custom_customer_mrp": flt(item.get("custom_customer_mrp")),
			"custom_gst_percent": flt(item.get("custom_gst_percent") or item.get("gst_percent") or 0),
			"custom_flat_discount": calc["flat_discount"],
			"custom_offer": item.get("custom_offer") or "",
			"custom_additional_discount": flt(item.get("custom_additional_discount")),
			"custom_item_tax": flt(calc.get("gst_amount") or item.get("custom_item_tax")),
		}
		w = item.get("warehouse")
		if w:
			row["warehouse"] = w
		child = so.append("items", row)
		_apply_calculated_item_values(child, calc)

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

	_apply_cash_discount(so)
	so.insert(ignore_permissions=True)
	if int(submit_now):
		so.submit()
	frappe.db.commit()
	_so_tax_logger().info(
		"[create] inserted so=%s template=%s tax_rows=%s total_taxes=%s grand_total=%s",
		so.name,
		so.get("taxes_and_charges"),
		len(so.get("taxes") or []),
		so.get("total_taxes_and_charges"),
		so.get("grand_total"),
	)

	return {"name": so.name, "docstatus": so.docstatus}
