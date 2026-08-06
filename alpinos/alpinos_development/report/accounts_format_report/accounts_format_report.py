"""Accounts Format Report — Tally-style billing export.

One row per Sales Order line (main items + marketing freebies + scheme items +
additional-unit/damage items, the latter at selling rate 0). Pulls from Sales Order,
Buyer Master, Item Master and the selected billing/shipping Addresses.

Exports to Excel via the standard report view (Menu → Export).
"""

import re

import frappe
from frappe.utils import cint, flt, getdate


# Indian States + UTs — longest-first so "Uttar Pradesh" wins over a bare "Pradesh" match.
_INDIAN_STATES = sorted(
	[
		"Andaman and Nicobar Islands", "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar",
		"Chandigarh", "Chhattisgarh", "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Goa",
		"Gujarat", "Haryana", "Himachal Pradesh", "Jammu and Kashmir", "Jharkhand", "Karnataka",
		"Kerala", "Ladakh", "Lakshadweep", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya",
		"Mizoram", "Nagaland", "Odisha", "Puducherry", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu",
		"Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
	],
	key=len,
	reverse=True,
)


def _scp_from_free_text(text):
	"""Best-effort {state, city, pincode} pulled straight from a free-text address — the SAME
	source as the printed address lines — so the combined city/state/pincode cell stays
	consistent with them even when the text can't be matched to a structured family Address.
	State is matched against the India state/UT list; pincode is the 6-digit token; city is the
	comma part just before the state."""
	t = (text or "").strip()
	if not t:
		return {"state": "", "city": "", "pincode": ""}
	state = ""
	for s in _INDIAN_STATES:
		if re.search(r"\b" + re.escape(s) + r"\b", t, re.IGNORECASE):
			state = s
			break
	m = re.search(r"\b(\d{6})\b", t)
	pincode = m.group(1) if m else ""
	city = ""
	if state:
		parts = [p.strip() for p in t.replace(" - ", ", ").split(",") if p.strip()]
		for i, p in enumerate(parts):
			if re.search(r"\b" + re.escape(state) + r"\b", p, re.IGNORECASE):
				if i > 0:
					city = parts[i - 1]
				break
	return {"state": state, "city": city, "pincode": pincode}


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
	"""Per-(item, source table) picked qty + box from the SUBMITTED Pick List(s) of
	this Sales Order. Keyed by (item_code, source_table) so the same SKU appearing in
	both the Items section and a sample section (Marketing Freebies / Scheme /
	Additional Units) reports each section's qty on its own row — not their sum on
	both. Picked qty uses picked_qty, falling back to qty when picked_qty is 0."""
	rows = frappe.db.sql(
		"""
		SELECT pli.item_code,
			CASE WHEN IFNULL(pli.custom_source_table, '') IN
				('Marketing Freebies', 'Scheme Table', 'Additional Units')
				THEN pli.custom_source_table ELSE 'Items' END AS src,
			SUM(IFNULL(NULLIF(pli.picked_qty, 0), pli.qty)) AS qty,
			SUM(IFNULL(pli.custom_box, 0)) AS box
		FROM `tabPick List Item` pli
		INNER JOIN `tabPick List` pl ON pl.name = pli.parent AND pl.docstatus = 1
		WHERE pl.custom_sales_order_id = %(so)s OR pli.sales_order = %(so)s
		GROUP BY pli.item_code, src
		""",
		{"so": so_name},
		as_dict=True,
	)
	return {(r.item_code, r.src): r for r in rows}


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
				# Owning Buyer Master of the matched address, so GST can follow it.
				"buyer_master": row.get("buyer_master") or "",
			}
	return {}


