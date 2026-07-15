"""
Whitelisted API methods for Sales Order customizations.
These bypass child table permission issues when called from client scripts.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate
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


def _resolve_default_warehouse(company):
	"""Pick a default stock warehouse for the selected company."""
	if not company:
		return None

	abbr = frappe.db.get_value("Company", company, "abbr")
	candidates = []
	if abbr:
		candidates.append(f"Warehouse - {abbr}")
		candidates.append(f"Finished Goods - {abbr}")
		candidates.append(f"Stores - {abbr}")
	candidates.append("Warehouse")

	for wh in candidates:
		if not wh:
			continue
		if frappe.db.exists("Warehouse", {"name": wh, "is_group": 0, "company": company}):
			return wh

	# Fallback to first non-group warehouse in the company.
	return frappe.db.get_value(
		"Warehouse",
		{"is_group": 0, "company": company},
		"name",
		order_by="modified desc",
	)


def _resolve_item_warehouse(item_code, company, fallback=None):
	"""Resolve warehouse for a row, preferring Item Default by company."""
	if item_code and company:
		item_wh = frappe.db.get_value(
			"Item Default",
			{"parent": item_code, "company": company},
			"default_warehouse",
		)
		if item_wh:
			return item_wh
	return fallback


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


def _resolve_address_name(address_string, customer):
	"""
	If the frontend passes the display label instead of the actual ERPNext Address Name,
	this function resolves it back to the Address Name. Accepts any address in the
	customer's buyer-master family (parent + siblings) — the entry page offers the
	whole family's addresses.
	"""
	if not address_string or not customer:
		return address_string

	from alpinos.sales_order_offline_buyer import buyer_family_customers

	# Check if it's already a valid Address name linked to a family customer
	family = buyer_family_customers(customer)
	exists = frappe.db.get_value(
		"Dynamic Link",
		{"parent": address_string, "parenttype": "Address", "link_doctype": "Customer",
		 "link_name": ["in", family]},
		"parent"
	)
	if exists:
		return address_string

	# If not found, it might be the display string. Resolve via display label.
	try:
		address_string = address_string.strip()
		from alpinos.sales_order_offline_buyer import get_customer_addresses_for_display
		opts = get_customer_addresses_for_display(customer)
		for o in opts:
			if (o.get("display") or "").strip() == address_string:
				return o.get("name")
	except Exception:
		pass

	return address_string


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

	if callable(getattr(doc, "set", None)):
		doc.set("taxes", [])
	if callable(getattr(doc, "append_taxes_from_master", None)):
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

	billing_address = _resolve_address_name(billing_address, customer)
	shipping_address = _resolve_address_name(shipping_address, customer)

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

	selling_price = flt(item.get("custom_selling_price") or item.get("selling_price"))
	if not selling_price and mrp:
		selling_price = mrp * (1 - flat_discount / 100.0) * (1 - offer_pct / 100.0)

	if not qty or not selling_price:
		return {
			"rate": flt(item.get("rate")),
			"amount": flt(item.get("amount")),
			"flat_discount": flat_discount,
			"gst_amount": flt(item.get("custom_item_tax")),
			"selling_price": selling_price,
		}

	# Apply additional discount directly on selling price
	gross_incl = selling_price * qty
	final_incl = gross_incl - (gross_incl * additional_discount_pct / 100.0)
	final_incl = max(final_incl, 0)

	div = 1 + (gst_pct / 100.0)
	net_amount = (final_incl / div) if div else final_incl
	gst_amount = max(final_incl - net_amount, 0)

	return {
		# Store net values in rate/amount; GST can be calculated by Taxes & Charges template.
		"rate": flt(net_amount / qty, 2) if qty else 0,
		"amount": flt(net_amount, 2),
		"flat_discount": flat_discount,
		"gst_amount": flt(gst_amount, 2),
		"selling_price": flt(selling_price, 2),
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


def validate_so_freebies_and_box_multiples(doc, method=None):
	"""Two Sales Order save rules (drafts only):

	1. Marketing Freebies may only contain items that are also in the Items
	   table (the entry page warns and clears immediately; this is the backstop).
	2. Ordered qty must fill whole boxes: per item, (order qty + freebie qty)
	   must be a multiple of the Box conversion factor when freebies exist for
	   that item, otherwise the order qty alone must be. Items without a Box
	   UOM are skipped. Replaces the old client-side auto-rounding of qty.
	"""
	if doc.docstatus != 0:
		return

	order_qty = {}
	for row in doc.get("items") or []:
		if row.item_code:
			order_qty[row.item_code] = order_qty.get(row.item_code, 0) + flt(row.qty)

	freebie_qty = {}
	for row in doc.get("custom_marketing_freebies") or []:
		if not row.item_code:
			continue
		if row.item_code not in order_qty:
			frappe.throw(
				f"Marketing Freebie row #{row.idx}: {row.item_code} is not in the "
				"order Items table. Freebies can only be given for ordered items."
			)
		freebie_qty[row.item_code] = freebie_qty.get(row.item_code, 0) + flt(row.qty)

	for item_code, qty in order_qty.items():
		cf = get_box_conversion_factor(item_code)
		if not cf:
			continue
		total = qty + freebie_qty.get(item_code, 0)
		remainder = total % cf
		if min(remainder, cf - remainder) > 1e-4:
			if item_code in freebie_qty:
				frappe.throw(
					f"{item_code}: a box holds {flt(cf)} units — "
					f"ordered qty {flt(qty)} + freebies {flt(freebie_qty[item_code])} = {flt(total)} "
					f"must be a multiple of {flt(cf)}."
				)
			frappe.throw(
				f"{item_code}: a box holds {flt(cf)} units — ordered qty {flt(qty)} "
				f"must be a multiple of {flt(cf)} (or top it up with Marketing Freebies)."
			)


@frappe.whitelist()
def download_sales_orders_zip(names, no_letterhead=0):
	"""Bulk export: one PDF per Sales Order, bundled into a single ZIP download.

	`names` is a JSON list (or list) of Sales Order names sent from the list
	page's bulk action. Each order is rendered with the Sales Order default
	print format and added to the zip as <name>.pdf, so the user gets separate
	PDFs (not one merged document).
	"""
	import json
	import zipfile
	from io import BytesIO

	if isinstance(names, str):
		names = json.loads(names)
	if not names:
		frappe.throw(_("Please select at least one Sales Order."))

	meta = frappe.get_meta("Sales Order")
	format_name = (meta.default_print_format or "").strip() or "Standard"
	no_letterhead = cint(no_letterhead)

	buf = BytesIO()
	failed = []
	with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
		for name in names:
			# get_print enforces read permission on each document.
			try:
				pdf = frappe.get_print(
					"Sales Order", name, format_name, as_pdf=True, no_letterhead=no_letterhead
				)
				safe = str(name).replace("/", "-")
				zf.writestr("{0}.pdf".format(safe), pdf)
			except frappe.PermissionError:
				failed.append(name)
			except Exception:
				frappe.log_error(title="Bulk SO PDF failed for {0}".format(name))
				failed.append(name)

	if failed and len(failed) == len(names):
		frappe.throw(_("Could not generate PDFs for the selected Sales Orders: {0}").format(", ".join(failed)))

	frappe.local.response.filename = "sales-orders-{0}.zip".format(len(names))
	frappe.local.response.filecontent = buf.getvalue()
	frappe.local.response.type = "download"


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
	"""Buyer Master name + ERPNext Customer + Customer Type for Opportunity header."""
	if not offline_buyer_master or not frappe.db.exists(
		"Buyer Master", offline_buyer_master
	):
		return {}
	row = frappe.db.get_value(
		"Buyer Master",
		offline_buyer_master,
		["customer", "customer_business_name", "customer_type", "payment_term"],
		as_dict=True,
	)
	if not row:
		return {}

	# Use the Customer Type directly as it's now a Link field.
	cust_type = row.get("customer_type")
	if row.get("customer"):
		cust_type = frappe.db.get_value("Customer", row["customer"], "custom_order_type") or cust_type
	
	row["customer_type"] = cust_type
	return row


@frappe.whitelist()
def get_opportunity_line_pricing(opportunity_from, party_name, item_code):
	"""MRP + margin for an Opportunity line.

	Priority when **Opportunity From** is Buyer Master:
	1) Saved row on any **Buyer Items** catalog for that buyer (customer)
	2) **Buyer Margin** row on the selected master (`party_name`)

	Then ERPNext Customer Item MRP, else Item.valuation_rate.

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

	if opportunity_from == "Buyer Master":
		cust = frappe.db.get_value("Buyer Master", party_name, "customer")
		if not cust:
			return out
		out["customer"] = cust

		catalog = frappe.db.sql(
			"""
			SELECT obil.mrp, IFNULL(obil.margin_percent, 0) AS margin_percent
			FROM `tabBuyer Item` obil
			INNER JOIN `tabBuyer Items` obi ON obi.name = obil.parent AND obil.parenttype = 'Buyer Items'
			WHERE IFNULL(obi.docstatus, 0) < 2
				AND obil.item_code = %(item)s
				AND obi.buyer = %(cust)s
			ORDER BY obi.modified DESC
			LIMIT 1
			""",
			{"item": item_code, "cust": cust},
			as_dict=True,
		)
		std_mrp = flt(frappe.db.get_value("Item", item_code, "valuation_rate"))
		if catalog:
			r = catalog[0]
			mrp = flt(r.mrp) or std_mrp
			out["mrp"] = mrp
			out["margin_percent"] = flt(r.margin_percent)
			out["matched_buyer_sheet"] = True
			out["source"] = "offline_buyer_items"
			return out

		m_pct = frappe.db.get_value(
			"Buyer Margin",
			{
				"parent": party_name,
				"parenttype": "Buyer Master",
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
			mrp = flt(frappe.db.get_value("Item", item_code, "valuation_rate"))
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


def _parse_request_child_list(val):
	"""Desk sends table data JSON-stringified; normalize to a list safely."""
	import json

	if val is None:
		return []
	if isinstance(val, str):
		s = val.strip()
		if not s:
			return []
		try:
			out = json.loads(s)
		except Exception:
			return []
		return list(out) if isinstance(out, list) else []
	if isinstance(val, (list, tuple)):
		return list(val)
	return []


def _item_name_for_item_code(item_code):
	if not item_code:
		return ""
	return frappe.db.get_value("Item", item_code, "item_name") or ""


def _bundle_components(item_code):
	"""Return the Product Bundle Mapping rows for a bundle SKU, else None.

	None means "not a bundle (or no mapping)" — callers treat the SKU as a normal
	item. A bundle with an empty mapping therefore falls back to itself, never
	silently vanishing from the pick list.
	"""
	if not item_code or not frappe.db.get_value("Item", item_code, "custom_is_bundle"):
		return None
	rows = frappe.get_all(
		"Product Bundle Mapping",
		filters={"parent": item_code, "parenttype": "Item", "parentfield": "custom_product_mapping"},
		fields=["item", "base_qty"],
		order_by="idx",
	)
	return rows or None


def _ensure_so_packed_items(so):
	"""Make sure a bundle SO has its native Packed Items.

	A Sales Order created BEFORE the bundle's native Product Bundle existed (e.g. before
	this feature was migrated) has no packed_items — but the native pick-list -> Delivery
	Note bundle flow needs them (they carry the real `product_bundle_item` and let the DN
	pack + deduct component stock). Regenerate and persist them for any bundle line that
	is missing them. Returns the (reloaded) SO. No-op for non-bundle / already-packed SOs.
	"""
	bundle_lines = [
		i for i in (so.get("items") or [])
		if i.item_code and frappe.db.get_value("Item", i.item_code, "custom_is_bundle")
	]
	if not bundle_lines:
		return so
	packed_for = {p.parent_detail_docname for p in (so.get("packed_items") or [])}
	if all(i.name in packed_for for i in bundle_lines):
		return so

	# Clear any stale/partial packed rows first so a rebuild can't duplicate them, then
	# regenerate the whole table from the native Product Bundle definition.
	from erpnext.stock.doctype.packed_item.packed_item import make_packing_list
	frappe.db.delete("Packed Item", {"parent": so.name, "parenttype": "Sales Order"})
	so.set("packed_items", [])
	make_packing_list(so)
	for idx, p in enumerate(so.get("packed_items") or [], start=1):
		p.parent = so.name
		p.parenttype = "Sales Order"
		p.parentfield = "packed_items"
		p.idx = idx
		p.db_insert()
	frappe.db.commit()
	return frappe.get_doc("Sales Order", so.name)


def _explode_bundle_line(so, item):
	"""Components for a bundle SO line, as [(item_code, qty, product_bundle_item, base_qty)].

	Prefers the SO's NATIVE Packed Items (produced by the synced Product Bundle) so pick-list
	rows line up 1:1 with what the Delivery Note packs — `product_bundle_item` is the real
	Packed Item row name, which is exactly what ERPNext's pick-list->DN mapper keys on
	(skips the component as a normal DN line, adds the bundle line + packed_items, and updates
	the packed item's picked_qty). Falls back to the Item's custom mapping (display-only, no DN
	bundling) only if a bundle SO line somehow has no packed items.
	"""
	if not frappe.db.get_value("Item", item.item_code, "custom_is_bundle"):
		return None
	ordered = flt(item.qty)
	packed = [p for p in (so.get("packed_items") or []) if p.parent_detail_docname == item.name]
	if packed:
		return [
			(p.item_code, flt(p.qty), p.name, (flt(p.qty) / ordered if ordered else flt(p.qty)))
			for p in packed
		]
	comps = _bundle_components(item.item_code)
	if comps:
		return [(c.item, flt(c.base_qty) * ordered, None, flt(c.base_qty)) for c in comps]
	return None


def get_bundle_combos(sales_order):
	"""One combo entry per bundle SO line, for the Pick List COMBO table.

	[{combo_sku, combo_name, ordered_qty, components:[{item_code, item_name,
	base_qty, total_qty}]}].
	"""
	so = _ensure_so_packed_items(frappe.get_doc("Sales Order", sales_order))
	combos = []
	for item in so.get("items") or []:
		exploded = _explode_bundle_line(so, item)
		if not exploded:
			continue
		combos.append({
			"combo_sku": item.item_code,
			"combo_name": _item_name_for_item_code(item.item_code) or item.item_code,
			"ordered_qty": flt(item.qty),
			"components": [{
				"item_code": ic,
				"item_name": _item_name_for_item_code(ic) or ic,
				"base_qty": base,
				"total_qty": qty,
			} for (ic, qty, _pbi, base) in exploded],
		})
	return combos


def _parse_so_entry_args(items, freebies, scheme_items, additional_units_items):
	import json

	if isinstance(items, str):
		items = json.loads(items)
	if not items:
		frappe.throw(_("Order items are required"))
	return (
		items,
		_parse_request_child_list(freebies),
		_parse_request_child_list(scheme_items),
		_parse_request_child_list(additional_units_items),
	)


def _populate_so_from_entry(so, customer, order_type, company, items, cash_discount=0,
                            delivery_date=None, dispatch_date=None, freebies=None, scheme_items=None,
                            additional_units_items=None,
                            additional_units_damage=0, billing_address=None, shipping_address=None,
                            taxes_and_charges=None, po_no=None, po_expiry_date=None, site_name=None,
                            from_quotation=None, po_no_for_pdf=None):
	"""Populate a Sales Order's header + child tables from entry-page args.
	Shared by create_sales_order / update_sales_order; never touches owner,
	docstatus or the workflow status."""
	freebies = freebies or []
	scheme_items = scheme_items or []
	additional_units_items = additional_units_items or []

	so.customer = customer
	so.order_type = order_type
	so.company = _resolve_company(company)
	default_warehouse = _resolve_default_warehouse(so.company)
	so.delivery_date = delivery_date
	if po_no:
		so.po_no = po_no
	so.custom_po_expiry_date = po_expiry_date or None
	if po_no_for_pdf is not None:
		so.custom_po_no_for_pdf = (po_no_for_pdf or "").strip()
	if site_name is not None:
		so.custom_site_name = (site_name or "").strip()
	if dispatch_date:
		so.custom_dispatch_date = dispatch_date
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
	_so_tax_logger().info(
		"[create] company default warehouse=%s",
		default_warehouse,
	)
	if billing_address:
		billing_address = _resolve_address_name(billing_address, customer)
		so.customer_address = billing_address
	if shipping_address:
		shipping_address = _resolve_address_name(shipping_address, customer)
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
	_so_tax_logger().info(
		"[create] child_counts freebies=%s scheme=%s additional_units=%s damage_flag=%s",
		len(freebies),
		len(scheme_items),
		len(additional_units_items),
		int(cint(additional_units_damage)),
	)

	# The same SKU must not appear on more than one order line.
	_seen_item_codes = set()
	for item in items:
		ic = item.get("item_code")
		if not ic:
			continue
		if ic in _seen_item_codes:
			frappe.throw(
				_("SKU {0} appears more than once in the item table. Please combine the quantity onto a single line.").format(ic)
			)
		_seen_item_codes.add(ic)

	for item in items:
		item_code = item.get("item_code")
		qty = flt(item.get("qty"))
		custom_box = flt(item.get("custom_box"))
		factor = get_box_conversion_factor(item_code)
		if factor:
			# qty stays exactly as entered — whole-box compliance (incl. freebie
			# top-ups) is enforced by validate_so_freebies_and_box_multiples.
			# Box count is derived for display/downstream use only.
			if not qty and custom_box:
				qty = flt(ceil(custom_box) * factor)
			custom_box = ceil(qty / factor) if qty else ceil(custom_box)

		calc = _calculate_sales_order_line_values(
			{
				**item,
				"qty": qty,
				"custom_box": custom_box,
				"custom_customer_mrp": item.get("custom_customer_mrp"),
			}
		)

		flat_discount = flt(calc.get("flat_discount"))
		if customer and item_code:
			from alpinos.sales_order_offline_buyer import (
				update_offline_buyer_margin_if_changed,
				upsert_buyer_catalog_selling_rate,
			)
			update_offline_buyer_margin_if_changed(customer, item_code, flat_discount)
			# Keep the buyer catalogue in sync with the line's Selling Price —
			# creating the catalogue when the buyer has none, else the entered
			# price is lost and the next fetch falls back to MRP.
			upsert_buyer_catalog_selling_rate(
				customer, item_code,
				flt(item.get("custom_selling_price") or item.get("selling_price") or calc.get("selling_price") or 0),
				mrp=flt(item.get("custom_customer_mrp")),
			)

		row = {
			"item_code": item_code,
			"qty": qty,
			"rate": calc["rate"],
			"delivery_date": item.get("delivery_date") or delivery_date,
			"description": item.get("description") or "",
			"custom_box": custom_box,
			"custom_customer_mrp": flt(item.get("custom_customer_mrp")),
			"custom_selling_price": flt(item.get("custom_selling_price") or item.get("selling_price") or calc.get("selling_price") or 0),
			"custom_gst_percent": flt(item.get("custom_gst_percent") or item.get("gst_percent") or 0),
			"custom_flat_discount": calc["flat_discount"],
			"custom_offer": item.get("custom_offer") or "",
			"custom_additional_discount": flt(item.get("custom_additional_discount")),
			"custom_item_tax": flt(calc.get("gst_amount") or item.get("custom_item_tax")),
			"custom_remarks": (item.get("custom_remarks") or item.get("remarks") or "").strip(),
		}
		if from_quotation:
			row["prevdoc_docname"] = from_quotation
		w = item.get("warehouse")
		row["warehouse"] = w or _resolve_item_warehouse(item_code, so.company, default_warehouse)
		if not row["warehouse"]:
			# Last-resort fallback to any non-group warehouse on the site.
			row["warehouse"] = frappe.db.get_value("Warehouse", {"is_group": 0}, "name", order_by="modified desc")
		child = so.append("items", row)
		_apply_calculated_item_values(child, calc)

	# Marketing Freebies (include item_name; fetch_from is not always applied before first save)
	for freebie in freebies:
		ic = (freebie.get("item_code") or "").strip()
		if not ic:
			continue
		iname = (freebie.get("item_name") or "").strip() or _item_name_for_item_code(ic)
		so.append(
			"custom_marketing_freebies",
			{
				"item_code": ic,
				"item_name": iname,
				"qty": flt(freebie.get("qty")),
				"remarks": freebie.get("remarks") or "",
			},
		)

	# Scheme child table: persist every line with an item (scheme text may be empty; view shows "—").
	for scheme in scheme_items:
		ic = (scheme.get("item_code") or "").strip()
		if not ic:
			continue
		sch_txt = (scheme.get("scheme") or "").strip()
		iname = (scheme.get("item_name") or "").strip() or _item_name_for_item_code(ic)
		so.append(
			"custom_scheme_item_table",
			{
				"item_code": ic,
				"item_name": iname,
				"qty": flt(scheme.get("qty")),
				"scheme": sch_txt,
			},
		)

	# Additional Units – Damage: only explicit rows from the entry page (never from scheme).
	so.custom_additional_units_damage = int(additional_units_damage)
	if cint(additional_units_damage) and additional_units_items:
		for row in additional_units_items:
			ic = (row.get("item_code") or "").strip()
			if not ic:
				continue
			iname = (row.get("item_name") or "").strip() or _item_name_for_item_code(ic)
			so.append(
				"custom_additional_units_damage_items",
				{
					"item_code": ic,
					"item_name": iname,
					"qty": flt(row.get("qty")),
					"previous_order_id": row.get("previous_order_id") or "",
					"remarks": row.get("remarks") or "",
				},
			)

	_apply_cash_discount(so)


@frappe.whitelist()
def create_sales_order(customer, order_type, company, items, cash_discount=0,
                       delivery_date=None, dispatch_date=None, freebies=None, scheme_items=None,
                       additional_units_items=None,
                       additional_units_damage=0, billing_address=None, shipping_address=None,
                       taxes_and_charges=None, po_no=None, po_expiry_date=None, site_name=None,
                       from_quotation=None, po_no_for_pdf=None,
                       submit_now=1, ecom_fields=None):
	"""Create a Sales Order from the custom entry page.

	ecom_fields (JSON): optional e-com extra fields for offline Modern-Trade orders
	(flags, PO Number/Date, GSTINs, freebie PO) — applied with channel='Offline'.
	"""
	items, freebies, scheme_items, additional_units_items = _parse_so_entry_args(
		items, freebies, scheme_items, additional_units_items
	)
	if not frappe.has_permission("Sales Order", "create"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	so = frappe.new_doc("Sales Order")
	_populate_so_from_entry(
		so, customer, order_type, company, items, cash_discount,
		delivery_date, dispatch_date, freebies, scheme_items,
		additional_units_items, additional_units_damage,
		billing_address, shipping_address, taxes_and_charges, po_no, po_expiry_date, site_name,
		from_quotation, po_no_for_pdf,
	)
	if ecom_fields:
		from alpinos.ecom_sales_order_api import apply_ecom_fields_to_so
		apply_ecom_fields_to_so(so, ecom_fields, channel="Offline")
	so.insert()
	if int(submit_now):
		so.submit()
	frappe.db.commit()
	if so.get("custom_po_no_for_pdf"):
		from alpinos.po_pdf import maybe_fetch_po_pdf
		maybe_fetch_po_pdf(so.name)
	_so_tax_logger().info(
		"[create] inserted so=%s template=%s tax_rows=%s total_taxes=%s grand_total=%s",
		so.name,
		so.get("taxes_and_charges"),
		len(so.get("taxes") or []),
		so.get("total_taxes_and_charges"),
		so.get("grand_total"),
	)

	return {"name": so.name, "docstatus": so.docstatus}


@frappe.whitelist()
def update_sales_order(name, customer, order_type, company, items, cash_discount=0,
                       delivery_date=None, dispatch_date=None, freebies=None, scheme_items=None,
                       additional_units_items=None,
                       additional_units_damage=0, billing_address=None, shipping_address=None,
                       taxes_and_charges=None, po_no=None, po_expiry_date=None, site_name=None,
                       from_quotation=None, po_no_for_pdf=None, ecom_fields=None):
	"""Rewrite a draft Sales Order from the entry page (edit mode). Child tables
	are rebuilt from the payload; owner, docstatus and the workflow status are
	left untouched. ecom_fields (JSON): optional offline Modern-Trade extra fields."""
	items, freebies, scheme_items, additional_units_items = _parse_so_entry_args(
		items, freebies, scheme_items, additional_units_items
	)
	so = frappe.get_doc("Sales Order", name)
	so.check_permission("write")
	if so.docstatus != 0:
		frappe.throw(_("Only draft Sales Orders can be edited from the entry page."))

	so.set("items", [])
	so.set("custom_marketing_freebies", [])
	so.set("custom_scheme_item_table", [])
	so.set("custom_additional_units_damage_items", [])
	_populate_so_from_entry(
		so, customer, order_type, company, items, cash_discount,
		delivery_date, dispatch_date, freebies, scheme_items,
		additional_units_items, additional_units_damage,
		billing_address, shipping_address, taxes_and_charges, po_no, po_expiry_date, site_name,
		from_quotation, po_no_for_pdf,
	)
	if ecom_fields:
		from alpinos.ecom_sales_order_api import apply_ecom_fields_to_so
		apply_ecom_fields_to_so(so, ecom_fields, channel="Offline")
	so.save()
	frappe.db.commit()
	if so.get("custom_po_no_for_pdf"):
		from alpinos.po_pdf import maybe_fetch_po_pdf
		maybe_fetch_po_pdf(so.name)
	return {"name": so.name, "docstatus": so.docstatus}


@frappe.whitelist()
def get_so_entry_payload(sales_order):
	"""Prefill payload for the entry page from an existing Sales Order —
	used by Edit (drafts) and Duplicate. Same shape as the quotation payload."""
	doc = frappe.get_doc("Sales Order", sales_order)
	doc.check_permission("read")

	items = []
	for row in doc.items or []:
		items.append(
			{
				"item_code": row.item_code,
				"item_name": row.get("item_name") or "",
				"description": row.get("description") or "",
				"warehouse": row.get("warehouse") or "",
				"delivery_date": str(row.get("delivery_date") or doc.get("delivery_date") or ""),
				"qty": flt(row.qty),
				"box": flt(row.get("custom_box")),
				"mrp": flt(row.get("custom_customer_mrp")),
				"custom_selling_price": flt(row.get("custom_selling_price")),
				"gst_percent": flt(row.get("custom_gst_percent")),
				"flat_discount": flt(row.get("custom_flat_discount")),
				"offer": row.get("custom_offer") or "",
				"additional_discount": flt(row.get("custom_additional_discount")),
				"rate": flt(row.rate),
				"amount": flt(row.amount),
				"custom_item_tax": flt(row.get("custom_item_tax")),
				"custom_remarks": row.get("custom_remarks") or "",
				"image": row.get("image") or "",
			}
		)

	freebies = [
		{
			"item_code": r.item_code,
			"item_name": r.get("item_name") or "",
			"qty": flt(r.qty),
			"remarks": r.get("remarks") or "",
		}
		for r in (doc.get("custom_marketing_freebies") or [])
		if r.item_code
	]
	scheme_items = [
		{
			"item_code": r.item_code,
			"item_name": r.get("item_name") or "",
			"qty": flt(r.qty),
			"scheme": r.get("scheme") or "",
		}
		for r in (doc.get("custom_scheme_item_table") or [])
		if r.item_code
	]
	additional_units_items = [
		{
			"item_code": r.item_code,
			"item_name": r.get("item_name") or "",
			"qty": flt(r.qty),
			"previous_order_id": r.get("previous_order_id") or "",
			"remarks": r.get("remarks") or "",
		}
		for r in (doc.get("custom_additional_units_damage_items") or [])
		if r.item_code
	]

	return {
		"sales_order": doc.name,
		"docstatus": doc.docstatus,
		"workflow_status": doc.get("custom_workflow_status") or "",
		"owner": doc.owner,
		"owner_full_name": frappe.utils.get_fullname(doc.owner),
		"customer": doc.customer,
		"order_type": doc.get("order_type") or "",
		"delivery_date": str(doc.get("delivery_date") or ""),
		"dispatch_date": str(doc.get("custom_dispatch_date") or ""),
		"po_no": doc.get("po_no") or "",
		"from_quotation": next(
			(r.get("prevdoc_docname") for r in (doc.items or []) if r.get("prevdoc_docname")), ""
		),
		"po_expiry_date": str(doc.get("custom_po_expiry_date") or ""),
		"po_no_for_pdf": doc.get("custom_po_no_for_pdf") or "",
		"site_name": doc.get("custom_site_name") or "",
		"billing_address": doc.get("customer_address") or "",
		"shipping_address": doc.get("shipping_address_name") or "",
		"taxes_and_charges": doc.get("taxes_and_charges") or "",
		"custom_cash_discount": flt(doc.get("custom_cash_discount")),
		"additional_units_damage": cint(doc.get("custom_additional_units_damage")),
		# E-com extras (populated only for E-com / offline Modern-Trade orders).
		"channel": doc.get("custom_channel") or "",
		"ecom": {
			"flags": {
				"appointment_required": cint(doc.get("custom_appointment_required")),
				"grn_available": cint(doc.get("custom_grn_available")),
				"partial_order_allowed": cint(doc.get("custom_partial_order_allowed")),
				"gst_exclusive_buyer": cint(doc.get("custom_gst_exclusive_buyer")),
			},
			"po_number": doc.get("custom_po_number") or "",
			"po_date": str(doc.get("custom_po_date") or ""),
			"delivery_by_date": str(doc.get("custom_delivery_by_date") or ""),
			"billing_gstin": doc.get("custom_billing_gstin") or "",
			"shipping_gstin": doc.get("custom_shipping_gstin") or "",
			"is_freebie_po": cint(doc.get("custom_is_freebie_po")),
		},
		"items": items,
		"freebies": freebies,
		"scheme_items": scheme_items,
		"additional_units_items": additional_units_items,
	}


def _so_view_abs_url(path):
	if not path:
		return ""
	p = str(path).strip()
	if p.startswith(("http://", "https://")):
		return p
	return frappe.utils.get_url(p)


def _so_view_filter_dict_by_read_perm(doctype, row_dict, parenttype=None):
	"""Keep only field keys the current user may read (perm level + DocPerm)."""
	meta = frappe.get_meta(doctype)
	permitted = set(meta.get_permitted_fieldnames(permission_type="read", parenttype=parenttype) or [])
	if not permitted:
		return dict(row_dict)
	out = {}
	for k, v in row_dict.items():
		if k.startswith("_"):
			continue
		if k in permitted:
			out[k] = v
	return out


@frappe.whitelist()
def get_sales_order_entry_view_payload(sales_order):
	"""Sales Order read-only view data for Desk page; respects perm levels on SO + child rows."""
	if not sales_order:
		frappe.throw(_("Sales Order is required"))
	if not frappe.has_permission("Sales Order", "read", doc=sales_order):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	doc = frappe.get_doc("Sales Order", sales_order)
	meta_so = frappe.get_meta("Sales Order")
	permitted_parent = set(meta_so.get_permitted_fieldnames(permission_type="read") or [])
	parent_src = doc.as_dict()
	_skip_parent = frozenset(
		{
			"items",
			"taxes",
			"packed_items",
			"pricing_rules",
			"payment_schedule",
			"sales_team",
			"custom_marketing_freebies",
			"custom_scheme_item_table",
			"custom_additional_units_damage_items",
		}
	)
	parent = {}
	for k, v in parent_src.items():
		if k.startswith("_"):
			continue
		if k in _skip_parent:
			continue
		if isinstance(v, (list, tuple)):
			continue
		if k in permitted_parent:
			parent[k] = v
	parent["name"] = doc.name
	# Std fields aren't in permitted fieldnames; Created By is always shown.
	parent["owner"] = doc.owner
	parent["owner_full_name"] = frappe.utils.get_fullname(doc.owner)

	# Table fields (items, child tables) are excluded from get_permitted_fieldnames but SO read
	# implies line visibility; still filter each child row by Sales Order *Item* field perms.
	# NOTE: the view page (and pick list) always show the raw order lines (combos stay as combos).
	# Bundle explosion/combining per 'Combine Product Bundles' happens ONLY in the PDF print and
	# the Tally (Accounts Format) report.
	items = []
	for row in doc.items:
		rd = _so_view_filter_dict_by_read_perm("Sales Order Item", row.as_dict(), parenttype="Sales Order")
		img = rd.get("custom_product_image") or ""
		if img:
			rd["custom_product_image_url"] = _so_view_abs_url(img)
		items.append(rd)

	freebies = []
	for row in doc.get("custom_marketing_freebies") or []:
		freebies.append(
			_so_view_filter_dict_by_read_perm(
				"Sales Order Marketing Freebie", row.as_dict(), parenttype="Sales Order"
			)
		)

	# Scheme grid: all `custom_scheme_item_table` rows (blank scheme still shows SKU / qty; Scheme column "—").
	scheme_rows = []
	scheme_item_perm = "Sales Order Scheme Item"
	for row in doc.get("custom_scheme_item_table") or []:
		rd = _so_view_filter_dict_by_read_perm(
			scheme_item_perm, row.as_dict(), parenttype="Sales Order"
		)
		scheme_rows.append(rd)

	# Fallback: if child grid rows exist in DB but did not survive permission shaping,
	# return a minimal safe projection so the view never hides Scheme Details.
	if not scheme_rows and frappe.db.has_table("Sales Order Scheme Item"):
		raw_scheme = frappe.db.sql(
			"""
			SELECT item_code, item_name, qty, scheme
			FROM `tabSales Order Scheme Item`
			WHERE parent=%s
				AND parenttype='Sales Order'
				AND parentfield='custom_scheme_item_table'
				AND IFNULL(item_code, '') != ''
			ORDER BY idx ASC
			""",
			(sales_order,),
			as_dict=True,
		)
		scheme_rows = [dict(r) for r in (raw_scheme or [])]

	damage_item_rows = []
	add_units_perm = "Sales Order Additional Units Item"
	for row in doc.get("custom_additional_units_damage_items") or []:
		damage_item_rows.append(
			_so_view_filter_dict_by_read_perm(
				add_units_perm,
				row.as_dict(),
				parenttype="Sales Order",
			)
		)

	damage = 0
	if "custom_additional_units_damage" in permitted_parent:
		damage = int(doc.get("custom_additional_units_damage") or 0)

	# Partial orders: per-SKU remaining qty for the Remaining column (BRD).
	from alpinos import partial_dispatch as pd
	show_remaining = doc.docstatus == 1 and pd.is_partial_order(sales_order)
	remaining_qty = pd.remaining_qty_by_sku(sales_order) if show_remaining else {}

	return {
		"parent": parent,
		"items": items,
		"freebies": freebies,
		"scheme_rows": scheme_rows,
		"damage_item_rows": damage_item_rows,
		"additional_units_damage": damage,
		"show_remaining": int(show_remaining),
		"remaining_qty": remaining_qty,
	}


@frappe.whitelist()
def get_sales_order_entry_list(
	start=0,
	page_length=20,
	search=None,
	status=None,
	workflow_status=None,
	company=None,
	customer=None,
	from_date=None,
	to_date=None,
	additional_units_damage_filter=None,
	channel=None,
):
	"""Paginated Sales Order rows for Alpinos custom list page (respects DocPerm / user rules).

	channel: "Offline" or "E-com" restricts to that channel; legacy (blank) rows are
	treated as Offline so the offline list keeps showing pre-migration orders.
	"""
	if not frappe.has_permission("Sales Order", "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	start = cint(start)
	page_length = min(max(cint(page_length) or 20, 1), 100)

	filters = {}
	channel = (channel or "").strip()
	if channel == "E-com":
		filters["custom_channel"] = "E-com"
	elif channel == "Offline":
		# Offline + legacy(blank) rows.
		filters["custom_channel"] = ["in", ["Offline", ""]]
	if status:
		filters["status"] = str(status).strip()
	if workflow_status:
		filters["custom_workflow_status"] = str(workflow_status).strip()
	if company:
		filters["company"] = str(company).strip()
	if customer:
		filters["customer"] = str(customer).strip()

	# Optional: filter by Additional Units – Damage (`custom_additional_units_damage`).
	_aug = (additional_units_damage_filter or "").strip().lower()
	if _aug in ("yes", "1", "true", "y"):
		filters["custom_additional_units_damage"] = 1
	elif _aug in ("no", "0", "false", "n"):
		filters["custom_additional_units_damage"] = 0

	def _d(val):
		if not val:
			return None
		try:
			return getdate(val)
		except Exception:
			return None

	fd = _d(from_date)
	td = _d(to_date)
	if fd and td and fd > td:
		fd, td = td, fd
	if fd and td:
		filters["transaction_date"] = ["between", [fd, td]]
	elif fd:
		filters["transaction_date"] = [">=", fd]
	elif td:
		filters["transaction_date"] = ["<=", td]

	# A dedicated Warehouse Manager sees the whole warehouse work queue — every
	# stage from "waiting for approval" through dispatch-in-progress — not just
	# "Warehouse Approval Pending". The old single-status filter hid an order the
	# moment it left that status (e.g. the daily job flipping it to Today's
	# Dispatch), so warehouse orders vanished from their list. Users who also hold
	# a broad/sales/admin role keep full visibility. An explicit status filter
	# chosen in the UI is respected.
	_roles = set(frappe.get_roles())
	_override_roles = {
		"System Manager",
		"Administrator",
		"Sales Admin",
		"Sales Manager",
		"Sales User",
	}
	_WAREHOUSE_QUEUE = [
		"Warehouse Approval Pending", "Future Dispatch", "Today's Dispatch", "Warehouse Approved",
		"Picking In Progress", "Submission Pending", "Ready For Dispatch", "Delivery Note Created",
		"Partial Ready For Dispatch", "Partial Delivery Note Created", "Partial Dispatched",
		"Forced Ready For Dispatch", "Forced Delivery Note Created", "Forced Dispatched",
	]
	if "Warehouse Manager" in _roles and not (_roles & _override_roles):
		if "custom_workflow_status" not in filters:  # respect an explicit UI status filter
			filters["custom_workflow_status"] = ["in", _WAREHOUSE_QUEUE]

	or_filters = None
	search = (search or "").strip()
	if search:
		safe = search.replace("%", "").replace("_", "")
		like = f"%{safe}%"
		or_filters = [
			["name", "like", like],
			["customer", "like", like],
			["customer_name", "like", like],
		]

	fields = [
		"name",
		"customer",
		"customer_name",
		"transaction_date",
		"delivery_date",
		"company",
		"status",
		"custom_workflow_status",
		"order_type",
		"grand_total",
		"currency",
		"custom_additional_units_damage",
		"docstatus",
		"modified",
		"po_no",
		"po_date",
		"custom_dispatch_date",
		"custom_po_expiry_date",
		"custom_site_name",
		"custom_channel",
		"custom_po_number",
		"custom_po_date",
		"owner",
	]

	rows = frappe.get_list(
		"Sales Order",
		fields=fields,
		filters=filters or None,
		or_filters=or_filters,
		limit_start=start,
		limit_page_length=page_length + 1,
		order_by="modified desc",
	)

	has_more = len(rows) > page_length
	rows = rows[:page_length]

	_attach_so_list_row_extras(rows)

	return {"data": rows, "has_more": int(has_more), "start": start, "page_length": page_length}


def _attach_so_list_row_extras(rows):
	"""Per row: Created By full name + the latest linked Pick List / Delivery
	Note / Sales Invoice (for the list page's redirect buttons). One bulk query
	per doctype for the whole page."""
	if not rows:
		return
	names = [r.name for r in rows]

	pl_map = {}
	for r in frappe.get_all(
		"Pick List",
		filters={"custom_sales_order_id": ["in", names], "docstatus": ["<", 2]},
		fields=["name", "custom_sales_order_id"],
		order_by="modified asc",
	):
		pl_map[r.custom_sales_order_id] = r.name  # last write wins = latest

	dn_map = {}
	for r in frappe.get_all(
		"Delivery Note",
		filters={"custom_sales_order_id": ["in", names], "docstatus": ["<", 2], "is_return": 0},
		fields=["name", "custom_sales_order_id"],
		order_by="modified asc",
	):
		dn_map[r.custom_sales_order_id] = r.name

	inv_map = {}
	for r in frappe.get_all(
		"Sales Invoice Item",
		filters={"sales_order": ["in", names], "docstatus": ["<", 2]},
		fields=["parent", "sales_order"],
		order_by="modified asc",
	):
		inv_map[r.sales_order] = r.parent

	fullnames = {}
	for r in rows:
		if r.owner not in fullnames:
			fullnames[r.owner] = frappe.utils.get_fullname(r.owner)
		r["owner_full_name"] = fullnames[r.owner]
		r["pick_list"] = pl_map.get(r.name) or ""
		r["delivery_note"] = dn_map.get(r.name) or ""
		r["sales_invoice"] = inv_map.get(r.name) or ""

@frappe.whitelist()
def get_pick_list_mapping_data(sales_order, remaining_only=0):
	"""Build the Pick List skeleton for a Sales Order.

	remaining_only=1 (partial "Create PL for Remaining Qty"): each location's qty is
	reduced by the qty already committed on existing non-cancelled Pick Lists for the
	same SKU, and fully-covered rows are dropped — so the new PL pre-fills only the
	outstanding qty.
	"""
	so = _ensure_so_packed_items(frappe.get_doc("Sales Order", sales_order))

	pick_list = frappe._dict({
		"company": so.company,
		"purpose": "Delivery",
		"custom_sales_order_id": so.name,
		"custom_customer_name": so.customer_name,
		"custom_party_code": so.customer,
		"custom_order_date": so.transaction_date,
		"custom_dispatch_date": str(so.custom_dispatch_date) if so.custom_dispatch_date else "",
		"custom_po_no": so.po_no,
		"pick_manually": 1,
		"locations": []
	})
	
	def add_item_to_pick_list(item_row, source_table, sales_order_item=None, bundle_parent=None, box_override=None, product_bundle_item=None):
		if not item_row.item_code:
			return

		# Box conversion logic
		box = flt(item_row.get("custom_box"), 2)
		factor = get_box_conversion_factor(item_row.item_code) or 1
		if source_table in ["Marketing Freebies", "Scheme Table", "Additional Units"]:
			box = 0.0
		# Exploded bundle components: box is derived from the component qty, not entered.
		if box_override is not None:
			box = flt(box_override, 2)

		warehouse = item_row.get("warehouse")
		if not warehouse:
			warehouse = _resolve_item_warehouse(item_row.item_code, so.company, _resolve_default_warehouse(so.company))
			
		item_info = (
			frappe.db.get_value(
				"Item",
				item_row.item_code,
				["custom_sku_no", "custom_gross_weight", "shelf_life_in_days"],
				as_dict=True,
			)
			or {}
		)
		pick_list["locations"].append({
			"name": item_row.name, # Stable unique ID from SO Child Table Row
			"sales_order_item": sales_order_item or item_row.name,
			"product_bundle_item": product_bundle_item or "",
			"item_code": item_row.item_code,
			"custom_ordered_qty": item_row.qty,
			"qty": item_row.qty,
			"custom_box": box,
			"custom_source_table": source_table,
			"custom_conversion_factor": factor,
			"custom_bundle_parent": bundle_parent or "",
			"custom_sku_no": item_info.get("custom_sku_no") or "",
			"custom_weight_per_box": flt(item_info.get("custom_gross_weight")) or 0,
			"shelf_life_in_days": item_info.get("shelf_life_in_days") or 0,
			"warehouse": warehouse
		})

	combos = []
	for item in so.get("items") or []:
		exploded = _explode_bundle_line(so, item)
		if exploded:
			# Bundle SKU: explode into its component items (from the SO's native packed
			# items). The bundle SKU itself is NOT a pickable row — it only appears in the
			# COMBO table; each component row carries custom_bundle_parent (UI), the real
			# bundle SO line, and product_bundle_item (the Packed Item name) so the
			# Delivery Note maps it natively as a bundle.
			ordered = flt(item.qty)
			combo = {
				"combo_sku": item.item_code,
				"combo_name": _item_name_for_item_code(item.item_code) or item.item_code,
				"ordered_qty": ordered,
				"components": [],
			}
			for (comp_item, total, pbi, base) in exploded:
				comp_factor = get_box_conversion_factor(comp_item) or 1
				comp_box = flt(total / comp_factor, 2) if comp_factor else 0.0
				add_item_to_pick_list(
					frappe._dict({
						# Stable id from SO line + component (NOT the volatile packed-item
						# name) so render and save always agree and rows aren't dropped.
						"name": "%s::bundle::%s" % (item.name, comp_item),
						"item_code": comp_item,
						"qty": total,
					}),
					"Items",
					sales_order_item=item.name,
					bundle_parent=item.item_code,
					box_override=comp_box,
					product_bundle_item=pbi,
				)
				combo["components"].append({
					"item_code": comp_item,
					"item_name": _item_name_for_item_code(comp_item) or comp_item,
					"base_qty": base,
					"total_qty": total,
				})
			combos.append(combo)
		else:
			add_item_to_pick_list(item, "Items")

	for freebie in so.get("custom_marketing_freebies") or []:
		add_item_to_pick_list(freebie, "Marketing Freebies")
		
	for scheme in so.get("custom_scheme_item_table") or []:
		add_item_to_pick_list(scheme, "Scheme Table")
		
	for additional in so.get("custom_additional_units_damage_items") or []:
		add_item_to_pick_list(additional, "Additional Units")

	pick_list["combos"] = combos
	from alpinos import partial_dispatch as pd
	pick_list["partial_order_allowed"] = int(pd.is_partial_order(sales_order))

	if cint(remaining_only):
		from alpinos import partial_dispatch as pd

		# Running pool of already-committed qty per SKU; distribute it across the
		# mapped rows so duplicate SKUs (bundle components, freebie top-ups) subtract
		# correctly rather than each row over-subtracting the full committed amount.
		to_subtract = {k: flt(v) for k, v in pd.committed_pl_qty_by_sku(sales_order).items()}
		remaining_locs = []
		for loc in pick_list["locations"]:
			ic = loc.get("item_code")
			full = flt(loc.get("qty"))
			sub = min(full, flt(to_subtract.get(ic, 0)))
			to_subtract[ic] = flt(to_subtract.get(ic, 0)) - sub
			rem = flt(full - sub, 2)
			if rem <= 1e-6:
				continue  # already fully committed on earlier rounds
			loc["qty"] = rem
			loc["custom_ordered_qty"] = rem
			factor = flt(loc.get("custom_conversion_factor")) or 1
			if loc.get("custom_source_table") not in ("Marketing Freebies", "Scheme Table", "Additional Units"):
				loc["custom_box"] = flt(rem / factor, 2) if factor else 0.0
			remaining_locs.append(loc)
		pick_list["locations"] = remaining_locs

	return pick_list


@frappe.whitelist()
def get_so_pick_list_status(sales_order):
	if not sales_order:
		return {"fully_picked": False, "has_draft": False, "draft_name": None}
		
	so = frappe.get_doc("Sales Order", sales_order)
	
	# 1. Calculate ordered qtys
	ordered_qtys = {}
	for item in so.get("items") or []:
		if item.item_code:
			ordered_qtys[item.item_code] = ordered_qtys.get(item.item_code, 0.0) + flt(item.qty)
	for item in so.get("custom_marketing_freebies") or []:
		if item.item_code:
			ordered_qtys[item.item_code] = ordered_qtys.get(item.item_code, 0.0) + flt(item.qty)
	for item in so.get("custom_scheme_item_table") or []:
		if item.item_code:
			ordered_qtys[item.item_code] = ordered_qtys.get(item.item_code, 0.0) + flt(item.qty)
	for item in so.get("custom_additional_units_damage_items") or []:
		if item.item_code:
			ordered_qtys[item.item_code] = ordered_qtys.get(item.item_code, 0.0) + flt(item.qty)
			
	# 2. Get picked qtys from submitted Pick Lists
	picked_qtys = {}
	
	pl_names = frappe.get_all(
		"Pick List Item",
		filters={"sales_order": sales_order, "docstatus": ["<", 2]},
		pluck="parent"
	) or []
	
	custom_pl_names = frappe.get_all(
		"Pick List",
		filters={"custom_sales_order_id": sales_order, "docstatus": ["<", 2]},
		pluck="name"
	) or []
	
	all_pls = list(set(pl_names + custom_pl_names))
	
	draft_name = None
	has_draft = False
	
	if all_pls:
		# Check for draft
		drafts = frappe.get_all(
			"Pick List",
			filters={"name": ["in", all_pls], "docstatus": 0},
			pluck="name"
		)
		if drafts:
			has_draft = True
			draft_name = drafts[0]
			
		# Get picked quantities from submitted pick lists
		submitted_pls = frappe.get_all(
			"Pick List",
			filters={"name": ["in", all_pls], "docstatus": 1},
			pluck="name"
		)
		if submitted_pls:
			items = frappe.get_all(
				"Pick List Item",
				filters={"parent": ["in", submitted_pls]},
				fields=["item_code", "qty"]
			)
			for row in items:
				if row.item_code:
					picked_qtys[row.item_code] = picked_qtys.get(row.item_code, 0.0) + flt(row.qty)
					
	fully_picked = True
	if not ordered_qtys:
		fully_picked = False
	else:
		for sku, ordered in ordered_qtys.items():
			if picked_qtys.get(sku, 0.0) < ordered:
				fully_picked = False
				break
				
	from alpinos import partial_dispatch as pd
	partial_allowed = pd.is_partial_order(sales_order)
	remaining = pd.remaining_qty_by_sku(sales_order)
	has_remaining = any(v > 1e-6 for v in remaining.values())
	force_closed = bool(so.get("custom_force_closed"))

	return {
		"fully_picked": fully_picked,
		"has_draft": has_draft,
		"draft_name": draft_name,
		"has_pick_list": bool(all_pls),  # Any pick list exists (draft or submitted)
		# Partial dispatch: allow another PL for the remaining qty.
		"partial_order_allowed": int(partial_allowed),
		"has_remaining_qty": int(has_remaining),
		"remaining_qty": remaining,
		# Forced Close: order permanently locked.
		"force_closed": int(force_closed),
	}



