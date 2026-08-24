# Copyright (c) 2026, Alpinos and contributors
# License: MIT

import frappe
from frappe import _
from frappe.utils import cint, flt


def _customers_with_offline_buyer_master_query(txt, start, page_len, channel=None, parents_only=False):
	"""Customers that have a row in Buyer Master (same pool for Sales Order + Catalog).

	channel: "Offline" -> offline + legacy(blank) buyers, "E-com" -> e-com buyers only,
	None -> any channel.
	parents_only: True -> top-level buyer masters only (an explicit parent
	   is_parent=1 OR a standalone buyer with no parent_buyer — i.e. the root of its
	   family). CHILD sites are hidden; the Sales Order / e-com entry pages pick the
	   root, then narrow to a site + its addresses. This keeps standalone buyers
	   selectable instead of vanishing. False (default, e.g. Catalog) -> non-parent
	   buyers only.
	"""
	txt = txt or ""
	params = {"txt": f"%{txt}%", "start": int(start), "page_len": int(page_len)}
	if parents_only:
		# root = an explicit parent OR a buyer with no parent (its own single-node family)
		parent_clause = "AND (IFNULL(m.is_parent, 0) = 1 OR IFNULL(m.parent_buyer, '') = '')"
	else:
		parent_clause = "AND IFNULL(m.is_parent, 0) = 0"
	channel_clause = ""
	if channel == "Offline":
		channel_clause = "AND (IFNULL(m.channel, '') = '' OR m.channel = 'Offline')"
	elif channel == "E-com":
		channel_clause = "AND m.channel = 'E-com'"
	# MUST return positional tuples: Frappe's link search (build_for_autosuggest)
	# indexes each result as item[0]/item[1:], so dicts raise KeyError: 0.
	# With Customer.show_title_field_in_link enabled (see _ensure_customer_title_in_link),
	# the dropdown and selected value show the customer NAME (title) and the docname
	# ("<business name> - <gst>") as the muted description — which disambiguates
	# same-named customers by their GSTIN. Searching by GSTIN also works.
	return frappe.db.sql(
		f"""
		SELECT c.name, c.customer_name
		FROM `tabCustomer` c
		INNER JOIN `tabBuyer Master` m ON m.customer = c.name
		WHERE IFNULL(c.disabled, 0) = 0
			{parent_clause}
			{channel_clause}
			AND (c.name LIKE %(txt)s OR c.customer_name LIKE %(txt)s OR m.gst_no LIKE %(txt)s)
		GROUP BY c.name, c.customer_name
		ORDER BY c.customer_name ASC
		LIMIT %(page_len)s OFFSET %(start)s
		""",
		params,
	)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def sales_order_customer_query(doctype, txt, searchfield, start, page_len, filters):
	"""Limit offline Sales Order Customer link to offline (or legacy) PARENT Buyer Masters.

	Only parents show; the Site Name dropdown then narrows to a child site and its
	addresses. GST follows the chosen billing address, so anchoring on the parent
	stays tax-correct."""
	return _customers_with_offline_buyer_master_query(txt, start, page_len, channel="Offline", parents_only=True)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def ecom_sales_order_customer_query(doctype, txt, searchfield, start, page_len, filters):
	"""Limit E-Com Sales Order Customer link to E-com channel PARENT Buyer Masters.

	Only parents show; the Site Name dropdown narrows to a child site and its
	addresses."""
	return _customers_with_offline_buyer_master_query(txt, start, page_len, channel="E-com", parents_only=True)


def ensure_customer_title_in_link():
	"""Show the customer NAME (title_field = customer_name) in every Customer link
	field instead of the '<business name> - <gst>' docname — the SO / e-com
	customer dropdowns and elsewhere. The docname still appears as the muted
	description, disambiguating same-named customers by their GSTIN. Idempotent;
	wired into after_migrate."""
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	if not frappe.utils.cint(frappe.db.get_value("DocType", "Customer", "show_title_field_in_link")):
		make_property_setter(
			doctype="Customer",
			fieldname=None,  # DocType-level property
			property="show_title_field_in_link",
			value="1",
			property_type="Check",
			for_doctype=True,
		)
		frappe.clear_cache(doctype="Customer")
		print("✅ Customer link fields now show the customer name (show_title_field_in_link)")


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def catalog_customer_query(doctype, txt, searchfield, start, page_len, filters):
	"""Same customer list as Sales Order — only customers linked in Buyer Master."""
	return _customers_with_offline_buyer_master_query(txt, start, page_len)


