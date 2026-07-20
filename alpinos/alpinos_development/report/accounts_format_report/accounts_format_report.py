"""Accounts Format Report — Tally-style billing export.

One row per Sales Order line (main items + marketing freebies + scheme items +
additional-unit/damage items, the latter at selling rate 0). Pulls from Sales Order,
Buyer Master, Item Master and the selected billing/shipping Addresses.

Exports to Excel via the standard report view (Menu → Export).
"""

import frappe
from frappe.utils import flt, getdate


# ── helpers ────────────────────────────────────────────────────────────────
def _split_address(text, max_len=60, max_lines=6):
	"""Greedy word-wrap into <=max_len chunks (break on space), padded to max_lines."""
	lines, cur = [], ""
	for w in (text or "").split():
		if not cur:
			cur = w
		elif len(cur) + 1 + len(w) <= max_len:
			cur += " " + w
		else:
			lines.append(cur)
			cur = w
			if len(lines) >= max_lines:
				break
	if cur and len(lines) < max_lines:
		lines.append(cur)
	lines += [""] * (max_lines - len(lines))
	return lines[:max_lines]


def _voucher_type(registration_type, state):
	gujarat = (state or "").strip().lower() == "gujarat"
	if registration_type == "Registered":
		return "B to B GST Sales Offline" if gujarat else "B to B IGST Sales Offline"
	return "B to C GST Sales Offline" if gujarat else "B to C IGST Sales Offline"


def _picklist_map(so_name):
	"""Per-item picked qty + box from the SUBMITTED Pick List(s) of this Sales Order.
	Picked qty uses picked_qty, falling back to qty when picked_qty is 0."""
	rows = frappe.db.sql(
		"""
		SELECT pli.item_code,
			SUM(IFNULL(NULLIF(pli.picked_qty, 0), pli.qty)) AS qty,
			SUM(IFNULL(pli.custom_box, 0)) AS box
		FROM `tabPick List Item` pli
		INNER JOIN `tabPick List` pl ON pl.name = pli.parent AND pl.docstatus = 1
		WHERE pl.custom_sales_order_id = %(so)s OR pli.sales_order = %(so)s
		GROUP BY pli.item_code
		""",
		{"so": so_name},
		as_dict=True,
	)
	return {r.item_code: r for r in rows}


def _address(name):
	if not name:
		return {}
	return dict(
		frappe.db.get_value(
			"Address", name,
			["state", "city", "pincode", "address_line1", "address_line2"],
			as_dict=True,
		)
		or {}
	)


def _has_scp(d):
	"""True when an address dict carries any of state / city / pincode."""
	return bool(d.get("state") or d.get("city") or d.get("pincode"))


def _norm_addr(text):
	"""Normalize an address string for matching: lowercase, collapse whitespace,
	drop a trailing '(Billing)'/'(Shipping)' type suffix and stray punctuation."""
	s = " ".join((text or "").replace("\n", " ").replace("\r", " ").split()).lower()
	if "(" in s:  # the family-dropdown label carries a "(type)" suffix; strip defensively
		s = s.split("(", 1)[0]
	return s.strip().strip(",").strip()


def _resolve_scp_from_text(customer, text, cache):
	"""Recover {state, city, pincode} for a FREE-TEXT address (e-com orders store
	the address as text, not an Address link) by matching it back to one of the
	buyer family's Address records — composed the same way the entry page builds
	the option value: 'line1, line2, city, state, pincode'."""
	target = _norm_addr(text)
	if not customer or not target:
		return {}
	if customer not in cache:
		try:
			from alpinos.sales_order_offline_buyer import get_customer_addresses_for_display
			cache[customer] = get_customer_addresses_for_display(customer) or []
		except Exception:
			cache[customer] = []
	for row in cache[customer]:
		composed = _norm_addr(", ".join(
			str(p) for p in [
				row.get("address_line1"), row.get("address_line2"),
				row.get("city"), row.get("state"), row.get("pincode"),
			] if p and str(p).strip().upper() != "N/A"
		))
		if composed and composed == target:
			return {
				"state": row.get("state") or "",
				"city": row.get("city") or "",
				"pincode": row.get("pincode") or "",
			}
	return {}


