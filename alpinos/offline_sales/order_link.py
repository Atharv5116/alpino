"""Buyer Order Request link and the no-login order request page (doc Section 2, W3).

Every Approved Buyer Master can get a tokenized URL (/order-request?token=...) that its
buyer opens without logging in. The buyer sees only their own details, permitted addresses
and active Finished Goods with read-only prices, enters quantities and submits. Each new
submission gets a BOR-2627-##### reference and creates one Draft Quotation (Source = Buyer
Order Request Form); there is no separate Buyer Order Request record (doc L1209-1210).
The document routes it to a Draft Opportunity; the Opportunity is skipped since 20 Nov 2026
(Hetvi), so everything the document says of that Opportunity applies to the Quotation.

Link section on Buyer Master (doc 2.3): Generate / Copy / Open / Regenerate / Deactivate /
Activate. Statuses Not Generated, Active, Inactive, Expired. The doc defines no expiry rule,
so a link is never expired automatically; an Expired link is refused like an inactive one.

Every guest call re-checks the token, the link and the buyer on the server, prices are
always recomputed here (the page's values are never trusted), and calls are rate limited.
"""

import re
import secrets

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import cint, flt, get_url, now_datetime, nowdate

from alpinos.offline_sales import MANAGER_ROLES, audit

TOKEN_FIELD = "order_link_token"
STATUS_FIELD = "order_link_status"
NOT_GENERATED, ACTIVE, INACTIVE, EXPIRED = "Not Generated", "Active", "Inactive", "Expired"
SOURCE_PORTAL = "Buyer Order Request Form"
BOR_SERIES = "BOR-2627-.#####"

# doc messages (verbatim)
MSG_LINK_INACTIVE = "This order request link is no longer active. Please contact your assigned Sales Person from our Sales Team."
MSG_NO_PRODUCTS = "Please add at least one product to submit your order request."
MSG_ACK_FOOTER = "This is an order request acknowledgement, not a final commercial tax invoice/quotation."

_TOKEN_RE = re.compile(r"^[0-9a-f]{64}$")
# guest calls: per IP, generous enough for a buyer filling a long order, tight enough for scripts
_GUEST_LIMIT, _GUEST_WINDOW = 120, 60


# ------------------------------------------------------------------------------ link (desk)


def link_url(token):
	return get_url(f"/order-request?token={token}") if token else ""


def _manager_only():
	roles = set(frappe.get_roles())
	if frappe.session.user != "Administrator" and not roles & set(MANAGER_ROLES):
		frappe.throw(_("Only a Sales Manager or Sales Admin can manage the Buyer Order Request Link."), frappe.PermissionError)


def _approved_buyer(buyer):
	doc = frappe.get_doc("Buyer Master", buyer)
	doc.check_permission("read")
	if doc.get("buyer_status") != "Approved":
		frappe.throw(_("A Buyer Order Request Link can be generated only for an Approved Buyer."))
	return doc


def _set(buyer, values):
	frappe.db.set_value("Buyer Master", buyer, values, update_modified=False)


def _new_token():
	while True:
		token = secrets.token_hex(32)  # 64 characters
		if not frappe.db.exists("Buyer Master", {TOKEN_FIELD: token}):
			return token


def _issue(buyer):
	token = _new_token()
	_set(buyer, {
		TOKEN_FIELD: token,
		"order_link_url": link_url(token),
		STATUS_FIELD: ACTIVE,
		"order_link_generated_on": now_datetime(),
		"order_link_generated_by": frappe.session.user,
	})
	return token


def _state(buyer):
	return frappe.db.get_value("Buyer Master", buyer, [TOKEN_FIELD, STATUS_FIELD], as_dict=True)


@frappe.whitelist()
def generate_link(buyer):
	"""Generate Buyer Order Link: Approved buyer, no link yet (doc 2.4)."""
	_manager_only()
	_approved_buyer(buyer)
	if _state(buyer).get(TOKEN_FIELD):
		frappe.throw(_("A link already exists for this Buyer. Use Regenerate Link to replace it."))
	_issue(buyer)
	audit.log("Buyer Master", buyer, "Buyer Link Generated", "Link Status", NOT_GENERATED, ACTIVE)
	return link_info(buyer)


