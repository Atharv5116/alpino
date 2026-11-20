"""The Quotation ("Opportunity to Sales Order v1.0.0", Section 5; W5): status flow, commercial
values, Finalize and Cancel. Payments are alpinos.offline_sales.quotation_payments.

Quotation Status (custom_quotation_status; ERPNext's own `status` is left to ERPNext):

    Draft                created by Convert to Quotation on an Opportunity, or Standalone
    Negotiation          Start Negotiation (Sales Officer / Sales Manager / Sales Admin)
    Finalized            Finalize Quotation (Sales Manager / Sales Admin): the Quotation is
                         submitted, which locks its commercial values; Finalized By / On stamped;
                         a converted Opportunity becomes Won or Partial (offline_sales.opportunity)
    Sales Order Created  its Sales Order exists (offline_sales.so_handoff, W7)
    Cancelled            Cancel Quotation (Sales Manager / Sales Admin), mandatory reason. A Draft or
                         Negotiation one is discarded, a Finalized one cancelled (docstatus 2 both),
                         so it is read only and no longer the Opportunity's active Quotation; its
                         Opportunity returns to Pending (Submitted) for a new Quotation (A-46)

Payment Status, SO Eligibility and Force Complete are separate values (quotation_payments) and
never change the Quotation Status (S5-R72).

Commercial values are priced exactly as the Sales Order prices them (sales_order_api: the
Selling Price is GST inclusive, the Buyer Catalog price at the line's MRP, Round Off Per Unit,
GST-exclusive buyers, the tax template of the billing state, Cash Discount on the Grand Total).
A Sales Officer may add / remove SKUs and change quantities; Selling Price, the three discounts
and Cash Discount are the Sales Manager's or Sales Admin's (S5-R28, A-35).
"""

import re

import frappe
from frappe import _
from frappe.utils import add_days, cint, cstr, flt, getdate, now_datetime, today

from alpinos.alpinos_development.doctype.field_change_log.field_change_log import acting_role, log_field_change
from alpinos.offline_sales import audit, is_manager, is_sales_officer_only

DOCTYPE = "Quotation"
STATUS = "custom_quotation_status"

DRAFT = "Draft"
NEGOTIATION = "Negotiation"
FINALIZED = "Finalized"
SO_CREATED = "Sales Order Created"
CANCELLED = "Cancelled"
EDITABLE = (DRAFT, NEGOTIATION)
OPEN = (FINALIZED, SO_CREATED)

TERMS = ("Advance", "Credit", "Partial")

#: set only by the actions here, in quotation_payments and by the Sales Order hand-off
SYSTEM_FIELDS = (
	STATUS, "custom_finalized_by", "custom_finalized_on", "custom_linked_sales_order",
	"custom_cancellation_reason", "custom_cancelled_by", "custom_cancelled_by_role", "custom_cancelled_on",
	"custom_force_complete_applied", "custom_force_complete_reason", "custom_force_completed_by",
	"custom_force_completed_role", "custom_force_completed_on", "custom_force_complete_unpaid",
)
#: written only by the Buyer Order Request Form (order_link); every other Quotation is Direct
SOURCE_DIRECT, SOURCE_PORTAL = "Direct Quotation", "Buyer Order Request Form"
REQUEST_FIELDS = (
	"custom_quotation_source", "custom_buyer_order_request_ref", "custom_request_contact_person", "custom_source_display",
)
#: recomputed on every save (quotation_payments.recompute)
DERIVED_FIELDS = (
	"custom_total_received", "custom_total_pending", "custom_payment_status", "custom_so_eligibility",
	"custom_payment_process",
)
#: the payment arrangement: free before Finalize, after it only through the payment actions
PAYMENT_FIELDS = ("custom_payment_term", "custom_credit_days", "custom_expected_payment_date", "custom_payment_schedule")
RECEIPTS = "custom_payment_receipts"
#: header values that are part of the commercial agreement (some are allow-on-submit in ERPNext /
#: India Compliance, so the Finalize lock names them)
COMMERCIAL_AFTER_SUBMIT = (
	"customer_address", "address_display", "shipping_address_name", "shipping_address", "billing_address_gstin",
	"place_of_supply", "gst_category", "lost_reasons", "competitors", "order_lost_reason",
)
RESTRICTED_ITEM_FIELDS = (
	("custom_selling_price", "Selling Price"),
	("custom_flat_discount", "Flat Discount %"),
	("custom_offer", "Offer Discount %"),
	("custom_additional_discount", "Additional Discount %"),
)
ITEM_TABLES = (
	("items", "Order Items"),
	("custom_marketing_freebies", "Marketing Freebies"),
	("custom_scheme_item_table", "Scheme Items"),
	("custom_additional_units_damage_items", "Additional Unit / Damage"),
)

# messages the document gives word for word
M_ACTIVE_QUOTATION = (
	"An active Quotation [{0}] already exists for this Opportunity. Cancel the existing Quotation before creating "
	"another Quotation."
)
M_ZERO_QTY = "Quantity for SKU [{0}] must be greater than zero."
M_TERM_REQUIRED = "Payment Term is mandatory. Select Advance, Credit, or Partial."
#: Section 2, 7.2 Buyer External Notifications, "Quotation Finalized" (Email + PDF, Confirmed)
M_BUYER_FINALIZED = "Your Quotation {0} has been finalized. Review the attached terms."
# messages written for this build (the document gives the rule, not the words)
M_SO_PRICE = "A Sales Officer cannot change Selling Price or discounts on a Quotation. The Sales Manager or Sales Admin does."
M_FINALIZE_ROLE = "Only a Sales Manager or Sales Admin can finalize a Quotation."
M_CANCEL_ROLE = "Only a Sales Manager or Sales Admin can cancel a Quotation."
M_LOCKED = "This Quotation is Finalized. Its commercial values are locked."
M_FC_READ_ONLY = "This Quotation was Force Completed and is read-only."
M_CANCELLED_READ_ONLY = "This Quotation is Cancelled and is read-only."
M_CANCEL_SO = "Cancel Sales Order {0} first, through its existing cancellation flow."
M_REASON = "Enter the reason."
M_STATUS_SYSTEM = "Quotation Status and its stamps change only through the Quotation's actions."
M_PAYMENT_ACTIONS = (
	"After Finalize, the payment details change only through the payment actions (Record Payment, Change "
	"Payment Term, Change Expected Payment Date, Revise Payment Schedule, Convert to Partial, Force Complete)."
)
M_SUBMITTED_PAYMENT = "A submitted payment cannot be changed. Only a System Manager can correct it, with a reason."
M_NO_DRAFT_PAYMENT = "Payments can be recorded once the Quotation is Finalized."
M_USE_FINALIZE = "Use Finalize Quotation to finalize a Quotation."
M_USE_CANCEL = "Use Cancel Quotation to cancel a Quotation."
M_RSO_ROLE = "Only a Sales Manager or Sales Admin can change the Responsible Sales Officer."


