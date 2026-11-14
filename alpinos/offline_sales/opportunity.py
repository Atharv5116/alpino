"""The Opportunity ("Opportunity to Sales Order v1.0.0", Section 3, with the Opportunity column of
Section 4, 6.1). ERPNext's Opportunity, customised; the party is the Buyer Master.

Status (custom_opportunity_status; ERPNext's own `status` is kept out of sight):

    Pending (Draft)          created (Direct, or by the Buyer Order Request portal)
    Pending (Submitted)      Submit Opportunity: Submitted By / On stamped, the whole record locked
    Converted to Quotation   Convert to Quotation: a Draft Quotation is created and linked
    Won / Partial            the linked Quotation is Finalized (apply_quotation_finalized, called
                             by the Quotation's Finalize): every Order Item SKU at least the
                             requested quantity = Won, else Partial with a mandatory reason
    Hold                     Put on Hold (Draft / Submitted), mandatory reason
    Lost / Cancelled         Mark as Lost / Cancel Opportunity (Draft / Submitted), mandatory reason

Hold "pauses workflow" (6.1) and the document gives no way back, so Resume returns a Hold
Opportunity to the status it had before (the one addition to the document).

Only Pending (Draft) can be edited; every other status is read only for everyone (3.1 "Submitted
Opportunity Lock Rule"). The status and its stamps change only through the actions here.

Commercial values (MRP, Selling Price, Flat / Offer / Additional Discount %, Line Amount) are the
Buyer Catalog's, priced as the Sales Order prices them (Multiple MRP included) and recomputed on
every Draft save; nothing typed into them is kept (3.2 "Opportunity Commercial Value Rule").
Quantity is never changed; Box follows it with the Customer Type's Round Up / Round Down.
"""

import json
from math import ceil, floor

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, now_datetime

from alpinos.alpinos_development.doctype.field_change_log.field_change_log import log_field_change
from alpinos.offline_sales import (
	CANCELLED,
	INACTIVE,
	ON_HOLD,
	SALES_ADMIN,
	SALES_MANAGER,
	SALES_OFFICER,
	SYSTEM_MANAGER,
	user_roles,
)
from alpinos.offline_sales import audit

DOCTYPE = "Opportunity"
STATUS = "custom_opportunity_status"
BUYER_PARTY = "Buyer Master"

DRAFT = "Pending (Draft)"
SUBMITTED = "Pending (Submitted)"
CONVERTED = "Converted to Quotation"
WON = "Won"
PARTIAL = "Partial"
HOLD = "Hold"
LOST = "Lost"
CANCELLED_OPP = "Cancelled"
STATUSES = (DRAFT, SUBMITTED, CONVERTED, WON, PARTIAL, HOLD, LOST, CANCELLED_OPP)

DIRECT = "Direct Opportunity"
BOR_FORM = "Buyer Order Request Form"

#: who performs the actions of the Button & Action Dictionary (section 5): SO, SM, SA (and
#: System Manager, which the app treats as able to do anything)
ACTION_ROLES = (SALES_OFFICER, SALES_MANAGER, SALES_ADMIN, SYSTEM_MANAGER)

#: action -> (from statuses, to status, reason required, trail action, verb for messages)
ACTIONS = {
	"submit": ((DRAFT,), SUBMITTED, False, "Opportunity Submitted", "submitted"),
	"hold": ((DRAFT, SUBMITTED), HOLD, True, "Opportunity Put on Hold", "put on hold"),
	"lost": ((DRAFT, SUBMITTED), LOST, True, "Opportunity Marked Lost", "marked as lost"),
	"cancel": ((DRAFT, SUBMITTED), CANCELLED_OPP, True, "Opportunity Cancelled", "cancelled"),
	"resume": ((HOLD,), None, False, "Opportunity Resumed", "resumed"),
}

#: set only by the actions in this module
SYSTEM_FIELDS = (
	STATUS, "custom_status_reason", "custom_status_before_hold", "custom_submitted_by",
	"custom_submitted_on", "custom_linked_quotation",
)
#: set only by the Buyer Order Request portal (doc.flags.from_order_portal)
PORTAL_FIELDS = (
	"custom_opportunity_source", "custom_buyer_order_request_ref", "custom_request_contact_person",
	"custom_source_display",
)
#: stamped once, on creation
CREATION_FIELDS = ("custom_created_by", "custom_created_on")

ITEM_TABLES = (
	("items", "Order Items"),
	("custom_marketing_freebies", "Marketing Freebies"),
	("custom_scheme_item_table", "Scheme Items"),
	("custom_additional_units_damage_items", "Additional Unit / Damage"),
)

#: never compared by the lock: ERPNext keeps its own status / response time, and Comments
#: (CRM notes) are not Opportunity fields
_LOCK_IGNORED = {"status", "notes", "first_response_time", "modified", "modified_by"}
_NO_VALUE = {"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Image", "Fold", "Heading"}
_CHILD_IGNORED = {"name", "idx", "parent", "parentfield", "parenttype", "owner", "creation", "modified", "modified_by", "docstatus"}