@frappe.whitelist()
def regenerate_link(buyer):
	"""Regenerate Link: a new token; the old one stops working at once."""
	_manager_only()
	_approved_buyer(buyer)
	old = _state(buyer)
	_issue(buyer)
	masked = ("..." + old[TOKEN_FIELD][-6:]) if old.get(TOKEN_FIELD) else ""
	audit.log(
		"Buyer Master", buyer, "Buyer Link Regenerated (Old Token Deactivated)", "Buyer Order Request Link",
		masked, "new link generated",
	)
	return link_info(buyer)


@frappe.whitelist()
def deactivate_link(buyer):
	_manager_only()
	_approved_buyer(buyer)
	if _state(buyer).get(STATUS_FIELD) != ACTIVE:
		frappe.throw(_("Only an Active link can be deactivated."))
	_set(buyer, {STATUS_FIELD: INACTIVE})
	audit.log("Buyer Master", buyer, "Buyer Link Deactivated", "Link Status", ACTIVE, INACTIVE)
	return link_info(buyer)


@frappe.whitelist()
def activate_link(buyer):
	_manager_only()
	_approved_buyer(buyer)
	if _state(buyer).get(STATUS_FIELD) != INACTIVE:
		frappe.throw(_("Only an Inactive link can be activated."))
	_set(buyer, {STATUS_FIELD: ACTIVE})
	audit.log("Buyer Master", buyer, "Buyer Link Reactivated", "Link Status", INACTIVE, ACTIVE)
	return link_info(buyer)


@frappe.whitelist()
def link_info(buyer):
	"""What the Buyer Master form needs for the link buttons (no token to anyone who cannot read)."""
	doc = frappe.get_doc("Buyer Master", buyer)
	doc.check_permission("read")
	token = doc.get(TOKEN_FIELD)
	return {
		"url": link_url(token) if token else "",
		"status": doc.get(STATUS_FIELD) or NOT_GENERATED,
		"approved": doc.get("buyer_status") == "Approved",
		"manager": frappe.session.user == "Administrator" or bool(set(frappe.get_roles()) & set(MANAGER_ROLES)),
	}


# ------------------------------------------------------------------------------ token -> buyer


class LinkRefused(Exception):
	"""Any reason the page must show only the 'no longer active' message."""


def resolve(token):
	"""The Buyer Master behind a usable token, or LinkRefused (one message for every reason)."""
	token = (token or "").strip().lower()
	if not _TOKEN_RE.match(token):
		raise LinkRefused
	name = frappe.db.get_value("Buyer Master", {TOKEN_FIELD: token}, "name")
	if not name:
		raise LinkRefused
	buyer = frappe.get_doc("Buyer Master", name)
	# the link must be Active, and the buyer Approved: Inactive / Cancelled buyers are refused
	# whatever the link says (doc L1363), and an On Hold buyer cannot take new requests (L2762)
	if buyer.get(STATUS_FIELD) != ACTIVE or buyer.get("buyer_status") != "Approved" or not buyer.get("customer"):
		raise LinkRefused
	return buyer


class _AsSystem:
	"""Guest calls read pricing / addresses and write the Quotation as the system. Company
	scoping still applies through the buyer's own company (_company)."""

	def __enter__(self):
		self.user = frappe.session.user
		frappe.set_user("Administrator")
		return self

	def __exit__(self, *exc):
		frappe.set_user(self.user)
		return False


def _guest(token):
	try:
		return resolve(token)
	except LinkRefused:
		frappe.throw(_(MSG_LINK_INACTIVE), frappe.PermissionError, title=_("Link not active"))


def _company(buyer):
	from alpinos.company_scope import registry

	scope = buyer.get(registry.SCOPE_FIELD) or ""
	companies = [c for c in scope.split("|") if c]
	return companies[0] if companies else frappe.defaults.get_global_default("company")


# ------------------------------------------------------------------------------ page data