# ----------------------------------------------------------------------------- helpers


def status_of(doc):
	value = doc.get(STATUS) if doc else None
	if value:
		return value
	docstatus = cint(doc.get("docstatus")) if doc else 0
	return {1: FINALIZED, 2: CANCELLED}.get(docstatus, DRAFT)


def is_actor(user=None):
	from alpinos.offline_sales.opportunity import is_actor as _is_actor

	return _is_actor(user)


def assert_actor():
	if not is_actor():
		frappe.throw(
			_("Only a Sales Officer, Sales Manager or Sales Admin can do this."),
			frappe.PermissionError,
			title=_("Not Permitted"),
		)


def customer_of(doc):
	customer = doc.get("custom_resolved_customer")
	if not customer and doc.get("quotation_to") == "Customer":
		customer = doc.get("party_name")
	if not customer and doc.get("quotation_to") == "Buyer Master" and doc.get("party_name"):
		customer = frappe.db.get_value("Buyer Master", doc.party_name, "customer")
	return customer


def buyer_of(doc):
	from alpinos.offline_sales.catalog_gate import quotation_buyer

	return doc.get("custom_buyer_master") or quotation_buyer(doc)


def money(value):
	return "₹" + frappe.utils.fmt_money(flt(value, 2), 2)


def _blank(value):
	return value is None or cstr(value).strip() == ""


def _same(a, b):
	return abs(flt(a, 2) - flt(b, 2)) < 0.005


def _value(doc, field, meta=None):
	"""A field's value in a comparable form (the form sends 100 where the database gave 100.0)."""
	from alpinos.offline_sales.opportunity import _norm

	df = (meta or frappe.get_meta(DOCTYPE)).get_field(field)
	return _norm(doc.get(field), df.fieldtype if df else "Data")


def credit_days_of(value):
	"""Buyer Master Payment Term Days is free text: its leading number, else None (A-6)."""
	m = re.match(r"\s*(\d+)", cstr(value))
	return cint(m.group(1)) if m else None


def get(name):
	"""The Quotation for an action, locked for this request; the caller must be able to read it
	(Buyer assignment decides who sees which Quotation)."""
	doc = frappe.get_doc(DOCTYPE, name, for_update=True)
	doc.check_permission("read")
	return doc


def save(doc, action):
	"""Save after an action: the action itself checked role and state (a Sales Officer holds no
	submit right, and Frappe needs it to update a Finalized Quotation, A-2)."""
	doc.flags.alpinos_quotation_action = action
	doc.flags.ignore_permissions = True
	doc.flags.ignore_mandatory = True
	if doc.docstatus == 2:
		# a System Manager correction on a cancelled Quotation (A-15): Frappe saves no cancelled
		# document, so the corrected rows and totals are written directly
		from alpinos.offline_sales.quotation_payments import recompute

		recompute(doc)
		doc.db_update_all()
		doc.notify_update()
		return doc
	doc.save()
	return doc


def system_log(name, action, field, old, new):
	"""A trail entry the system makes (Done By: System)."""
	log_field_change(DOCTYPE, name, field, old, new, after_submit=0, action=action, user_role="System", reason=None)


# ----------------------------------------------------------------------------- pricing


def _item_gst(item_code):
	return flt(frappe.db.get_value("Item", item_code, "custom_gst_percent")) if item_code else 0


def _gst_exclusive(doc, customer):
	"""GST-Exclusive Buyer, site-wise, as the Sales Order takes it."""
	from alpinos.sales_order_offline_buyer import _flag_for_site

	if not customer:
		return 0
	fallback = frappe.db.get_value("Buyer Master", {"customer": customer}, "gst_exclusive_buyer")
	return cint(_flag_for_site(cstr(doc.get("custom_site_name")).strip(), "gst_exclusive_buyer", fallback, customer=customer))


def billing_gstin(customer, site_name):
	"""Billing GSTIN by the Sales Order's rule: the Site's GSTIN, else the buyer's own when it has
	no Parent Buyer (sales_order_offline_buyer.get_party_gstin)."""
	from alpinos.sales_order_offline_buyer import _gst_for_site

	if not customer:
		return ""
	row = frappe.db.get_value("Buyer Master", {"customer": customer}, ["gst_no", "parent_buyer"], as_dict=True)
	site_gst = (_gst_for_site(cstr(site_name).strip(), "", customer=customer) or "").strip().upper()
	if site_gst:
		return site_gst
	if row and not row.get("parent_buyer"):
		return (row.get("gst_no") or "").strip().upper()
	return ""


