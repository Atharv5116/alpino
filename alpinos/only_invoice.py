"""Changes(HP) #108: Only Invoice Sales Orders (Offline and E-com).

    Sales Order (Only Invoice ticked) --submit--> Accounts Format Report

No Pick List, no Delivery Note, so no stock reservation, deduction or ledger entry. The
order's Multiple MRP rules still apply on the order itself (alpinos.sales_mrp), without
batches or stock. On submit the order's workflow status is "Only Invoice" instead of
Warehouse Approval Pending, and the warehouse is not notified. A Pick List or Delivery Note
against such an order is refused, whichever screen or import tries.
"""

import frappe
from frappe import _
from frappe.utils import cint

FIELD = "custom_only_invoice"
STATUS = "Only Invoice"


def is_only_invoice(sales_order):
	if not sales_order or not frappe.db.has_column("Sales Order", FIELD):
		return False
	return bool(cint(frappe.db.get_value("Sales Order", sales_order, FIELD)))


def _refuse(doctype, sales_order):
	frappe.throw(
		_("Sales Order {0} is Only Invoice: it is invoiced from the Accounts Format Report and has no {1}.").format(
			frappe.bold(sales_order), _(doctype)
		),
		title=_("Only Invoice"),
	)


def pick_list_validate(doc, method=None):
	if doc.is_new() or doc.docstatus == 0:
		so = doc.get("custom_sales_order_id")
		if is_only_invoice(so):
			_refuse("Pick List", so)


def delivery_note_validate(doc, method=None):
	if doc.docstatus == 2:
		return
	orders = {doc.get("custom_sales_order_id")} | {r.get("against_sales_order") for r in doc.get("items") or []}
	for so in filter(None, orders):
		if is_only_invoice(so):
			_refuse("Delivery Note", so)
