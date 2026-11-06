"""Goods Return Request rules (FSD sections 1 and 2; Phase A).

The request is the central record of a customer return (INT-BR-01). What is checked here:

  * who: Coordinator + a role of the request's channel, on save, submit and cancel (2.3);
  * the returning party belongs to the request's channel, as on the Sales Order screens;
  * Customer-to-Customer Redistribution names a different destination customer (1.5.4);
  * an original Sales Order / Delivery Note is a submitted one of the same customer,
    company and channel;
  * every item has a quantity above 0 and an enabled reason (INT-AC-06); the same SKU may
    come back under two reasons, but not twice with the same batch, MRP and reason;
  * Supplementary requests are made by the system only (1.8.1), so a user's request is
    always Normal.

What is submitted stays as submitted (INT-BR-05): every field except reverse logistics is
locked by submission itself; only the logistics section is allow_on_submit.
"""

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt

from alpinos.goods_return import NORMAL, REDISTRIBUTION, SUPPLEMENTARY
from alpinos.goods_return import access


def before_insert(doc):
	# The company has to be known before the name is made: its Series Code goes into the
	# number (company_scope.numbering runs on before_naming, ahead of before_validate).
	if not doc.get("company"):
		from alpinos.company_scope.helpers import current_company

		doc.company = current_company() or frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
			"Global Defaults", "default_company"
		)


def validate(doc):
	access.assert_can_raise(doc, _("save"))
	_request_type(doc)
	_party(doc)
	_references(doc)
	_items(doc)
	if doc.docstatus == 0:
		doc.status = "Draft"


def before_submit(doc):
	access.assert_can_raise(doc, _("submit"))


def on_submit(doc):
	doc.db_set("status", "Submitted", update_modified=False)


def before_cancel(doc):
	access.assert_can_raise(doc, _("cancel"))


def on_cancel(doc):
	doc.db_set("status", "Cancelled", update_modified=False)


def before_update_after_submit(doc):
	# only reverse logistics is editable after submission
	access.assert_can_raise(doc, _("update"))


# ----------------------------------------------------------------------------- rules


def _request_type(doc):
	if doc.get("request_type") == SUPPLEMENTARY and frappe.flags.goods_return_system:
		return
	if doc.get("request_type") == SUPPLEMENTARY:
		frappe.throw(_("A Supplementary request is created by the system from a Return GRN, not by hand."))
	doc.request_type = NORMAL


def _party(doc):
	buyer = access.customer_in_channel(doc.customer, doc.channel)
	if not buyer:
		frappe.throw(
			_("{0} is not a buyer in the {1} channel. Pick a returning party from that channel.").format(
				frappe.bold(doc.customer_name or doc.customer), doc.channel
			)
		)
	doc.buyer_master = buyer

	if doc.return_handling_type == REDISTRIBUTION:
		if not doc.get("destination_customer"):
			frappe.throw(_("Enter the Destination Customer the goods are redistributed to."))
		if doc.destination_customer == doc.customer:
			frappe.throw(_("The Destination Customer must be different from the returning party."))
	else:
		doc.destination_customer = None
		doc.destination_customer_name = None