# ── column definitions ─────────────────────────────────────────────────────
def get_columns():
	def col(label, fn, w=120, ft="Data"):
		return {"label": label, "fieldname": fn, "fieldtype": ft, "width": w}

	cols = [
		col("Invoice No", "invoice_no", 100),
		col("Order Date", "order_date", 95, "Date"),
		col("Sales Order Id", "sales_order_id", 130),
		col("Customer PO Number", "customer_po_number", 130),
		col("Customer", "customer", 180),
		col("P&L Name / Voucher Type", "pl_voucher", 180),
		col("Registration Type", "registration_type", 110),
		col("GST No", "gst_no", 140),
		col("Alpino SKU", "alpino_sku", 120),
		col("EAN/FSN", "ean_fsn", 130),
		col("EAN/FSN Flag", "ean_fsn_flag", 90),
		col("Alpino Product Name", "alpino_product_name", 220),
		col("UNIT", "unit", 70, "Float"),
		col("Box", "box", 60, "Float"),
		col("Alpino Product MRP", "alpino_mrp", 110, "Currency"),
		col("Selling Price", "selling_price", 100, "Currency"),
		col("Flat Discount %", "flat_discount", 90, "Float"),
		col("Additional Discount", "additional_discount", 100, "Float"),
		col("Alpino GST Rate", "gst_rate", 90, "Float"),
		col("Final Taxable", "final_taxable", 110, "Currency"),
		col("CGST", "cgst", 90, "Currency"),
		col("IGST", "igst", 90, "Currency"),
		col("Final Total Value", "final_total", 120, "Currency"),
		col("Is Billable", "is_billable", 80),
		col("Mobile No", "mobile_no", 110),
		col("Place Of Supply (Bill to State)", "bill_state", 130),
		col("Bill to City", "bill_city", 110),
		col("Bill to Pincode", "bill_pincode", 90),
	]
	for i in range(1, 7):
		cols.append(col(f"Bill to Address Line.{i}", f"bill_addr_{i}", 160))
	cols += [
		col("Ship to State", "ship_state", 120),
		col("Ship to City", "ship_city", 110),
		col("Ship to Pincode", "ship_pincode", 90),
	]
	for i in range(1, 7):
		cols.append(col(f"Ship to Address Line.{i}", f"ship_addr_{i}", 160))
	cols += [
		col("Tally Warehouse Id", "tally_warehouse_id", 110),
		col("Channel", "channel", 120),
	]
	return cols


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), _get_data(filters)