# messages the document gives word for word
M_ZERO_QTY = "Quantity for SKU [{0}] must be greater than zero."
M_DUPLICATE = "Warning: SKU [{0}] is already added in row {1}. Are you sure you want to add a duplicate line?"
M_BUYER_ON_HOLD = "Quotation cannot be created because the linked Buyer is currently On Hold."
M_ACTIVE_QUOTATION = (
	"An active Quotation [{0}] already exists for this Opportunity. Cancel the existing Quotation before creating "
	"another Quotation."
)


# ----------------------------------------------------------------------------- helpers


def status_of(doc):
	return (doc.get(STATUS) if doc else None) or DRAFT


def buyer_of(doc):
	"""The Buyer Master of an Opportunity (None for an old Customer / Lead one)."""
	if doc.get("opportunity_from") == BUYER_PARTY and doc.get("party_name"):
		return doc.party_name
	return None


def customer_of(doc):
	buyer = buyer_of(doc)
	if buyer:
		return frappe.db.get_value("Buyer Master", buyer, "customer")
	if doc.get("opportunity_from") == "Customer":
		return doc.get("party_name")
	return None


def is_actor(user=None):
	user = user or frappe.session.user
	return user == "Administrator" or bool(user_roles(user) & set(ACTION_ROLES))


def _assert_actor():
	if not is_actor():
		frappe.throw(
			_("Only a Sales Officer, Sales Manager or Sales Admin can do this."),
			frappe.PermissionError,
			title=_("Not Permitted"),
		)


def _label(fieldname, meta=None):
	meta = meta or frappe.get_meta(DOCTYPE)
	return _(meta.get_label(fieldname)) if meta.has_field(fieldname) else fieldname


# ----------------------------------------------------------------------------- buyer gates


def create_block_reason(buyer):
	"""Why a new Opportunity (or its Submit) is refused for this Buyer (Section 4, 6.1), or None.

	Pending Approval and Approved buyers (catalogue or not) may have Opportunities; On Hold,
	Inactive and Cancelled ones may not."""
	if not buyer:
		return None
	from alpinos.offline_sales.buyer_rules import status_of as buyer_status
	from alpinos.offline_sales.catalog_gate import readiness

	row = frappe.db.get_value("Buyer Master", buyer, ["channel", "buyer_status"], as_dict=True)
	if not row:
		return None
	if buyer_status(row.buyer_status) in (ON_HOLD, INACTIVE, CANCELLED):
		return readiness(buyer, _("Opportunity"))
	return None


def convert_block_reason(buyer):
	"""Why Convert to Quotation is refused for this Buyer (3 7.1, Section 4 6.1-6.3), or None."""
	if not buyer:
		return None
	from alpinos.offline_sales import is_offline
	from alpinos.offline_sales.buyer_rules import status_of as buyer_status
	from alpinos.offline_sales.catalog_gate import readiness

	row = frappe.db.get_value("Buyer Master", buyer, ["channel", "buyer_status"], as_dict=True)
	if row and is_offline(row.channel) and buyer_status(row.buyer_status) == ON_HOLD:
		return _(M_BUYER_ON_HOLD)
	return readiness(buyer, _("Quotation"))


def _assert_assigned(doc):
	"""A user whom Buyer assignment narrows may only raise Opportunities for their Buyers."""
	from alpinos import buyer_assignment_visibility as V

	buyer = buyer_of(doc)
	if not buyer or not V.is_assignment_scoped():
		return
	if buyer not in V._assigned_buyer_names(V._employee_for(frappe.session.user)):
		frappe.throw(
			_("You are not assigned to Buyer {0}.").format(frappe.bold(buyer)),
			frappe.PermissionError,
			title=_("Not Permitted"),
		)


# ----------------------------------------------------------------------------- pricing


def line_pricing(customer, item_code, mrp=None):
	"""MRP, Flat Discount % and Selling Price of one SKU for a buyer, as the Sales Order prices it.

	Item MRP table (Multiple MRP): one active MRP is used; with several, the line's MRP when it
	is one of them, else none yet (Submit asks for it). The Buyer Catalog price at that MRP,
	else Flat 0 % and Selling Price = MRP. An SKU without an MRP table: the Buyer Catalog /
	SKU margin, else Customer Item MRP, else the Item's rate, at Flat 0 %."""
	from alpinos import item_mrp as IM
	from alpinos.sales_order_api import get_customer_item_mrp
	from alpinos.sales_order_offline_buyer import get_offline_buyer_item_rate

	out = frappe._dict(mrp=0.0, flat=0.0, selling_price=0.0, mrp_options=[], needs_mrp=0)
	if not item_code:
		return out
	info = IM.applicable(item_code)
	if info.tracked:
		out.mrp_options = list(info.mrps)
		if len(info.mrps) == 1:
			chosen = info.mrps[0]
		elif IM.q(mrp) in info.mrps:
			chosen = IM.q(mrp)
		else:
			chosen = 0
		if not chosen:
			out.needs_mrp = 1 if info.multiple else 0
			return out
		out.mrp = chosen
		rate = (get_offline_buyer_item_rate(customer, item_code, mrp=chosen) if customer else None) or {}
		if rate.get("rate") is not None:
			out.flat = flt(rate.get("margin_percent"))
			out.selling_price = flt(rate.get("rate"), 2)
		else:
			out.selling_price = flt(chosen, 2)
		return out

	rate = (get_offline_buyer_item_rate(customer, item_code) if customer else None) or {}
	if flt(rate.get("mrp")) > 0 or flt(rate.get("margin_percent")) > 0:
		out.mrp = flt(rate.get("mrp"))
		out.flat = flt(rate.get("margin_percent"))
		if rate.get("source") == "offline_buyer_items" and flt(rate.get("rate")):
			out.selling_price = flt(rate.get("rate"), 2)
		else:
			out.selling_price = flt(out.mrp * (1 - out.flat / 100.0), 2)
		return out
	mrp_value = flt(get_customer_item_mrp(customer, item_code)) if customer else 0
	if not mrp_value:
		mrp_value = flt(frappe.db.get_value("Item", item_code, "valuation_rate"))
	out.mrp = mrp_value
	out.selling_price = flt(mrp_value, 2)
	return out


