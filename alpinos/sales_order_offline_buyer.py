# Copyright (c) 2026, Alpinos and contributors
# License: MIT

import frappe
from frappe import _
from frappe.utils import flt


def _customers_with_offline_buyer_master_query(txt, start, page_len):
	"""Customers that have a row in Offline Buyer Master (same pool for Sales Order + Catalog)."""
	txt = txt or ""
	return frappe.db.sql(
		"""
		SELECT c.name, c.customer_name
		FROM `tabCustomer` c
		INNER JOIN `tabOffline Buyer Master` m ON m.customer = c.name
		WHERE IFNULL(c.disabled, 0) = 0
			AND (c.name LIKE %(txt)s OR c.customer_name LIKE %(txt)s)
		ORDER BY c.name ASC
		LIMIT %(page_len)s OFFSET %(start)s
		""",
		{"txt": f"%{txt}%", "start": int(start), "page_len": int(page_len)},
	)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def sales_order_customer_query(doctype, txt, searchfield, start, page_len, filters):
	"""Limit Sales Order Customer link to customers that have an Offline Buyer Master."""
	return _customers_with_offline_buyer_master_query(txt, start, page_len)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def catalog_customer_query(doctype, txt, searchfield, start, page_len, filters):
	"""Same customer list as Sales Order — only customers linked in Offline Buyer Master."""
	return _customers_with_offline_buyer_master_query(txt, start, page_len)


@frappe.whitelist()
def get_offline_buyer_item_rate(customer, item_code):
	"""Return selling rate from Offline Buyer Master margins (same formula as offline buyer catalog)."""
	if not customer or not item_code:
		return None

	obm_name = frappe.db.get_value(
		"Offline Buyer Master",
		{"customer": customer},
		"name",
		order_by="modified desc",
	)
	if not obm_name:
		return None

	margin_pct = frappe.db.get_value(
		"Offline Buyer Margin",
		{"parent": obm_name, "parenttype": "Offline Buyer Master", "sku": item_code},
		"margin_percent",
	)
	if margin_pct is None:
		return None

	mrp = flt(frappe.db.get_value("Item", item_code, "standard_rate") or 0)
	pct = flt(margin_pct)
	rate = flt(mrp * (1 - pct / 100), 2) if mrp else 0.0

	return {"rate": rate, "margin_percent": pct, "mrp": mrp, "offline_buyer_master": obm_name}


@frappe.whitelist()
def get_offline_buyer_for_customer(customer):
	"""Return Offline Buyer Master name and trade customer_type for a linked ERPNext Customer."""
	if not customer:
		return {"offline_buyer_master": None, "customer_type": None}

	row = frappe.db.get_value(
		"Offline Buyer Master",
		{"customer": customer},
		["name", "customer_type"],
		as_dict=True,
	)
	if not row:
		return {"offline_buyer_master": None, "customer_type": None}

	return {
		"offline_buyer_master": row.get("name"),
		"customer_type": row.get("customer_type"),
	}


def sync_sales_order_offline_buyer_fields(doc, method=None):
	"""Keep OBM link and trade Customer Type on Sales Order in sync with Customer (save/API/import)."""
	if doc.docstatus != 0:
		return
	try:
		meta = frappe.get_meta("Sales Order")
	except Exception:
		return
	if not meta.has_field("custom_offline_buyer_master"):
		return

	if not doc.customer:
		doc.custom_offline_buyer_master = None
		doc.custom_offline_buyer_customer_type = None
		return

	row = frappe.db.get_value(
		"Offline Buyer Master",
		{"customer": doc.customer},
		["name", "customer_type"],
		as_dict=True,
	)
	if row:
		doc.custom_offline_buyer_master = row.get("name")
		doc.custom_offline_buyer_customer_type = row.get("customer_type")
	else:
		doc.custom_offline_buyer_master = None
		doc.custom_offline_buyer_customer_type = None


def _nz(val):
	s = "" if val is None else str(val).strip()
	return s


def _find_customer_address(customer, line1: str, city: str, pincode: str):
	"""Reuse an ERPNext Address linked to Customer when line contents match."""

	line1 = (line1 or "")[:240]
	city = _nz(city)
	pincode = _nz(pincode)
	if not line1:
		return None

	found = frappe.db.sql(
		"""
		SELECT a.name
		FROM `tabAddress` a
		INNER JOIN `tabDynamic Link` dl
			ON dl.parent = a.name AND dl.parenttype = 'Address'
			AND dl.link_doctype = 'Customer' AND dl.link_name = %(cust)s
		WHERE IFNULL(a.address_line1, '') = %(l1)s
			AND IFNULL(a.city, '') = %(city)s
			AND IFNULL(a.pincode, '') = %(pin)s
		LIMIT 1
		""",
		{"cust": customer, "l1": line1, "city": city, "pin": pincode},
	)
	return found[0][0] if found else None