# ── column definitions ─────────────────────────────────────────────────────
def get_columns():
	def col(label, fn, w=120, ft="Data"):
		return {"label": label, "fieldname": fn, "fieldtype": ft, "width": w}

	cols = [
		col("Invoice No", "invoice_no", 100),
		col("Dispatch Date", "dispatch_date", 95, "Date"),
		col("Sales Order Id", "sales_order_id", 130),
		col("Customer PO Number", "customer_po_number", 130),
		col("Customer", "customer", 180),
		col("P&L Name / Voucher Type", "pl_voucher", 180),
		col("Registration Type", "registration_type", 110),
		col("Alpino SKU", "alpino_sku", 120),
		col("EAN/FSN", "ean_fsn", 130),
		col("EAN/FSN Flag", "ean_fsn_flag", 90),
		col("Alpino Product Name", "alpino_product_name", 220),
		col("UNIT", "unit", 70, "Float"),
		col("Box", "box", 60, "Float"),
		col("Alpino Product MRP", "alpino_mrp", 110, "Currency"),
		col("Flat Discount %", "flat_discount", 90, "Float"),
		col("Additional Discount", "additional_discount", 100, "Float"),
		col("Alpino GST Rate", "gst_rate", 90, "Float"),
		col("Selling Price", "selling_price", 100, "Currency"),
		col("Final Total Value", "final_total", 120, "Currency"),
		col("Final Taxable", "final_taxable", 110, "Currency"),
		col("IGST", "igst", 90, "Currency"),
		col("CGST", "cgst", 90, "Currency"),
		col("Is Billable", "is_billable", 80),
	]
	for i in range(1, 5):
		cols.append(col(f"Bill to Address Line.{i}", f"bill_addr_{i}", 160))
	cols += [
		col("Bill to City + Place Of Supply (Bill to State) + Bill to Pincode + Mobile No", "bill_combined", 260),
		col("Place Of Supply (Bill to State)", "bill_state", 130),
		col("Bill to Pincode", "bill_pincode", 90),
		col("Bill To GST No", "bill_gst_no", 140),
	]
	for i in range(1, 5):
		cols.append(col(f"Ship to Address Line.{i}", f"ship_addr_{i}", 160))
	cols += [
		col("Ship to City + Ship to State + Ship to Pincode + Mobile No", "ship_combined", 260),
		col("Ship to State", "ship_state", 120),
		col("Ship to Pincode", "ship_pincode", 90),
		col("Ship To GST No", "ship_gst_no", 140),
		col("Warehouse", "warehouse", 130),
		col("Tally Warehouse Id", "tally_warehouse_id", 110),
		col("Channel", "channel", 120),
		col("Site Name", "site_name", 130),
		col("Order Date", "order_date", 95, "Date"),
		col("Cash Discount", "cash_discount", 90, "Float"),
	]
	return cols


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), _get_data(filters)


def _buyer_master_scope_customers(filters):
	"""Customers whose Buyer Master matches the parent and/or site-name filters — or
	None when neither is set. Selecting a parent pulls the WHOLE family: the parent
	master plus every child site whose parent_buyer is it."""
	parent = (filters.get("buyer_master_parent") or "").strip()
	site = (filters.get("site_name") or "").strip()
	if not parent and not site:
		return None
	conditions = ["IFNULL(bm.customer, '') <> ''"]
	params = {}
	if parent:
		conditions.append("(bm.name = %(parent)s OR bm.parent_buyer = %(parent)s)")
		params["parent"] = parent
	if site:
		conditions.append("bm.site_name = %(site)s")
		params["site"] = site
	rows = frappe.db.sql(
		"SELECT DISTINCT bm.customer FROM `tabBuyer Master` bm WHERE " + " AND ".join(conditions),
		params, as_dict=True,
	)
	return {r.customer for r in rows}