def _references(doc):
	so_channel = None
	if doc.get("sales_order"):
		so = frappe.db.get_value(
			"Sales Order", doc.sales_order, ["customer", "company", "docstatus", "custom_channel"], as_dict=True
		)
		if not so or so.docstatus != 1:
			frappe.throw(_("Sales Order {0} is not submitted.").format(frappe.bold(doc.sales_order)))
		if so.customer != doc.customer:
			frappe.throw(_("Sales Order {0} is not an order of {1}.").format(
				frappe.bold(doc.sales_order), frappe.bold(doc.customer_name or doc.customer)))
		if so.company != doc.company:
			frappe.throw(_("Sales Order {0} belongs to {1}.").format(frappe.bold(doc.sales_order), so.company))
		so_channel = so.custom_channel or "Offline"
		if access.family(so_channel) != access.family(doc.channel):
			frappe.throw(_("Sales Order {0} is a {1} order, and this request is for {2}.").format(
				frappe.bold(doc.sales_order), so_channel, doc.channel))

	if doc.get("delivery_note"):
		dn = frappe.db.get_value(
			"Delivery Note",
			doc.delivery_note,
			["customer", "company", "docstatus", "is_return", "custom_sales_order_id"],
			as_dict=True,
		)
		if not dn or dn.docstatus != 1 or cint(dn.is_return):
			frappe.throw(_("Delivery Note {0} is not a submitted delivery.").format(frappe.bold(doc.delivery_note)))
		if dn.customer != doc.customer:
			frappe.throw(_("Delivery Note {0} is not a delivery to {1}.").format(
				frappe.bold(doc.delivery_note), frappe.bold(doc.customer_name or doc.customer)))
		if dn.company != doc.company:
			frappe.throw(_("Delivery Note {0} belongs to {1}.").format(frappe.bold(doc.delivery_note), dn.company))
		if doc.get("sales_order") and dn.custom_sales_order_id and dn.custom_sales_order_id != doc.sales_order:
			frappe.throw(_("Delivery Note {0} belongs to Sales Order {1}, not {2}.").format(
				frappe.bold(doc.delivery_note), dn.custom_sales_order_id, doc.sales_order))
		if not doc.get("sales_order") and dn.custom_sales_order_id:
			channel = frappe.db.get_value("Sales Order", dn.custom_sales_order_id, "custom_channel") or "Offline"
			if access.family(channel) != access.family(doc.channel):
				frappe.throw(_("Delivery Note {0} is a {1} delivery, and this request is for {2}.").format(
					frappe.bold(doc.delivery_note), channel, doc.channel))

	# a row taken from a Delivery Note keeps pointing at it
	dn_rows = {d.get("delivery_note_item") for d in doc.items if d.get("delivery_note_item")}
	if dn_rows:
		parents = dict(
			frappe.get_all(
				"Delivery Note Item",
				filters={"name": ["in", list(dn_rows)]},
				fields=["name", "parent"],
				as_list=True,
			)
		)
		for d in doc.items:
			ref = d.get("delivery_note_item")
			if ref and parents.get(ref) != doc.get("delivery_note"):
				# the row came from another Delivery Note than the one now on the request
				d.delivery_note_item = None
				d.mrp_batch = None


def _items(doc):
	if not doc.get("items"):
		frappe.throw(_("Add at least one item to return."))
	reasons = {d.return_reason for d in doc.items if d.return_reason}
	enabled = set(frappe.get_all("Goods Return Reason", {"name": ["in", list(reasons)], "enabled": 1}, pluck="name")) if reasons else set()
	seen = {}
	total = 0.0
	for d in doc.items:
		if flt(d.expected_qty) <= 0:
			frappe.throw(_("Row {0}: the expected return quantity of {1} must be more than 0.").format(d.idx, d.item_code))
		if not d.return_reason:
			frappe.throw(_("Row {0}: pick the return reason for {1}.").format(d.idx, d.item_code))
		if d.return_reason not in enabled:
			frappe.throw(_("Row {0}: return reason {1} is disabled.").format(d.idx, frappe.bold(d.return_reason)))
		if not d.get("uom"):
			d.uom = frappe.get_cached_value("Item", d.item_code, "stock_uom")
		d.batch_code = cstr(d.get("batch_code")).strip() or None
		key = (d.item_code, cstr(d.batch_code).upper(), flt(d.mrp, 2), d.return_reason)
		if key in seen:
			frappe.throw(
				_("Rows {0} and {1} are the same item, batch, MRP and reason ({2}). Put the quantity in one row.").format(
					seen[key], d.idx, d.item_code
				)
			)
		seen[key] = d.idx
		total += flt(d.expected_qty)
	doc.total_expected_qty = total