def box_count(qty, item_code, mode):
	"""Box from Quantity (3.2): the Box UOM factor, rounded by the Customer Type's rule."""
	from alpinos.sales_order_api import get_box_conversion_factor

	factor = flt(get_box_conversion_factor(item_code, strict=1))
	if not factor or not flt(qty):
		return 0
	raw = flt(qty) / factor
	if mode == "up":
		return ceil(raw)
	if mode == "down":
		return floor(raw)
	return flt(raw, 2)


def _gst_exclusive(doc):
	buyer = buyer_of(doc)
	return cint(frappe.db.get_value("Buyer Master", buyer, "gst_exclusive_buyer")) if buyer else 0


def _row_amounts(row, gst_exclusive, conversion_rate):
	"""Line Amount = Quantity x Selling Price (GST included, as on the Sales Order); ERPNext's
	rate / amount carry the value before GST, the Tax column the GST in it."""
	from alpinos.sales_order_api import _calculate_sales_order_line_values

	qty = flt(row.get("qty"))
	selling_price = flt(row.get("custom_selling_price"), 2)
	row.custom_line_amount = flt(qty * selling_price, 2)
	gst = flt(frappe.db.get_value("Item", row.item_code, "custom_gst_percent")) if row.get("item_code") else 0
	calc = _calculate_sales_order_line_values(
		{
			"qty": qty,
			"custom_customer_mrp": flt(row.get("custom_mrp")),
			"custom_selling_price": selling_price,
			"custom_flat_discount": flt(row.get("custom_flat_discount")),
			"custom_offer": 0,
			"custom_additional_discount": 0,
			"custom_gst_percent": gst,
		},
		gst_exclusive,
	)
	if calc.get("computed"):
		row.rate = flt(calc["rate"])
		row.amount = flt(calc["amount"])
		row.custom_item_tax = flt(calc.get("gst_amount"))
	else:
		row.rate = row.amount = row.custom_item_tax = 0
	row.base_rate = flt(row.rate * flt(conversion_rate or 1), 2)
	row.base_amount = flt(row.amount * flt(conversion_rate or 1), 2)


def price_rows(doc):
	"""Draft save: every Order Item row priced from the Buyer Catalog; typed values are dropped."""
	from alpinos.sales_order_api import _buyer_rounds_per_unit, get_box_rounding_mode

	customer = customer_of(doc)
	round_per_unit = _buyer_rounds_per_unit(customer)
	mode = get_box_rounding_mode(customer, doc.get("custom_site_name"), doc.get("custom_order_type"))
	for row in doc.get("items") or []:
		if not row.get("item_code"):
			continue
		p = line_pricing(customer, row.item_code, row.get("custom_mrp"))
		selling_price = flt(p.selling_price, 2)
		if round_per_unit and selling_price:
			selling_price = round(selling_price)
		row.custom_mrp = p.mrp
		row.custom_flat_discount = p.flat
		row.custom_buyer_margin_percent = p.flat
		row.custom_offer = "0"
		row.custom_additional_discount = 0
		row.custom_selling_price = selling_price
		row.custom_boxes = box_count(row.qty, row.item_code, mode)


def set_totals(doc):
	"""Totals from the rows as they stand (also on a locked Opportunity, where ERPNext's own
	calculate_totals would otherwise put its pre-GST sum back)."""
	gst_exclusive = _gst_exclusive(doc)
	conversion_rate = flt(doc.get("conversion_rate")) or 1
	total = gst = over = 0.0
	for row in doc.get("items") or []:
		if not row.get("item_code"):
			continue
		_row_amounts(row, gst_exclusive, conversion_rate)
		total += flt(row.custom_line_amount)
		gst += flt(row.custom_item_tax)
		over += max(flt(row.custom_mrp) * flt(row.qty) - flt(row.custom_line_amount), 0)
	doc.total = doc.opportunity_amount = flt(total, 2)
	doc.base_total = doc.base_opportunity_amount = flt(total * conversion_rate, 2)
	doc.custom_gst_total = flt(gst, 2)
	doc.custom_over_discount = flt(over, 2)
	doc.custom_additional_discount_total = 0
	doc.custom_cash_discount = 0


# ----------------------------------------------------------------------------- doc events


def _norm(value, fieldtype):
	if fieldtype in ("Int", "Check"):
		return cint(value)
	if fieldtype in ("Float", "Currency", "Percent"):
		return round(flt(value), 6)
	return cstr(value).strip()