def _get_data(filters):
	so_filters = {"docstatus": 1}
	if filters.get("from_date") and filters.get("to_date"):
		so_filters["transaction_date"] = ["between", [filters.from_date, filters.to_date]]
	if filters.get("customer"):
		so_filters["customer"] = filters.customer
	if filters.get("sales_order"):
		so_filters["name"] = ["like", "%" + filters.get("sales_order") + "%"]
	if filters.get("order_date"):
		so_filters["transaction_date"] = filters.get("order_date")
	if filters.get("dispatch_date"):
		so_filters["custom_dispatch_date"] = filters.get("dispatch_date")

	# Buyer Master parent / site scoping: restrict the SO scan to the Customers whose
	# Buyer Master is (or sits under) the selected parent and/or carries the selected site.
	allowed_customers = _buyer_master_scope_customers(filters)
	if allowed_customers is not None:
		if not allowed_customers:
			return []
		if filters.get("customer"):
			if filters.customer not in allowed_customers:
				return []
		else:
			so_filters["customer"] = ["in", list(allowed_customers)]

	so_names = frappe.get_all("Sales Order", filters=so_filters, pluck="name", order_by="transaction_date asc, name asc")

	# Only report orders whose Pick List has been SUBMITTED — billing data should
	# appear only once picking is done, not on unpicked/draft orders. docstatus=1
	# also means CANCELLED Pick Lists (docstatus=2) never qualify an order here.
	if so_names:
		picked = set(
			frappe.get_all(
				"Pick List",
				filters={"custom_sales_order_id": ["in", so_names], "docstatus": 1},
				pluck="custom_sales_order_id",
			)
		)
		so_names = [s for s in so_names if s in picked]

	# By default hide orders whose invoice PDF has already been fetched (invoice
	# done). "Show All" reveals them again. Orders with an Invoice No assigned but
	# no PDF yet still show — with the number visible in the Invoice No column.
	if so_names and not cint(filters.get("show_all")):
		pdf_rows = frappe.get_all(
			"Sales Order", filters={"name": ["in", so_names]},
			fields=["name", "custom_invoice_pdf"],
		)
		fetched = {r.name for r in pdf_rows if (r.get("custom_invoice_pdf") or "").strip()}
		so_names = [s for s in so_names if s not in fetched]

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
				 "custom_tally_warehouse_id", "custom_tally_warehouse", "customer_type", "combine_product_bundles"],
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
		# City / State / Pincode MUST come from the same source as the printed address lines.
		# When the SO carries a free-text address (e-com), the lines are that text — so resolve
		# state/city/pincode from the text (matched back to a family Address) and let it WIN
		# over the structured customer_address, which can point at a different/generic site and
		# show the wrong state. Offline orders (no free text) keep the Address record's scp.
		bill_free = (so.get("custom_billing_address_text") or "").strip()
		ship_free = (so.get("custom_shipping_address_text") or "").strip()
		if bill_free:
			bill_scp = _resolve_scp_from_text(so.customer, bill_free, addr_cache) or {}
			free_scp = _scp_from_free_text(bill_free)  # same text as the printed lines
			bill["state"] = bill_scp.get("state") or free_scp.get("state") or ""
			bill["city"] = bill_scp.get("city") or free_scp.get("city") or ""
			bill["pincode"] = bill_scp.get("pincode") or free_scp.get("pincode") or ""
		if ship_free:
			ship_scp = _resolve_scp_from_text(so.customer, ship_free, addr_cache) or {}
			free_scp = _scp_from_free_text(ship_free)
			ship["state"] = ship_scp.get("state") or free_scp.get("state") or ""
			ship["city"] = ship_scp.get("city") or free_scp.get("city") or ""
			ship["pincode"] = ship_scp.get("pincode") or free_scp.get("pincode") or ""
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
		# record (customer_address / shipping_address_name). State/city/pincode were
		# resolved from the same source above, so they stay consistent with these lines.
		bill_text = (so.get("custom_billing_address_text") or "").strip() \
			or " ".join(filter(None, [bill.get("address_line1"), bill.get("address_line2")]))
		ship_text = (so.get("custom_shipping_address_text") or "").strip() \
			or " ".join(filter(None, [ship.get("address_line1"), ship.get("address_line2")]))
		bill_lines = _split_address(bill_text, max_lines=4)
		ship_lines = _split_address(ship_text, max_lines=4)

		customer_name = obm.get("tally_buyer_name") or so.get("customer_name") or so.customer

		# Bill/Ship GST No are read directly from the Sales Order's own GST fields, which
		# the SO save hook keeps site-wise (from custom_offline_buyer_master's gst_no).
		# Fall back to this SO's buyer master gst_no for older orders not yet re-saved.
		bill_gst = so.get("custom_billing_gstin") or so.get("tax_id") or gst_no or ""
		ship_gst = so.get("custom_shipping_gstin") or so.get("custom_billing_gstin") or so.get("tax_id") or gst_no or ""

		mobile = obm.get("contact_no") or ""
		bill_city = bill.get("city") or ""
		bill_state = bill.get("state") or ""
		bill_pincode = bill.get("pincode") or ""
		ship_city = ship.get("city") or ""
		ship_state = ship.get("state") or ""
		ship_pincode = ship.get("pincode") or ""

		header = {
			# Invoice No assigned by the Excel invoice-sync import (blank until then).
			"invoice_no": so.get("custom_invoice_no") or "",
			"dispatch_date": so.get("custom_dispatch_date") or "",
			"sales_order_id": so.name,
			"customer_po_number": so.get("po_no") or "",
			"customer": customer_name,
			"pl_voucher": pl_voucher,
			"registration_type": registration_type,
			# Bill/Ship GST No come from the Buyer Master that owns each chosen address
			# (Address records have no gstin field); blank when that master is Unregistered.
			"bill_gst_no": bill_gst,
			"ship_gst_no": ship_gst,
			"bill_state": bill_state,
			"bill_pincode": bill_pincode,
			# Combined single-cell address (city, state, pincode, mobile) per the Final Format.
			"bill_combined": ", ".join(p for p in (bill_city, bill_state, bill_pincode, mobile) if p),
			"ship_state": ship_state,
			"ship_pincode": ship_pincode,
			"ship_combined": ", ".join(p for p in (ship_city, ship_state, ship_pincode, mobile) if p),
			# Warehouse column comes from the buyer's Buyer Master (Tally Warehouse);
			# fall back to the SO's set_warehouse for buyers that have not set it yet.
			"warehouse": obm.get("custom_tally_warehouse") or so.get("set_warehouse") or "",
			"tally_warehouse_id": obm.get("custom_tally_warehouse_id") or "T24",
			"channel": channel,
			"site_name": so.get("custom_site_name") or "",
			"order_date": so.transaction_date,
		}
		for i in range(4):
			header[f"bill_addr_{i+1}"] = bill_lines[i]
			header[f"ship_addr_{i+1}"] = ship_lines[i]

		pl_map = _picklist_map(so.name)
		has_pl = bool(pl_map)
		# Cash discount %: the Sales Order applies it once, as a % of the grand total
		# (apply_discount_on = "Grand Total"). Being a flat %, applying the SAME % to each
		# line's GST-inclusive amount makes the report's lines sum to the SO grand total
		# after cash discount — just distributed per row so it shows in the table.
		cash_pct = flt(so.get("custom_cash_discount"))

		def emit(item_code, fallback_qty, fallback_box, mrp, selling_price, flat, offer, additional, is_priced, from_picklist=True, source_table="Items"):
			it = item_info(item_code)
			# Every line — billable AND marketing freebies / scheme / damage — is taken from
			# the submitted Pick List (all of them are added to it at creation), with UNIT /
			# Box = picked qty. So the report simply mirrors the submitted pick list: a line
			# not in it (not picked / removed) is dropped; with no submitted pick list at all,
			# fall back to the ordered qty/box. Keyed per source table so a SKU present in
			# both the Items and a sample section reports each section's qty separately.
			if not from_picklist:
				unit, box = flt(fallback_qty), flt(fallback_box)
			else:
				plr = pl_map.get((item_code, source_table))
				if not plr and source_table == "Items":
					# Exploded bundle components can land under a source table other
					# than "Items" depending on how the Pick List was built, so the
					# exact (item, "Items") key can miss and the component would be
					# dropped. Fall back to this item's TOTAL picked qty/box across all
					# sections (a genuinely-unpicked item sums to 0 and still drops).
					tq = sum(flt(v.get("qty")) for (ic, _s), v in pl_map.items() if ic == item_code)
					tb = sum(flt(v.get("box")) for (ic, _s), v in pl_map.items() if ic == item_code)
					if tq:
						plr = {"qty": tq, "box": tb}
				if plr:
					unit, box = flt(plr.get("qty")), flt(plr.get("box"))
				elif has_pl:
					# On the Sales Order but NOT in the submitted Pick List — not
					# picked/dispatched, so it is dropped from the report.
					return
				else:
					unit, box = flt(fallback_qty), flt(fallback_box)

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
			# Deduct the cash discount % per line (freebies are 0, so unaffected).
			if cash_pct:
				final_total = flt(final_total * (1 - cash_pct / 100.0), 2)
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
				"cash_discount": cash_pct,
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
			# NOT combined: show the bundle's COMPONENT items individually (each its
			# own line with its own picked qty), never the combo SKU and never rolled
			# up. The Pick List holds the components, so each shows its picked qty.
			from alpinos.sales_order_offline_buyer import get_offline_buyer_item_rate
			from alpinos.sales_order_api import get_customer_item_mrp, _bundle_components

			def _combo_components(r):
				"""[(component_item, base_qty)] for a bundle SO line, else None — same
				sources as the combine path (native packed items, custom mapping,
				Product Bundle)."""
				packed = [p for p in (so.get("packed_items") or []) if p.parent_detail_docname == r.name]
				oq = flt(r.qty) or 1
				if packed:
					return [(p.item_code, (flt(p.qty) / oq) if oq else flt(p.qty)) for p in packed]
				comps = _bundle_components(r.item_code)
				if comps:
					return [(c.item, flt(c.base_qty)) for c in comps]
				pb_name = frappe.db.get_value("Product Bundle", {"new_item_code": r.item_code}, "name")
				if pb_name:
					pbis = frappe.db.get_all("Product Bundle Item", filters={"parent": pb_name}, fields=["item_code", "qty"])
					return [(p.item_code, flt(p.qty)) for p in pbis]
				return None

			def _component_price(item_code):
				res = get_offline_buyer_item_rate(so.customer, item_code)
				if res and flt(res.get("mrp")) > 0:
					return flt(res.get("mrp")), flt(res.get("margin_percent")), flt(res.get("rate"))
				res_mrp = get_customer_item_mrp(so.customer, item_code)
				mrp = flt(res_mrp) if res_mrp else flt(frappe.db.get_value("Item", item_code, "valuation_rate") or 0)
				return mrp, 0.0, mrp

			# Emit each item at most once (a component / standalone SKU has a single
			# merged Pick List row, so a second emit would double-count its picked qty).
			emitted = set()
			for r in so.items:
				comps = _combo_components(r)
				if comps:
					for (citem, base) in comps:
						if citem in emitted:
							continue
						emitted.add(citem)
						mrp_v, flat_v, sp_v = _component_price(citem)
						emit(
							citem, flt(r.qty) * (base or 1), 0,
							mrp_v, sp_v, flat_v,
							r.get("custom_offer"), r.get("custom_additional_discount"),
							is_priced=True,
						)
				else:
					if r.item_code in emitted:
						continue
					emitted.add(r.item_code)
					emit(
						r.item_code, r.qty, r.get("custom_box"),
						r.get("custom_customer_mrp"), r.get("custom_selling_price"),
						r.get("custom_flat_discount"), r.get("custom_offer"),
						r.get("custom_additional_discount"), is_priced=True,
					)
		else:
			import math
			from alpinos.sales_order_offline_buyer import get_offline_buyer_item_rate
			from alpinos.sales_order_api import get_customer_item_mrp, get_box_conversion_factor, _bundle_components

			exploded_items = {}

			def add_item_to_exploded(item_code, qty, parent_offer, parent_additional, source_row=None):
				if source_row is not None:
					# Plain saved Sales Order line: use its OWN stored pricing verbatim — never
					# re-price from the (possibly since-changed) buyer catalog, so the report
					# matches the SO view/PDF exactly (what the order was confirmed at).
					mrp_val = flt(source_row.get("custom_customer_mrp") or 0)
					flat_val = flt(source_row.get("custom_flat_discount") or 0)
					sp_val = flt(source_row.get("custom_selling_price") or source_row.get("rate") or 0)
				else:
					# Exploded bundle component — no saved SO line of its own, so derive the price
					# from the buyer catalog (fallback to customer MRP / item valuation).
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
					# alpinos custom bundle (custom_is_bundle / custom_product_mapping):
					# no native Packed Items, so explode it the SAME way the Pick List
					# does — otherwise the combo SKU (which isn't in the pick list, only
					# its components are) reports qty 0.
					comps = _bundle_components(r.item_code)
					if comps:
						for c in comps:
							add_item_to_exploded(c.item, flt(r.qty) * flt(c.base_qty), flt(r.get("custom_offer") or 0), flt(r.get("custom_additional_discount") or 0))
					else:
						pb_name = frappe.db.get_value("Product Bundle", {"new_item_code": r.item_code}, "name")
						if pb_name:
							pb_items = frappe.db.get_all("Product Bundle Item", filters={"parent": pb_name}, fields=["item_code", "qty"])
							for p in pb_items:
								add_item_to_exploded(p.item_code, flt(p.qty) * flt(r.qty), flt(r.get("custom_offer") or 0), flt(r.get("custom_additional_discount") or 0))
						else:
							add_item_to_exploded(r.item_code, flt(r.qty), flt(r.get("custom_offer") or 0), flt(r.get("custom_additional_discount") or 0), source_row=r)

			for code, item_dict in exploded_items.items():
				cf = flt(get_box_conversion_factor(code))
				box = math.ceil(item_dict["qty"] / cf) if cf else 0
				emit(
					code, item_dict["qty"], box,
					item_dict["mrp"], item_dict["selling_price"],
					item_dict["flat_discount"], item_dict["offer"],
					item_dict["additional_discount"], is_priced=True,
				)

		# Marketing freebies / scheme items / additional-unit (damage) items — selling
		# rate 0, qty taken straight from the Sales Order (not the pick list, which
		# doesn't carry these free lines — they would otherwise report qty 0).
		for r in (so.get("custom_marketing_freebies") or []):
			if r.get("item_code"):
				emit(r.item_code, r.get("qty"), 0, 0, 0, 0, 0, 0, is_priced=False, from_picklist=True, source_table="Marketing Freebies")
		for r in (so.get("custom_scheme_item_table") or []):
			if r.get("item_code"):
				emit(r.item_code, r.get("qty"), 0, 0, 0, 0, 0, 0, is_priced=False, from_picklist=True, source_table="Scheme Table")
		for r in (so.get("custom_additional_units_damage_items") or []):
			if r.get("item_code"):
				emit(r.item_code, r.get("qty"), 0, 0, 0, 0, 0, 0, is_priced=False, from_picklist=True, source_table="Additional Units")

	return data