def _addresses(buyer):
	"""Billing and shipping choices of the buyer: [{address, site, label, gstin}].

	Per Site where the buyer has Site Names; a buyer without any (most of them) offers its
	own billing / shipping addresses, as the Sales Order entry page does."""
	from alpinos.sales_order_offline_buyer import _gst_for_site, get_customer_family_sites, site_address_options

	customer = buyer.customer
	own_gstin = (buyer.get("gst_no") or "") if not buyer.get("parent_buyer") else ""
	billing, shipping, seen_b, seen_s = [], [], set(), set()
	for site in (get_customer_family_sites(customer) or []) + [None]:
		b, s, _every = site_address_options(customer, site)
		gstin = (_gst_for_site(site, customer=customer) if site else "") or own_gstin
		for name in b:
			if name not in seen_b:
				seen_b.add(name)
				billing.append({"address": name, "site": site or "", "label": _address_label(name, site), "gstin": gstin})
		for name in s:
			if name not in seen_s:
				seen_s.add(name)
				shipping.append({"address": name, "site": site or "", "label": _address_label(name, site)})
	return billing, shipping


def _address_label(name, site):
	a = frappe.db.get_value("Address", name, ["address_line1", "city", "pincode"], as_dict=True) or {}
	parts = [p for p in (a.get("address_line1"), a.get("city"), a.get("pincode")) if p and p != "N/A"]
	return f"{site}: {', '.join(parts)}" if site else ", ".join(parts)


def page_context(token):
	"""Everything the page shows for a usable token (called by www/order-request.py)."""
	buyer = resolve(token)
	with _AsSystem():
		billing, shipping = _addresses(buyer)
		return {
			"customer": buyer.customer_business_name or buyer.customer,
			"customer_type": buyer.customer_type or "",
			"contact_person": buyer.get("contact_person") or "",
			"billing": billing,
			"shipping": shipping,
			"requests": _editable_requests(buyer),
		}


DOCTYPE = "Quotation"


def _editable_requests(buyer):
	"""This buyer's portal requests, newest first; editable while the Quotation is a Draft."""
	if not frappe.db.has_column(DOCTYPE, "custom_buyer_order_request_ref"):
		return []
	rows = frappe.get_all(
		DOCTYPE,
		filters={"quotation_to": "Buyer Master", "party_name": buyer.name, "custom_quotation_source": SOURCE_PORTAL},
		fields=["custom_buyer_order_request_ref as bor", "custom_quotation_status", "docstatus", "creation", "name"],
		order_by="creation desc",
		limit_page_length=20,
	)
	return [
		{"bor": r.bor, "on": str(r.creation)[:16], "editable": _editable(r), "total": _total(r.name)}
		for r in rows
	]


def _editable(quotation):
	"""Doc Section 2, 6.2: while the request is still a Draft (Hetvi, 20 Nov 2026: "While Draft")."""
	# the Quotation Status, never ERPNext's own status field (which stays "Draft")
	return quotation.get("custom_quotation_status") == "Draft" and cint(quotation.get("docstatus")) == 0


def _total(quotation):
	return flt(sum(r.amount for r in _quotation_rows(quotation)), 2)


def _quotation_rows(quotation):
	"""Rows as the page showed them: Item Amount = Quantity x Selling Price (the Quotation's own
	line amount is net of the GST that the Selling Price includes)."""
	return [
		frappe._dict(item_code=r.item_code, qty=flt(r.qty), amount=flt(flt(r.qty) * flt(r.custom_selling_price), 2))
		for r in frappe.get_all(
			"Quotation Item", filters={"parent": quotation, "parenttype": DOCTYPE},
			fields=["item_code", "qty", "custom_selling_price"], order_by="idx",
		)
	]


# ------------------------------------------------------------------------------ products + prices