def price(doc, before=None):
	"""Draft / Negotiation: the Order Items and totals, as the Sales Order prices them.

	A new row, or a row whose SKU or MRP changed, takes the Buyer Catalog price (Flat Discount %,
	Selling Price; Offer and Additional 0) unless a Sales Manager / Sales Admin sent their own
	Selling Price. A Sales Officer's rows always take the catalogue's, and on an existing row the
	restricted values cannot change (S5-R28)."""
	from alpinos import item_mrp as IM
	from alpinos.offline_sales.opportunity import box_count, line_pricing
	from alpinos.sales_order_api import get_box_rounding_mode

	customer = customer_of(doc)
	officer = is_sales_officer_only()
	old_rows = {r.name: r for r in (before.get("items") if before else None) or [] if r.get("name")}
	mode = get_box_rounding_mode(customer, doc.get("custom_site_name"), doc.get("order_type"))
	for row in doc.get("items") or []:
		if not row.get("item_code"):
			continue
		old = old_rows.get(row.get("name"))
		fresh = not old or old.item_code != row.item_code or IM.q(old.get("custom_mrp")) != IM.q(row.get("custom_mrp"))
		if officer and not fresh:
			for field, _label in RESTRICTED_ITEM_FIELDS:
				if not _same(row.get(field), old.get(field)):
					frappe.throw(_(M_SO_PRICE), frappe.PermissionError, title=_("Not Permitted"))
		info = IM.applicable(row.item_code)
		p = line_pricing(customer, row.item_code, row.get("custom_mrp"))
		if info.tracked or fresh or not flt(row.get("custom_mrp")):
			row.custom_mrp = p.mrp
		if fresh and (officer or _blank(row.get("custom_selling_price"))):
			row.custom_flat_discount = p.flat
			row.custom_offer = 0
			row.custom_additional_discount = 0
			row.custom_selling_price = p.selling_price
		elif _blank(row.get("custom_selling_price")):
			row.custom_selling_price = flt(
				flt(row.custom_mrp) * (1 - flt(row.get("custom_flat_discount")) / 100.0) * (1 - flt(row.get("custom_offer")) / 100.0), 2
			)
		row.custom_buyer_margin_percent = flt(row.get("custom_flat_discount"))
		row.custom_discount_type = "Percentage"
		row.custom_additional_discount_type = "Percentage"
		row.custom_boxes = box_count(row.qty, row.item_code, mode)
		if not flt(row.get("custom_item_tax_percent")):
			row.custom_item_tax_percent = _item_gst(row.item_code)

	if officer:
		was = flt(before.get("custom_cash_discount")) if before else 0
		if not _same(doc.get("custom_cash_discount"), was):
			frappe.throw(_(M_SO_PRICE), frappe.PermissionError, title=_("Not Permitted"))
	engine(doc, customer)


def engine(doc, customer):
	"""sales_order_api.validate_sales_order_pricing on the Quotation. The Sales Order engine reads
	the Sales Order's field names (customer, custom_customer_mrp, custom_gst_percent,
	custom_gst_exclusive_buyer); they are lent to the Quotation for the call, never stored."""
	from alpinos.sales_order_api import get_tax_template_for_sales_order, validate_sales_order_pricing

	gst_exclusive = _gst_exclusive(doc, customer)
	if customer and not gst_exclusive:
		tax = get_tax_template_for_sales_order(
			customer, doc.get("company"), doc.get("customer_address"), doc.get("shipping_address_name")
		)
		if tax.get("tax_category"):
			doc.tax_category = tax["tax_category"]
		if tax.get("taxes_and_charges"):
			doc.taxes_and_charges = tax["taxes_and_charges"]
			doc.set("taxes", [])
			doc.append_taxes_from_master("Sales Taxes and Charges Template")

	lent = {"customer": customer, "custom_gst_exclusive_buyer": gst_exclusive}
	for key, value in lent.items():
		doc.__dict__[key] = value
	for row in doc.get("items") or []:
		row.__dict__["custom_customer_mrp"] = flt(row.get("custom_mrp"))
		row.__dict__["custom_gst_percent"] = flt(row.get("custom_item_tax_percent")) or _item_gst(row.get("item_code"))
	try:
		validate_sales_order_pricing(doc)
	finally:
		for key in lent:
			doc.__dict__.pop(key, None)
		for row in doc.get("items") or []:
			row.__dict__.pop("custom_customer_mrp", None)
			row.__dict__.pop("custom_gst_percent", None)

	# the old Quotation breakdown (hidden; earlier print formats read it)
	sub = over = extra = 0.0
	for row in doc.get("items") or []:
		qty, mrp, sp = flt(row.get("qty")), flt(row.get("custom_mrp")), flt(row.get("custom_selling_price"))
		sub += mrp * qty
		over += max(mrp - sp, 0) * qty
		extra += sp * qty * flt(row.get("custom_additional_discount")) / 100.0
	doc.custom_sub_total = flt(sub, 2)
	doc.custom_over_discount = flt(over, 2)
	doc.custom_additional_discount_total = flt(extra, 2)
	doc.custom_gst_total = flt(doc.get("total_taxes_and_charges"), 2)
	doc.custom_total_payable = flt(doc.get("grand_total"), 2)


@frappe.whitelist()
def line_values(party_name, item_code, qty=0, mrp=None, site_name=None, quotation_to="Buyer Master", order_type=None):
	"""For the form, right after an SKU, Quantity or MRP is entered: the catalogue values the
	server will price the row with."""
	# company-scope: n/a (pricing of one SKU for one Buyer; get_offline_buyer_item_rate follows the company)
	from alpinos.offline_sales.opportunity import box_count, line_pricing
	from alpinos.sales_order_api import _buyer_rounds_per_unit, get_box_rounding_mode

	if not (frappe.has_permission(DOCTYPE, "create") or frappe.has_permission(DOCTYPE, "write")):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	doc = frappe._dict(quotation_to=quotation_to, party_name=party_name)
	customer = customer_of(doc) if party_name else None
	p = line_pricing(customer, item_code, mrp)
	selling_price = flt(p.selling_price, 2)
	if _buyer_rounds_per_unit(customer) and selling_price:
		selling_price = round(selling_price)
	mode = get_box_rounding_mode(customer, site_name, order_type)
	return {
		"custom_mrp": p.mrp,
		"custom_flat_discount": p.flat,
		"custom_selling_price": selling_price,
		"custom_offer": 0,
		"custom_additional_discount": 0,
		"custom_boxes": box_count(qty, item_code, mode),
		"custom_item_tax_percent": _item_gst(item_code),
		"mrp_options": p.mrp_options,
		"needs_mrp": p.needs_mrp,
	}


# ----------------------------------------------------------------------------- defaults


def default_responsible_officer(doc):
	"""A-16: the creator when a Sales Officer; else the Opportunity's creator when a Sales
	Officer; else the Buyer's only assigned Sales Officer; else nobody."""
	me = frappe.session.user
	if me not in ("Administrator", "Guest") and is_sales_officer_only(me):
		return me
	if doc.get("opportunity"):
		creator = frappe.db.get_value("Opportunity", doc.opportunity, "custom_created_by") if frappe.db.has_column(
			"Opportunity", "custom_created_by"
		) else None
		if creator and frappe.db.exists("User", creator) and is_sales_officer_only(creator):
			return creator
	buyer = buyer_of(doc)
	if buyer:
		employees = frappe.get_all(
			"Buyer Sales Officer", filters={"parent": buyer, "parenttype": "Buyer Master"}, pluck="employee"
		)
		users = {
			u for u in frappe.get_all("Employee", filters={"name": ("in", employees or [""])}, pluck="user_id") if u
		}
		users = set(frappe.get_all("User", filters={"name": ("in", list(users) or [""]), "enabled": 1}, pluck="name"))
		if len(users) == 1:
			return users.pop()
	return None


