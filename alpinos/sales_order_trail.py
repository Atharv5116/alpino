"""The Sales Order Activity / Change Trail.

Sections 16-18 and 21 of "Buyer Master & Sales Order - Required Changes" (03-10-2026).

    17. For every significant change capture: Date & Time, Changed By, User Role, Action
        (Created / Saved / Edited / Submitted / Cancelled / Duplicated), Field Changed,
        Previous Value, New Value, and the Item / SKU when the change is item-level.
    18. "Activity logging must not begin only after Sales Order submission. Changes made
        while the Sales Order is in Draft must also be tracked."

That last line is the whole point of this module. The app already had a Field Change Log,
but every caller wrote with after_submit=1 -- the draft stage, which is where the commercial
negotiation actually happens, left no trace at all.

Only the fields that carry meaning are tracked. A trail that logged every recalculated total
would bury the one line somebody needs to find, so the header set is the commercial and
scheduling fields a person chooses, and the line set is the four values section 7 lets a
Sales Officer change, plus the quantity.
"""

import frappe
from frappe.utils import flt

from alpinos.alpinos_development.doctype.field_change_log.field_change_log import (
	acting_role,
	log_field_change,
)

#: Header fields worth a trail entry, with the label a reader will recognise.
TRACKED_HEADER_FIELDS = {
	"customer": "Customer",
	"custom_site_name": "Site Name",
	"po_no": "Customer PO No.",
	"custom_dispatch_date": "Dispatch Date",
	"delivery_date": "Delivery Date",
	"custom_cash_discount": "Cash Discount %",
	"custom_workflow_status": "Status",
	"custom_billing_gstin": "Billing GSTIN",
	"custom_shipping_gstin": "Shipping GSTIN",
	"grand_total": "Grand Total",
}

#: Line fields worth a trail entry -- the four section 7 lets a Sales Officer change, and qty.
TRACKED_ITEM_FIELDS = {
	"qty": "Quantity",
	"rate": "Selling Price",
	"custom_flat_discount": "Flat Discount %",
	"custom_margin_percent": "Margin %",
	"custom_additional_discount": "Additional Discount %",
	"custom_box": "Box",
}

#: Values below this are treated as equal, so a float recalculation does not look like an edit.
_EPS = 0.001


def _changed(old, new):
	if isinstance(old, (int, float)) or isinstance(new, (int, float)):
		try:
			return abs(flt(old) - flt(new)) > _EPS
		except (TypeError, ValueError):
			pass
	return (old or "") != (new or "")


def _log(doc, label, old, new, action, item_code=None):
	log_field_change(
		"Sales Order", doc.name, label, old, new,
		after_submit=1 if doc.docstatus == 1 else 0,
		action=action, item_code=item_code, user_role=acting_role(),
	)


def record_creation(doc, method=None):
	"""Section 17's "Created" action, logged while the order is still a Draft."""
	_log(doc, frappe._("Sales Order"), "", doc.name, "Created")


def record_submission(doc, method=None):
	_log(doc, frappe._("Status"), frappe._("Draft"), frappe._("Submitted"), "Submitted")


def record_changes(doc, method=None):
	"""Diff this save against the stored version and log what a person would call a change.

	Runs on every save, Draft included -- section 18. A brand new document has nothing to
	diff against and is handled by record_creation instead.
	"""
	before = doc.get_doc_before_save()
	if not before:
		return

	action = "Edited" if doc.docstatus == 0 else "Edited after submission"

	for fieldname, label in TRACKED_HEADER_FIELDS.items():
		old, new = before.get(fieldname), doc.get(fieldname)
		if _changed(old, new):
			_log(doc, label, old, new, action)

	old_rows = {r.name: r for r in (before.get("items") or []) if r.name}
	new_rows = {r.name: r for r in (doc.get("items") or []) if r.name}

	for row_name, row in new_rows.items():
		old_row = old_rows.get(row_name)
		if not old_row:
			# Section 7 counts adding a line as a change in its own right.
			_log(doc, frappe._("Item Added"), "", f"{row.item_code} x {flt(row.qty)}",
			     action, item_code=row.item_code)
			continue
		for fieldname, label in TRACKED_ITEM_FIELDS.items():
			old, new = old_row.get(fieldname), row.get(fieldname)
			if _changed(old, new):
				_log(doc, label, old, new, action, item_code=row.item_code)

	for row_name, old_row in old_rows.items():
		if row_name not in new_rows:
			_log(doc, frappe._("Item Removed"), f"{old_row.item_code} x {flt(old_row.qty)}", "",
			     action, item_code=old_row.item_code)


@frappe.whitelist()
def get_activity_trail(sales_order, limit=200):
	"""The trail for one Sales Order, newest first. Backs the panel on the order page."""
	rows = frappe.get_all(
		"Field Change Log",
		filters={"reference_doctype": "Sales Order", "reference_name": sales_order},
		fields=["name", "action", "field_label", "previous_value", "new_value", "item_code",
		        "user_role", "reason", "changed_by", "changed_on", "after_submit"],
		order_by="changed_on desc, creation desc",
		limit_page_length=int(limit or 200),
	)
	names = {r.changed_by for r in rows if r.changed_by}
	full = {
		u.name: (u.full_name or u.name)
		for u in frappe.get_all("User", filters={"name": ["in", list(names)]} if names else {"name": ""},
		                        fields=["name", "full_name"])
	}
	for r in rows:
		r["changed_by_name"] = full.get(r.changed_by, r.changed_by)
	return rows


@frappe.whitelist()
def get_previous_sales_orders(sales_order, limit=20):
	"""Sections 19-20: the Buyer's other Sales Orders, for quick navigation only.

	Deliberately separate from the trail: one answers "what happened inside this order",
	the other "what other orders exist for this Buyer", and section 21 is explicit that
	they must not be mixed.
	"""
	row = frappe.db.get_value(
		"Sales Order", sales_order, ["customer", "custom_offline_buyer_master"], as_dict=True
	)
	if not row:
		return []
	filters = {"name": ["!=", sales_order], "docstatus": ["<", 2]}
	if row.custom_offline_buyer_master:
		filters["custom_offline_buyer_master"] = row.custom_offline_buyer_master
	else:
		filters["customer"] = row.customer
	orders = frappe.get_all(
		"Sales Order", filters=filters,
		fields=["name", "transaction_date", "grand_total", "custom_workflow_status",
		        "docstatus", "owner"],
		order_by="transaction_date desc, creation desc",
		limit_page_length=int(limit or 20),
	)
	owners = {o.owner for o in orders if o.owner}
	full = {
		u.name: (u.full_name or u.name)
		for u in frappe.get_all("User", filters={"name": ["in", list(owners)]} if owners else {"name": ""},
		                        fields=["name", "full_name"])
	}
	for o in orders:
		o["created_by_name"] = full.get(o.owner, o.owner)
		o["status"] = o.custom_workflow_status or ("Draft" if o.docstatus == 0 else "Submitted")
	return orders
