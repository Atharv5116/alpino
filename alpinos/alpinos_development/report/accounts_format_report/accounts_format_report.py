"""Tally-style billing export, one row per Sales Order line."""

import re

import frappe
from frappe.utils import cint, flt, formatdate, getdate


# Indian States + UTs, longest-first so "Uttar Pradesh" wins over a bare "Pradesh".
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
	"""Best-effort {state, city, pincode} parsed from a free-text address."""
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
	"""Picked qty + box per (item, source table) from the submitted Pick List(s).

	Keying by source table keeps a SKU that appears in both the Items section and a
	sample section reporting each section's qty on its own row.
	"""
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
	"""Picked qty + box per (component item, combo SKU) for combo-component Pick List rows.

	Kept apart from the standalone 'Items' picks so a combo line reports its own picked qty.
	"""
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
	"""Dispatch header (transporter, PO no, gate, total box/weight, updated-on) from the submitted Pick List(s)."""
	pls = frappe.db.sql(
		"""
		SELECT custom_transporter, custom_po_no, custom_gate, custom_total_box,
		       custom_gross_weight, modified
		FROM `tabPick List`
		WHERE custom_sales_order_id = %(so)s AND docstatus = 1
		ORDER BY modified DESC
		""",
		{"so": so_name}, as_dict=True,
	)
	if not pls:
		return {}
	# Sticker grand total (custom_total_box) across the SO's submitted Pick List(s).
	total_box = sum(flt(p.custom_total_box) for p in pls)
	total_weight = sum(flt(p.custom_gross_weight) for p in pls)
	# Latest Delivery Note modified for this SO, so a post-dispatch DN edit updates the cell too.
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
	_gate = (pls[0].custom_gate or "").strip()
	_po = pls[0].custom_po_no or ""
	_transporter = pls[0].custom_transporter or ""
	# Box count is whole; show it without a trailing ".0".
	_box_str = str(int(total_box)) if float(total_box).is_integer() else ("%g" % total_box)
	terms_of_delivery = (
		"PL PO No: {po} / Total Box: {box} / Total Weight: {wt} / Transporter: {tr}".format(
			po=_po, box=_box_str, wt="%.2f" % flt(total_weight), tr=_transporter
		)
	)
	return {
		"transporter": _transporter,
		"pl_po_no": _po,
		"gate_no": ("Gate No. : " + _gate) if _gate else "",
		"total_box": total_box,
		"total_weight": total_weight,
		"pl_dn_updated_on": updated_on,
		"terms_of_delivery": terms_of_delivery,
	}


def _combined_addr(city, state, pincode, mobile, pin_label):
	"""Labeled single-cell address per the Final Format."""
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
	"""{city, state, pincode} from the Buyer Master Address child row for a site (structured fallback)."""
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
	"""Normalize an address string for matching: lowercase, collapse whitespace, drop a trailing '(type)' suffix."""
	s = " ".join((text or "").replace("\n", " ").replace("\r", " ").split()).lower()
	if "(" in s:  # the family-dropdown label carries a "(type)" suffix
		s = s.split("(", 1)[0]
	return s.strip().strip(",").strip()


def _resolve_scp_from_text(customer, text, cache):
	"""Recover {state, city, pincode} for a free-text address by matching it to a family Address record."""
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


def get_columns():
	def col(label, fn, w=120, ft="Data"):
		return {"label": label, "fieldname": fn, "fieldtype": ft, "width": w}

	# Column order follows the client's Final Format.
	cols = [
		col("Invoice No", "invoice_no", 100),
		# Dispatch / Order dates are emitted as dd-MM-yyyy text so the export matches the screen.
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
		col("Terms of Delivery", "terms_of_delivery", 340),
	]
	return cols


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), _get_data(filters)