def _set_defaults(doc):
	"""On creation only (9.1): Payment Term and Credit Days from the Buyer Master, the
	Responsible Sales Officer, today's date."""
	buyer = buyer_of(doc)
	row = frappe.db.get_value("Buyer Master", buyer, ["payment_term", "payment_term_days"], as_dict=True) if buyer else None
	if not doc.get("custom_payment_term"):
		term = (row or {}).get("payment_term")
		doc.custom_payment_term = term if term in TERMS else None
	if not cint(doc.get("custom_credit_days")) and row:
		doc.custom_credit_days = credit_days_of(row.get("payment_term_days"))
	if not doc.get("custom_responsible_sales_officer"):
		doc.custom_responsible_sales_officer = default_responsible_officer(doc)
	doc.transaction_date = today()


# ----------------------------------------------------------------------------- doc events


def before_validate(doc, method=None):
	"""The status and its stamps belong to the actions; the document's quantity message comes
	before ERPNext's own."""
	acting = doc.flags.alpinos_quotation_action
	if doc.is_new():
		doc.set(STATUS, DRAFT)
		for f in SYSTEM_FIELDS[1:]:
			doc.set(f, None)
		doc.custom_force_complete_applied = 0
		doc.set(RECEIPTS, [])
		if not doc.flags.from_order_portal and doc.meta.has_field("custom_quotation_source"):
			doc.custom_quotation_source = SOURCE_DIRECT
			for f in REQUEST_FIELDS[1:]:
				doc.set(f, None)
	else:
		before = doc.get_doc_before_save()
		if before and not doc.flags.from_order_portal and doc.meta.has_field("custom_quotation_source"):
			for f in REQUEST_FIELDS:
				if cstr(doc.get(f)) != cstr(before.get(f)):
					frappe.throw(_("{0} is set by the Buyer Order Request Form and cannot be changed.").format(_(doc.meta.get_label(f))), title=_("Not Permitted"))
		if before and not acting and before.docstatus == 0:
			meta = frappe.get_meta(DOCTYPE)
			for f in SYSTEM_FIELDS:
				if _value(doc, f, meta) != _value(before, f, meta):
					frappe.throw(_(M_STATUS_SYSTEM), title=_("Not Permitted"))
			if doc.get(RECEIPTS) or before.get(RECEIPTS):
				frappe.throw(_(M_NO_DRAFT_PAYMENT), title=_("Not Permitted"))
			if (
				before.get("custom_quotation_source") == SOURCE_PORTAL
				and cstr(before.get("party_name")) != cstr(doc.get("party_name"))
			):
				frappe.throw(
					_("This Quotation is the order request {0} of its Buyer, so its Customer cannot be changed.").format(
						before.get("custom_buyer_order_request_ref")
					),
					title=_("Not Permitted"),
				)
			if before.get("opportunity") and cstr(before.get("party_name")) != cstr(doc.get("party_name")):
				# A-28: the Customer of a converted Quotation is its Opportunity's
				frappe.throw(
					_("This Quotation was created from Opportunity {0}, so its Customer cannot be changed.").format(before.opportunity),
					title=_("Not Permitted"),
				)
	if doc.docstatus == 0 and (doc.is_new() or acting != "cancel"):
		for row in doc.get("items") or []:
			if flt(row.get("qty")) <= 0:
				if row.get("item_code"):
					frappe.throw(_(M_ZERO_QTY).format(row.item_code), title=_("Order Items"))
				frappe.throw(_("Order Items row {0}: select the SKU.").format(row.idx), title=_("Order Items"))
		for table, label in ITEM_TABLES[1:]:
			for row in doc.get(table) or []:
				if row.get("item_code") and flt(row.get("qty")) <= 0:
					frappe.throw(
						_("Quantity for SKU [{0}] in {1} must be greater than zero.").format(row.item_code, _(label)),
						title=_(label),
					)


def validate(doc, method=None):
	"""After ERPNext's validate (and catalog_gate's buyer): defaults on creation, the one active
	Quotation per Opportunity, prices while Draft / Negotiation (and at Finalize), the payment
	summary."""
	from alpinos.offline_sales import quotation_payments as P

	before = None if doc.is_new() else doc.get_doc_before_save()
	if doc.is_new():
		_set_defaults(doc)
	_officer_buyer_guard(doc, before)
	_one_active_per_opportunity(doc, before)
	drafting = doc.docstatus == 0 or (before is not None and before.docstatus == 0)
	if drafting and doc.flags.alpinos_quotation_action != "cancel":
		if before and not doc.flags.alpinos_quotation_action:
			_responsible_officer_guard(doc, before)
		price(doc, before)
		doc.custom_billing_gstin = billing_gstin(customer_of(doc), doc.get("custom_site_name"))
		P.prepare_schedule(doc, blocking=doc.flags.alpinos_quotation_action == "finalize")
	P.recompute(doc)


def _officer_buyer_guard(doc, before):
	"""Changes(HP) #124: a Sales Officer quotes only to a Buyer (the Customer on screen; Quotation
	To is fixed) assigned to them. The Customer picker lists only those; this is the server's
	check, as the Opportunity had."""
	if doc.flags.from_order_portal:
		return
	if not (doc.is_new() or (before and cstr(before.get("party_name")) != cstr(doc.get("party_name")))):
		return
	from alpinos import buyer_assignment_visibility as V

	if not V.is_assignment_scoped():
		return
	if doc.get("quotation_to") != "Buyer Master":
		frappe.throw(_("A Sales Officer's Quotation is always for a Customer (Buyer Master)."), frappe.PermissionError, title=_("Not Permitted"))
	buyer = buyer_of(doc)
	if buyer and buyer not in V._assigned_buyer_names(V._employee_for(frappe.session.user)):
		frappe.throw(
			_("You are not assigned to Customer {0}.").format(frappe.bold(frappe.db.get_value("Buyer Master", buyer, "customer_business_name") or buyer)),
			frappe.PermissionError,
			title=_("Not Permitted"),
		)