def _ensure_address_doc(
	customer,
	*,
	address_type: str,
	line1: str,
	city: str,
	state,
	country: str,
	pincode: str,
	address_title=None,
):

	line1_u = _nz(line1)[:240] or _("Address")

	country_name = None
	if country:
		if frappe.db.exists("Country", country):
			country_name = country
		else:
			co = frappe.db.get_value(
				"Country",
				{"country_name": country},
				"name",
				order_by="creation asc",
			)
			country_name = co or country

	if not country_name:
		country_name = frappe.db.get_value("Country", {}, "name", order_by="modified desc")

	existing = _find_customer_address(customer, line1_u, city, pincode)
	if existing:
		return existing

	addr = frappe.new_doc("Address")
	addr.flags.ignore_permissions = True
	ti = address_title if address_title else (line1_u[:40] if line1_u else _nz(customer))
	addr.address_title = (ti or customer)[:140]
	addr.address_type = address_type or "Billing"
	addr.address_line1 = line1_u
	addr.city = _nz(city) or _("N/A")
	addr.state = _nz(state) if state else ""
	addr.country = country_name
	addr.pincode = _nz(pincode)
	addr.append("links", {"link_doctype": "Customer", "link_name": customer})
	addr.insert(ignore_permissions=True)

	return addr.name


def _offline_buyer_addresses_for_addresses_table(obm_doc):
	"""Map Offline Buyer Address child rows to ERPNext Address names for Customer."""

	customer = obm_doc.customer
	all_rows = list(obm_doc.get("addresses") or [])
	if not customer or not all_rows:
		return {"billing_default": None}

	def row_to_addr(obrow):
		addr_type = "Billing" if int(obrow.get("is_primary") or 0) else "Other"
		addr_title_parts = []
		if _nz(obrow.get("address_label")):
			addr_title_parts.append(_nz(obrow.get("address_label")))
		if int(obrow.get("is_primary") or 0):
			addr_title_parts.append(_("Primary"))
		address_title = " — ".join(addr_title_parts) if addr_title_parts else _nz(customer)[:40]

		return _ensure_address_doc(
			customer,
			address_type=addr_type,
			line1=_nz(obrow.get("address_line")),
			city=obrow.get("city"),
			state=obrow.get("state"),
			country=obrow.get("country"),
			pincode=obrow.get("pincode"),
			address_title=address_title[:140],
		)

	results = []
	for row in all_rows:
		results.append(row_to_addr(row))

	default_billing = None
	for i, row in enumerate(all_rows):
		if int(row.get("is_primary") or 0):
			default_billing = results[i]
			break
	if default_billing is None and results:
		default_billing = results[0]

	return {"billing_default": default_billing}


def _primary_ob_address_row(obm_doc):
	rws = obm_doc.get("addresses") or []
	for r in rws:
		if int(r.get("is_primary") or 0):
			return r
	return rws[0] if rws else None


