"""Accounts Format Report — Tally-style billing export.

One row per Sales Order line (main items + marketing freebies + scheme items +
additional-unit/damage items, the latter at selling rate 0). Pulls from Sales Order,
Buyer Master, Item Master and the selected billing/shipping Addresses.

Exports to Excel via the standard report view (Menu → Export).
"""

import re

import frappe
from frappe.utils import cint, flt, formatdate, getdate


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
		WHERE (pl.custom_sales_order_id = %(so)s OR pli.sales_order = %(so)s)
			AND IFNULL(pli.custom_bundle_parent, '') = ''
		GROUP BY pli.item_code, src
		""",
		{"so": so_name},
		as_dict=True,
	)
	return {(r.item_code, r.src): r for r in rows}


def _combo_picklist_map(so_name):
	"""Per-(component item, combo SKU) picked qty + box for COMBO-component Pick List rows
	(tagged with custom_bundle_parent). Kept apart from the standalone 'Items' picks so a combo
	line reports its OWN picked qty and short-pick, not a total pooled with a standalone line."""
	rows = frappe.db.sql(
		"""
		SELECT pli.item_code, pli.custom_bundle_parent AS combo,
			SUM(IFNULL(NULLIF(pli.picked_qty, 0), pli.qty)) AS qty,
			SUM(IFNULL(pli.custom_box, 0)) AS box
		FROM `tabPick List Item` pli
		INNER JOIN `tabPick List` pl ON pl.name = pli.parent AND pl.docstatus = 1
		WHERE (pl.custom_sales_order_id = %(so)s OR pli.sales_order = %(so)s)
			AND IFNULL(pli.custom_bundle_parent, '') <> ''
		GROUP BY pli.item_code, pli.custom_bundle_parent
		""",
		{"so": so_name},
		as_dict=True,
	)
	return {(r.item_code, r.combo): r for r in rows}


def _pl_header(so_name):
	"""Dispatch header info from the SUBMITTED Pick List(s) of this Sales Order:
	Transporter, PL PO No, Gate No, Total Box (sticker grand total) and the latest
	PL / Delivery Note modified datetime — one value set per order."""
	pls = frappe.db.sql(
		"""
		SELECT custom_transporter, custom_po_no, custom_gate, custom_total_box, modified
		FROM `tabPick List`
		WHERE custom_sales_order_id = %(so)s AND docstatus = 1
		ORDER BY modified DESC
		""",
		{"so": so_name}, as_dict=True,
	)
	if not pls:
		return {}
	# Total Box = the sticker grand total across the SO's submitted Pick List(s). The
	# Pick List stores it on custom_total_box (item boxes + combined sample boxes),
	# computed by the SAME combine_sample_boxes() the sticker generator uses.
	total_box = sum(flt(p.custom_total_box) for p in pls)
	# Latest Delivery Note modified for this SO (drafts + submitted), so "PL / DN
	# Updated On" reflects a post-dispatch DN edit too, not just the Pick List.
	dn_mod = frappe.db.sql(
		"""
		SELECT MAX(dn.modified) AS m
		FROM `tabDelivery Note` dn
		INNER JOIN `tabDelivery Note Item` dni ON dni.parent = dn.name
		WHERE dni.against_sales_order = %(so)s AND dn.docstatus < 2
		""",
		{"so": so_name},
	)
	updated_on = pls[0].modified
	if dn_mod and dn_mod[0][0] and dn_mod[0][0] > updated_on:
		updated_on = dn_mod[0][0]
	# Gate No is shown labeled in the cell, e.g. "Gate No. : G-3" (raw "G-3" from the PL).
	_gate = (pls[0].custom_gate or "").strip()
	return {
		"transporter": pls[0].custom_transporter or "",
		"pl_po_no": pls[0].custom_po_no or "",
		"gate_no": ("Gate No. : " + _gate) if _gate else "",
		"total_box": total_box,
		"pl_dn_updated_on": updated_on,
	}


def _combined_addr(city, state, pincode, mobile, pin_label):
	"""Labeled single-cell address per the Final Format:
	'City - <city> , State - <state> , <pin_label> - <pincode> , (M) - <mobile>'."""
	parts = []
	if city:
		parts.append(f"City - {city}")
	if state:
		parts.append(f"State - {state}")
	if pincode:
		parts.append(f"{pin_label} - {pincode}")
	if mobile:
		parts.append(f"(M) - {mobile}")
	return " , ".join(parts)


def _scp_for_site(site_name):
	"""{city, state, pincode} from the Buyer Master Address child row for a site — the
	STRUCTURED source, correct even when the free-text address is misspelled (e.g. a
	'Maharastra' typo that the state-name matcher can't resolve). Used only as a fallback
	when the address-line parsing leaves city/state/pincode blank."""
	if not site_name:
		return {}
	rows = frappe.db.sql(
		"""
		SELECT city, state, pincode
		FROM `tabBuyer Address`
		WHERE site_name = %s AND (IFNULL(city,'') <> '' OR IFNULL(state,'') <> '')
		LIMIT 1
		""",
		site_name, as_dict=True,
	)
	return dict(rows[0]) if rows else {}


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

	# Column order follows the client's Final Format (Accounts_Format ... Final_Formate).
	cols = [
		col("Invoice No", "invoice_no", 100),
		# Dispatch / Order dates are emitted as dd-MM-yyyy TEXT (not Date) so the Excel
		# export shows the same format as the on-screen report (a Date value exports as a
		# datetime like "2026-08-12 00:00:00").
		col("Dispatch Date", "dispatch_date", 95),
		col("Sales Order Id", "sales_order_id", 130),
		col("Customer PO Number", "customer_po_number", 130),
		col("Customer", "customer", 180),
		col("Site Name", "site_name", 130),
		col("Alpino SKU", "alpino_sku", 120),
		col("Alpino Product Name", "alpino_product_name", 220),
		col("UNIT", "unit", 70, "Float"),
		col("Box", "box", 60, "Float"),
		col("Flat Discount %", "flat_discount", 90, "Float"),
		col("Final Total Value", "final_total", 120, "Currency"),
		col("Final Taxable", "final_taxable", 110, "Currency"),
		col("IGST", "igst", 90, "Currency"),
		col("CGST", "cgst", 90, "Currency"),
		col("Is Billable", "is_billable", 80),
		col("Less Qty", "less_qty", 80, "Float"),
		col("Less Qty Amount", "less_qty_amount", 100, "Currency"),
	]
	for i in range(1, 4):
		cols.append(col(f"Bill to Address Line.{i}", f"bill_addr_{i}", 160))
	cols += [
		col("Bill to City + Place Of Supply (Bill to State) + Bill to Pincode + Mobile No", "bill_combined", 260),
		col("Place Of Supply (Bill to State)", "bill_state", 130),
		col("Bill to Pincode", "bill_pincode", 90),
		col("Bill To GST No", "bill_gst_no", 140),
	]
	for i in range(1, 4):
		cols.append(col(f"Ship to Address Line.{i}", f"ship_addr_{i}", 160))
	cols += [
		col("Ship to City + Ship to State + Ship to Pincode + Mobile No", "ship_combined", 260),
		col("Ship to State", "ship_state", 120),
		col("Ship to Pincode", "ship_pincode", 90),
		col("Ship To GST No", "ship_gst_no", 140),
		col("Warehouse", "warehouse", 130),
		col("Tally Warehouse Id", "tally_warehouse_id", 110),
		col("EAN/FSN", "ean_fsn", 130),
		col("EAN/FSN Flag", "ean_fsn_flag", 90),
		col("Alpino Product MRP", "alpino_mrp", 110, "Currency"),
		col("Additional Discount", "additional_discount", 100, "Float"),
		col("Alpino GST Rate", "gst_rate", 90, "Float"),
		col("Selling Price", "selling_price", 100, "Currency"),
		col("Channel", "channel", 120),
		col("Order Date", "order_date", 95),
		col("P&L Name / Voucher Type", "pl_voucher", 180),
		col("Registration Type", "registration_type", 110),
		col("Offer Discount", "offer_discount", 100, "Float"),
		col("Cash Discount", "cash_discount", 90, "Float"),
		col("Selling Price GST Excl. Flag", "gst_excl_flag", 130),
		col("Item Type", "item_type", 120),
		col("Transporter", "transporter", 140),
		col("Total Box", "total_box", 80, "Float"),
		col("PL PO NO", "pl_po_no", 120),
		col("Gate No", "gate_no", 80),
		col("PL / DN Updated On", "pl_dn_updated_on", 140, "Datetime"),
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
	# Dispatch Date is the primary date filter (Order Date From/To removed).
	if filters.get("from_date") and filters.get("to_date"):
		so_filters["custom_dispatch_date"] = ["between", [filters.from_date, filters.to_date]]
	if filters.get("customer"):
		so_filters["customer"] = filters.customer
	if filters.get("sales_order"):
		so_filters["name"] = ["like", "%" + filters.get("sales_order") + "%"]

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

	so_names = frappe.get_all("Sales Order", filters=so_filters, pluck="name", order_by="custom_dispatch_date asc, name asc")

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
				 "custom_fsn_no", "custom_is_billable", "valuation_rate", "custom_gst_percent",
				 "item_group"],
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
		# Buyer-wise "Round Off Per Unit Amount": report the rounded per-unit selling price.
		_round_pu = bool(frappe.db.get_value("Buyer Master", {"customer": so.customer}, "round_off_per_unit"))
		# GST-EXCLUSIVE buyer: SO value is the taxable; the report adds GST separately.
		_gst_excl = int(so.get("custom_gst_exclusive_buyer") or 0)
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
		# Structured fallback: when city/state/pincode couldn't be resolved from the address
		# text (e.g. a misspelled state like "Maharastra"), fill them from the SITE's Buyer
		# Master Address child row (structured, correct). Only fills blanks — never overrides
		# a value already resolved from the printed address lines.
		site_scp = _scp_for_site(so.get("custom_site_name"))
		if site_scp:
			for _d in (bill, ship):
				_d["state"] = _d.get("state") or site_scp.get("state") or ""
				_d["city"] = _d.get("city") or site_scp.get("city") or ""
				_d["pincode"] = _d.get("pincode") or site_scp.get("pincode") or ""
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
		bill_lines = _split_address(bill_text, max_lines=3)
		ship_lines = _split_address(ship_text, max_lines=3)

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
			# dd-MM-yyyy text so the export matches the on-screen format.
			"dispatch_date": formatdate(so.get("custom_dispatch_date"), "dd-MM-yyyy") if so.get("custom_dispatch_date") else "",
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
			# Combined single-cell address (labeled: City / State / Pincode / Mobile) per Final Format.
			"bill_combined": _combined_addr(bill_city, bill_state, bill_pincode, mobile, "Bill To Pincode"),
			"ship_state": ship_state,
			"ship_pincode": ship_pincode,
			"ship_combined": _combined_addr(ship_city, ship_state, ship_pincode, mobile, "Ship To Pincode"),
			# Warehouse column comes from the buyer's Buyer Master (Tally Warehouse);
			# fall back to the SO's set_warehouse for buyers that have not set it yet.
			"warehouse": obm.get("custom_tally_warehouse") or so.get("set_warehouse") or "",
			"tally_warehouse_id": obm.get("custom_tally_warehouse_id") or "T24",
			"channel": channel,
			"site_name": so.get("custom_site_name") or "",
			"order_date": formatdate(so.transaction_date, "dd-MM-yyyy") if so.transaction_date else "",
			# GST-exclusive buyer flag (whole SO) — shown per Final Format.
			"gst_excl_flag": "Yes" if _gst_excl else "",
			# Less Qty / Less Qty Amount: computed per line in emit() (ordered - dispatched qty, valued at GST-inclusive selling price).
			"less_qty": None,
			"less_qty_amount": None,
		}
		# Dispatch header (Transporter / PL PO / Gate / Total Box / PL·DN Updated On).
		header.update(_pl_header(so.name))
		for i in range(3):
			header[f"bill_addr_{i+1}"] = bill_lines[i]
			header[f"ship_addr_{i+1}"] = ship_lines[i]

		pl_map = _picklist_map(so.name)
		combo_pl_map = _combo_picklist_map(so.name)
		has_pl = bool(pl_map) or bool(combo_pl_map)
		# Cash discount %: the Sales Order applies it once, as a % of the grand total
		# (apply_discount_on = "Grand Total"). Being a flat %, applying the SAME % to each
		# line's GST-inclusive amount makes the report's lines sum to the SO grand total
		# after cash discount — just distributed per row so it shows in the table.
		cash_pct = flt(so.get("custom_cash_discount"))

		def emit(item_code, fallback_qty, fallback_box, mrp, selling_price, flat, offer, additional, is_priced, from_picklist=True, source_table="Items", ordered_qty=None):
			it = item_info(item_code)
			if _round_pu and selling_price:
				selling_price = round(flt(selling_price))
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
				base_line = flt(flt(selling_price) * flt(unit) * (1 - flt(additional) / 100.0), 2)
			else:
				base_line = flt(
					flt(mrp) * flt(unit)
					* (1 - flt(flat) / 100.0)
					* (1 - flt(offer) / 100.0)
					* (1 - flt(additional) / 100.0),
					2,
				)
			# Deduct the cash discount % per line (freebies are 0, so unaffected).
			if cash_pct:
				base_line = flt(base_line * (1 - cash_pct / 100.0), 2)

			if _gst_excl:
				# GST-EXCLUSIVE buyer: the SO line value IS the taxable; add GST on top.
				# Final Total = Taxable + Applicable GST% (no inclusive back-calculation,
				# no extra rounding of the taxable).
				final_taxable = base_line
				igst = flt(final_taxable * gst_pct / 100.0, 2)
				cgst = flt(igst / 2.0, 2)
				final_total = flt(final_taxable + igst, 2)
			else:
				final_total = base_line
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

			# Less Qty (Final Format): ordered qty - dispatched (picked) qty, valued at the
			# GST-inclusive selling price. Selling price is GST-exclusive only for a
			# GST-exclusive buyer, so gross it up with GST% there. No shortfall -> blank.
			less_qty = flt(flt(ordered_qty) - flt(unit), 3) if ordered_qty is not None else 0
			if less_qty and selling_price:
				sp_incl = flt(selling_price) * (1 + gst_pct / 100.0) if _gst_excl else flt(selling_price)
				less_qty_amount = flt(less_qty * sp_incl, 2)
			else:
				less_qty_amount = None
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
				# Offer and Additional are now distinct columns in the Final Format.
				"offer_discount": flt(offer),
				"additional_discount": flt(additional),
				"item_type": it.get("item_group") or "",
				"cash_discount": cash_pct,
				"gst_rate": gst_rate,
				"final_taxable": final_taxable if is_priced else 0,
				"cgst": cgst if is_priced else 0,
				"igst": igst if is_priced else 0,
				"final_total": final_total,
				"is_billable": "Yes" if it.get("custom_is_billable") else "No",
				"less_qty": less_qty or None,
				"less_qty_amount": less_qty_amount,
			})
			data.append(row)

		# Check if product bundles should be combined/exploded
		combine_product_bundles = True
		val = obm.get("combine_product_bundles")
		if val is not None:
			combine_product_bundles = bool(val)

		# ── Main item lines (priced) ────────────────────────────────────────
		# ONE ROW PER SALES ORDER LINE's own contribution — a combo's components are
		# never merged into a standalone line of the same SKU. For 2 x ITEMC (a combo of
		# 2 x ITEMA + 3 x ITEMB) ordered alongside 1 x ITEMA:
		#   Combine Product Bundles ON  -> ITEMA 4, ITEMB 6 (the combo, exploded), ITEMA 1
		#   Combine Product Bundles OFF -> ITEMC 2, ITEMA 1  (as entered, like the PDF —
		#       utils.get_combined_items returns doc.items untouched when the flag is off)
		#
		# Qty still follows the submitted Pick List, but it has to be allocated back onto
		# the SO lines first: the Pick List only ever holds EXPLODED components, so a combo
		# SKU is never in it by name, and a component that is ALSO ordered standalone sits
		# in ONE merged picked row shared by both lines. Walking the lines in order and
		# consuming picked stock as we go (a combo unit eats base_qty of each component)
		# keeps the lines from double-counting that shared row, and still shrinks or drops
		# a line that was short-picked / removed.
		import math
		from alpinos.sales_order_offline_buyer import get_offline_buyer_item_rate
		from alpinos.sales_order_api import get_customer_item_mrp, get_box_conversion_factor, _bundle_components

		def _combo_components(r):
			"""[(component_item, qty_per_combo_unit)] for a bundle SO line, else None —
			native packed items, the alpinos custom mapping, or a Product Bundle."""
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
			"""(mrp, flat%, selling price) for an exploded component from the buyer
			catalog — it has no saved Sales Order line of its own to price it from."""
			res = get_offline_buyer_item_rate(so.customer, item_code)
			if res and flt(res.get("mrp")) > 0:
				return flt(res.get("mrp")), flt(res.get("margin_percent")), flt(res.get("rate"))
			res_mrp = get_customer_item_mrp(so.customer, item_code)
			mrp = flt(res_mrp) if res_mrp else flt(frappe.db.get_value("Item", item_code, "valuation_rate") or 0)
			return mrp, 0.0, mrp

		# Picked-but-not-yet-allocated stock per item, from the submitted Pick List.
		avail, box_pool = {}, {}
		for (ic, src), v in pl_map.items():
			if src == "Items":
				avail[ic] = flt(avail.get(ic, 0.0)) + flt(v.get("qty"))
				box_pool[ic] = flt(box_pool.get(ic, 0.0)) + flt(v.get("box"))
		for (ic, _src), v in pl_map.items():
			# Exploded components can land under a source table other than "Items"
			# depending on how the Pick List was built; fall back to the item's total
			# picked qty when it has no "Items" row at all (same fallback as emit()).
			if ic not in avail:
				avail[ic] = sum(flt(x.get("qty")) for (c, _s), x in pl_map.items() if c == ic)
				box_pool[ic] = sum(flt(x.get("box")) for (c, _s), x in pl_map.items() if c == ic)
		picked_total = dict(avail)  # snapshot, before the lines consume it

		def _take(item_code, want):
			"""Consume up to `want` of item_code from the unallocated picked stock."""
			got = min(flt(avail.get(item_code, 0.0)), flt(want))
			if got > 0:
				avail[item_code] = flt(avail.get(item_code, 0.0)) - got
			return got

		def _box_share(item_code, units):
			"""This line's slice of the item's PICKED boxes, pro rata on units. The Pick
			List merges a component shared by a combo line and a standalone line into one
			row, so its box count has to be split the same way its qty is — a line that
			takes the whole picked qty keeps the whole box count."""
			tot = flt(picked_total.get(item_code, 0.0))
			if not tot or not flt(units):
				return 0.0
			return flt(round(flt(box_pool.get(item_code, 0.0)) * flt(units) / tot))

		for r in so.items:
			ordered = flt(r.qty)
			comps = _combo_components(r)
			if not has_pl:
				picked = ordered
			elif comps:
				# This combo's OWN picked qty, from Pick List rows tagged with this combo
				# (custom_bundle_parent) - the short-pick stays on the combo line, not the loose line.
				picked = ordered
				for (citem, per) in comps:
					per = flt(per) or 1
					cp = combo_pl_map.get((citem, r.item_code))
					comp_picked = flt(cp.get("qty")) if cp else 0.0
					picked = min(picked, math.floor(comp_picked / per))
				picked = max(flt(picked), 0.0)
			else:
				picked = _take(r.item_code, ordered)

			if has_pl and not picked:
				# Nothing of this line survived in the Pick List — not dispatched.
				continue

			if comps and combine_product_bundles:
				# Combined: this combo line explodes into its own component rows, priced
				# from the buyer catalog. Kept separate from any standalone line of the
				# same SKU, which reports its own qty at its own confirmed price.
				for (citem, per) in comps:
					cqty = picked * (flt(per) or 1)
					if not cqty:
						continue
					if has_pl:
						cp = combo_pl_map.get((citem, r.item_code))
						cbox = flt(cp.get("box")) if cp else 0.0
					else:
						cf = flt(get_box_conversion_factor(citem))
						cbox = math.ceil(cqty / cf) if cf else 0
					mrp_v, flat_v, sp_v = _component_price(citem)
					emit(
						citem, cqty, cbox,
						mrp_v, sp_v, flat_v,
						r.get("custom_offer"), r.get("custom_additional_discount"),
						is_priced=True, from_picklist=False,
						ordered_qty=ordered * (flt(per) or 1),
					)
				continue

			# The line itself: a plain item (either mode), or the combo SKU as entered
			# when Combine Product Bundles is off — with its own stored pricing. A combo
			# SKU has no picked row of its own, so its Box is its components' picked boxes.
			if not has_pl:
				box = flt(r.get("custom_box"))
			elif comps:
				box = sum(_box_share(citem, picked * (flt(per) or 1)) for (citem, per) in comps)
			else:
				box = _box_share(r.item_code, picked)

			emit(
				r.item_code, picked, box,
				r.get("custom_customer_mrp"),
				r.get("custom_selling_price") or r.get("rate"),
				r.get("custom_flat_discount"), r.get("custom_offer"),
				r.get("custom_additional_discount"), is_priced=True,
				from_picklist=False,
				ordered_qty=ordered,
			)

		# Marketing freebies / scheme items / additional-unit (damage) items — selling
		# rate 0, qty taken straight from the Sales Order (not the pick list, which
		# doesn't carry these free lines — they would otherwise report qty 0).
		for r in (so.get("custom_marketing_freebies") or []):
			if r.get("item_code"):
				emit(r.item_code, r.get("qty"), 0, 0, 0, 0, 0, 0, is_priced=False, from_picklist=True, source_table="Marketing Freebies", ordered_qty=r.get("qty"))
		for r in (so.get("custom_scheme_item_table") or []):
			if r.get("item_code"):
				emit(r.item_code, r.get("qty"), 0, 0, 0, 0, 0, 0, is_priced=False, from_picklist=True, source_table="Scheme Table", ordered_qty=r.get("qty"))
		for r in (so.get("custom_additional_units_damage_items") or []):
			if r.get("item_code"):
				emit(r.item_code, r.get("qty"), 0, 0, 0, 0, 0, 0, is_priced=False, from_picklist=True, source_table="Additional Units", ordered_qty=r.get("qty"))

	return data