def _rows_of(doc, df):
	meta = frappe.get_meta(df.options)
	fields = [d for d in meta.fields if d.fieldtype not in _NO_VALUE and d.fieldname not in _CHILD_IGNORED]
	return [tuple(_norm(r.get(d.fieldname), d.fieldtype) for d in fields) for r in doc.get(df.fieldname) or []]


def changed_fields(before, doc, ignore=()):
	"""The fields (header and tables) whose values differ between two versions."""
	out = []
	for df in frappe.get_meta(DOCTYPE).fields:
		if df.fieldtype in _NO_VALUE or df.fieldname in _LOCK_IGNORED or df.fieldname in ignore:
			continue
		if df.fieldtype in ("Table", "Table MultiSelect"):
			if _rows_of(before, df) != _rows_of(doc, df):
				out.append(df)
		elif _norm(before.get(df.fieldname), df.fieldtype) != _norm(doc.get(df.fieldname), df.fieldtype):
			out.append(df)
	return out


def before_validate(doc, method=None):
	before = None if doc.is_new() else doc.get_doc_before_save()
	acting = doc.flags.alpinos_opportunity_action
	portal = doc.flags.from_order_portal

	if doc.is_new():
		doc.set(STATUS, DRAFT)
		for f in SYSTEM_FIELDS:
			if f != STATUS:
				doc.set(f, None)
		if not portal:
			doc.custom_opportunity_source = DIRECT
			for f in PORTAL_FIELDS[1:]:
				doc.set(f, None)
		doc.custom_opportunity_source = doc.get("custom_opportunity_source") or DIRECT
		doc.custom_created_by = None if portal else frappe.session.user
		doc.custom_created_on = now_datetime()
		if not doc.get("opportunity_from"):
			doc.opportunity_from = BUYER_PARTY
		# what the desk form fills in the browser, for an Opportunity made without it (the portal)
		if not doc.get("company"):
			doc.company = frappe.defaults.get_user_default("Company") or frappe.defaults.get_global_default("company")
		if not doc.get("currency") and doc.get("company"):
			doc.currency = frappe.get_cached_value("Company", doc.company, "default_currency")
			doc.conversion_rate = 1
	elif before:
		# 3.1 Submitted Opportunity Lock Rule: nothing changes once it has left Pending (Draft)
		if not acting and status_of(before) != DRAFT:
			changes = changed_fields(before, doc)
			if changes:
				frappe.throw(
					_("This Opportunity is {0} and can no longer be changed ({1}).").format(
						_(status_of(before)), ", ".join(_(df.label or df.fieldname) for df in changes[:5])
					),
					title=_("Not Permitted"),
				)
		if not acting:
			for f in SYSTEM_FIELDS:
				if cstr(doc.get(f)) != cstr(before.get(f)):
					frappe.throw(_("Opportunity Status changes only through its actions."), title=_("Not Permitted"))
		if not portal:
			for f in PORTAL_FIELDS:
				if cstr(doc.get(f)) != cstr(before.get(f)):
					frappe.throw(
						_("{0} is set by the system and cannot be changed.").format(_label(f)), title=_("Not Permitted")
					)
		for f in CREATION_FIELDS:
			doc.set(f, before.get(f))

	_validate_rows_on_save(doc)


def _validate_rows_on_save(doc):
	"""Quantities (3.2-3.5, 7.2): zero or negative blocks the save. Runs before ERPNext's own
	quantity check so the document's message is the one shown."""
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
	for table, label in ITEM_TABLES:
		codes = {r.item_code for r in doc.get(table) or [] if r.get("item_code")}
		if not codes:
			continue
		inactive = frappe.get_all("Item", filters={"name": ("in", list(codes)), "disabled": 1}, pluck="name")
		if inactive:
			frappe.throw(_("SKU {0} is not active.").format(", ".join(sorted(inactive))), title=_(label))


def validate(doc, method=None):
	"""After ERPNext's validate: header from the Buyer, prices (Draft only), totals, gates."""
	before = None if doc.is_new() else doc.get_doc_before_save()
	draft = doc.is_new() or status_of(before) == DRAFT
	buyer = buyer_of(doc)

	if draft and buyer:
		row = frappe.db.get_value(
			"Buyer Master", buyer, ["customer_type", "customer_business_name", "secondary_poc"], as_dict=True
		) or {}
		if row.get("customer_type"):
			doc.custom_order_type = row.customer_type
		doc.custom_secondary_poc = row.get("secondary_poc")
		party_changed = doc.is_new() or (before and before.get("party_name") != doc.party_name)
		if party_changed and not doc.flags.alpinos_opportunity_action:
			reason = create_block_reason(buyer)
			if reason:
				frappe.throw(reason, title=_("Buyer Not Ready"))
			if not doc.flags.from_order_portal:
				_assert_assigned(doc)
		_validate_header_belongs(doc)

	if draft:
		price_rows(doc)
	set_totals(doc)