def _responsible_officer_guard(doc, before):
	if cstr(doc.get("custom_responsible_sales_officer")) != cstr(before.get("custom_responsible_sales_officer")):
		if not is_manager():
			frappe.throw(_(M_RSO_ROLE), frappe.PermissionError, title=_("Not Permitted"))


def active_quotation_of(opportunity, exclude=None):
	"""The non-cancelled Quotation of an Opportunity (S5 "One Active Quotation per Opportunity")."""
	if not opportunity:
		return None
	# a cancelled Quotation is docstatus 2 (cancel_quotation discards a Draft one)
	return frappe.db.get_value(DOCTYPE, {"opportunity": opportunity, "docstatus": ("<", 2), "name": ("!=", exclude or "")}, "name")


def _one_active_per_opportunity(doc, before):
	if not doc.get("opportunity"):
		return
	if before and before.get("opportunity") == doc.opportunity:
		return
	other = active_quotation_of(doc.opportunity, exclude=doc.name)
	if other:
		frappe.throw(_(M_ACTIVE_QUOTATION).format(other), title=_("Quotation Exists"))


def after_insert(doc, method=None):
	"""Quotation Created: creator, time, source (the Buyer Order Request, the Opportunity ID or
	Standalone)."""
	if doc.get("custom_buyer_order_request_ref"):
		source = _("Buyer Order Request {0}").format(doc.custom_buyer_order_request_ref)
	elif doc.get("opportunity"):
		source = _("Opportunity {0}").format(doc.opportunity)
	else:
		source = _("Standalone")
	audit.log(DOCTYPE, doc.name, "Quotation Created", _("Quotation"), "", f"{doc.get('customer_name') or doc.party_name} ({source})")


def on_update(doc, method=None):
	"""Commercial Edit: every header and line change of a Draft / Negotiation save, with the SKU."""
	if doc.flags.alpinos_quotation_action or doc.flags.in_insert:
		return
	before = doc.get_doc_before_save()
	if not before or before.docstatus != 0:
		return
	meta = frappe.get_meta(DOCTYPE)
	for field in (
		"party_name", "customer_address", "shipping_address_name", "custom_site_name", "custom_quotation_remarks",
		"custom_cash_discount", "valid_till",
	):
		if _value(before, field, meta) != _value(doc, field, meta):
			audit.log(DOCTYPE, doc.name, "Commercial Edit", _(meta.get_label(field)), before.get(field), doc.get(field))
	if cstr(before.get("custom_responsible_sales_officer")) != cstr(doc.get("custom_responsible_sales_officer")):
		audit.log(
			DOCTYPE, doc.name, "Responsible Sales Officer Changed", _("Responsible Sales Officer"),
			before.get("custom_responsible_sales_officer"), doc.get("custom_responsible_sales_officer"),
		)
	_log_item_changes(doc, before)
	for table, label in ITEM_TABLES[1:]:
		old, new = _table_summary(before, table), _table_summary(doc, table)
		if old != new:
			audit.log(DOCTYPE, doc.name, "Commercial Edit", _(label), old, new)
	if not _same(before.get("grand_total"), doc.get("grand_total")):
		audit.log(DOCTYPE, doc.name, "Commercial Edit", _("Grand Total"), flt(before.grand_total, 2), flt(doc.grand_total, 2))
	if cstr(before.get("custom_payment_term")) != cstr(doc.get("custom_payment_term")):
		audit.log(DOCTYPE, doc.name, "Payment Term Changed", _("Payment Term"), before.get("custom_payment_term"), doc.get("custom_payment_term"))
	if cint(before.get("custom_credit_days")) != cint(doc.get("custom_credit_days")):
		audit.log(DOCTYPE, doc.name, "Commercial Edit", _("Credit Days"), before.get("custom_credit_days"), doc.get("custom_credit_days"))
	from alpinos.offline_sales.quotation_payments import schedule_summary

	old, new = schedule_summary(before), schedule_summary(doc)
	if old != new:
		audit.log(DOCTYPE, doc.name, "Partial Schedule Added / Revised", _("Payment Schedule"), old, new)


def _log_item_changes(doc, before):
	old_rows = {r.name: r for r in before.get("items") or []}
	new_rows = {r.name: r for r in doc.get("items") or []}
	for name, row in old_rows.items():
		if name not in new_rows:
			audit.log(DOCTYPE, doc.name, "Commercial Edit", _("Order Items"), f"{row.item_code} x {flt(row.qty):g}", _("removed"), item_code=row.item_code)
	for name, row in new_rows.items():
		old = old_rows.get(name)
		if not old:
			audit.log(DOCTYPE, doc.name, "Commercial Edit", _("Order Items"), "", f"{row.item_code} x {flt(row.qty):g}", item_code=row.item_code)
			continue
		if old.item_code != row.item_code:
			audit.log(DOCTYPE, doc.name, "Commercial Edit", _("SKU"), old.item_code, row.item_code, item_code=row.item_code)
		for field, label in (("qty", "Quantity"), ("custom_mrp", "MRP"), *RESTRICTED_ITEM_FIELDS):
			if not _same(old.get(field), row.get(field)):
				audit.log(DOCTYPE, doc.name, "Commercial Edit", _(label), flt(old.get(field), 2), flt(row.get(field), 2), item_code=row.item_code)


def _table_summary(doc, table):
	return "; ".join(f"{r.item_code} x {flt(r.qty):g}" for r in doc.get(table) or [] if r.get("item_code"))


def before_submit(doc, method=None):
	if doc.flags.alpinos_quotation_action != "finalize":
		frappe.throw(_(M_USE_FINALIZE), title=_("Not Permitted"))


def before_cancel(doc, method=None):
	if doc.flags.alpinos_quotation_action != "cancel":
		frappe.throw(_(M_USE_CANCEL), title=_("Not Permitted"))


def before_discard(doc, method=None):
	if doc.flags.alpinos_quotation_action != "cancel":
		frappe.throw(_(M_USE_CANCEL), title=_("Not Permitted"))


