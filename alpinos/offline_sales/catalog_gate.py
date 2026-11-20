"""Buyer readiness for sales transactions, and the Buyer Catalog (document Section 4, 4.4 and 6).

The 6.1 grid, without the Opportunity columns (the Opportunity module is not part of this build):

    Buyer Master Status                  Quotation      Sales Order
    Pending Approval                     BLOCKED        BLOCKED
    Approved + Buyer Catalog Pending     BLOCKED        BLOCKED
    Approved + Buyer Catalog Completed   allowed        allowed
    On Hold / Inactive / Cancelled       BLOCKED        BLOCKED

A Sales Order is checked when it is created and when it is submitted. A Quotation: since the
Opportunity is skipped (20 Nov 2026) a Draft may be saved for a buyer still Pending Approval or
with the Buyer Catalog Pending (On Hold / Inactive / Cancelled are refused); Start Negotiation
and Finalize Quotation need the approval and the Buyer Catalog. Old buyers carry Approved / Completed (the migration), and a blank status counts the
same, so nothing selling today stops. E-com buyers and E-com orders are never checked.

The Buyer Catalog is the Buyer Items record of the buyer's Customer, plus the SKU margins on
Buyer Master. A Sales Officer cannot set it up or change it (3.1); every change to it is in the
buyer's Activity Trail with Buyer, SKU, old and new Flat Discount % and Selling Price, user,
role and time (4.4), including the changes a submitted Sales Order writes into it.
"""

import frappe
from frappe import _
from frappe.utils import flt

from alpinos.offline_sales import (
	APPROVED,
	CANCELLED,
	CATALOG_COMPLETED,
	CATALOG_PENDING,
	INACTIVE,
	ON_HOLD,
	PENDING,
	is_offline,
	is_sales_officer_only,
)
from alpinos.offline_sales import audit
from alpinos.offline_sales.buyer_rules import catalog_of, mark_catalog_completed, status_of

SO_BUYER_FIELD = "custom_offline_buyer_master"
QUOTATION_BUYER_FIELD = "custom_buyer_master"


def readiness(buyer, purpose, action=None, draft=False):
	"""None when `buyer` may be used for a new `purpose` transaction, else the reason why not.

	`action` replaces "created" in the approval / catalogue message ("finalized", ...). `draft`:
	only the statuses that stop all sales (On Hold, Inactive, Cancelled) count; a Draft Quotation
	may wait for the approval and the Buyer Catalog (the Opportunity is skipped, 20 Nov 2026)."""
	if not buyer:
		return None
	row = frappe.db.get_value(
		"Buyer Master", buyer, ["channel", "buyer_status", "buyer_catalog_status", "customer_business_name"], as_dict=True
	)
	if not row or not is_offline(row.channel):
		return None
	status = status_of(row.buyer_status)
	if status == ON_HOLD:
		return _("This Buyer is currently On Hold and cannot be used for new sales transactions until approved by SM or SA.")
	if status == INACTIVE:
		return _("This Buyer is currently Inactive and cannot be used for new sales transactions until a Sales Manager or Sales Admin reactivates it.")
	if status == CANCELLED:
		return _("This Buyer is Cancelled and cannot be used for new sales transactions. Create a new Buyer Master if business with this customer starts again.")
	if draft:
		return None
	verb = action or _("created")
	if status == PENDING:
		return _("{0} cannot be {1} because linked Buyer Approval & Buyer Catalog creation is pending.").format(purpose, verb)
	if catalog_of(row.buyer_catalog_status) != CATALOG_COMPLETED:
		return _("{0} cannot be {1} because mandatory Buyer Catalog setup is pending.").format(purpose, verb)
	return None


def assert_buyer_ready(buyer, purpose):
	reason = readiness(buyer, purpose)
	if reason:
		name = frappe.db.get_value("Buyer Master", buyer, "customer_business_name") or buyer
		frappe.throw(f"{frappe.bold(name)}: {reason}", title=_("Buyer Not Ready"))


@frappe.whitelist()
def get_readiness(buyer, purpose="Sales Order"):
	"""For screens: whether the buyer can take a new Sales Order / Quotation, and why not."""
	# company-scope: n/a (Buyer Master has no company; the caller's read permission is checked)
	frappe.has_permission("Buyer Master", "read", buyer, throw=True)
	row = frappe.db.get_value("Buyer Master", buyer, ["buyer_status", "buyer_catalog_status"], as_dict=True) or {}
	return {
		"buyer_status": status_of(row.get("buyer_status")),
		"buyer_catalog_status": catalog_of(row.get("buyer_catalog_status")),
		"blocked_reason": readiness(buyer, _(purpose)),
	}


# ----------------------------------------------------------------------------- Sales Order


def sales_order_gate(doc, method=None):
	"""Sales Order validate: a new order, and the submission of any order, need a ready buyer."""
	if not (doc.is_new() or doc.get("_action") == "submit"):
		return
	if (doc.get("custom_channel") or "") == "E-com" or doc.flags.ignore_buyer_readiness:
		return
	assert_buyer_ready(doc.get(SO_BUYER_FIELD), _("Sales Order"))


# ----------------------------------------------------------------------------- Quotation