def _visible_items_sql(customer_type, txt=None, names=None):
	"""Product Visibility Logic (doc 3.3): active Finished Goods (any FG group) that this
	Customer Type / Channel may buy; the Buyer Catalog never hides an item. Never stock."""
	from alpinos.production.material_type import FG, sql_in_types

	params = {"ct": customer_type or "", "chan": frappe.db.get_value("Alpino Customer Type", customer_type, "channel") if customer_type else ""}
	cond = [
		"i.disabled = 0",
		"i.is_sales_item = 1",
		"i.has_variants = 0",
		"(i.end_of_life IS NULL OR i.end_of_life >= CURDATE())",
		sql_in_types("i", FG),
		"""(
			(NOT EXISTS (SELECT 1 FROM `tabItem Allowed Customer Type` t WHERE t.parent = i.name)
			 AND NOT EXISTS (SELECT 1 FROM `tabItem Allowed Channel` c WHERE c.parent = i.name))
			OR EXISTS (SELECT 1 FROM `tabItem Allowed Customer Type` t WHERE t.parent = i.name AND t.customer_type = %(ct)s)
			OR EXISTS (SELECT 1 FROM `tabItem Allowed Channel` c WHERE c.parent = i.name AND c.channel = %(chan)s)
		)""",
	]
	if txt:
		params["txt"] = f"%{txt}%"
		cond.append("(i.name LIKE %(txt)s OR i.item_name LIKE %(txt)s)")
	if names is not None:
		if not names:
			return None, None
		params["names"] = tuple(names)
		cond.append("i.name IN %(names)s")
	return " AND ".join(cond), params