def _validate_header_belongs(doc):
	"""Site Name and the addresses must be the Buyer's own (3.1 #6-#8)."""
	from alpinos.sales_order_offline_buyer import buyer_family_customers, get_customer_family_sites

	customer = customer_of(doc)
	if not customer:
		return
	site = cstr(doc.get("custom_site_name")).strip()
	if site:
		sites = get_customer_family_sites(customer)
		if sites and site not in sites:
			frappe.throw(_("Site {0} is not a site of this Buyer.").format(frappe.bold(site)), title=_("Site Name"))
	family = buyer_family_customers(customer) or [customer]
	for field in ("custom_billing_address", "customer_address"):
		address = doc.get(field)
		if address and not frappe.db.exists(
			"Dynamic Link",
			{"parenttype": "Address", "parent": address, "link_doctype": "Customer", "link_name": ("in", family)},
		):
			frappe.throw(
				_("{0} {1} is not an address of this Buyer.").format(_label(field), frappe.bold(address)),
				title=_label(field),
			)


def after_insert(doc, method=None):
	"""Opportunity Created: creator, Opportunity ID, Customer, Source. The portal writes its own
	entry for a Buyer Order Request (BOR reference, contact), so not for that one."""
	if doc.flags.from_order_portal:
		return
	details = f"{doc.get('customer_name') or doc.party_name} ({doc.get('custom_opportunity_source') or DIRECT})"
	audit.log(DOCTYPE, doc.name, "Opportunity Created", _("Opportunity"), "", details)


def on_update(doc, method=None):
	"""Opportunity Draft Saved: the fields that changed. A Buyer's edit through the portal is
	logged by the portal itself ("Opportunity Updated")."""
	if doc.flags.alpinos_opportunity_action or doc.flags.in_insert or doc.flags.from_order_portal:
		return
	before = doc.get_doc_before_save()
	if not before:
		return
	action = "Opportunity Draft Saved"
	ignore = set(SYSTEM_FIELDS) | set(CREATION_FIELDS) | {
		"custom_secondary_poc", "total", "base_total", "opportunity_amount", "base_opportunity_amount",
		"custom_gst_total", "custom_over_discount", "customer_name", "title", "address_display",
	}
	for df in changed_fields(before, doc, ignore=ignore):
		if df.fieldtype in ("Table", "Table MultiSelect"):
			audit.log(DOCTYPE, doc.name, action, _(df.label), _table_summary(before, df.fieldname), _table_summary(doc, df.fieldname))
		else:
			audit.log(DOCTYPE, doc.name, action, _(df.label), before.get(df.fieldname), doc.get(df.fieldname))


def _table_summary(doc, table):
	return "; ".join(f"{r.item_code} x {flt(r.qty):g}" for r in doc.get(table) or [] if r.get("item_code"))


# ----------------------------------------------------------------------------- actions


def _validate_for_submit(doc):
	"""Submit Opportunity "validates form" (5, 6.1): the header, every row, the Buyer."""
	from alpinos import item_mrp as IM
	from alpinos.sales_order_offline_buyer import get_customer_family_sites

	errors = []
	if not doc.get("party_name"):
		errors.append(_("Select the Customer."))
	if not doc.get("custom_order_type"):
		errors.append(_("Customer Type is missing."))
	buyer = buyer_of(doc)
	if buyer:
		customer = customer_of(doc)
		if not cstr(doc.get("custom_site_name")).strip() and customer and get_customer_family_sites(customer):
			errors.append(_("Select the Site Name."))
		if not doc.get("custom_billing_address"):
			errors.append(_("Select the Billing Address."))
		if not doc.get("customer_address"):
			errors.append(_("Select the Shipping Address."))
	if not [r for r in doc.get("items") or [] if r.get("item_code")]:
		errors.append(_("Add at least one SKU to the Order Items."))
	for row in doc.get("items") or []:
		if not row.get("item_code"):
			errors.append(_("Order Items row {0}: select the SKU.").format(row.idx))
			continue
		mrp_error = IM.line_mrp_error(row.item_code, row.get("custom_mrp"))
		if mrp_error:
			errors.append(_("Order Items row {0}: {1}").format(row.idx, mrp_error))
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
	if errors:
		frappe.throw("<br>".join(errors), title=_("Opportunity cannot be submitted"))
	reason = create_block_reason(buyer)
	if reason:
		frappe.throw(reason, title=_("Buyer Not Ready"))


def _set_status(doc, to_status, action, trail_action, current, reason=None, extra=None):
	doc.flags.alpinos_opportunity_action = action
	doc.set(STATUS, to_status)
	for k, v in (extra or {}).items():
		doc.set(k, v)
	doc.save(ignore_permissions=True)
	audit.status_change(DOCTYPE, doc.name, trail_action, current, to_status, reason=reason or None)


@frappe.whitelist()
def opportunity_action(name, action, reason=None):
	"""Submit Opportunity / Put on Hold / Mark as Lost / Cancel Opportunity / Resume."""
	# company-scope: n/a (one Opportunity, after its own write permission check)
	if action not in ACTIONS:
		frappe.throw(_("Unknown action {0}.").format(action))
	doc = frappe.get_doc(DOCTYPE, name)
	doc.check_permission("write")
	_assert_actor()
	from_statuses, to_status, needs_reason, trail_action, verb = ACTIONS[action]
	current = status_of(doc)
	if current not in from_statuses:
		frappe.throw(
			_("An Opportunity that is {0} cannot be {1}.").format(_(current), _(verb)), title=_("Not Permitted")
		)
	reason = cstr(reason).strip()
	if needs_reason and not reason:
		frappe.throw(_("Enter the reason."), title=_("Reason Required"))

	extra = {}
	if action == "submit":
		_validate_for_submit(doc)
		extra = {"custom_submitted_by": frappe.session.user, "custom_submitted_on": now_datetime()}
	elif action == "hold":
		extra = {"custom_status_before_hold": current, "custom_status_reason": reason}
	elif action in ("lost", "cancel"):
		extra = {"custom_status_reason": reason}
	elif action == "resume":
		to_status = doc.get("custom_status_before_hold") if doc.get("custom_status_before_hold") in (DRAFT, SUBMITTED) else DRAFT
		extra = {"custom_status_before_hold": None, "custom_status_reason": None}

	_set_status(doc, to_status, action, trail_action, current, reason=reason, extra=extra)
	return {"status": to_status, "message": _("Opportunity {0}.").format(_(verb))}