def quotation_buyer(doc):
	if doc.get("quotation_to") == "Buyer Master" and doc.get("party_name"):
		return doc.party_name
	customer = doc.get("custom_resolved_customer") or (doc.party_name if doc.get("quotation_to") == "Customer" else None)
	if customer:
		return frappe.db.get_value("Buyer Master", {"customer": customer}, "name", order_by="creation asc")
	return None


def quotation_validate(doc, method=None):
	meta = frappe.get_meta("Quotation")
	buyer = quotation_buyer(doc)
	if meta.has_field(QUOTATION_BUYER_FIELD):
		doc.set(QUOTATION_BUYER_FIELD, buyer)
	if meta.has_field("custom_secondary_poc"):
		doc.set("custom_secondary_poc", frappe.db.get_value("Buyer Master", buyer, "secondary_poc") if buyer else None)
	if doc.is_new() and not doc.flags.ignore_buyer_readiness:
		# a Draft may wait for the buyer's approval and Buyer Catalog; Start Negotiation and
		# Finalize Quotation check those (alpinos.offline_sales.quotation)
		reason = readiness(quotation_buyer(doc), _("Quotation"), draft=True)
		if reason:
			name = frappe.db.get_value("Buyer Master", quotation_buyer(doc), "customer_business_name") or quotation_buyer(doc)
			frappe.throw(f"{frappe.bold(name)}: {reason}", title=_("Buyer Not Ready"))


# ----------------------------------------------------------------------------- Buyer Catalog


def _catalog_buyer(customer):
	return frappe.db.get_value("Buyer Master", {"customer": customer}, "name", order_by="creation asc") if customer else None


def buyer_items_validate(doc, method=None):
	"""A Sales Officer neither creates nor changes Buyer Catalog pricing (3.1, 4.4)."""
	if frappe.flags.alpinos_catalog_sync:
		return
	if is_sales_officer_only():
		frappe.throw(
			_("A Sales Officer cannot create or change Buyer Catalog pricing. The Sales Manager or Sales Admin maintains it."),
			frappe.PermissionError,
			title=_("Not Permitted"),
		)


def _key(row):
	return (row.get("item_code"), round(flt(row.get("mrp")), 2))


def buyer_items_on_update(doc, method=None):
	buyer = _catalog_buyer(doc.get("buyer"))
	if not buyer:
		return
	before = doc.get_doc_before_save()
	old = {_key(r): r for r in (before.get("items") if before else None) or [] if r.get("item_code")}
	new = {_key(r): r for r in doc.get("items") or [] if r.get("item_code")}
	action = "Buyer Catalog Synced from Sales Order" if frappe.flags.alpinos_catalog_sync else "Buyer Catalog Changed"
	for key in sorted(set(old) | set(new), key=lambda k: (k[0] or "", k[1])):
		log_catalog_row(buyer, key[0], key[1], old.get(key), new.get(key), action)

	if not frappe.flags.alpinos_catalog_sync and not is_sales_officer_only():
		bm = frappe.get_doc("Buyer Master", buyer)
		priced = any(flt(r.get("selling_rate")) > 0 or flt(r.get("margin_percent")) > 0 for r in new.values())
		if (
			priced
			and is_offline(bm.get("channel"))
			and status_of(bm) == APPROVED
			and catalog_of(bm) == CATALOG_PENDING
		):
			mark_catalog_completed(bm)


def log_catalog_row(buyer, item_code, mrp, old_row, new_row, action):
	"""Trail lines for one catalogue row (Buyer + SKU [+ MRP])."""
	where = _(" at MRP {0}").format(frappe.format_value(mrp, {"fieldtype": "Currency"})) if mrp else ""
	for field, label in (("margin_percent", _("Flat Discount %")), ("selling_rate", _("Selling Price"))):
		o = flt(old_row.get(field)) if old_row else None
		n = flt(new_row.get(field)) if new_row else None
		if o is not None and n is not None and abs(o - n) < 0.005:
			continue
		if o is None and not n:
			continue
		audit.log(
			"Buyer Master", buyer, action, f"{label}{where}",
			"" if o is None else o, "" if n is None else n, item_code=item_code,
		)


def log_margin_sync(customer, item_code, new_margin, mrp=None):
	"""Trail lines for the catalogue rows a submitted Sales Order is about to re-margin.

	sales_order_offline_buyer.update_offline_buyer_margin_if_changed writes those rows with a
	direct UPDATE, which no document event sees, so it calls this first.
	"""
	buyer = _catalog_buyer(customer)
	if not buyer:
		return
	conditions = {"parenttype": "Buyer Items", "item_code": item_code}
	parents = frappe.get_all("Buyer Items", {"buyer": customer, "docstatus": ("<", 2)}, pluck="name")
	if not parents:
		return
	conditions["parent"] = ("in", parents)
	for row in frappe.get_all("Buyer Item", filters=conditions, fields=["item_code", "mrp", "margin_percent", "selling_rate"]):
		if mrp and round(flt(row.mrp), 2) != round(flt(mrp), 2):
			continue
		if abs(flt(row.margin_percent) - flt(new_margin)) < 0.005:
			continue
		log_catalog_row(
			buyer, item_code, round(flt(row.mrp), 2), row, {"margin_percent": new_margin, "selling_rate": row.selling_rate},
			"Buyer Catalog Synced from Sales Order",
		)