def visible_items(buyer, txt=None, names=None, limit=30):
	from alpinos.company_scope import registry

	where, params = _visible_items_sql(buyer.customer_type, txt, names)
	if where is None:
		return []
	company = _company(buyer)
	params["scope"] = f"%|{company}|%"
	params["limit"] = cint(limit)
	# company-scope: n/a (guest page: restricted to the buyer's own company explicitly below)
	return frappe.db.sql(
		f"""
		SELECT i.name AS item_code, i.item_name, i.image
		FROM `tabItem` i
		WHERE {where}
			AND (IFNULL(i.`{registry.SCOPE_FIELD}`, '') = '' OR i.`{registry.SCOPE_FIELD}` LIKE %(scope)s)
		ORDER BY i.item_name
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)


def price(customer, item_code, qty=0):
	"""Read-only pricing of one product (doc 3.4): Buyer Catalog where configured, otherwise
	MRP with 0% Flat Discount (the row is never blocked). Same lookup as the Sales Order."""
	from alpinos import item_mrp as IM
	from alpinos.sales_order_offline_buyer import get_offline_buyer_item_rate

	info = IM.applicable(item_code)
	mrp = IM.q(info.mrps[-1]) if info.tracked and info.mrps else None  # the current (highest) active MRP
	rate = get_offline_buyer_item_rate(customer, item_code, mrp if info.tracked else None)
	if rate and rate.get("rate") not in (None, ""):
		mrp = flt(mrp if info.tracked else rate.get("mrp"))
		flat, selling = flt(rate.get("margin_percent")), flt(rate.get("rate"))
	else:
		mrp = flt(mrp) if info.tracked else flt(frappe.db.get_value("Item", item_code, "valuation_rate"))
		flat, selling = 0.0, mrp
	return {"mrp": mrp, "flat_discount": flat, "selling_price": selling, "amount": flt(cint(qty) * selling, 2)}


def _priced_rows(buyer, rows):
	"""Validated, server-priced rows: [{item_code, item_name, qty, mrp, flat_discount, selling_price, amount}]."""
	wanted = [r for r in (rows or []) if (r.get("item_code") or "").strip()]
	if not wanted:
		frappe.throw(_(MSG_NO_PRODUCTS))
	codes = list({r["item_code"].strip() for r in wanted})
	allowed = {i.item_code: i for i in visible_items(buyer, names=codes, limit=len(codes) or 1)}
	out = []
	for r in wanted:
		code = r["item_code"].strip()
		if code not in allowed:
			frappe.throw(_("SKU {0} is not available for ordering.").format(code))
		raw = r.get("qty")
		qty = flt(raw)
		if qty <= 0 or qty != cint(qty):
			frappe.throw(_("Quantity for SKU [{0}] must be greater than zero.").format(code))
		p = price(buyer.customer, code, cint(qty))
		# Changes(HP) #123: the row keeps its Product Image, also when a submitted request is reopened
		out.append(dict(item_code=code, item_name=allowed[code].item_name, image=allowed[code].get("image"), qty=cint(qty), **p))
	return out


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=_GUEST_LIMIT, seconds=_GUEST_WINDOW)
def search_products(token, txt=""):
	buyer = _guest(token)
	with _AsSystem():
		items = visible_items(buyer, txt=(txt or "").strip()[:60] or None)
		for i in items:
			i.update(price(buyer.customer, i.item_code))
		return items


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=_GUEST_LIMIT, seconds=_GUEST_WINDOW)
def quote_rows(token, rows):
	"""Prices and totals for the rows on the page (display only; submit recomputes)."""
	buyer = _guest(token)
	rows = frappe.parse_json(rows) if isinstance(rows, str) else rows
	with _AsSystem():
		priced = _priced_rows(buyer, rows)
		sub = flt(sum(r["amount"] for r in priced), 2)
		return {"rows": priced, "sub_total": sub, "net_total": sub}


# ------------------------------------------------------------------------------ submit / edit


def _header(buyer, data):
	billing, shipping = _addresses(buyer)
	b = next((x for x in billing if x["address"] == data.get("billing_address")), None)
	s = next((x for x in shipping if x["address"] == data.get("shipping_address")), None)
	if not b or not s:
		frappe.throw(_("Select a Billing Address and a Shipping Address from the list."))
	contact = (data.get("contact_person") or "").strip()[:140]
	return {
		"site": b["site"],
		"billing_address": b["address"],
		"shipping_address": s["address"],
		"contact_person": contact,
		"remarks": (data.get("remarks") or "").strip()[:2000],
	}


def _apply(qtn, buyer, header, rows):
	"""Doc 5.1, carried forward onto the Draft Quotation: addresses, site, the buyer's remarks
	(Quotation Remarks), the contact person, "Buyer Portal - name", and the rows (SKU, quantity,
	the MRP the page priced; the Quotation prices them as the page did, from the Buyer Catalog)."""
	from frappe.contacts.doctype.address.address import get_address_display

	qtn.update({
		"custom_site_name": header["site"],
		"customer_address": header["billing_address"],
		"address_display": get_address_display(header["billing_address"]),
		"shipping_address_name": header["shipping_address"],
		"shipping_address": get_address_display(header["shipping_address"]),
		"custom_quotation_remarks": header["remarks"],
		"custom_request_contact_person": header["contact_person"],
		"custom_source_display": "Buyer Portal – {0}".format(header["contact_person"]) if header["contact_person"] else "Buyer Portal",
	})
	qtn.set("items", [])
	for r in rows:
		qtn.append("items", {"item_code": r["item_code"], "item_name": r["item_name"], "qty": r["qty"]})
	_fill_item_details(qtn, buyer)
	# the Buyer Catalog values the page showed (the same lookup as the Sales Order); the form puts
	# them on a new row the same way before it saves (ERPNext's item details would leave 0.00)
	for row, r in zip(qtn.items, rows):
		row.update({
			"custom_mrp": r["mrp"], "custom_flat_discount": r["flat_discount"], "custom_selling_price": r["selling_price"],
			"custom_offer": 0, "custom_additional_discount": 0,
		})


def _fill_item_details(qtn, buyer):
	"""ERPNext's item details (UOM, conversion, price list) for the rows. ERPNext reads a selling
	party, so it is shown the buyer's Customer for the call (as Convert to Quotation did)."""
	qtn.quotation_to, qtn.party_name = "Customer", buyer.customer
	try:
		qtn.run_method("set_missing_values")
	finally:
		qtn.quotation_to, qtn.party_name = "Buyer Master", buyer.name
	qtn.customer_name = buyer.customer_business_name or buyer.customer
	qtn.custom_resolved_customer = buyer.customer


def _row_text(qtn):
	return "; ".join(f"{r.item_code} x {cint(r.qty)}" for r in qtn.items)


def _request_values(qtn):
	return {
		"Billing Address": qtn.get("customer_address"), "Shipping Address": qtn.get("shipping_address_name"),
		"Contact Person": qtn.get("custom_request_contact_person"), "Quotation Remarks": qtn.get("custom_quotation_remarks"),
		"Items": _row_text(qtn),
	}


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=20, seconds=_GUEST_WINDOW)
def submit_request(token, data):
	"""New request: a new BOR reference and one Draft Quotation (doc 4.1-4.3, 5.1)."""
	buyer = _guest(token)
	data = frappe.parse_json(data) if isinstance(data, str) else (data or {})
	with _AsSystem():
		rows = _priced_rows(buyer, data.get("rows"))
		header = _header(buyer, data)
		from frappe.model.naming import make_autoname

		bor = make_autoname(BOR_SERIES)
		qtn = frappe.new_doc(DOCTYPE)
		qtn.update({
			"quotation_to": "Buyer Master",
			"party_name": buyer.name,
			"company": _company(buyer),
			"transaction_date": nowdate(),
			"order_type": buyer.customer_type,
			"ignore_pricing_rule": 1,
			"custom_quotation_source": SOURCE_PORTAL,
			"custom_buyer_order_request_ref": bor,
		})
		_apply(qtn, buyer, header, rows)
		qtn.flags.ignore_permissions = True
		qtn.flags.from_order_portal = True
		qtn.insert()
		frappe.db.set_value("Buyer Master", buyer.name, "order_link_last_used_on", now_datetime(), update_modified=False)
		audit.log(DOCTYPE, qtn.name, "Quotation Created", "Buyer Order Request Ref", None, bor, reason=qtn.custom_source_display)
		frappe.enqueue(
			"alpinos.offline_sales.order_link.after_submit", queue="short", enqueue_after_commit=True,
			quotation=qtn.name,
		)
		return {"bor": bor, "total": _total(qtn.name), "requests": _editable_requests(buyer)}


