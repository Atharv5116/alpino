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
			AND IFNULL(m.is_parent, 0) = 0
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
	"""Return MRP + buyer margin from Offline Buyer catalog/master for a Customer SKU."""
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

	catalog = frappe.db.sql(
		"""
		SELECT obil.mrp, IFNULL(obil.margin_percent, 0) AS margin_percent
		FROM `tabOffline Buyer Item` obil
		INNER JOIN `tabOffline Buyer Items` obi
			ON obi.name = obil.parent AND obil.parenttype = 'Offline Buyer Items'
		WHERE IFNULL(obi.docstatus, 0) < 2
			AND obi.buyer = %(customer)s
			AND obil.item_code = %(item_code)s
		ORDER BY obi.modified DESC
		LIMIT 1
		""",
		{"customer": customer, "item_code": item_code},
		as_dict=True,
	)
	std_mrp = flt(frappe.db.get_value("Item", item_code, "valuation_rate") or 0)
	if catalog:
		mrp = flt(catalog[0].mrp) or std_mrp
		pct = flt(catalog[0].margin_percent)
		rate = flt(mrp * (1 - pct / 100), 2) if mrp else 0.0
		return {
			"rate": rate,
			"margin_percent": pct,
			"mrp": mrp,
			"offline_buyer_master": obm_name,
			"source": "offline_buyer_items",
		}

	margin_pct = frappe.db.get_value(
		"Offline Buyer Margin",
		{"parent": obm_name, "parenttype": "Offline Buyer Master", "sku": item_code},
		"margin_percent",
	)
	if margin_pct is None:
		return None

	mrp = std_mrp
	pct = flt(margin_pct)
	rate = flt(mrp * (1 - pct / 100), 2) if mrp else 0.0

	return {
		"rate": rate,
		"margin_percent": pct,
		"mrp": mrp,
		"offline_buyer_master": obm_name,
		"source": "offline_buyer_margin",
	}