def _get_data(filters):
	so_filters = {"docstatus": 1}
	if filters.get("from_date") and filters.get("to_date"):
		so_filters["transaction_date"] = ["between", [filters.from_date, filters.to_date]]
	if filters.get("customer"):
		so_filters["customer"] = filters.customer

	so_names = frappe.get_all("Sales Order", filters=so_filters, pluck="name", order_by="transaction_date asc, name asc")

	item_cache, obm_cache, ct_channel_cache = {}, {}, {}

	def item_info(code):
		if code not in item_cache:
			item_cache[code] = frappe.db.get_value(
				"Item", code,
				["custom_tally_sku", "custom_tally_item_name", "item_name", "custom_ean_no",
				 "custom_fsn_no", "custom_is_billable", "valuation_rate", "custom_gst_percent"],
				as_dict=True,
			) or {}
		return item_cache[code]

	def obm_info(customer):
		if customer not in obm_cache:
			obm_cache[customer] = frappe.db.get_value(
				"Buyer Master", {"customer": customer},
				["tally_buyer_name", "tally_pl_name", "gst_type", "gst_no", "contact_no",
				 "custom_tally_warehouse_id", "customer_type", "combine_product_bundles"],
				as_dict=True,
			) or {}
		return obm_cache[customer]

	def channel_of(customer_type):
		if customer_type not in ct_channel_cache:
			ct_channel_cache[customer_type] = frappe.db.get_value("Alpino Customer Type", customer_type, "channel") or ""
		return ct_channel_cache[customer_type]

	data = []
	addr_cache = {}  # customer -> family Address rows (for free-text state/city/pincode recovery)
	for so_name in so_names:
		so = frappe.get_doc("Sales Order", so_name)
		obm = obm_info(so.customer)
		# Customer type sits on the SO (Alpino Customer Type); fall back to the OBM master.
		cust_type = so.get("custom_offline_buyer_customer_type") or obm.get("customer_type") or ""
		channel = channel_of(cust_type) if cust_type else ""

		# Channel / customer-type filters
		if filters.get("channel") and channel != filters.channel:
			continue
		if filters.get("customer_type") and cust_type != filters.customer_type:
			continue

		registered = obm.get("gst_type") == "Registered Business"
		registration_type = "Registered" if registered else "Unregistered"
		gst_no = obm.get("gst_no") if registered else ""
		pl_voucher = obm.get("tally_pl_name") or ""

		bill = _address(so.get("customer_address"))
		ship = _address(so.get("shipping_address_name"))
		# Recover state/city/pincode when the address isn't a structured Address
		# link (e-com orders keep it as free text) by matching the stored text
		# back to the buyer family's Address records.
		if not _has_scp(bill):
			bill.update({k: v for k, v in _resolve_scp_from_text(
				so.customer, so.get("custom_billing_address_text"), addr_cache).items() if v})
		if not _has_scp(ship):
			ship.update({k: v for k, v in _resolve_scp_from_text(
				so.customer, so.get("custom_shipping_address_text"), addr_cache).items() if v})
		# No distinct shipping address at all (common for offline orders) — the
		# order ships to the billing address, so mirror its state/city/pincode.
		if not _has_scp(ship):
			ship["state"] = bill.get("state") or ""
			ship["city"] = bill.get("city") or ""
			ship["pincode"] = bill.get("pincode") or ""
		if not pl_voucher:
			pl_voucher = _voucher_type(registration_type, bill.get("state"))

		# Address lines: e-com orders store the billing/shipping address as free
		# text on the SO (custom_*_address_text) — that's what the user entered, so
		# prefer it. Offline orders leave it blank and use the structured Address
		# record (customer_address / shipping_address_name). State/city/pincode
		# still come from the Address record (free text isn't parsed into those).
		bill_text = (so.get("custom_billing_address_text") or "").strip() \
			or " ".join(filter(None, [bill.get("address_line1"), bill.get("address_line2")]))
		ship_text = (so.get("custom_shipping_address_text") or "").strip() \
			or " ".join(filter(None, [ship.get("address_line1"), ship.get("address_line2")]))
		bill_lines = _split_address(bill_text)
		ship_lines = _split_address(ship_text)

		customer_name = obm.get("tally_buyer_name") or so.get("customer_name") or so.customer

		header = {
			"invoice_no": "",
			"order_date": so.transaction_date,
			"sales_order_id": so.name,
			"customer_po_number": so.get("po_no") or "",
			"customer": customer_name,
			"pl_voucher": pl_voucher,
			"registration_type": registration_type,
			"gst_no": gst_no,
			"mobile_no": obm.get("contact_no") or "",
			"bill_state": bill.get("state") or "",
			"bill_city": bill.get("city") or "",
			"bill_pincode": bill.get("pincode") or "",
			"ship_state": ship.get("state") or "",
			"ship_city": ship.get("city") or "",
			"ship_pincode": ship.get("pincode") or "",
			"tally_warehouse_id": obm.get("custom_tally_warehouse_id") or "T24",
			"channel": channel,
		}
		for i in range(6):
			header[f"bill_addr_{i+1}"] = bill_lines[i]
			header[f"ship_addr_{i+1}"] = ship_lines[i]

		pl_map = _picklist_map(so.name)
		has_pl = bool(pl_map)

		def emit(item_code, fallback_qty, fallback_box, mrp, selling_price, flat, offer, additional, is_priced):
			it = item_info(item_code)
			# UNIT / Box come from the submitted Pick List (picked qty). If the SO has a
			# submitted pick list but this item isn't in it, it wasn't picked → 0; if there
			# is no submitted pick list at all, fall back to the ordered qty/box.
			plr = pl_map.get(item_code)
			if plr:
				unit, box = flt(plr.get("qty")), flt(plr.get("box"))
			else:
				unit = 0 if has_pl else flt(fallback_qty)
				box = 0 if has_pl else flt(fallback_box)

			gst_pct = flt(it.get("custom_gst_percent"))
			gst_rate = 100 + gst_pct
			
			if not is_priced:
				mrp, selling_price = 0, 0
			
			if selling_price:
				final_total = flt(flt(selling_price) * flt(unit) * (1 - flt(additional) / 100.0), 2)
			else:
				final_total = flt(
					flt(mrp) * flt(unit)
					* (1 - flt(flat) / 100.0)
					* (1 - flt(offer) / 100.0)
					* (1 - flt(additional) / 100.0),
					2,
				)
			final_taxable = flt(final_total * 100.0 / gst_rate, 2) if gst_rate else final_total
			igst = flt(final_total - final_taxable, 2)
			cgst = flt(igst / 2.0, 2)

			# EAN/FSN by the order's customer type: Amazon needs EAN, Flipkart needs FSN.
			# Flag "Missing" only for those two when the required code is absent; else blank.
			ean_fsn, ean_fsn_flag = "", ""
			if cust_type == "Amazon":
				ean_fsn = it.get("custom_ean_no") or ""
				if not ean_fsn:
					ean_fsn_flag = "Missing"
			elif cust_type == "Flipkart":
				ean_fsn = it.get("custom_fsn_no") or ""
				if not ean_fsn:
					ean_fsn_flag = "Missing"

			row = dict(header)
			row.update({
				"alpino_sku": it.get("custom_tally_sku") or item_code,
				"ean_fsn": ean_fsn,
				"ean_fsn_flag": ean_fsn_flag,
				"alpino_product_name": it.get("custom_tally_item_name") or it.get("item_name") or item_code,
				"unit": flt(unit),
				"box": flt(box),
				"alpino_mrp": mrp,
				"selling_price": flt(selling_price) or None,
				"flat_discount": flt(flat),
				"additional_discount": flt(offer) or flt(additional),
				"gst_rate": gst_rate,
				"final_taxable": final_taxable if is_priced else 0,
				"cgst": cgst if is_priced else 0,
				"igst": igst if is_priced else 0,
				"final_total": final_total,
				"is_billable": "Yes" if it.get("custom_is_billable") else "No",
			})
			data.append(row)

		# Check if product bundles should be combined/exploded
		combine_product_bundles = True
		val = obm.get("combine_product_bundles")
		if val is not None:
			combine_product_bundles = bool(val)

		# Main item lines (priced)
		if not combine_product_bundles:
			for r in so.items:
				emit(
					r.item_code, r.qty, r.get("custom_box"),
					r.get("custom_customer_mrp"), r.get("custom_selling_price"),
					r.get("custom_flat_discount"), r.get("custom_offer"),
					r.get("custom_additional_discount"), is_priced=True,
				)
		else:
			import math
			from alpinos.sales_order_offline_buyer import get_offline_buyer_item_rate
			from alpinos.sales_order_api import get_customer_item_mrp, get_box_conversion_factor

			exploded_items = {}

			def add_item_to_exploded(item_code, qty, parent_offer, parent_additional):
				mrp_val = 0
				flat_val = 0
				sp_val = 0
				
				res = get_offline_buyer_item_rate(so.customer, item_code)
				if res and flt(res.get("mrp")) > 0:
					mrp_val = flt(res.get("mrp"))
					flat_val = flt(res.get("margin_percent"))
					sp_val = flt(res.get("rate"))
				else:
					res_mrp = get_customer_item_mrp(so.customer, item_code)
					if res_mrp:
						mrp_val = flt(res_mrp)
					else:
						mrp_val = flt(frappe.db.get_value("Item", item_code, "valuation_rate") or 0)
					sp_val = mrp_val * (1 - flat_val / 100.0)

				if item_code not in exploded_items:
					exploded_items[item_code] = {
						"item_code": item_code,
						"qty": 0.0,
						"mrp": mrp_val,
						"flat_discount": flat_val,
						"offer": parent_offer,
						"additional_discount": parent_additional,
						"selling_price": sp_val,
					}
				exploded_items[item_code]["qty"] += qty

			for r in so.items:
				packed = [p for p in (so.get("packed_items") or []) if p.parent_detail_docname == r.name]
				if packed:
					for p in packed:
						add_item_to_exploded(p.item_code, flt(p.qty), flt(r.get("custom_offer") or 0), flt(r.get("custom_additional_discount") or 0))
				else:
					pb_name = frappe.db.get_value("Product Bundle", {"new_item_code": r.item_code}, "name")
					if pb_name:
						pb_items = frappe.db.get_all("Product Bundle Item", filters={"parent": pb_name}, fields=["item_code", "qty"])
						for p in pb_items:
							add_item_to_exploded(p.item_code, flt(p.qty) * flt(r.qty), flt(r.get("custom_offer") or 0), flt(r.get("custom_additional_discount") or 0))
					else:
						add_item_to_exploded(r.item_code, flt(r.qty), flt(r.get("custom_offer") or 0), flt(r.get("custom_additional_discount") or 0))

			for code, item_dict in exploded_items.items():
				cf = flt(get_box_conversion_factor(code))
				box = math.ceil(item_dict["qty"] / cf) if cf else 0
				emit(
					code, item_dict["qty"], box,
					item_dict["mrp"], item_dict["selling_price"],
					item_dict["flat_discount"], item_dict["offer"],
					item_dict["additional_discount"], is_priced=True,
				)

		# Marketing freebies / scheme items / additional-unit (damage) items — selling rate 0
		for r in (so.get("custom_marketing_freebies") or []):
			if r.get("item_code"):
				emit(r.item_code, r.get("qty"), 0, 0, 0, 0, 0, 0, is_priced=False)
		for r in (so.get("custom_scheme_item_table") or []):
			if r.get("item_code"):
				emit(r.item_code, r.get("qty"), 0, 0, 0, 0, 0, 0, is_priced=False)
		for r in (so.get("custom_additional_units_damage_items") or []):
			if r.get("item_code"):
				emit(r.item_code, r.get("qty"), 0, 0, 0, 0, 0, 0, is_priced=False)

	return data