@frappe.whitelist()
def get_offline_buyer_item_rate(customer, item_code):
	"""Return MRP + buyer margin from Offline Buyer catalog/master for a Customer SKU."""
	if not customer or not item_code:
		return None

	obm_name = frappe.db.get_value(
		"Buyer Master",
		{"customer": customer},
		"name",
		order_by="modified desc",
	)
	if not obm_name:
		return None

	catalog = frappe.db.sql(
		"""
		SELECT obil.mrp, IFNULL(obil.margin_percent, 0) AS margin_percent, IFNULL(obil.selling_rate, 0) AS selling_rate
		FROM `tabBuyer Item` obil
		INNER JOIN `tabBuyer Items` obi
			ON obi.name = obil.parent AND obil.parenttype = 'Buyer Items'
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
		rate = flt(catalog[0].selling_rate) if flt(catalog[0].selling_rate) > 0 else (flt(mrp * (1 - pct / 100), 2) if mrp else 0.0)
		return {
			"rate": rate,
			"margin_percent": pct,
			"mrp": mrp,
			"offline_buyer_master": obm_name,
			"source": "offline_buyer_items",
		}

	margin_pct = frappe.db.get_value(
		"Buyer Margin",
		{"parent": obm_name, "parenttype": "Buyer Master", "sku": item_code},
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
	"""Return Buyer Master name and trade customer_type for a linked ERPNext Customer.
	Fallback to Customer.custom_order_type if not defined on OBM."""
	if not customer:
		return {"offline_buyer_master": None, "customer_type": None}

	row = frappe.db.get_value(
		"Buyer Master",
		{"customer": customer},
		[
			"name", "customer_type", "site_name", "channel",
			"appointment_required", "grn_available",
			"partial_order_allowed", "gst_exclusive_buyer",
			"gst_no", "shipping_address",
		],
		as_dict=True,
	)

	cust_type = row.get("customer_type") if row else None
	if not cust_type:
		# Fallback to Customer master
		cust_type = frappe.db.get_value("Customer", customer, "custom_order_type")

	return {
		"offline_buyer_master": row.get("name") if row else None,
		"customer_type": cust_type,
		"site_name": (row.get("site_name") if row else None) or "",
		"channel": (row.get("channel") if row else None) or "",
		# Order-behaviour flags (auto-populated onto the SO, overridable per order).
		"appointment_required": int(row.get("appointment_required") or 0) if row else 0,
		"grn_available": int(row.get("grn_available") or 0) if row else 0,
		"partial_order_allowed": int(row.get("partial_order_allowed") or 0) if row else 0,
		"gst_exclusive_buyer": int(row.get("gst_exclusive_buyer") or 0) if row else 0,
		"gst_no": (row.get("gst_no") if row else None) or "",
	}


# GST state (first two digits of a GSTIN) -> India state/UT name.
_GST_STATE_CODES = {
	"Jammu and Kashmir": "01", "Himachal Pradesh": "02", "Punjab": "03", "Chandigarh": "04",
	"Uttarakhand": "05", "Haryana": "06", "Delhi": "07", "Rajasthan": "08", "Uttar Pradesh": "09",
	"Bihar": "10", "Sikkim": "11", "Arunachal Pradesh": "12", "Nagaland": "13", "Manipur": "14",
	"Mizoram": "15", "Tripura": "16", "Meghalaya": "17", "Assam": "18", "West Bengal": "19",
	"Jharkhand": "20", "Odisha": "21", "Chhattisgarh": "22", "Madhya Pradesh": "23", "Gujarat": "24",
	"Dadra and Nagar Haveli and Daman and Diu": "26", "Maharashtra": "27", "Karnataka": "29",
	"Goa": "30", "Lakshadweep": "31", "Kerala": "32", "Tamil Nadu": "33", "Puducherry": "34",
	"Andaman and Nicobar Islands": "35", "Telangana": "36", "Andhra Pradesh": "37", "Ladakh": "38",
}


def gst_state_code(gstin):
	"""First two digits of a GSTIN (the state code), or '' when not a valid GSTIN prefix."""
	g = (gstin or "").strip()
	return g[:2] if len(g) >= 2 and g[:2].isdigit() else ""


def validate_gstin_state_match(gstin, state):
	"""(ok, expected_code, gstin_code): ok is True when either side is unknown or they match.
	Used to flag a GSTIN whose state code doesn't match the bill-to state."""
	gc = gst_state_code(gstin)
	ec = _GST_STATE_CODES.get((state or "").strip())
	if not gc or not ec:
		return True, ec or "", gc
	return gc == ec, ec, gc


def site_exists_in_buyer_family(customer, site_name):
	"""True when `site_name` is a real site of `customer`'s Buyer Master family — either a
	master's header Site Name or one of its Buyer Address rows. Used to guard imports."""
	site_name = (site_name or "").strip()
	if not customer or not site_name:
		return False
	masters = masters_for_customer_business(customer)
	if not masters:
		return False
	if frappe.db.exists("Buyer Master", {"name": ["in", masters], "site_name": site_name}):
		return True
	return bool(frappe.db.exists("Buyer Address", {"parent": ["in", masters], "site_name": site_name}))


# Customer types (channels) for which a Site Name is MANDATORY on import — each has
# many sites (dark stores / FCs), so the order must name one. Other types may omit it.
SITE_MANDATORY_CUSTOMER_TYPES = {
	"Other E-commerce", "Zepto", "Swiggy", "Bigbasket", "Reliance",
	"Flipkart", "Amazon", "Modern Trade", "Blinkit",
}


def assert_import_site_requirements(customer, site_name, customer_type=None):
	"""Import guard for a Sales Order's Site (the site-validation spec).

	Site Name is mandatory only for the e-commerce / modern-trade customer types in
	SITE_MANDATORY_CUSTOMER_TYPES. When a Site IS given (mandatory or not) it must map to a
	Buyer Master site of the family, and that SITE record must carry its OWN required data
	- never taken from the family parent (only the customer / parent-buyer name may come
	from the parent). Raises on the first problem, so the importer reports it per order.
	"""
	site_name = (site_name or "").strip()
	if customer_type is None:
		customer_type = frappe.db.get_value("Buyer Master", {"customer": customer}, "customer_type") or ""
	site_mandatory = (customer_type or "").strip() in SITE_MANDATORY_CUSTOMER_TYPES

	# (1)(2) Site Name: mandatory for the listed channels; optional otherwise.
	if not site_name:
		if site_mandatory:
			frappe.throw(
				_("Site Name is required for customer type '{0}'.").format(customer_type),
				title=_("Missing Site"),
			)
		return
	if not site_exists_in_buyer_family(customer, site_name):
		frappe.throw(
			_("Site Name '{0}' is not mapped in the Buyer Master for {1}. Add the site to the Buyer Master before importing.").format(site_name, customer),
			title=_("Site Not Mapped"),
		)
	# (5) Resolve the SITE's OWN Buyer Master(s) - never the family parent.
	masters = masters_for_customer_business(customer)
	owners = _masters_owning_site(masters, site_name)
	if not owners:
		frappe.throw(
			_("Site '{0}' has no owning Buyer Master record for {1}.").format(site_name, customer),
			title=_("Site Not Mapped"),
		)
	# (3)(4) Required site-level data must exist on the site record itself (no parent fallback).
	missing = []
	registered = False
	for o in owners:
		if frappe.db.get_value("Buyer Master", o, "gst_type") == "Registered Business":
			registered = True
	if registered and not (_gst_for_site(site_name, "") or "").strip():
		missing.append("GST No")
	if missing:
		frappe.throw(
			_("Site '{0}' (Buyer Master {1}) is missing required site-level data: {2}. Set it on the site record - the parent buyer's data is not used as a fallback.").format(site_name, ", ".join(sorted(owners)), ", ".join(missing)),
			title=_("Incomplete Site Data"),
		)

def _gst_for_site(site_name, fallback=""):
	"""Site-wise GST No: the gst_no of the Buyer Master that owns an address (Buyer Address
	child row) whose site_name matches — so the SO carries the SELECTED SITE's GSTIN, not
	the family parent's. Falls back to `fallback` (the customer's buyer master gst) when the
	site can't be resolved to a registered master."""
	if site_name:
		rows = frappe.db.sql(
			"""
			SELECT bm.gst_no
			FROM `tabBuyer Address` ba
			JOIN `tabBuyer Master` bm ON bm.name = ba.parent
			WHERE ba.site_name = %s AND IFNULL(bm.gst_no, '') <> ''
			LIMIT 1
			""",
			site_name,
		)
		if rows and rows[0][0]:
			return rows[0][0]
	return fallback or ""


# Order-behaviour flags that are read SITE-WISE (from the Buyer Master owning the chosen
# site's address), not from the family parent. GST-Exclusive Buyer is per-site (e.g. an
# Amazon FBF site) so it must follow the site, exactly like GST No does.
def _flag_for_site(site_name, field, fallback=0):
	"""Value of a Buyer Master flag for the SELECTED SITE — the master that owns a Buyer
	Address child row whose site_name matches — falling back to `fallback` (the family
	master's value) when the site can't be resolved. `field` is a fixed column name."""
	if site_name:
		rows = frappe.db.sql(
			"""
			SELECT bm.`{field}`
			FROM `tabBuyer Address` ba
			JOIN `tabBuyer Master` bm ON bm.name = ba.parent
			WHERE ba.site_name = %s
			LIMIT 1
			""".format(field=field),
			site_name,
		)
		if rows:
			return int(rows[0][0] or 0)
	return int(fallback or 0)


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

	has_site_field = meta.has_field("custom_site_name")

	if not doc.customer:
		doc.custom_offline_buyer_master = None
		doc.custom_offline_buyer_customer_type = None
		return

	row = frappe.db.get_value(
		"Buyer Master",
		{"customer": doc.customer},
		[
			"name", "customer_type", "site_name", "channel",
			"appointment_required", "grn_available",
			"partial_order_allowed", "gst_exclusive_buyer", "gst_no",
			"parent_buyer", "gst_type",
		],
		as_dict=True,
	)
	if row:
		doc.custom_offline_buyer_master = row.get("name")
		doc.custom_offline_buyer_customer_type = row.get("customer_type")
		# Site name is user-editable — only default it when blank. Priority:
		# the selected shipping address's site (OBM per-address site_name is
		# synced onto Address.custom_site_name), then the OBM header site_name.
		if has_site_field and not (doc.get("custom_site_name") or "").strip():
			addr_site = ""
			if doc.get("shipping_address_name"):
				addr_site = (
					frappe.db.get_value(
						"Address", doc.shipping_address_name, "custom_site_name"
					)
					or ""
				)
			doc.custom_site_name = addr_site or row.get("site_name") or ""
		# GST No is taken SITE-WISE: the Buyer Master that owns the chosen site (its Buyer
		# Address child row's site_name == the SO's site) carries that site's GSTIN — NOT the
		# family parent. Falls back to the customer's buyer master gst_no when the site can't
		# be resolved. Blank for an Unregistered site with no registered site master.
		# GST is SITE-WISE: only the GSTIN of the Buyer Master that owns the chosen site.
		# If the site is missing / can't be resolved to a registered site master, leave GST
		# BLANK — never fall back to the family parent's GSTIN.
		_site = (doc.get("custom_site_name") or "").strip() if has_site_field else ""
		_site_gst = (_gst_for_site(_site, "") or "").strip().upper()
		doc.tax_id = _site_gst
		# #24 Billing GST No.: the site's GST when a Site resolves; else the buyer's OWN GST
		# but ONLY when it has no Parent Buyer; else leave blank for manual entry. NEVER the
		# Parent Buyer's GST. A value already entered is preserved when nothing auto-resolves.
		if meta.has_field("custom_billing_gstin"):
			billing_gst = _site_gst
			if not billing_gst and not row.get("parent_buyer"):
				billing_gst = (row.get("gst_no") or "").strip().upper()
			if billing_gst:
				doc.custom_billing_gstin = billing_gst
			# else: keep whatever is on the doc (manual entry) — don't clobber to blank
		if meta.has_field("custom_shipping_gstin"):
			doc.custom_shipping_gstin = _site_gst
		# #24 Billing GST No. is mandatory for a Registered Business buyer. Enforced on new
		# orders (the auto-fetch fills most; the entry pages allow manual entry for the rest)
		# so editing a legacy order is never retroactively blocked.
		if (
			doc.is_new()
			and meta.has_field("custom_billing_gstin")
			and (row.get("gst_type") == "Registered Business")
			and not (doc.get("custom_billing_gstin") or "").strip()
		):
			frappe.throw(
				_("Billing GST No. is required for a Registered Business buyer — pick a Site whose GST resolves, or enter the Billing GST No. manually."),
				title=_("Billing GST No. Required"),
			)
		# GST-Exclusive Buyer is a SITE-WISE property, exactly like GST No: always reflect
		# the Buyer Master that owns the chosen site — on every save and for every entry path
		# (offline / e-com / import), NOT the family parent picked up in `row`. Falls back to
		# the family master's value only when the site can't be resolved.
		if meta.has_field("custom_gst_exclusive_buyer"):
			doc.custom_gst_exclusive_buyer = _flag_for_site(
				_site, "gst_exclusive_buyer", row.get("gst_exclusive_buyer")
			)
		# Validate the GSTIN's state code against the bill-to state (soft flag). Only when
		# a structured billing Address carries a state — free-text imports simply skip it.
		if _site_gst and doc.get("customer_address"):
			_bstate = frappe.db.get_value("Address", doc.customer_address, "state") or ""
			ok, ec, gc = validate_gstin_state_match(_site_gst, _bstate)
			if not ok:
				frappe.msgprint(
					_("Billing GSTIN state code {0} doesn't match the bill-to state ({1}, expected {2}).").format(gc, _bstate, ec),
					indicator="orange", alert=True,
				)
		# Channel: default from the buyer only when the entry path hasn't set it.
		# The offline/e-com entry pages set custom_channel explicitly.
		if meta.has_field("custom_channel") and not (doc.get("custom_channel") or "").strip():
			doc.custom_channel = row.get("channel") or "Offline"
		# Order-behaviour flags: default from the buyer on new orders (raw form /
		# import robustness). Editable overrides on existing orders are preserved,
		# and the create API sets flags.skip_ecom_flag_default when it owns them.
		if (
			meta.has_field("custom_appointment_required")
			and doc.is_new()
			and not getattr(doc.flags, "skip_ecom_flag_default", False)
		):
			doc.custom_appointment_required = int(row.get("appointment_required") or 0)
			doc.custom_grn_available = int(row.get("grn_available") or 0)
			doc.custom_partial_order_allowed = int(row.get("partial_order_allowed") or 0)
		# Site validation for every entry path — Frappe's native Data Import and the
		# entry pages, not just the Excel bulk importer. For the e-commerce / modern-
		# trade customer types a Site is mandatory; when a Site is given (any type) it
		# must map to a Buyer Master site of this family and that site must carry its
		# own site-level data (no parent-buyer fallback). New orders only, so edits /
		# submits of legacy orders are never retroactively blocked.
		if doc.is_new():
			assert_import_site_requirements(
				doc.customer,
				(doc.get("custom_site_name") or "").strip(),
				row.get("customer_type"),
			)
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
	site_name=None,
):

	line1_u = _nz(line1)[:240] or _("Address")
	site_name = _nz(site_name)

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
		# Keep the site name on the existing Address in sync with the OBM row.
		if site_name and frappe.db.get_value("Address", existing, "custom_site_name") != site_name:
			frappe.db.set_value("Address", existing, "custom_site_name", site_name, update_modified=False)
		return existing

	addr = frappe.new_doc("Address")
	addr.flags.ignore_permissions = True
	ti = address_title if address_title else (line1_u[:40] if line1_u else _nz(customer))
	addr.address_title = (ti or customer)[:140]
	if site_name:
		addr.custom_site_name = site_name
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
	"""Map Buyer Address child rows to ERPNext Address names for Customer."""

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
		if _nz(obrow.get("site_name")):
			addr_title_parts.append(_nz(obrow.get("site_name")))
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
			site_name=obrow.get("site_name"),
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
	"""Derive one or more ERPNext Shipping Address records from the Buyer Master.

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
			site = _nz(sh_row.get("site_name"))
			title_parts = [_("Shipping")]
			if site:
				title_parts.append(site)
			elif label:
				title_parts.append(label)
			addr_name = _ensure_address_doc(
				customer,
				address_type="Shipping",
				line1=line1,
				city=sh_row.get("city"),
				state=sh_row.get("state"),
				country=sh_row.get("country"),
				pincode=sh_row.get("pincode"),
				address_title=" — ".join(title_parts)[:140],
				site_name=sh_row.get("site_name"),
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

	sh_site = _nz(primary.get("site_name"))
	addr_title_parts = [_("Shipping")]
	if sh_site:
		addr_title_parts.append(sh_site)
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
		site_name=primary.get("site_name"),
	)


def _offline_buyer_address_sync(customer: str):
	"""Materialise ERPNext Address rows from the Buyer Master(s); return billing/shipping defaults.

	Syncs EVERY Buyer Master in the family (parent + children / all masters that
	share a family customer), not just the customer's own. A customer can own
	several buyer masters — one per site — and each site's addresses must be
	materialised so the entry page can offer them; syncing only one master is why a
	sibling site's address never appeared in the dropdown. Each Address is tagged
	with its own master's Site Name so the dropdowns can be narrowed by site.
	Returned defaults are the customer's own (primary) master's billing/shipping."""

	if not customer:
		return {"default_billing": None, "default_shipping": None}

	family = buyer_family_customers(customer)
	masters = (
		frappe.get_all(
			"Buyer Master",
			filters={"customer": ["in", family]},
			pluck="name",
			order_by="modified desc",
		)
		if family
		else []
	)
	if not masters:
		return {"default_billing": None, "default_shipping": None}

	own_master = frappe.db.get_value(
		"Buyer Master", {"customer": customer}, "name", order_by="modified desc"
	)

	default_billing = default_shipping = None
	first_billing = first_shipping = None
	for master_name in masters:
		doc = frappe.get_doc("Buyer Master", master_name)
		mapped = _offline_buyer_addresses_for_addresses_table(doc)
		billing = mapped["billing_default"]
		shipping = _ensure_shipping_address_from_obm(doc, billing) or billing
		if first_billing is None and billing:
			first_billing, first_shipping = billing, (shipping or billing)
		if master_name == own_master:
			default_billing, default_shipping = billing, (shipping or billing)

	# The customer's own master had no usable address → fall back to the first that did.
	if default_billing is None:
		default_billing, default_shipping = first_billing, first_shipping

	return {
		"default_billing": default_billing,
		"default_shipping": default_shipping or default_billing,
		"offline_buyer_master": own_master,
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

	# The buyer's email is the SOLE primary — clear any other primary first, else Frappe's
	# Contact validation ("Only one Email ID can be set as primary") rejects the save when
	# the contact already had a primary email.
	if email:
		seen_email = False
		for e in contact.get("email_ids") or []:
			hit = _nz(e.email_id) == email
			e.is_primary = 1 if hit else 0
			seen_email = seen_email or hit
		if not seen_email:
			contact.append("email_ids", {"email_id": email, "is_primary": 1})

	# Likewise the main phone is the sole primary phone + mobile; the alt phone is added
	# non-primary (a second primary phone/mobile would hit the same validation).
	if phone:
		seen_phone = False
		for p in contact.get("phone_nos") or []:
			hit = _nz(p.phone) == phone
			p.is_primary_phone = 1 if hit else 0
			p.is_primary_mobile_no = 1 if hit else 0
			seen_phone = seen_phone or hit
		if not seen_phone:
			contact.append("phone_nos", {"phone": phone, "is_primary_phone": 1, "is_primary_mobile_no": 1})
	if alt_phone and not any(_nz(p.phone) == alt_phone for p in (contact.get("phone_nos") or [])):
		contact.append("phone_nos", {"phone": alt_phone, "is_primary_phone": 0, "is_primary_mobile_no": 0})

	contact.save(ignore_permissions=True)
	return contact.name


def sync_obm_to_customer_party(obm_doc):
	"""Create/refresh ERPNext Address + Contact for the OBM's Customer and set
	them as the customer's primary address/contact.

	Runs on every Buyer Master save (via on_update) and from the
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
	"""Re-sync one Buyer Master's Address + Contact onto its Customer.

	Administrator only — backs the "Sync to Customer" button on the OBM form.
	"""

	if frappe.session.user != "Administrator":
		frappe.throw(_("Only the Administrator can run this action."), frappe.PermissionError)

	doc = frappe.get_doc("Buyer Master", offline_buyer_master)
	if not doc.customer or not frappe.db.exists("Customer", doc.customer):
		frappe.throw(_("This Buyer Master has no linked Customer yet."))

	result = sync_obm_to_customer_party(doc)
	frappe.db.commit()
	return result