def _buyer_master_scope_customers(filters):
	"""Customers whose Buyer Master matches the parent and/or site-name filters, or None when neither is set."""
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

	# Buyer Master parent / site scoping restricts the SO scan to matching customers.
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

	# Only report orders whose Pick List is submitted (docstatus=1).
	if so_names:
		picked = set(
			frappe.get_all(
				"Pick List",
				filters={"custom_sales_order_id": ["in", so_names], "docstatus": 1},
				pluck="custom_sales_order_id",
			)
		)
		so_names = [s for s in so_names if s in picked]

	# Hide orders whose invoice PDF is already fetched, unless "Show All" is set.
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
	addr_cache = {}  # customer: family Address rows, for free-text scp recovery
	for so_name in so_names:
		so = frappe.get_doc("Sales Order", so_name)
		# Buyer-wise "Round Off Per Unit Amount".
		_round_pu = bool(frappe.db.get_value("Buyer Master", {"customer": so.customer}, "round_off_per_unit"))
		# GST-exclusive buyer: SO value is the taxable; the report adds GST separately.
		_gst_excl = int(so.get("custom_gst_exclusive_buyer") or 0)
		obm = obm_info(so.customer)
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
		# City/State/Pincode come from the same source as the printed lines. For a free-text
		# (e-com) address, resolve them from the text (matched back to a family Address) and let
		# that win over the structured customer_address. Priority: family-matched, then the
		# site's structured Buyer Master Address, then the heuristic free-text parse.
		bill_free = (so.get("custom_billing_address_text") or "").strip()
		ship_free = (so.get("custom_shipping_address_text") or "").strip()
		site_scp = _scp_for_site(so.get("custom_site_name")) or {}
		if bill_free:
			bill_scp = _resolve_scp_from_text(so.customer, bill_free, addr_cache) or {}
			free_scp = _scp_from_free_text(bill_free)
			bill["state"] = bill_scp.get("state") or site_scp.get("state") or free_scp.get("state") or ""
			bill["city"] = bill_scp.get("city") or site_scp.get("city") or free_scp.get("city") or ""
			bill["pincode"] = bill_scp.get("pincode") or site_scp.get("pincode") or free_scp.get("pincode") or ""
		if ship_free:
			ship_scp = _resolve_scp_from_text(so.customer, ship_free, addr_cache) or {}
			free_scp = _scp_from_free_text(ship_free)
			ship["state"] = ship_scp.get("state") or site_scp.get("state") or free_scp.get("state") or ""
			ship["city"] = ship_scp.get("city") or site_scp.get("city") or free_scp.get("city") or ""
			ship["pincode"] = ship_scp.get("pincode") or site_scp.get("pincode") or free_scp.get("pincode") or ""
		# Structured fallback for offline orders or anything still blank.
		if site_scp:
			for _d in (bill, ship):
				_d["state"] = _d.get("state") or site_scp.get("state") or ""
				_d["city"] = _d.get("city") or site_scp.get("city") or ""
				_d["pincode"] = _d.get("pincode") or site_scp.get("pincode") or ""
		# No distinct shipping address: mirror the billing state/city/pincode.
		if not _has_scp(ship):
			ship["state"] = bill.get("state") or ""
			ship["city"] = bill.get("city") or ""
			ship["pincode"] = bill.get("pincode") or ""
		if not pl_voucher:
			pl_voucher = _voucher_type(registration_type, bill.get("state"))

		# Address lines: prefer the SO's free-text address (e-com), else the structured Address record.
		bill_text = (so.get("custom_billing_address_text") or "").strip() \
			or " ".join(filter(None, [bill.get("address_line1"), bill.get("address_line2")]))
		ship_text = (so.get("custom_shipping_address_text") or "").strip() \
			or " ".join(filter(None, [ship.get("address_line1"), ship.get("address_line2")]))
		bill_lines = _split_address(bill_text, max_lines=3)
		ship_lines = _split_address(ship_text, max_lines=3)

		customer_name = obm.get("tally_buyer_name") or so.get("customer_name") or so.customer

		# Bill/Ship GST No come from the SO's own GST fields; fall back to the buyer master for older orders.
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
			# Invoice No assigned by the invoice-sync import; blank until then.
			"invoice_no": so.get("custom_invoice_no") or "",
			"dispatch_date": formatdate(so.get("custom_dispatch_date"), "dd-MM-yyyy") if so.get("custom_dispatch_date") else "",
			"sales_order_id": so.name,
			"customer_po_number": so.get("po_no") or "",
			"customer": customer_name,
			"pl_voucher": pl_voucher,
			"registration_type": registration_type,
			"bill_gst_no": bill_gst,
			"ship_gst_no": ship_gst,
			"bill_state": bill_state,
			"bill_pincode": bill_pincode,
			"bill_combined": _combined_addr(bill_city, bill_state, bill_pincode, mobile, "Bill To Pincode"),
			"ship_state": ship_state,
			"ship_pincode": ship_pincode,
			"ship_combined": _combined_addr(ship_city, ship_state, ship_pincode, mobile, "Ship To Pincode"),
			# Warehouse from the Buyer Master's Tally Warehouse, else the SO's set_warehouse.
			"warehouse": obm.get("custom_tally_warehouse") or so.get("set_warehouse") or "",
			"tally_warehouse_id": obm.get("custom_tally_warehouse_id") or "T24",
			"channel": channel,
			"site_name": so.get("custom_site_name") or "",
			"order_date": formatdate(so.transaction_date, "dd-MM-yyyy") if so.transaction_date else "",
			"gst_excl_flag": "Yes" if _gst_excl else "",
			# Less Qty / Less Qty Amount are computed per line in emit().
			"less_qty": None,
			"less_qty_amount": None,
		}
		header.update(_pl_header(so.name))
		for i in range(3):
			header[f"bill_addr_{i+1}"] = bill_lines[i]
			header[f"ship_addr_{i+1}"] = ship_lines[i]

		pl_map = _picklist_map(so.name)
		combo_pl_map = _combo_picklist_map(so.name)
		has_pl = bool(pl_map) or bool(combo_pl_map)
		# Cash discount % is a flat % of the grand total; applying it per line keeps the
		# rows summing to the SO grand total after cash discount.
		cash_pct = flt(so.get("custom_cash_discount"))

		def emit(item_code, fallback_qty, fallback_box, mrp, selling_price, flat, offer, additional, is_priced, from_picklist=True, source_table="Items", ordered_qty=None):
			it = item_info(item_code)
			if _round_pu and selling_price:
				selling_price = round(flt(selling_price))
			# UNIT/Box mirror the submitted Pick List: a line not in it is dropped; with no
			# submitted pick list at all, fall back to the ordered qty/box.
			if not from_picklist:
				unit, box = flt(fallback_qty), flt(fallback_box)
			else:
				plr = pl_map.get((item_code, source_table))
				if not plr and source_table == "Items":
					# Exploded components can land under a source table other than "Items",
					# so fall back to this item's total picked qty/box across all sections.
					tq = sum(flt(v.get("qty")) for (ic, _s), v in pl_map.items() if ic == item_code)
					tb = sum(flt(v.get("box")) for (ic, _s), v in pl_map.items() if ic == item_code)
					if tq:
						plr = {"qty": tq, "box": tb}
				if plr:
					unit, box = flt(plr.get("qty")), flt(plr.get("box"))
				elif has_pl:
					# On the SO but not in the submitted Pick List: not dispatched, drop it.
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
			# Deduct the cash discount % per line (freebies are 0, unaffected).
			if cash_pct:
				base_line = flt(base_line * (1 - cash_pct / 100.0), 2)

			if _gst_excl:
				# GST-exclusive buyer: the SO line value is the taxable; add GST on top.
				final_taxable = base_line
				igst = flt(final_taxable * gst_pct / 100.0, 2)
				cgst = flt(igst / 2.0, 2)
				final_total = flt(final_taxable + igst, 2)
			else:
				final_total = base_line
				final_taxable = flt(final_total * 100.0 / gst_rate, 2) if gst_rate else final_total
				igst = flt(final_total - final_taxable, 2)
				cgst = flt(igst / 2.0, 2)

			# EAN for Amazon, FSN for Flipkart; flag "Missing" when the required code is absent.
			ean_fsn, ean_fsn_flag = "", ""
			if cust_type == "Amazon":
				ean_fsn = it.get("custom_ean_no") or ""
				if not ean_fsn:
					ean_fsn_flag = "Missing"
			elif cust_type == "Flipkart":
				ean_fsn = it.get("custom_fsn_no") or ""
				if not ean_fsn:
					ean_fsn_flag = "Missing"

			# Less Qty = ordered - dispatched qty, valued at the GST-inclusive selling price.
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

		combine_product_bundles = True
		val = obm.get("combine_product_bundles")
		if val is not None:
			combine_product_bundles = bool(val)

		# Main item lines (priced). One row per SO line's own contribution; a combo's
		# components are never merged into a standalone line of the same SKU. Qty follows
		# the submitted Pick List, but has to be allocated back onto the SO lines first: the
		# Pick List holds only exploded components, and a component also ordered standalone
		# sits in one merged picked row. Walking the lines in order and consuming picked
		# stock as we go keeps them from double-counting that shared row.
		import math
		from alpinos.sales_order_offline_buyer import get_offline_buyer_item_rate
		from alpinos.sales_order_api import get_customer_item_mrp, get_box_conversion_factor, _bundle_components

		def _combo_components(r):
			"""[(component_item, qty_per_combo_unit)] for a bundle SO line, else None."""
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
			"""(mrp, flat%, selling price) for an exploded component from the buyer catalog."""
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
			# Fall back to the item's total picked qty when it has no "Items" row (same as emit()).
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
			"""This line's slice of the item's picked boxes, pro rata on units."""
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
				# This combo's own picked qty, from Pick List rows tagged with this combo.
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
				# Nothing of this line survived in the Pick List: not dispatched.
				continue

			if comps and combine_product_bundles:
				# Combined: explode this combo line into component rows priced from the buyer catalog.
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

			# The line itself: a plain item, or the combo SKU as entered when Combine Product
			# Bundles is off. A combo SKU has no picked row, so its Box is its components' picked boxes.
			if not has_pl:
				box = flt(r.get("custom_box"))
			elif comps:
				box = sum(flt((combo_pl_map.get((citem, r.item_code)) or {}).get("box") or 0) for (citem, per) in comps)
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

		# Marketing freebies / scheme / additional-unit (damage) items: selling rate 0,
		# qty taken straight from the Sales Order.
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
