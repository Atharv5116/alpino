"""
E-Commerce Sales Order — API.

Creates/edits Sales Orders on the E-com channel from the e-com entry page, reusing
the offline `_populate_so_from_entry` pricing/tax path (Selling Price is passed
through so the same GST split applies) and layering the e-com-only header fields:
channel, the 4 order-behaviour flags, PO Number/Date, Delivery-By, GSTINs, address
text, and per-line Margin %.

Also hosts the e-com validate hook (PO uniqueness, date/margin/GSTIN rules) which is
gated to E-com orders AND offline Modern-Trade orders (which carry the same fields).
"""

import re

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from alpinos.ecom_sales_order_custom_fields import CHANNEL_ECOM, is_modern_trade
from alpinos.sales_order_api import (
	_parse_so_entry_args,
	_populate_so_from_entry,
)
from alpinos.sales_order_api import get_box_conversion_factor
from alpinos.sales_order_offline_buyer import (
	get_offline_buyer_for_customer,
	get_offline_buyer_item_rate,
)

# 15-char GSTIN: 2 state digits, 5 letters, 4 digits, 1 letter, 1 alnum, 'Z', 1 alnum.
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")


# ---------------------------------------------------------------------------
# Buyer lookup (customer selection on the e-com entry page)
# ---------------------------------------------------------------------------
@frappe.whitelist()
def get_ecom_buyer_for_customer(customer):
	"""Full buyer profile for the e-com entry page: flags, addresses, GSTIN, type."""
	# Only order creators may look up buyer GSTIN/addresses (avoid RPC data leak).
	if not frappe.has_permission("Sales Order", "create"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	base = get_offline_buyer_for_customer(customer) or {}
	obm_name = base.get("offline_buyer_master")

	billing = {"address": "", "gstin": base.get("gst_no") or "", "state": "", "city": "", "pincode": ""}
	shipping = {"address": "", "gstin": base.get("gst_no") or "", "state": "", "city": "", "pincode": ""}

	if obm_name:
		obm = frappe.get_doc("Buyer Master", obm_name)
		rows = list(obm.get("addresses") or [])
		primary = next((r for r in rows if cint(r.get("is_primary"))), (rows[0] if rows else None))
		ship = next((r for r in rows if cint(r.get("is_shipping"))), None)

		def _fill(dst, row):
			if not row:
				return
			dst["address"] = row.get("address_line") or dst["address"]
			dst["state"] = row.get("state") or dst["state"]
			dst["city"] = row.get("city") or dst["city"]
			dst["pincode"] = row.get("pincode") or dst["pincode"]

		_fill(billing, primary)
		# Shipping: dedicated shipping row, else the header shipping_address text, else billing.
		if ship:
			_fill(shipping, ship)
		elif (obm.get("shipping_address") or "").strip():
			shipping["address"] = obm.get("shipping_address")
			shipping["state"] = obm.get("shipping_state") or shipping["state"]
			shipping["city"] = obm.get("shipping_city") or shipping["city"]
		else:
			shipping.update({k: billing[k] for k in ("address", "state", "city", "pincode")})

	return {
		**base,
		"billing": billing,
		"shipping": shipping,
	}


@frappe.whitelist()
def get_ecom_item_defaults(customer, item_code):
	"""SKU defaults for an e-com order row: MRP, box factor, GST %, margin, name."""
	# Buyer-specific pricing — restrict to order creators (avoid RPC price leak).
	if not frappe.has_permission("Sales Order", "create"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	if not item_code:
		return {}
	item = frappe.db.get_value(
		"Item", item_code, ["item_name", "custom_gst_percent"], as_dict=True
	) or {}
	rate = get_offline_buyer_item_rate(customer, item_code) or {}
	mrp = flt(rate.get("mrp"))
	margin = flt(rate.get("margin_percent"))
	selling = flt(mrp * (1 - margin / 100.0), 2) if mrp else 0.0
	return {
		"item_code": item_code,
		"item_name": item.get("item_name") or "",
		"mrp": mrp,
		"margin_percent": margin,
		"selling_price": selling,
		"gst_percent": flt(item.get("custom_gst_percent")),
		"box_factor": flt(get_box_conversion_factor(item_code)),
	}


# ---------------------------------------------------------------------------
# Create / Update
# ---------------------------------------------------------------------------
def _apply_ecom_header(so, *, flags, po_number, po_date, delivery_by_date,
                       billing_gstin, shipping_gstin, billing_address, shipping_address,
                       is_freebie_po, channel=CHANNEL_ECOM):
	"""Set the e-com header fields on the Sales Order (channel overridable so the
	offline Modern-Trade path can reuse this with channel='Offline')."""
	so.custom_channel = channel
	flags = flags or {}
	so.custom_appointment_required = cint(flags.get("appointment_required"))
	so.custom_grn_available = cint(flags.get("grn_available"))
	so.custom_partial_order_allowed = cint(flags.get("partial_order_allowed"))
	so.custom_gst_exclusive_buyer = cint(flags.get("gst_exclusive_buyer"))
	so.custom_po_number = (po_number or "").strip()
	so.custom_po_date = po_date or None
	so.custom_delivery_by_date = delivery_by_date or None
	so.custom_billing_gstin = (billing_gstin or "").strip().upper()
	so.custom_shipping_gstin = (shipping_gstin or "").strip().upper()
	so.custom_billing_address_text = (billing_address or "").strip()
	so.custom_shipping_address_text = (shipping_address or "").strip()
	so.custom_is_freebie_po = cint(is_freebie_po)
	# We own the flags — stop the generic sync from re-defaulting them from the buyer.
	so.flags.skip_ecom_flag_default = True


def apply_ecom_fields_to_so(so, ecom_fields, channel="Offline"):
	"""Apply the e-com header fields onto an offline Modern-Trade Sales Order.

	Called from the offline entry page's create/update path (channel stays 'Offline').
	Addresses are managed by the offline flow, so only flags/PO/GSTIN/freebie are set.
	"""
	data = _parse_json(ecom_fields) or {}
	if not data:
		return
	_apply_ecom_header(
		so,
		flags=data.get("flags") or {},
		po_number=data.get("po_number"),
		po_date=data.get("po_date"),
		delivery_by_date=data.get("delivery_by_date"),
		billing_gstin=data.get("billing_gstin"),
		shipping_gstin=data.get("shipping_gstin"),
		billing_address=None,
		shipping_address=None,
		is_freebie_po=data.get("is_freebie_po"),
		channel=channel,
	)


def _apply_ecom_item_margins(so, items):
	"""Copy per-line Margin % onto the appended Sales Order Item rows (1:1 by order)."""
	for i, row in enumerate(so.items):
		if i < len(items):
			row.custom_margin_percent = flt(items[i].get("margin_percent") or items[i].get("custom_margin_percent"))


def _ecom_common_populate(so, customer, order_type, company, items, freebies,
                          dispatch_date, delivery_by_date, po_number, po_expiry_date,
                          site_name, billing_address, shipping_address, taxes_and_charges):
	"""Route e-com payload through the shared offline populate helper.

	billing/shipping here are FREE TEXT (stored in custom_*_address_text by
	_apply_ecom_header) — never passed to the offline Address-record resolution,
	which expects real ERPNext Address names."""
	_populate_so_from_entry(
		so,
		customer=customer,
		order_type=order_type,
		company=company,
		items=items,
		cash_discount=0,
		delivery_date=delivery_by_date,
		dispatch_date=dispatch_date,
		freebies=freebies,
		scheme_items=[],
		additional_units_items=[],
		additional_units_damage=0,
		billing_address=None,
		shipping_address=None,
		taxes_and_charges=taxes_and_charges,
		po_no=po_number,
		po_expiry_date=po_expiry_date,
		site_name=site_name,
		from_quotation=None,
		po_no_for_pdf=None,
	)
	_apply_ecom_item_margins(so, items)


def _write_back_addresses_to_buyer(so):
	"""BRD Module 2 §2: a billing/shipping address edited on the e-com SO is
	stored back into the Buyer Master as a NEW address entry. Deduped against
	existing rows (normalized text) so repeated orders don't pile up copies."""
	obm_name = frappe.db.get_value("Buyer Master", {"customer": so.customer}, "name")
	if not obm_name:
		return

	def norm(s):
		return " ".join((s or "").lower().split())

	texts = []
	for fieldname, is_shipping in (("custom_billing_address_text", 0), ("custom_shipping_address_text", 1)):
		t = (so.get(fieldname) or "").strip()
		if t and norm(t) not in [norm(x) for _, x in texts]:
			texts.append((is_shipping, t))
	if not texts:
		return

	obm = frappe.get_doc("Buyer Master", obm_name)
	existing = {norm(r.address_line) for r in (obm.get("addresses") or [])}
	changed = False
	for is_shipping, t in texts:
		if norm(t) in existing:
			continue
		obm.append("addresses", {
			"address_line": t,
			"is_shipping": is_shipping,
			"site_name": (so.get("custom_site_name") or "").strip(),
		})
		existing.add(norm(t))
		changed = True
	if changed:
		obm.flags.ignore_permissions = True
		obm.flags.ignore_mandatory = True
		obm.save()


@frappe.whitelist()
def create_ecom_sales_order(customer, order_type, company, items, flags=None,
                            po_number=None, po_date=None, po_expiry_date=None,
                            delivery_by_date=None, dispatch_date=None,
                            billing_gstin=None, shipping_gstin=None,
                            billing_address=None, shipping_address=None,
                            site_name=None, is_freebie_po=0, freebies=None,
                            taxes_and_charges=None, submit_now=1):
	"""Create an E-com channel Sales Order from the e-com entry page."""
	if not frappe.has_permission("Sales Order", "create"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	items, freebies, _s, _a = _parse_so_entry_args(items, freebies, [], [])
	flags = _parse_json(flags) or {}

	so = frappe.new_doc("Sales Order")
	_apply_ecom_header(
		so, flags=flags, po_number=po_number, po_date=po_date,
		delivery_by_date=delivery_by_date, billing_gstin=billing_gstin,
		shipping_gstin=shipping_gstin, billing_address=billing_address,
		shipping_address=shipping_address, is_freebie_po=is_freebie_po,
	)
	_ecom_common_populate(
		so, customer, order_type, company, items, freebies,
		dispatch_date, delivery_by_date, po_number, po_expiry_date,
		site_name, billing_address, shipping_address, taxes_and_charges,
	)
	so.insert()
	if cint(submit_now):
		so.submit()
	_write_back_addresses_to_buyer(so)
	frappe.db.commit()
	return {"name": so.name, "docstatus": so.docstatus}


@frappe.whitelist()
def update_ecom_sales_order(name, customer, order_type, company, items, flags=None,
                            po_number=None, po_date=None, po_expiry_date=None,
                            delivery_by_date=None, dispatch_date=None,
                            billing_gstin=None, shipping_gstin=None,
                            billing_address=None, shipping_address=None,
                            site_name=None, is_freebie_po=0, freebies=None,
                            taxes_and_charges=None):
	"""Rewrite a draft E-com Sales Order from the e-com entry page (edit mode)."""
	items, freebies, _s, _a = _parse_so_entry_args(items, freebies, [], [])
	flags = _parse_json(flags) or {}

	so = frappe.get_doc("Sales Order", name)
	so.check_permission("write")
	if so.docstatus != 0:
		frappe.throw(_("Only draft Sales Orders can be edited from the entry page."))

	so.set("items", [])
	so.set("custom_marketing_freebies", [])
	_apply_ecom_header(
		so, flags=flags, po_number=po_number, po_date=po_date,
		delivery_by_date=delivery_by_date, billing_gstin=billing_gstin,
		shipping_gstin=shipping_gstin, billing_address=billing_address,
		shipping_address=shipping_address, is_freebie_po=is_freebie_po,
	)
	_ecom_common_populate(
		so, customer, order_type, company, items, freebies,
		dispatch_date, delivery_by_date, po_number, po_expiry_date,
		site_name, billing_address, shipping_address, taxes_and_charges,
	)
	so.save()
	_write_back_addresses_to_buyer(so)
	frappe.db.commit()
	return {"name": so.name, "docstatus": so.docstatus}


@frappe.whitelist()
def get_ecom_so_entry_payload(sales_order):
	"""Prefill payload for the e-com entry page (Edit drafts / Duplicate)."""
	doc = frappe.get_doc("Sales Order", sales_order)
	doc.check_permission("read")

	items = []
	for row in doc.items or []:
		items.append({
			"item_code": row.item_code,
			"item_name": row.get("item_name") or "",
			"warehouse": row.get("warehouse") or "",
			"qty": flt(row.qty),
			"box": flt(row.get("custom_box")),
			"mrp": flt(row.get("custom_customer_mrp")),
			"margin_percent": flt(row.get("custom_margin_percent")),
			"custom_selling_price": flt(row.get("custom_selling_price")),
			"gst_percent": flt(row.get("custom_gst_percent")),
			"rate": flt(row.rate),
			"amount": flt(row.amount),
		})

	freebies = [
		{"item_code": r.item_code, "item_name": r.get("item_name") or "", "qty": flt(r.qty)}
		for r in (doc.get("custom_marketing_freebies") or [])
	]

	return {
		"name": doc.name,
		"customer": doc.customer,
		"customer_name": doc.customer_name,
		"order_type": doc.order_type,
		"channel": doc.get("custom_channel") or CHANNEL_ECOM,
		"flags": {
			"appointment_required": cint(doc.get("custom_appointment_required")),
			"grn_available": cint(doc.get("custom_grn_available")),
			"partial_order_allowed": cint(doc.get("custom_partial_order_allowed")),
			"gst_exclusive_buyer": cint(doc.get("custom_gst_exclusive_buyer")),
		},
		"po_number": doc.get("custom_po_number") or "",
		"po_date": str(doc.get("custom_po_date") or ""),
		"po_expiry_date": str(doc.get("custom_po_expiry_date") or ""),
		"delivery_by_date": str(doc.get("custom_delivery_by_date") or ""),
		"dispatch_date": str(doc.get("custom_dispatch_date") or ""),
		"site_name": doc.get("custom_site_name") or "",
		"billing_gstin": doc.get("custom_billing_gstin") or "",
		"shipping_gstin": doc.get("custom_shipping_gstin") or "",
		"billing_address": doc.get("custom_billing_address_text") or "",
		"shipping_address": doc.get("custom_shipping_address_text") or "",
		"is_freebie_po": cint(doc.get("custom_is_freebie_po")),
		"items": items,
		"freebies": freebies,
	}


def validate_po_expiry_terminal_lock(doc, method=None):
	"""PO Expiry Date stays editable after submit (allow_on_submit) but locks the
	moment the order reaches a terminal status; a changed value must still be
	on/after the PO Date. Runs on before_update_after_submit (post-submit edits
	skip the normal validate event)."""
	before = doc.get_doc_before_save()
	if not before:
		return
	old = str(before.get("custom_po_expiry_date") or "")
	new = str(doc.get("custom_po_expiry_date") or "")
	if old == new:
		return
	status = doc.get("custom_workflow_status")
	if status in ("Completed", "Forced Completed", "Cancelled"):
		frappe.throw(
			_("PO Expiry Date can no longer be changed — the order is {0}.").format(status),
			title=_("PO Expiry Locked"),
		)
	if new and doc.get("custom_po_date") and getdate(new) < getdate(doc.custom_po_date):
		frappe.throw(_("Expiry Date must be on or after PO Date."))


# ---------------------------------------------------------------------------
# Validation (validate doc_event) — gated to E-com + offline Modern Trade
# ---------------------------------------------------------------------------
def ecom_fields_apply(doc) -> bool:
	"""True when the e-com extra fields/validations apply to this Sales Order."""
	channel = (doc.get("custom_channel") or "").strip()
	if channel == CHANNEL_ECOM:
		return True
	cust_type = doc.get("order_type") or doc.get("custom_offline_buyer_customer_type")
	return channel == "Offline" and is_modern_trade(cust_type)


def validate_ecom_sales_order(doc, method=None):
	"""E-com/MT field validations. No-op for plain offline orders."""
	if doc.docstatus == 2 or not ecom_fields_apply(doc):
		return

	# PO Number unique per customer.
	po_no = (doc.get("custom_po_number") or "").strip()
	if po_no and doc.customer:
		clash = frappe.db.exists(
			"Sales Order",
			{
				"custom_po_number": po_no,
				"customer": doc.customer,
				"name": ["!=", doc.name or ""],
				"docstatus": ["<", 2],
			},
		)
		if clash:
			frappe.throw(
				_("PO Number {0} already exists for this customer.").format(frappe.bold(po_no)),
				title=_("Duplicate PO Number"),
			)

	# PO Date cannot be in the future.
	if doc.get("custom_po_date") and getdate(doc.custom_po_date) > getdate(nowdate()):
		frappe.throw(_("PO Date cannot be in the future."))

	# PO Expiry >= PO Date.
	if doc.get("custom_po_date") and doc.get("custom_po_expiry_date"):
		if getdate(doc.custom_po_expiry_date) < getdate(doc.custom_po_date):
			frappe.throw(_("Expiry Date must be on or after PO Date."))

	# GSTIN format (billing / shipping).
	for label, val in (("Billing", doc.get("custom_billing_gstin")), ("Shipping", doc.get("custom_shipping_gstin"))):
		val = (val or "").strip().upper()
		if val and not GSTIN_RE.match(val):
			frappe.throw(_("Invalid {0} GSTIN format.").format(label))

	# Per-line: Margin 0–90 (both channels). MRP > 0 only for E-com orders, where
	# margin-based pricing needs it — offline MT orders keep their existing rules.
	is_ecom = (doc.get("custom_channel") or "").strip() == CHANNEL_ECOM
	freebie_po = cint(doc.get("custom_is_freebie_po"))
	for row in doc.get("items") or []:
		margin = flt(row.get("custom_margin_percent"))
		if margin < 0 or margin > 90:
			frappe.throw(_("Margin must be between 0 and 90 (row {0}).").format(row.idx))
		if is_ecom and not freebie_po and flt(row.get("custom_customer_mrp")) <= 0:
			frappe.throw(_("MRP must be greater than 0 (row {0}).").format(row.idx))


# ---------------------------------------------------------------------------
def _parse_json(value):
	if value is None or isinstance(value, (dict, list)):
		return value
	if isinstance(value, str) and value.strip():
		import json
		return json.loads(value)
	return None