def _own_request(buyer, bor):
	"""This buyer's Quotation for `bor` (any status), or the inactive-link refusal."""
	name = frappe.db.get_value(
		DOCTYPE,
		{"quotation_to": "Buyer Master", "party_name": buyer.name, "custom_buyer_order_request_ref": bor, "custom_quotation_source": SOURCE_PORTAL},
		"name",
	)
	if not name:
		frappe.throw(_(MSG_LINK_INACTIVE), frappe.PermissionError)
	return frappe.get_doc(DOCTYPE, name)


def _own_draft(buyer, bor):
	qtn = _own_request(buyer, bor)
	if not _editable(qtn.as_dict()):
		frappe.throw(_("This order request is already being processed by our Sales Team and can no longer be changed."))
	return qtn


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=_GUEST_LIMIT, seconds=_GUEST_WINDOW)
def get_request(token, bor):
	"""A submitted request, for the buyer to edit while it is still a Draft."""
	buyer = _guest(token)
	with _AsSystem():
		qtn = _own_draft(buyer, bor)
		return {
			"bor": bor,
			"billing_address": qtn.get("customer_address"),
			"shipping_address": qtn.get("shipping_address_name"),
			"contact_person": qtn.get("custom_request_contact_person") or "",
			"remarks": qtn.get("custom_quotation_remarks") or "",
			"rows": [{"item_code": r.item_code, "qty": cint(r.qty)} for r in qtn.items],
		}


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=20, seconds=_GUEST_WINDOW)
def update_request(token, bor, data):
	"""Edit while the Quotation is a Draft: same BOR, same Quotation, every change in the
	Activity / Audit Trail (doc 6.2)."""
	buyer = _guest(token)
	data = frappe.parse_json(data) if isinstance(data, str) else (data or {})
	with _AsSystem():
		qtn = _own_draft(buyer, bor)
		before = _request_values(qtn)
		rows = _priced_rows(buyer, data.get("rows"))
		header = _header(buyer, data)
		_apply(qtn, buyer, header, rows)
		qtn.flags.ignore_permissions = True
		qtn.flags.from_order_portal = True
		qtn.save()
		after = _request_values(qtn)
		for label, old in before.items():
			if (old or "") != (after[label] or ""):
				audit.log(DOCTYPE, qtn.name, "Buyer Request Updated", label, old, after[label], reason=qtn.custom_source_display)
		frappe.db.set_value("Buyer Master", buyer.name, "order_link_last_used_on", now_datetime(), update_modified=False)
		return {"bor": bor, "total": _total(qtn.name), "requests": _editable_requests(buyer)}