@frappe.whitelist()
def get_offline_buyer_for_customer(customer):
	"""Return Offline Buyer Master name and trade customer_type for a linked ERPNext Customer.
	Fallback to Customer.custom_order_type if not defined on OBM."""
	if not customer:
		return {"offline_buyer_master": None, "customer_type": None}

	row = frappe.db.get_value(
		"Offline Buyer Master",
		{"customer": customer},
		["name", "customer_type"],
		as_dict=True,
	)

	cust_type = row.get("customer_type") if row else None
	if not cust_type:
		# Fallback to Customer master
		cust_type = frappe.db.get_value("Customer", customer, "custom_order_type")

	return {
		"offline_buyer_master": row.get("name") if row else None,
		"customer_type": cust_type,
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
		is_primary = int(obrow.get("is_primary") or 0)
		is_shipping = int(obrow.get("is_shipping") or 0)
		if is_primary:
			addr_type = "Billing"
		elif is_shipping:
			addr_type = "Shipping"
		else:
			addr_type = "Billing"  # all OBM addresses are usable as billing
		addr_title_parts = []
		if _nz(obrow.get("address_label")):
			addr_title_parts.append(_nz(obrow.get("address_label")))
		if is_primary:
			addr_title_parts.append(_("Primary"))
		elif is_shipping:
			addr_title_parts.append(_("Shipping"))
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

	if default_billing is None:
		# If no primary row in OBM, try to find an existing ERPNext address of type 'Billing' for this customer
		existing = frappe.db.sql(
			"""
			SELECT a.name
			FROM `tabAddress` a
			INNER JOIN `tabDynamic Link` dl
				ON dl.parent = a.name AND dl.parenttype = 'Address'
				AND dl.link_doctype = 'Customer' AND dl.link_name = %(cust)s
			WHERE a.address_type = 'Billing' AND IFNULL(a.disabled, 0) = 0
			ORDER BY a.is_primary_address DESC, a.creation DESC
			LIMIT 1
			""",
			{"cust": customer},
		)
		if existing:
			default_billing = existing[0][0]

	if default_billing is None and results:
		# Still nothing? Fall back to the first address created from OBM
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
	# Exclude rows that are ALSO the primary address — those are already created as the
	# Billing address (billing_default_name). Treating them as shipping too would create
	# a duplicate Shipping-type Address record, leading to "not found" errors in the UI.
	shipping_rows = [
		r for r in (obm_doc.get("addresses") or [])
		if int(r.get("is_shipping") or 0) and not int(r.get("is_primary") or 0)
	]
	if not shipping_rows:
		# All shipping rows were also primary → single address serves as both
		all_shipping = [r for r in (obm_doc.get("addresses") or []) if int(r.get("is_shipping") or 0)]
		if all_shipping:
			return billing_default_name or None
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


def _ensure_contact_for_obm(obm_doc):
	"""Create or refresh an ERPNext Contact linked to the OBM's Customer.

	Pulls the contact person / email / phone numbers from the Offline Buyer
	Master flat fields. Idempotent: reuses a Contact already linked to the
	Customer (the customer's primary contact when present). Returns the Contact
	name, or None when there is no meaningful contact data to store.
	"""

	customer = obm_doc.customer
	if not customer:
		return None

	person = _nz(obm_doc.get("contact_person"))
	email = _nz(obm_doc.get("email"))
	phone = _nz(obm_doc.get("contact_no"))
	alt_phone = _nz(obm_doc.get("alternate_no"))

	# Nothing worth a Contact record — skip to avoid clutter.
	if not (person or email or phone or alt_phone):
		return None

	first_name = (person or _nz(obm_doc.get("customer_business_name")) or _nz(customer))[:140]

	contact_name = frappe.db.get_value("Customer", customer, "customer_primary_contact")
	if not contact_name:
		existing_contact = frappe.db.sql(
			"""
			SELECT c.name
			FROM `tabContact` c
			INNER JOIN `tabDynamic Link` dl
				ON dl.parent = c.name AND dl.parenttype = 'Contact'
				AND dl.link_doctype = 'Customer' AND dl.link_name = %(cust)s
			ORDER BY c.creation ASC
			LIMIT 1
			""",
			{"cust": customer},
		)
		if existing_contact:
			contact_name = existing_contact[0][0]

	if contact_name and frappe.db.exists("Contact", contact_name):
		contact = frappe.get_doc("Contact", contact_name)
	else:
		contact = frappe.new_doc("Contact")
		contact.flags.ignore_permissions = True
		contact.append("links", {"link_doctype": "Customer", "link_name": customer})

	contact.first_name = first_name

	if email and not any(_nz(e.email_id) == email for e in (contact.get("email_ids") or [])):
		contact.append("email_ids", {"email_id": email, "is_primary": 1})

	for ph, is_primary in ((phone, 1), (alt_phone, 0)):
		if ph and not any(_nz(p.phone) == ph for p in (contact.get("phone_nos") or [])):
			contact.append(
				"phone_nos",
				{"phone": ph, "is_primary_phone": is_primary, "is_primary_mobile_no": is_primary},
			)

	contact.save(ignore_permissions=True)
	return contact.name


def sync_obm_to_customer_party(obm_doc):
	"""Create/refresh ERPNext Address + Contact for the OBM's Customer and set
	them as the customer's primary address/contact.

	Runs on every Offline Buyer Master save (via on_update) and from the
	backfill job for existing customers. All underlying helpers are idempotent,
	so repeated runs reuse existing Address/Contact records instead of
	duplicating them.
	"""

	customer = obm_doc.customer
	if not customer or not frappe.db.exists("Customer", customer):
		return {"default_billing": None, "default_shipping": None, "contact": None}

	mapped = _offline_buyer_addresses_for_addresses_table(obm_doc)
	billing = mapped.get("billing_default")
	shipping = _ensure_shipping_address_from_obm(obm_doc, billing) or billing
	contact = _ensure_contact_for_obm(obm_doc)

	# Link the defaults onto the Customer without re-running Customer.validate.
	if billing:
		frappe.db.set_value("Customer", customer, "customer_primary_address", billing, update_modified=False)
	if contact:
		frappe.db.set_value("Customer", customer, "customer_primary_contact", contact, update_modified=False)

	return {"default_billing": billing, "default_shipping": shipping or billing, "contact": contact}


@frappe.whitelist()
def sync_single_offline_buyer_master(offline_buyer_master):
	"""Re-sync one Offline Buyer Master's Address + Contact onto its Customer.

	Administrator only — backs the "Sync to Customer" button on the OBM form.
	"""

	if frappe.session.user != "Administrator":
		frappe.throw(_("Only the Administrator can run this action."), frappe.PermissionError)

	doc = frappe.get_doc("Offline Buyer Master", offline_buyer_master)
	if not doc.customer or not frappe.db.exists("Customer", doc.customer):
		frappe.throw(_("This Offline Buyer Master has no linked Customer yet."))

	result = sync_obm_to_customer_party(doc)
	frappe.db.commit()
	return result


def _customer_has_linked(doctype, customer):
	"""True when an Address/Contact is linked to the Customer via Dynamic Link."""
	return bool(
		frappe.db.exists(
			"Dynamic Link",
			{
				"parenttype": doctype,
				"link_doctype": "Customer",
				"link_name": customer,
			},
		)
	)


@frappe.whitelist()
def report_offline_buyers_missing_customer_party():
	"""List customers whose Offline Buyer Master holds address/contact data but
	whose Customer record is still missing the linked Address and/or Contact.

	These are exactly the records the backfill would fix. Returns one row per
	Offline Buyer Master with flags for what's missing.

	Run with:
	  bench --site <site> execute \
	    alpinos.sales_order_offline_buyer.report_offline_buyers_missing_customer_party
	"""

	masters = frappe.get_all(
		"Offline Buyer Master",
		filters={"customer": ["is", "set"]},
		fields=[
			"name",
			"customer",
			"customer_business_name",
			"email",
			"contact_no",
			"contact_person",
			"alternate_no",
			"address",
		],
	)

	rows = []
	for m in masters:
		if not m.customer or not frappe.db.exists("Customer", m.customer):
			continue

		has_addr_rows = bool(
			frappe.db.exists("Offline Buyer Address", {"parent": m.name})
		)
		obm_has_address = has_addr_rows or bool(_nz(m.address))
		obm_has_contact = bool(
			_nz(m.email) or _nz(m.contact_no) or _nz(m.contact_person) or _nz(m.alternate_no)
		)

		if not (obm_has_address or obm_has_contact):
			continue

		missing_address = obm_has_address and not _customer_has_linked("Address", m.customer)
		missing_contact = obm_has_contact and not _customer_has_linked("Contact", m.customer)

		if missing_address or missing_contact:
			rows.append(
				{
					"offline_buyer_master": m.name,
					"customer": m.customer,
					"business_name": m.customer_business_name,
					"missing_address": missing_address,
					"missing_contact": missing_contact,
				}
			)

	# Readable summary in the bench console.
	print(f"\n{len(rows)} Offline Buyer Master record(s) need a Customer Address/Contact:\n")
	if rows:
		print(f"{'Customer':<24} {'Business Name':<32} {'Addr?':<7} {'Contact?':<8} OBM")
		print("-" * 100)
		for r in rows:
			print(
				f"{(r['customer'] or '')[:24]:<24} "
				f"{(r['business_name'] or '')[:32]:<32} "
				f"{('MISSING' if r['missing_address'] else 'ok'):<7} "
				f"{('MISSING' if r['missing_contact'] else 'ok'):<8} "
				f"{r['offline_buyer_master']}"
			)

	return rows


@frappe.whitelist()
def backfill_offline_buyer_addresses_and_contacts():
	"""Maintenance job: create ERPNext Address + Contact for every existing
	Offline Buyer Master that already has a linked Customer.

	Run with:
	  bench --site <site> execute \
	    alpinos.sales_order_offline_buyer.backfill_offline_buyer_addresses_and_contacts
	"""

	names = frappe.get_all(
		"Offline Buyer Master",
		filters={"customer": ["is", "set"]},
		pluck="name",
	)

	processed, errors = 0, []
	for nm in names:
		try:
			doc = frappe.get_doc("Offline Buyer Master", nm)
			if not doc.customer or not frappe.db.exists("Customer", doc.customer):
				continue
			sync_obm_to_customer_party(doc)
			processed += 1
		except Exception as e:
			errors.append({"offline_buyer_master": nm, "error": str(e)})
			frappe.log_error(frappe.get_traceback(), f"OBM party backfill failed: {nm}")

	frappe.db.commit()
	return {"processed": processed, "total": len(names), "errors": errors}


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
		parts = []
		for p in [row.address_line1, row.address_line2, row.city, row.state, row.pincode]:
			if p:
				# Remove newlines so the label matches the single-line Autocomplete input text
				clean_p = " ".join(str(p).replace("\n", " ").replace("\r", " ").split())
				if clean_p:
					parts.append(clean_p)
		row.display = "{} ({})".format(", ".join(parts), row.address_type or "Address")

	return rows


def update_offline_buyer_margin_if_changed(customer, item_code, new_margin):
	"""If the Flat Disc % on the Sales Order differs from the Offline Buyer Margin/Catalog, update the master."""
	new_margin = flt(new_margin, 2)
	if new_margin <= 0:
		return
	obm_name = frappe.db.get_value("Offline Buyer Master", {"customer": customer}, "name")
	if not obm_name:
		return

	# 1. Update in Offline Buyer Items (Catalog)
	obi_list = frappe.db.get_all("Offline Buyer Items", {"buyer": customer, "docstatus": ("<", 2)}, order_by="modified desc")
	for obi in obi_list:
		frappe.db.sql("""
			UPDATE `tabOffline Buyer Item`
			SET margin_percent = %s
			WHERE parent = %s AND item_code = %s AND IFNULL(margin_percent, 0) != %s
		""", (new_margin, obi.name, item_code, new_margin))

	# 2. Update in Offline Buyer Master (Margin table)
	doc = frappe.get_doc("Offline Buyer Master", obm_name)
	updated = False
	found = False
	for row in doc.get("margins") or []:
		if row.sku == item_code:
			found = True
			if flt(row.margin_percent, 2) != new_margin:
				row.margin_percent = new_margin
				updated = True
	
	if not found:
		doc.append("margins", {
			"sku": item_code,
			"margin_percent": new_margin
		})
		updated = True
		
	if updated:
		doc.flags.ignore_permissions = True
		doc.save()


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