@frappe.whitelist()
def report_duplicate_buyer_masters(customer=None):
	"""Read-only: list Customers that have MORE THAN ONE Buyer Master — the cause
	of the 'Only one Buyer Master is allowed per Customer' error on edit, and of
	buyers behaving oddly in the Sales Order customer dropdown.

	Run:
	  bench --site <site> execute alpinos.sales_order_offline_buyer.report_duplicate_buyer_masters
	Pass customer='<name>' to check a single customer.
	"""
	params = {}
	cond = ""
	if customer:
		cond = "AND b.customer = %(customer)s"
		params["customer"] = customer
	rows = frappe.db.sql(
		f"""
		SELECT b.customer,
			COUNT(*) AS n,
			GROUP_CONCAT(b.name ORDER BY b.modified DESC SEPARATOR ' | ') AS buyer_masters,
			GROUP_CONCAT(IFNULL(NULLIF(b.channel, ''), '(blank)') ORDER BY b.modified DESC SEPARATOR ' | ') AS channels,
			GROUP_CONCAT(IFNULL(b.is_parent, 0) ORDER BY b.modified DESC SEPARATOR ' | ') AS is_parent
		FROM `tabBuyer Master` b
		WHERE IFNULL(b.customer, '') != '' {cond}
		GROUP BY b.customer
		HAVING n > 1
		ORDER BY n DESC
		""",
		params,
		as_dict=True,
	)
	return {"duplicate_customers": len(rows), "rows": rows}


