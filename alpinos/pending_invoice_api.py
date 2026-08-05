# Copyright (c) 2026, Alpinos and contributors
"""Data feed for the Invoice Download Queue page (tick-and-download UI).

Reuses the Pending Invoice Downloads report's query so the page and the report
stay in lockstep.
"""

import frappe

from alpinos.alpinos_development.report.pending_invoice_downloads.pending_invoice_downloads import (
	execute as _pending_execute,
)


@frappe.whitelist()
def get_pending_invoice_downloads(sales_order=None, order_date=None, dispatch_date=None, customer=None):
	if not frappe.has_permission("Sales Order", "read"):
		frappe.throw(frappe._("Not permitted"), frappe.PermissionError)
	filters = {}
	if sales_order:
		filters["sales_order"] = sales_order
	if order_date:
		filters["order_date"] = order_date
	if dispatch_date:
		filters["dispatch_date"] = dispatch_date
	if customer:
		filters["customer"] = customer
	_columns, data = _pending_execute(filters)
	return {"data": data}