def active_quotation(doc):
	"""The non-cancelled Quotation of this Opportunity, if there is one (S5 "One Active
	Quotation per Opportunity")."""
	linked = doc.get("custom_linked_quotation")
	if linked and cint(frappe.db.get_value("Quotation", linked, "docstatus")) < 2 and frappe.db.exists("Quotation", linked):
		return linked
	return frappe.db.get_value("Quotation", {"opportunity": doc.name, "docstatus": ("<", 2)}, "name")


@frappe.whitelist()
def convert_to_quotation(name):
	"""Convert to Quotation (5, 6.1): a Draft Quotation with the Opportunity's header and its four
	item tables, linked both ways; the Opportunity becomes Converted to Quotation."""
	# company-scope: n/a (one Opportunity, after its own write permission check)
	doc = frappe.get_doc(DOCTYPE, name)
	doc.check_permission("write")
	_assert_actor()
	current = status_of(doc)
	existing = active_quotation(doc)
	if existing and current in (SUBMITTED, CONVERTED, WON, PARTIAL):
		frappe.throw(_(M_ACTIVE_QUOTATION).format(existing), title=_("Quotation Exists"))
	if current != SUBMITTED:
		frappe.throw(
			_("Only a Pending (Submitted) Opportunity can be converted to a Quotation. This one is {0}.").format(_(current)),
			title=_("Not Permitted"),
		)
	reason = convert_block_reason(buyer_of(doc))
	if reason:
		frappe.throw(reason, title=_("Buyer Not Ready"))

	quotation = build_quotation(doc)
	quotation.flags.alpinos_from_opportunity = True
	# The Draft carries what the Opportunity has; its payment details (Payment Mode proof,
	# Expected Payment Date) are entered on the Quotation itself (Section 5), whose own save
	# asks for them.
	quotation.flags.ignore_mandatory = True
	quotation.insert()

	_set_status(doc, CONVERTED, "convert", "Converted to Quotation", current, extra={"custom_linked_quotation": quotation.name})
	audit.log(DOCTYPE, doc.name, "Converted to Quotation", _("Linked Quotation ID"), "", quotation.name)
	return {"quotation": quotation.name, "status": CONVERTED}


def build_quotation(opp):
	"""The Draft Quotation for an Opportunity (not saved)."""
	from frappe.contacts.doctype.address.address import get_address_display

	from alpinos.opportunity_make_quotation import map_quotation

	quotation = map_quotation(opp.name)
	if opp.get("custom_billing_address"):
		quotation.customer_address = opp.custom_billing_address
		quotation.address_display = get_address_display(opp.custom_billing_address)
	if opp.get("customer_address"):
		quotation.shipping_address_name = opp.customer_address
		quotation.shipping_address = get_address_display(opp.customer_address)
	quotation.order_type = opp.get("custom_order_type") or quotation.get("order_type")
	quotation.custom_site_name = opp.get("custom_site_name")
	quotation.custom_opportunity_remark = opp.get("custom_common_remark")

	# the mapper copies the rows in order, one Quotation row per Opportunity row
	if frappe.get_meta("Quotation Item").has_field("custom_remarks"):
		for row, src in zip(quotation.get("items") or [], opp.get("items") or []):
			if src.get("custom_row_remark"):
				row.custom_remarks = src.custom_row_remark

	for table, _label_text in ITEM_TABLES[1:]:
		quotation.set(table, [])
		for src in opp.get(table) or []:
			values = {
				k: v for k, v in src.as_dict().items()
				if k not in _CHILD_IGNORED and k not in ("doctype", "__islocal", "__unsaved")
			}
			quotation.append(table, values)
	quotation.custom_additional_units_damage = cint(opp.get("custom_additional_units_damage"))
	return quotation


# ----------------------------------------------------------------------------- Won / Partial


def _order_qty(rows):
	out = {}
	for r in rows or []:
		if r.get("item_code") and not cint(r.get("is_free_item")):
			out[r.item_code] = flt(out.get(r.item_code)) + flt(r.get("qty"))
	return out


def compare(opportunity, quotation):
	"""6.2: the standard Order Items of both, quantity per SKU. Freebies, Scheme Items and
	Additional Unit / Damage rows are other tables and never counted."""
	wanted = _order_qty(opportunity.get("items"))
	offered = _order_qty(quotation.get("items"))
	shortfalls = [
		{"item_code": sku, "opportunity_qty": qty, "quotation_qty": flt(offered.get(sku))}
		for sku, qty in wanted.items()
		if flt(offered.get(sku)) < qty
	]
	return frappe._dict(result=PARTIAL if shortfalls else WON, shortfalls=shortfalls)