@frappe.whitelist()
def clean_customer_names_strip_gst(commit=True):
	"""One-off cleanup: strip a trailing ' - <gstin/pan>' that leaked into
	Customer.customer_name, keeping the docname (id) unchanged.

	The buyer -> Customer flow names the Customer DOCNAME '<business name> - <gst>'
	(kept unique), but the DISPLAY name (customer_name) should be just the
	business name. Older records ended up with the GST in customer_name too;
	this restores the clean business name while the id stays '<name> - <gst>'.

	Idempotent and safe to re-run. Run with:
	  bench --site <site> execute alpinos.sales_order_offline_buyer.clean_customer_names_strip_gst
	"""
	if frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
		frappe.throw(_("Only an Administrator / System Manager can run this."), frappe.PermissionError)

	rows = frappe.db.sql(
		"""
		SELECT c.name, c.customer_name, c.tax_id
		FROM `tabCustomer` c
		INNER JOIN `tabBuyer Master` m ON m.customer = c.name
		WHERE IFNULL(c.tax_id, '') != '' AND IFNULL(c.customer_name, '') != ''
		GROUP BY c.name, c.customer_name, c.tax_id
		""",
		as_dict=True,
	)
	fixed = []
	for r in rows:
		cn = (r.get("customer_name") or "").strip()
		tax = (r.get("tax_id") or "").strip()
		suffix = f" - {tax}"
		if tax and cn.endswith(suffix):
			cleaned = cn[: -len(suffix)].strip()
			if cleaned and cleaned != cn:
				# Update the display name only; the docname (id) is untouched so
				# the GST-disambiguated unique id is preserved.
				frappe.db.set_value("Customer", r.get("name"), "customer_name", cleaned, update_modified=False)
				fixed.append({"customer_id": r.get("name"), "from": cn, "to": cleaned})
	if commit:
		frappe.db.commit()
	return {"scanned": len(rows), "fixed_count": len(fixed), "fixed": fixed[:100]}


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
	"""List customers whose Buyer Master holds address/contact data but
	whose Customer record is still missing the linked Address and/or Contact.

	These are exactly the records the backfill would fix. Returns one row per
	Buyer Master with flags for what's missing.

	Run with:
	  bench --site <site> execute \
	    alpinos.sales_order_offline_buyer.report_offline_buyers_missing_customer_party
	"""

	masters = frappe.get_all(
		"Buyer Master",
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
			frappe.db.exists("Buyer Address", {"parent": m.name})
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
	print(f"\n{len(rows)} Buyer Master record(s) need a Customer Address/Contact:\n")
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
	Buyer Master that already has a linked Customer.

	Run with:
	  bench --site <site> execute \
	    alpinos.sales_order_offline_buyer.backfill_offline_buyer_addresses_and_contacts
	"""

	names = frappe.get_all(
		"Buyer Master",
		filters={"customer": ["is", "set"]},
		pluck="name",
	)

	processed, errors = 0, []
	for nm in names:
		try:
			doc = frappe.get_doc("Buyer Master", nm)
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
	"""Lazy-sync Buyer Address table + shipping panel into ERPNext Address (linked to Customer).

	Desk Sales Order Entry uses this as default Billing/Shipping picks; Address Link fields stay a full customer list.
	"""
	return _offline_buyer_address_sync(customer)


def buyer_family_customers(customer):
	"""Customers of every Buyer Master in the same parent family (parent + all
	its children, including this one). A buyer with no parent returns just itself."""
	if not customer:
		return []
	obm = frappe.db.get_value(
		"Buyer Master", {"customer": customer},
		["name", "is_parent", "parent_buyer"], as_dict=True,
	)
	if not obm:
		return [customer]
	root = obm.parent_buyer or (obm.name if cint(obm.is_parent) else None)
	if not root:
		return [customer]
	family = frappe.db.sql_list(
		"""
		SELECT DISTINCT customer FROM `tabBuyer Master`
		WHERE IFNULL(customer, '') != ''
			AND (name = %(root)s OR parent_buyer = %(root)s)
		""",
		{"root": root},
	)
	if customer not in family:
		family.append(customer)
	return family


def buyer_family_masters(customer):
	"""Every Buyer Master in the family (parent + children / all masters that share a
	family customer), as dicts of name + customer + site_name. This is the address
	source of truth for the entry page — a customer can own several masters (one per
	site), so we enumerate masters, not just customers."""
	family = buyer_family_customers(customer)
	if not family:
		return []
	return frappe.get_all(
		"Buyer Master",
		filters={"customer": ["in", family]},
		fields=["name", "customer", "site_name"],
		order_by="creation asc",
	)


def masters_for_customer_business(customer):
	"""Every Buyer Master that makes up this BUYER, for site validation.

	A single buyer (e.g. an e-commerce entity such as SCOOTSY / Swiggy) typically has ONE
	Buyer Master per GST / region, each linked to its OWN Customer id ("<Business> - <GST>")
	and NOT joined by parent_buyer. Grouping only by the linked-customer family therefore
	sees just one region's sites and rejects every other region's site as "not mapped".
	So group by customer_business_name (the buyer itself), unioned with the parent_buyer
	family to also cover masters named differently. Falls back to the customer's own name."""
	names = set(m.name for m in (buyer_family_masters(customer) or []))
	biz = frappe.db.get_value("Buyer Master", {"customer": customer}, "customer_business_name")
	if not biz:
		biz = frappe.db.get_value("Customer", customer, "customer_name")
	if biz:
		names.update(
			frappe.get_all("Buyer Master", filters={"customer_business_name": biz}, pluck="name")
		)
	return list(names)


def _masters_owning_site(master_names, site):
	"""Buyer Master(s) that OWN a Site — the master's own Site Name is it, OR one of
	its Buyer Address rows carries it. A master can host several sites, and picking
	any one of them shows that master's WHOLE address book; so a site resolves to its
	master(s), not to a single address row."""
	site = (site or "").strip()
	if not site or not master_names:
		return set()
	owners = set(
		frappe.db.sql_list(
			"SELECT name FROM `tabBuyer Master` WHERE name IN %(m)s AND site_name = %(s)s",
			{"m": tuple(master_names), "s": site},
		)
	)
	owners.update(
		frappe.db.sql_list(
			"""
			SELECT DISTINCT parent FROM `tabBuyer Address`
			WHERE parent IN %(m)s AND parenttype = 'Buyer Master' AND site_name = %(s)s
			""",
			{"m": tuple(master_names), "s": site},
		)
	)
	return owners


@frappe.whitelist()
def get_customer_family_sites(customer):
	"""Distinct Site Names across the buyer family (parent + all children) — the
	options for the Site Name dropdown on the SO / e-com entry pages.

	Sites live in TWO places on the Buyer Master(s): the master's own site_name AND
	each Buyer Address row's site_name (a master can host several sites). Union both
	straight from the masters so every site the family has is offered."""
	if not customer:
		return []
	masters = buyer_family_masters(customer)
	if not masters:
		return []
	master_names = [m.name for m in masters]
	sites = {(m.site_name or "").strip() for m in masters if (m.site_name or "").strip()}
	sites.update(
		frappe.db.sql_list(
			"""
			SELECT DISTINCT site_name FROM `tabBuyer Address`
			WHERE parent IN %(m)s AND parenttype = 'Buyer Master'
				AND IFNULL(site_name, '') != ''
			""",
			{"m": tuple(master_names)},
		)
	)
	return sorted(s for s in sites if (s or "").strip())


def _address_name_for_buyer_row(customer, line1, city, pincode):
	"""Match a Buyer Address row back to the ERPNext Address the buyer-master sync
	materialised for it. Matches on customer + line1 + pincode + city, treating a
	blank row city as the 'N/A' placeholder the sync stores for cityless rows."""
	line1 = (line1 or "")[:240]
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
			AND IFNULL(a.pincode, '') = %(pin)s
			AND (IFNULL(a.city, '') = %(city)s OR (%(city)s = '' AND a.city = 'N/A'))
		ORDER BY a.creation ASC
		LIMIT 1
		""",
		{"cust": customer, "l1": line1, "city": _nz(city), "pin": _nz(pincode)},
	)
	return found[0][0] if found else None


@frappe.whitelist()
def get_customer_addresses_for_display(customer, site_name=None):
	"""Addresses for the Autocomplete on the SO / e-com entry pages, sourced DIRECTLY
	from the Buyer Master(s) in the family.

	- site_name blank -> every address row of every Buyer Master in the family
	  (parent + children / all masters sharing a family customer).
	- site_name set   -> the Buyer Master(s) that OWN that site (the master's own
	  Site Name is it, OR one of its address rows carries it); ALL of those masters'
	  addresses are then offered — a master can host several sites, and picking any
	  one shows the master's WHOLE address book.

	Each row keeps its is_primary / is_shipping ticks so the page routes Primary rows
	to Billing and Shipping rows to Shipping (a row ticked both appears in both).
	Read-only: rows are matched to the ERPNext Address the buyer-master sync already
	created (so GST can follow the billing address); a row without a materialised
	Address yet is skipped. Return rows keep the Address component fields
	(address_line1/2, city, state, pincode) other callers rely on."""
	if not customer:
		return []
	site_name = (site_name or "").strip()
	masters = buyer_family_masters(customer)
	if not masters:
		return []

	if site_name:
		owners = _masters_owning_site([m.name for m in masters], site_name)
		if owners:
			masters = [m for m in masters if m.name in owners]

	family_custs = {m.customer for m in masters if m.customer}
	multi = len(family_custs) > 1
	owner_names = {}
	if multi:
		for cust, cname in frappe.db.sql(
			"SELECT name, customer_name FROM `tabCustomer` WHERE name IN %(f)s",
			{"f": tuple(family_custs)},
		):
			owner_names[cust] = cname or cust

	seen = set()
	out = []
	for m in masters:
		obm = frappe.get_doc("Buyer Master", m.name)
		for brow in obm.get("addresses") or []:
			line1 = _nz(brow.get("address_line"))
			if not line1:
				continue
			addr_name = _address_name_for_buyer_row(
				obm.customer, line1, brow.get("city"), brow.get("pincode")
			)
			if not addr_name:
				continue  # not materialised as an Address yet (sync creates it first)
			addr = frappe.db.get_value(
				"Address",
				addr_name,
				[
					"address_line1", "address_line2", "city", "state",
					"country", "pincode", "custom_site_name", "address_type",
				],
				as_dict=True,
			) or {}
			parts = []
			for p in [
				addr.get("address_line1"), addr.get("address_line2"),
				addr.get("city"), addr.get("state"), addr.get("pincode"),
			]:
				clean_p = " ".join(str(p or "").replace("\n", " ").replace("\r", " ").split())
				if clean_p and clean_p.upper() != "N/A":
					parts.append(clean_p)
			value = ", ".join(parts)
			if not value:
				continue
			is_primary = int(brow.get("is_primary") or 0)
			is_shipping = int(brow.get("is_shipping") or 0)
			# Type/suffix from the ROW's own ticks (not the deduped Address's type) so a
			# shared address used for both billing and shipping is offered in both.
			addr_type = "Billing" if is_primary else ("Shipping" if is_shipping else "Billing")
			suffix = "Billing" if is_primary else ("Shipping" if is_shipping else "Address")
			if multi and obm.customer and obm.customer != customer:
				suffix += " — " + owner_names.get(obm.customer, obm.customer)
			display = "{} ({})".format(value, suffix)
			# Collapse identical entries — same owner + same address text + same
			# Primary/Shipping role — that repeated Buyer Address rows can produce.
			key = (obm.customer, value, is_primary, is_shipping)
			if key in seen:
				continue
			seen.add(key)
			out.append(frappe._dict({
				"name": addr_name,
				"value": value,
				"display": display,
				"address_line1": addr.get("address_line1"),
				"address_line2": addr.get("address_line2"),
				"city": addr.get("city"),
				"state": addr.get("state"),
				"country": addr.get("country"),
				"pincode": addr.get("pincode"),
				"custom_site_name": addr.get("custom_site_name"),
				"address_type": addr_type,
				"is_primary": is_primary,
				"is_shipping": is_shipping,
				"site_name": _nz(brow.get("site_name")),
				"buyer_master": obm.name,
			}))

	return out


def upsert_buyer_catalog_selling_rate(customer, item_code, selling_rate, mrp=None):
	"""Persist the SO line's Selling Price into the buyer's catalogue (Buyer Items).

	Creates the catalogue in the backend when the buyer doesn't have one yet —
	without it the next rate fetch falls back to MRP and the entered price is
	lost (get_offline_buyer_item_rate only returns a stored selling_rate)."""
	selling_rate = flt(selling_rate, 2)
	if not customer or not item_code or selling_rate <= 0:
		return
	if not frappe.db.exists("Buyer Master", {"customer": customer}):
		return

	obi_name = frappe.db.get_value(
		"Buyer Items", {"buyer": customer, "docstatus": ("<", 2)}, "name",
		order_by="modified desc",
	)
	if obi_name:
		doc = frappe.get_doc("Buyer Items", obi_name)
	else:
		doc = frappe.new_doc("Buyer Items")
		doc.title = "{} Catalogue".format(
			frappe.db.get_value("Customer", customer, "customer_name") or customer
		)
		doc.buyer = customer

	mrp = flt(mrp)
	margin = flt((1 - selling_rate / mrp) * 100, 2) if mrp > 0 else 0.0
	row = next((r for r in doc.get("items") or [] if r.item_code == item_code), None)
	if row:
		if flt(row.selling_rate, 2) == selling_rate and (not mrp or flt(row.mrp, 2) == mrp):
			return  # unchanged — don't churn the catalogue's modified stamp
		row.selling_rate = selling_rate
		if mrp:
			row.mrp = mrp
			row.margin_percent = margin
	else:
		doc.append("items", {
			"item_code": item_code,
			"selling_rate": selling_rate,
			"mrp": mrp or 0,
			"margin_percent": margin,
		})

	doc.flags.ignore_permissions = True
	doc.flags.ignore_mandatory = True
	if doc.is_new():
		doc.insert()
	else:
		doc.save()


def update_offline_buyer_margin_if_changed(customer, item_code, new_margin):
	"""If the Flat Disc % on the Sales Order differs from the Buyer Margin/Catalog, update the master."""
	new_margin = flt(new_margin, 2)
	if new_margin <= 0:
		return
	obm_name = frappe.db.get_value("Buyer Master", {"customer": customer}, "name")
	if not obm_name:
		return

	# 1. Update in Buyer Items (Catalog)
	obi_list = frappe.db.get_all("Buyer Items", {"buyer": customer, "docstatus": ("<", 2)}, order_by="modified desc")
	for obi in obi_list:
		frappe.db.sql("""
			UPDATE `tabBuyer Item`
			SET margin_percent = %s
			WHERE parent = %s AND item_code = %s AND IFNULL(margin_percent, 0) != %s
		""", (new_margin, obi.name, item_code, new_margin))

	# 2. Update in Buyer Master (Margin table)
	doc = frappe.get_doc("Buyer Master", obm_name)
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
		# Background margin sync during SO creation — must not trip mandatory
		# fields (e.g. Channel) missing on legacy Buyer Master rows.
		doc.flags.ignore_mandatory = True
		doc.save()


def validate_sales_order_offline_buyer_customer(doc, method=None):
	"""Ensure Sales Order customer is linked to an Buyer Master (UI also restricts the link)."""
	if doc.docstatus != 0:
		return
	if getattr(doc.flags, "ignore_offline_buyer_customer_check", False):
		return
	if not doc.customer:
		return
	if frappe.db.exists("DocType", "Buyer Master") and not frappe.db.exists(
		"Buyer Master", {"customer": doc.customer}
	):
		frappe.throw(
			_("Customer {0} is not linked to an Buyer Master. Only offline-buyer customers can be selected.").format(
				frappe.bold(doc.customer)
			),
			title=_("Invalid Customer"),
		)