def _ensure_shipping_address_from_obm(obm_doc, billing_default_name: str | None):
	"""Derive one or more ERPNext Shipping Address records from the Offline Buyer Master.

	Priority:
	  1. If 'Shipping Same as Primary' is checked → use the billing default.
	  2. Rows in the addresses table that have is_shipping=1 → create/reuse Shipping-type
	     ERPNext Address records for each; return the first one as the default shipping address.
	  3. Legacy flat-field shipping panel (shipping_address / shipping_city / shipping_state).
	  4. Fall back to billing default.
	"""

	customer = obm_doc.customer
	primary = _primary_ob_address_row(obm_doc)
	if not customer or not primary:
		return billing_default_name

	same_as = int(obm_doc.get("shipping_same_as_profile") or 0)
	if same_as:
		return billing_default_name or None

	# --- Priority 2: is_shipping rows in child table ---
	shipping_rows = [r for r in (obm_doc.get("addresses") or []) if int(r.get("is_shipping") or 0)]
	if shipping_rows:
		default_shipping = None
		for sh_row in shipping_rows:
			line1 = _nz(sh_row.get("address_line"))
			if not line1:
				continue
			label = _nz(sh_row.get("address_label"))
			title_parts = [_("Shipping")]
			if label:
				title_parts.append(label)
			elif obm_doc.get("site_name"):
				title_parts.append(_nz(obm_doc.site_name))
			addr_name = _ensure_address_doc(
				customer,
				address_type="Shipping",
				line1=line1,
				city=sh_row.get("city"),
				state=sh_row.get("state"),
				country=sh_row.get("country"),
				pincode=sh_row.get("pincode"),
				address_title=" — ".join(title_parts)[:140],
			)
			if default_shipping is None:
				default_shipping = addr_name
		if default_shipping:
			return default_shipping

	# --- Priority 3: legacy flat-field shipping panel ---
	sh_line = _nz(obm_doc.get("shipping_address"))
	sh_city_link = obm_doc.get("shipping_city")
	sh_state_link = obm_doc.get("shipping_state")

	if not sh_line and not sh_city_link:
		return billing_default_name or None

	addr_title_parts = [_("Shipping")]
	if obm_doc.get("site_name"):
		addr_title_parts.append(_nz(obm_doc.site_name))
	address_title = " — ".join(addr_title_parts)[:140]

	city_txt = _nz(sh_city_link) if sh_city_link else _nz(primary.get("city"))
	state_txt = _nz(sh_state_link) if sh_state_link else _nz(primary.get("state"))
	country_txt = primary.get("country")
	pincode_txt = primary.get("pincode")

	line1_final = sh_line or _nz(primary.get("address_line"))
	if not _nz(line1_final):
		return billing_default_name or None

	return _ensure_address_doc(
		customer,
		address_type="Shipping",
		line1=line1_final,
		city=city_txt or _nz(primary.get("city")),
		state=state_txt,
		country=country_txt,
		pincode=pincode_txt,
		address_title=address_title,
	)


def _offline_buyer_address_sync(customer: str):
	"""Create missing ERPNext Address rows from Offline Buyer Master; return billing/shipping defaults."""

	if not customer:
		return {"default_billing": None, "default_shipping": None}

	master_name = frappe.db.get_value(
		"Offline Buyer Master",
		{"customer": customer},
		"name",
		order_by="modified desc",
	)
	if not master_name:
		return {"default_billing": None, "default_shipping": None}

	doc = frappe.get_doc("Offline Buyer Master", master_name)
	mapped = _offline_buyer_addresses_for_addresses_table(doc)
	billing = mapped["billing_default"]
	shipping = _ensure_shipping_address_from_obm(doc, billing) or billing

	return {
		"default_billing": billing,
		"default_shipping": shipping or billing,
		"offline_buyer_master": master_name,
	}


@frappe.whitelist()
def sync_offline_buyer_master_addresses(customer):
	"""Lazy-sync Offline Buyer Address table + shipping panel into ERPNext Address (linked to Customer).

	Desk Sales Order Entry uses this as default Billing/Shipping picks; Address Link fields stay a full customer list.
	"""
	return _offline_buyer_address_sync(customer)


@frappe.whitelist()
def get_customer_addresses_for_display(customer):
	"""Return addresses linked to a Customer with a human-readable display string for Autocomplete."""
	if not customer:
		return []

	rows = frappe.db.sql(
		"""
		SELECT a.name, a.address_type,
			a.address_line1, a.address_line2,
			a.city, a.state, a.country, a.pincode
		FROM `tabAddress` a
		INNER JOIN `tabDynamic Link` dl
			ON dl.parent = a.name
			AND dl.parenttype = 'Address'
			AND dl.link_doctype = 'Customer'
			AND dl.link_name = %(customer)s
		ORDER BY a.address_type, a.name
		""",
		{"customer": customer},
		as_dict=True,
	)

	for row in rows:
		parts = [p for p in [
			row.address_line1, row.address_line2,
			row.city, row.state, row.pincode,
		] if p]
		row.display = "{} ({})".format(", ".join(parts), row.address_type or "Address")

	return rows


def validate_sales_order_offline_buyer_customer(doc, method=None):
	"""Ensure Sales Order customer is linked to an Offline Buyer Master (UI also restricts the link)."""
	if doc.docstatus != 0:
		return
	if getattr(doc.flags, "ignore_offline_buyer_customer_check", False):
		return
	if not doc.customer:
		return
	if frappe.db.exists("DocType", "Offline Buyer Master") and not frappe.db.exists(
		"Offline Buyer Master", {"customer": doc.customer}
	):
		frappe.throw(
			_("Customer {0} is not linked to an Offline Buyer Master. Only offline-buyer customers can be selected.").format(
				frappe.bold(doc.customer)
			),
			title=_("Invalid Customer"),
		)