def _linked_opportunity(quotation):
	opp = quotation.get("opportunity")
	if not opp or not frappe.db.exists(DOCTYPE, opp):
		return None
	doc = frappe.get_doc(DOCTYPE, opp)
	if doc.get("custom_linked_quotation") != quotation.name or status_of(doc) != CONVERTED:
		return None
	return doc


@frappe.whitelist()
def quotation_result(quotation):
	"""For the Quotation's Finalize dialog: would it make its Opportunity Won or Partial?"""
	# company-scope: n/a (one Quotation, after its own read permission check)
	q = frappe.get_doc("Quotation", quotation)
	q.check_permission("read")
	opp = _linked_opportunity(q)
	if not opp:
		return {"opportunity": None}
	r = compare(opp, q)
	return {"opportunity": opp.name, "result": r.result, "shortfalls": r.shortfalls, "reason_required": int(r.result == PARTIAL)}


def apply_quotation_finalized(quotation, partial_reason=None):
	"""Called when `quotation` becomes Finalized (Section 5's Finalize Quotation).

	Returns Won / Partial, or None for a Quotation that is not the converted one of an
	Opportunity (a Standalone Quotation has no Opportunity result). Partial needs the reason
	of whoever finalizes; without it nothing changes and the call is refused."""
	q = quotation if not isinstance(quotation, str) else frappe.get_doc("Quotation", quotation)
	opp = _linked_opportunity(q)
	if not opp:
		return None
	r = compare(opp, q)
	reason = cstr(partial_reason).strip()
	if r.result == PARTIAL and not reason:
		short = ", ".join(
			f"{s['item_code']} ({flt(s['quotation_qty']):g} of {flt(s['opportunity_qty']):g})" for s in r.shortfalls
		)
		frappe.throw(
			_("Quotation {0} does not cover every SKU and quantity of Opportunity {1} ({2}). Enter the Partial Reason.").format(
				q.name, opp.name, short
			),
			title=_("Partial Reason Required"),
		)
	opp.flags.alpinos_opportunity_action = "quotation_finalized"
	opp.set(STATUS, r.result)
	opp.custom_status_reason = reason if r.result == PARTIAL else None
	opp.save(ignore_permissions=True)
	if r.result == WON:
		log_field_change(
			DOCTYPE, opp.name, _("Status"), CONVERTED, WON, after_submit=0, action="Opportunity Won",
			user_role="System", reason=None,
		)
		audit.log(DOCTYPE, opp.name, "Opportunity Won", _("Linked Finalized Quotation"), "", q.name)
	else:
		audit.status_change(DOCTYPE, opp.name, "Opportunity Partial", CONVERTED, PARTIAL, reason=reason)
		audit.log(DOCTYPE, opp.name, "Opportunity Partial", _("Linked Finalized Quotation"), "", q.name)
	return r.result


# ----------------------------------------------------------------------------- form support


def _people(rows_or_names):
	names = [r for r in rows_or_names if r]
	if not names:
		return []
	full = dict(frappe.get_all("Employee", filters={"name": ("in", names)}, fields=["name", "employee_name"], as_list=True))
	return [full.get(n) or n for n in names]


@frappe.whitelist()
def buyer_context(party_name, sync_addresses=0):
	"""For the form: the Buyer's header values, sites, readiness and assignments.

	sync_addresses=1 (when the Customer is picked) first turns the Buyer's address rows into
	the Address records the pickers offer, as the Sales Order entry page does."""
	# company-scope: n/a (Buyer Master has no company; the caller's read permission is checked)
	from alpinos.offline_sales.buyer_rules import catalog_of
	from alpinos.offline_sales.buyer_rules import status_of as buyer_status
	from alpinos.sales_order_offline_buyer import get_customer_family_sites, sync_offline_buyer_master_addresses

	if not party_name or not frappe.db.exists("Buyer Master", party_name):
		return {}
	frappe.has_permission("Buyer Master", "read", party_name, throw=True)
	bm = frappe.get_doc("Buyer Master", party_name)
	sites = get_customer_family_sites(bm.customer) if bm.customer else []
	if bm.customer and cint(sync_addresses):
		sync_offline_buyer_master_addresses(bm.customer)
	default_site = (bm.get("site_name") or "").strip()
	if default_site not in sites:
		default_site = sites[0] if sites else ""
	return {
		"customer": bm.customer,
		"customer_name": bm.customer_business_name,
		"customer_type": bm.customer_type,
		"buyer_status": buyer_status(bm),
		"buyer_catalog_status": catalog_of(bm),
		"sites": sites,
		"default_site": default_site,
		"sales_officers": _people([r.employee for r in bm.get("sales_officers") or []]),
		"primary_pocs": _people([r.employee for r in bm.get("primary_pocs") or []]),
		"secondary_poc": (_people([bm.secondary_poc]) or [None])[0],
		"create_blocked_reason": create_block_reason(party_name),
		"convert_blocked_reason": convert_block_reason(party_name),
	}