def before_update_after_submit(doc, method=None):
	"""The Finalize lock (7): an Update from the form changes only what is not commercial and not
	part of the payment record. The actions check their own rules."""
	if doc.flags.alpinos_quotation_action:
		return
	before = doc.get_doc_before_save()
	if not before:
		return
	meta = frappe.get_meta(DOCTYPE)

	def changed(field):
		df = meta.get_field(field)
		if df and df.fieldtype in ("Table", "Table MultiSelect"):
			return _rows(before, df) != _rows(doc, df)
		return _value(before, field, meta) != _value(doc, field, meta)

	everything = [df.fieldname for df in meta.fields if df.allow_on_submit and df.fieldtype not in ("Section Break", "Column Break", "Tab Break", "HTML", "Button")]
	moved = [f for f in everything if changed(f)]
	# ERPNext's Update Items saves new lines and prices past Frappe's own after-submit check
	lines_moved = changed("items") or not _same(before.get("grand_total"), doc.get("grand_total"))
	if not moved and not lines_moved:
		return
	if cint(before.get("custom_force_complete_applied")):
		frappe.throw(_(M_FC_READ_ONLY), title=_("Not Permitted"))
	if lines_moved or any(f in COMMERCIAL_AFTER_SUBMIT for f in moved):
		frappe.throw(_(M_LOCKED), title=_("Not Permitted"))
	if RECEIPTS in moved:
		frappe.throw(_(M_SUBMITTED_PAYMENT), title=_("Not Permitted"))
	if any(f in SYSTEM_FIELDS for f in moved):
		frappe.throw(_(M_STATUS_SYSTEM), title=_("Not Permitted"))
	if any(f in PAYMENT_FIELDS or f in DERIVED_FIELDS for f in moved):
		frappe.throw(_(M_PAYMENT_ACTIONS), title=_("Not Permitted"))
	if "custom_responsible_sales_officer" in moved:
		if not is_manager():
			frappe.throw(_(M_RSO_ROLE), frappe.PermissionError, title=_("Not Permitted"))
		doc.flags.alpinos_rso_changed = (before.get("custom_responsible_sales_officer"), doc.get("custom_responsible_sales_officer"))


def on_update_after_submit(doc, method=None):
	change = doc.flags.get("alpinos_rso_changed")
	if change:
		doc.flags.alpinos_rso_changed = None
		audit.log(DOCTYPE, doc.name, "Responsible Sales Officer Changed", _("Responsible Sales Officer"), change[0], change[1])


def _rows(doc, df):
	from alpinos.offline_sales.opportunity import _CHILD_IGNORED, _NO_VALUE, _norm

	fields = [d for d in frappe.get_meta(df.options).fields if d.fieldtype not in _NO_VALUE and d.fieldname not in _CHILD_IGNORED]
	return [tuple(_norm(r.get(d.fieldname), d.fieldtype) for d in fields) for r in doc.get(df.fieldname) or []]


# ----------------------------------------------------------------------------- actions


@frappe.whitelist(methods=["POST"])
def start_negotiation(name):
	"""Draft -> Negotiation (A-1: the document names the status, not its trigger)."""
	# company-scope: n/a (one Quotation, after its own read permission check)
	doc = get(name)
	assert_actor()
	current = status_of(doc)
	if current != DRAFT:
		frappe.throw(_("Only a Draft Quotation can move to Negotiation. This one is {0}.").format(_(current)), title=_("Not Permitted"))
	reason = buyer_not_ready(doc, _("moved to Negotiation"))
	if reason:
		frappe.throw(reason, title=_("Buyer Not Ready"))
	doc.set(STATUS, NEGOTIATION)
	save(doc, "negotiation")
	audit.status_change(DOCTYPE, doc.name, "Negotiation Started", DRAFT, NEGOTIATION)
	return {"status": NEGOTIATION}


def finalize_errors(doc):
	"""What Finalize Quotation needs (7, S5-R153): the header, every row, the Payment Term and
	its configuration, a buyer that may still trade (A-30)."""
	from alpinos import item_mrp as IM
	from alpinos.offline_sales.quotation_payments import schedule_errors
	from alpinos.sales_order_offline_buyer import get_customer_family_sites

	errors = []
	customer = customer_of(doc)
	if not doc.get("party_name"):
		errors.append(_("Select the Customer."))
	if not doc.get("order_type"):
		errors.append(_("Customer Type is missing."))
	sites = get_customer_family_sites(customer) if customer else []
	site = cstr(doc.get("custom_site_name")).strip()
	if sites and not site:
		errors.append(_("Select the Site Name."))
	elif site and sites and site not in sites:
		errors.append(_("Site {0} is not a site of this Buyer.").format(site))
	if not doc.get("customer_address"):
		errors.append(_("Select the Billing Address."))
	if not doc.get("shipping_address_name"):
		errors.append(_("Select the Shipping Address."))
	if not [r for r in doc.get("items") or [] if r.get("item_code")]:
		errors.append(_("Add at least one SKU to the Order Items."))
	for row in doc.get("items") or []:
		if not row.get("item_code"):
			errors.append(_("Order Items row {0}: select the SKU.").format(row.idx))
			continue
		if flt(row.get("qty")) <= 0:
			errors.append(_(M_ZERO_QTY).format(row.item_code))
		mrp_error = IM.line_mrp_error(row.item_code, row.get("custom_mrp"))
		if mrp_error:
			errors.append(_("Order Items row {0}: {1}").format(row.idx, mrp_error))
		elif flt(row.get("custom_mrp")) <= 0:
			errors.append(_("Order Items row {0}: MRP is missing for SKU {1}.").format(row.idx, row.item_code))
	for table, label in ITEM_TABLES[1:]:
		if table == "custom_additional_units_damage_items" and not cint(doc.get("custom_additional_units_damage")):
			continue
		for row in doc.get(table) or []:
			if not row.get("item_code"):
				errors.append(_("{0} row {1}: select the SKU.").format(_(label), row.idx))
			elif flt(row.get("qty")) <= 0:
				errors.append(_("Quantity for SKU [{0}] in {1} must be greater than zero.").format(row.item_code, _(label)))
			if table == "custom_scheme_item_table" and not cstr(row.get("scheme")).strip():
				errors.append(_("{0} row {1}: enter the Scheme.").format(_(label), row.idx))
	term = doc.get("custom_payment_term")
	if term not in TERMS:
		errors.append(_(M_TERM_REQUIRED))
	elif term == "Credit" and cint(doc.get("custom_credit_days")) <= 0:
		errors.append(_("Enter the Credit Days for a Credit Quotation."))
	elif term == "Partial":
		errors.extend(schedule_errors(doc))
	reason = buyer_not_ready(doc, _("finalized"))
	if reason:
		errors.append(reason)
	return errors