# ------------------------------------------------------------------------------ PDF + notifications

ACK_PRINT_FORMAT = "Buyer Order Request Acknowledgement"
#: requests made before 20 Nov 2026 are Opportunities and keep their own acknowledgement
LEGACY_ACK_DOCTYPE = "Opportunity"


def ack_pdf(quotation, doctype=DOCTYPE):
	from alpinos.offline_sales.order_ack_print import print_format_for

	return frappe.get_print(doctype, quotation, print_format_for(doctype), as_pdf=True)


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=30, seconds=_GUEST_WINDOW)
def download_ack(token, bor):
	"""The acknowledgement PDF of one of this buyer's own requests."""
	buyer = _guest(token)
	with _AsSystem():
		doctype, name = DOCTYPE, frappe.db.get_value(
			DOCTYPE, {"quotation_to": "Buyer Master", "party_name": buyer.name, "custom_buyer_order_request_ref": bor,
				"custom_quotation_source": SOURCE_PORTAL}, "name"
		)
		if not name and frappe.db.has_column(LEGACY_ACK_DOCTYPE, "custom_buyer_order_request_ref"):
			doctype, name = LEGACY_ACK_DOCTYPE, frappe.db.get_value(
				LEGACY_ACK_DOCTYPE, {"party_name": buyer.name, "custom_buyer_order_request_ref": bor, "custom_opportunity_source": SOURCE_PORTAL}, "name"
			)
		if not name:
			frappe.throw(_(MSG_LINK_INACTIVE), frappe.PermissionError)
		frappe.local.response.filename = f"{bor}.pdf"
		frappe.local.response.filecontent = ack_pdf(name, doctype)
		frappe.local.response.type = "pdf"


def recipients(buyer):
	"""Users of the buyer's assigned Sales Officer(s), Primary POC(s) and Secondary POC (doc 5)."""
	employees = set()
	for child in ("Buyer Sales Officer", "Buyer Primary POC"):
		employees.update(frappe.get_all(child, filters={"parent": buyer, "parenttype": "Buyer Master"}, pluck="employee"))
	sec = frappe.db.get_value("Buyer Master", buyer, "secondary_poc")
	if sec:
		employees.add(sec)
	employees.discard(None)
	if not employees:
		return []
	return sorted(set(frappe.get_all("Employee", filters={"name": ("in", list(employees)), "user_id": ("is", "set")}, pluck="user_id")))


def after_submit(quotation):
	"""After the request is saved: internal in-app + email (doc 7.1, linking to the Quotation)
	and the buyer's email with the acknowledgement PDF (doc 5.2, 7.2). Never raises: the request
	itself is already saved."""
	try:
		qtn = frappe.get_doc(DOCTYPE, quotation)
		buyer = frappe.get_doc("Buyer Master", qtn.party_name)
		bor = qtn.custom_buyer_order_request_ref
		units = cint(sum(flt(r.qty) for r in qtn.items))
		total = frappe.utils.fmt_money(_total(qtn.name), currency="INR")
		subject = (
			f"New Buyer Order Request {bor} submitted by {buyer.customer_business_name or buyer.customer} "
			f"({units} units, Total: {total}). Click to review Quotation."
		)
		from alpinos.production.notify import notify

		notify([], subject, doctype=DOCTYPE, name=qtn.name, email=True, users=recipients(buyer.name))
		if buyer.get("email"):
			frappe.sendmail(
				recipients=[buyer.email],
				subject=_("Order request {0} received").format(bor),
				message=_("Your order request {0} has been received. Attached is your acknowledgement PDF.").format(bor),
				attachments=[{"fname": f"{bor}.pdf", "fcontent": ack_pdf(qtn.name)}],
				reference_doctype=DOCTYPE,
				reference_name=qtn.name,
			)
	except Exception:
		frappe.log_error(title=f"Buyer Order Request notifications failed for {quotation}")