@frappe.whitelist()
def site_addresses(party_name, site_name=None):
	"""The Site's Primary Billing and Primary Shipping addresses (3.1 #7, #8 defaults)."""
	# company-scope: n/a (Buyer Master has no company; the caller's read permission is checked)
	from alpinos.sales_order_offline_buyer import site_address_options

	frappe.has_permission("Buyer Master", "read", party_name, throw=True)
	customer = frappe.db.get_value("Buyer Master", party_name, "customer")
	billing, shipping, every = site_address_options(customer, site_name)
	return {"billing": (billing or every or [None])[0], "shipping": (shipping or every or [None])[0]}


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def address_query(doctype, txt, searchfield, start, page_len, filters):
	"""Billing / Shipping Address pickers: only the Buyer's billing (or shipping) addresses."""
	# company-scope: n/a (the Buyer's own addresses; the caller's read permission is checked)
	from alpinos.sales_order_offline_buyer import site_address_options

	party = (filters or {}).get("party_name")
	kind = (filters or {}).get("kind") or "billing"
	if not party or not frappe.has_permission("Buyer Master", "read", party):
		return []
	customer = frappe.db.get_value("Buyer Master", party, "customer")
	billing, shipping, every = site_address_options(customer, None)
	names = (shipping if kind == "shipping" else billing) or every
	if not names:
		return []
	txt = cstr(txt).lower().strip("%")
	rows = frappe.get_all(
		"Address", filters={"name": ("in", names)}, fields=["name", "address_line1", "city", "custom_site_name"]
	)
	order = {n: i for i, n in enumerate(names)}
	rows.sort(key=lambda r: order.get(r.name, 0))
	out = []
	for r in rows:
		text = ", ".join(v for v in (r.custom_site_name, r.address_line1, r.city) if v)
		if txt and txt not in (r.name + " " + text).lower():
			continue
		out.append((r.name, text))
	return out[cint(start) : cint(start) + cint(page_len or 20)]


@frappe.whitelist()
def line_values(party_name, item_code, qty=0, mrp=None, site_name=None):
	"""For the form, right after an SKU or Quantity is entered: what the server will store."""
	# company-scope: n/a (pricing of one SKU for one Buyer; get_offline_buyer_item_rate follows the company)
	from alpinos.sales_order_api import _buyer_rounds_per_unit, get_box_rounding_mode

	if not (frappe.has_permission(DOCTYPE, "create") or frappe.has_permission(DOCTYPE, "write")):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	customer = frappe.db.get_value("Buyer Master", party_name, "customer") if party_name else None
	customer_type = frappe.db.get_value("Buyer Master", party_name, "customer_type") if party_name else None
	p = line_pricing(customer, item_code, mrp)
	selling_price = flt(p.selling_price, 2)
	if _buyer_rounds_per_unit(customer) and selling_price:
		selling_price = round(selling_price)
	mode = get_box_rounding_mode(customer, site_name, customer_type)
	return {
		"custom_mrp": p.mrp,
		"custom_flat_discount": p.flat,
		"custom_selling_price": selling_price,
		"custom_offer": "0",
		"custom_additional_discount": 0,
		"custom_boxes": box_count(qty, item_code, mode),
		"custom_line_amount": flt(flt(qty) * selling_price, 2),
		"mrp_options": p.mrp_options,
		"needs_mrp": p.needs_mrp,
	}


def duplicate_sku_warning(doc, row_name):
	"""3.5 Duplicate SKU Alert: the warning for an Order Items SKU that is already in another
	Order Items row, or in Marketing Freebies / Scheme Items; None when it is not."""
	rows = doc.get("items") or []
	row = next((r for r in rows if r.get("name") == row_name), None)
	sku = row.get("item_code") if row else None
	if not sku:
		return None
	for table in ("items", "custom_marketing_freebies", "custom_scheme_item_table"):
		for other in doc.get(table) or []:
			if table == "items" and other.get("name") == row_name:
				continue
			if other.get("item_code") == sku:
				return _(M_DUPLICATE).format(sku, other.get("idx"))
	return None


@frappe.whitelist()
def get_duplicate_sku_warning(doc, row_name):
	"""The form's call for duplicate_sku_warning (the unsaved form is sent, nothing is read)."""
	# company-scope: n/a (reads nothing: works on the form values it is sent)
	doc = frappe._dict(json.loads(doc) if isinstance(doc, str) else doc)
	for table in ("items", "custom_marketing_freebies", "custom_scheme_item_table"):
		doc[table] = [frappe._dict(r) for r in doc.get(table) or []]
	return duplicate_sku_warning(doc, row_name)


@frappe.whitelist()
def form_actions(name):
	"""The actions this user may take on this Opportunity now, and why Convert is not one."""
	# company-scope: n/a (one Opportunity, after its own read permission check)
	doc = frappe.get_doc(DOCTYPE, name)
	doc.check_permission("read")
	status = status_of(doc)
	can = is_actor() and frappe.has_permission(DOCTYPE, "write", doc)
	actions = [a for a, spec in ACTIONS.items() if can and status in spec[0]]
	convert = can and status == SUBMITTED
	return {
		"status": status,
		"actions": actions,
		"convert": int(convert),
		"convert_blocked_reason": convert_block_reason(buyer_of(doc)) if convert else None,
		"active_quotation": active_quotation(doc) if convert else None,
	}