def buyer_not_ready(doc, action):
	"""Why this Quotation's buyer cannot go further yet (approval / Buyer Catalog / status), or
	None. A Draft may be saved before (the Opportunity is skipped, 20 Nov 2026)."""
	from alpinos.offline_sales.catalog_gate import readiness

	buyer = buyer_of(doc)
	return readiness(buyer, _("Quotation"), action=action) if buyer else None


@frappe.whitelist(methods=["POST"])
def finalize(name, partial_reason=None):
	"""Finalize Quotation (7): Sales Manager / Sales Admin. The commercial values lock (submit),
	Finalized By / On, the Credit date, the payment summary, the Opportunity's Won / Partial."""
	# company-scope: n/a (one Quotation, after its own read permission check)
	from alpinos.offline_sales import quotation_payments as P
	from alpinos.offline_sales.opportunity import PARTIAL, _linked_opportunity, apply_quotation_finalized, compare

	doc = get(name)
	if not is_manager():
		frappe.throw(_(M_FINALIZE_ROLE), frappe.PermissionError, title=_("Not Permitted"))
	current = status_of(doc)
	if current not in EDITABLE or doc.docstatus != 0:
		frappe.throw(_("A Quotation that is {0} cannot be finalized.").format(_(current)), title=_("Not Permitted"))
	errors = finalize_errors(doc)
	if errors:
		frappe.throw("<br>".join(errors), title=_("Quotation cannot be finalized"))
	partial_reason = cstr(partial_reason).strip()
	opp = _linked_opportunity(doc)
	if opp and compare(opp, doc).result == PARTIAL and not partial_reason:
		apply_quotation_finalized(doc, None)  # refuses with the Opportunity's own message

	before = P.snapshot(doc)
	stamp = now_datetime()
	doc.set(STATUS, FINALIZED)
	doc.custom_finalized_by = frappe.session.user
	doc.custom_finalized_on = stamp
	if doc.get("custom_payment_term") == "Credit":
		doc.custom_expected_payment_date = add_days(getdate(stamp), cint(doc.custom_credit_days))
	doc.flags.alpinos_quotation_action = "finalize"
	doc.flags.ignore_permissions = True
	doc.submit()

	result = apply_quotation_finalized(doc, partial_reason or None)
	audit.status_change(DOCTYPE, doc.name, "Quotation Finalized", current, FINALIZED, reason=partial_reason or None)
	audit.log(DOCTYPE, doc.name, "Quotation Finalized", _("Final Commercial Values"), "", commercial_summary(doc))
	if doc.get("custom_payment_term") == "Credit":
		audit.log(DOCTYPE, doc.name, "Quotation Finalized", _("Expected Payment Date"), "", frappe.format(doc.custom_expected_payment_date, {"fieldtype": "Date"}))
	P.log_derived(doc, before)
	# the buyer's email with the Quotation PDF, after the Finalize is committed (Section 2, 7.2)
	frappe.enqueue(
		"alpinos.offline_sales.quotation.email_buyer_finalized", queue="short", enqueue_after_commit=True,
		quotation=doc.name,
	)
	return {"status": FINALIZED, "opportunity": opp.name if opp else None, "opportunity_result": result}


def quotation_pdf(name):
	from alpinos.offline_sales.quotation_print import PF_NAME

	return frappe.get_print(DOCTYPE, name, PF_NAME, as_pdf=True)


def email_buyer_finalized(quotation):
	"""Background job: the Buyer Master's email gets the finalized Quotation's PDF and the doc's
	text (Section 2, 7.2). No email on the Buyer: nothing is sent. Never raises: the Quotation is
	already Finalized, a mail failure only goes to the Error Log."""
	try:
		doc = frappe.get_doc(DOCTYPE, quotation)
		buyer = buyer_of(doc)
		email = cstr(frappe.db.get_value("Buyer Master", buyer, "email") if buyer else "").strip()
		if not email:
			return
		frappe.sendmail(
			recipients=[email],
			subject=_("Quotation {0} finalized").format(doc.name),
			message=_(M_BUYER_FINALIZED).format(doc.name),
			attachments=[{"fname": f"{doc.name}.pdf", "fcontent": quotation_pdf(doc.name)}],
			reference_doctype=DOCTYPE,
			reference_name=doc.name,
		)
	except Exception:
		frappe.log_error(title=f"Quotation finalized email failed for {quotation}")


def commercial_summary(doc):
	lines = "; ".join(
		f"{r.item_code} x {flt(r.qty):g} @ {money(r.custom_selling_price)}" for r in doc.get("items") or [] if r.get("item_code")
	)
	return _("Grand Total {0} (Net Total {1}, Taxes {2}, Cash Discount {3}); Payment Term {4}; {5}").format(
		money(doc.grand_total), money(doc.net_total), money(doc.total_taxes_and_charges),
		money(doc.get("custom_cash_discount_amount")), doc.get("custom_payment_term") or "", lines,
	)


def active_sales_order_of(name):
	"""The Quotation's active Sales Order: linked by Linked Quotation (W7) or, for an order made
	before it, by its lines; Draft or submitted, not Cancelled / Rejected."""
	from alpinos.offline_sales.so_handoff import INACTIVE, active_sales_order

	so = active_sales_order(name)
	if so:
		return so
	rows = frappe.db.sql(
		"""
		SELECT DISTINCT so.name FROM `tabSales Order` so
		JOIN `tabSales Order Item` soi ON soi.parent = so.name
		WHERE soi.prevdoc_docname = %(q)s AND so.docstatus < 2
			AND IFNULL(so.custom_workflow_status, '') NOT IN %(inactive)s
		LIMIT 1
		""",
		{"q": name, "inactive": INACTIVE},
	)
	return rows[0][0] if rows else None


@frappe.whitelist(methods=["POST"])
def cancel_quotation(name, reason=None):
	"""Cancel Quotation (21): Sales Manager / Sales Admin, mandatory reason, no active Sales Order.
	Everything on it is kept; it becomes read only; its Opportunity can be converted again."""
	# company-scope: n/a (one Quotation, after its own read permission check)
	doc = get(name)
	if not is_manager():
		frappe.throw(_(M_CANCEL_ROLE), frappe.PermissionError, title=_("Not Permitted"))
	current = status_of(doc)
	if current == CANCELLED or doc.docstatus == 2:
		frappe.throw(_("This Quotation is already Cancelled."), title=_("Not Permitted"))
	reason = cstr(reason).strip()
	if not reason:
		frappe.throw(_(M_REASON), title=_("Reason Required"))
	if current in OPEN:
		so = active_sales_order_of(doc.name)
		if so:
			frappe.throw(_(M_CANCEL_SO).format(so), title=_("Active Sales Order"))

	doc.set(STATUS, CANCELLED)
	doc.custom_cancellation_reason = reason
	doc.custom_cancelled_by = frappe.session.user
	doc.custom_cancelled_by_role = acting_role()
	doc.custom_cancelled_on = now_datetime()
	if doc.docstatus == 0:
		save(doc, "cancel")
		doc.flags.alpinos_quotation_action = "cancel"
		doc.flags.ignore_permissions = True
		doc.discard()
		doc.db_set("status", "Cancelled", update_modified=False)
	else:
		doc.flags.alpinos_quotation_action = "cancel"
		doc.flags.ignore_permissions = True
		doc.flags.ignore_links = True  # the active-order check above is the business rule
		doc.cancel()
	audit.status_change(DOCTYPE, doc.name, "Quotation Cancelled", current, CANCELLED, reason=reason)
	reopen_opportunity(doc, reason)
	return {"status": CANCELLED}


def reopen_opportunity(doc, reason):
	"""A-46: the Opportunity of a cancelled Quotation is Pending (Submitted) again, its Linked
	Quotation cleared, so Convert to Quotation is offered for the new Quotation (21.3)."""
	from alpinos.offline_sales import opportunity as O

	if not doc.get("opportunity") or not frappe.db.exists(O.DOCTYPE, doc.opportunity):
		return
	opp = frappe.get_doc(O.DOCTYPE, doc.opportunity)
	if opp.get("custom_linked_quotation") != doc.name:
		return
	old = O.status_of(opp)
	opp.flags.alpinos_opportunity_action = "quotation_cancelled"
	opp.set(O.STATUS, O.SUBMITTED)
	opp.custom_linked_quotation = None
	opp.custom_status_reason = None
	opp.save(ignore_permissions=True)
	audit.status_change(O.DOCTYPE, opp.name, "Quotation Cancelled", old, O.SUBMITTED, reason=reason)
	audit.log(O.DOCTYPE, opp.name, "Quotation Cancelled", _("Linked Quotation ID"), doc.name, "")


# ----------------------------------------------------------------------------- form support


@frappe.whitelist()
def form_actions(name):
	"""The actions this user may take on this Quotation now (the form shows these buttons)."""
	# company-scope: n/a (one Quotation, after its own read permission check)
	from alpinos.offline_sales import quotation_payments as P

	doc = frappe.get_doc(DOCTYPE, name)
	doc.check_permission("read")
	status = status_of(doc)
	actor = is_actor()
	manager = is_manager()
	fc = cint(doc.get("custom_force_complete_applied"))
	open_ = status in OPEN and doc.docstatus == 1
	term = doc.get("custom_payment_term")
	pending = flt(doc.get("custom_total_pending"), 2)
	actions = []
	if status == DRAFT and doc.docstatus == 0 and actor:
		actions.append("start_negotiation")
	if status in EDITABLE and doc.docstatus == 0 and manager:
		actions.append("finalize")
	if open_ and actor and not fc:
		if pending > 0:
			actions += ["record_payment", "force_complete"]
		actions.append("change_payment_term")
		if term == "Credit":
			actions.append("change_expected_payment_date")
		if term == "Partial":
			actions.append("revise_schedule")
		if term in ("Advance", "Credit") and doc.get("custom_payment_status") == "Partially Received":
			actions.append("convert_to_partial")
	if manager and status != CANCELLED and doc.docstatus < 2:
		actions.append("cancel")
	if P.is_system_manager() and doc.get(RECEIPTS):
		actions.append("correct_payment")
	active_so = active_sales_order_of(doc.name) if status in OPEN else None
	return {
		"status": status,
		"actions": actions,
		"active_sales_order": active_so,
		"is_manager": int(manager),
		"is_officer": int(is_sales_officer_only()),
		"eligibility_note": P.eligibility_note(doc),
		# a Draft saved before the buyer was ready: why Start Negotiation / Finalize wait
		"buyer_not_ready": buyer_not_ready(doc, _("moved forward")) if status in EDITABLE and doc.docstatus == 0 else None,
		"summary": {
			"grand_total": flt(doc.grand_total, 2),
			"total_received": flt(doc.get("custom_total_received"), 2),
			"total_pending": pending,
		},
	}


@frappe.whitelist()
def finalize_check(name):
	"""For the Finalize dialog: what is missing, and whether the Opportunity needs a Partial Reason."""
	# company-scope: n/a (one Quotation, after its own read permission check)
	from alpinos.offline_sales.opportunity import quotation_result

	doc = frappe.get_doc(DOCTYPE, name)
	doc.check_permission("read")
	return {"errors": finalize_errors(doc), "opportunity": quotation_result(name)}


@frappe.whitelist()
def buyer_defaults(party_name, quotation_to="Buyer Master"):
	"""For a new Quotation's form when the Customer is picked: the Buyer's Payment Term and Credit
	Days (9.1), filled once; the server keeps what the form shows."""
	# company-scope: n/a (Buyer Master has no company; the caller's read permission is checked)
	doc = frappe._dict(quotation_to=quotation_to, party_name=party_name)
	buyer = buyer_of(doc) if party_name else None
	if not buyer:
		return {}
	frappe.has_permission("Buyer Master", "read", buyer, throw=True)
	row = frappe.db.get_value("Buyer Master", buyer, ["payment_term", "payment_term_days"], as_dict=True) or {}
	return {
		"custom_payment_term": row.get("payment_term") if row.get("payment_term") in TERMS else "",
		"custom_credit_days": credit_days_of(row.get("payment_term_days")),
	}
