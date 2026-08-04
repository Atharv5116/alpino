# Copyright (c) 2026, Alpinos and contributors
# For license information, please see license.txt
"""Pending Invoice Downloads.

Sales Orders whose invoice has been assigned an Invoice No (via invoice sync) but
has NOT yet been downloaded (custom_invoice_downloaded = 0). From the report the
accounts team ticks rows and hits "Download Selected" to pull the invoice PDFs;
downloading marks them, so they drop off this list.
"""

import frappe
from frappe import _


def execute(filters=None):
	filters = filters or {}

	columns = [
		{"label": _("Sales Order"), "fieldname": "sales_order", "fieldtype": "Link", "options": "Sales Order", "width": 160},
		{"label": _("Pick List"), "fieldname": "pick_list", "fieldtype": "Link", "options": "Pick List", "width": 160},
		{"label": _("Invoice ID"), "fieldname": "invoice_id", "fieldtype": "Data", "width": 150},
		{"label": _("LR Number"), "fieldname": "lr_number", "fieldtype": "Data", "width": 140},
		{"label": _("Customer PO No"), "fieldname": "customer_po_no", "fieldtype": "Data", "width": 170},
		{"label": _("Customer"), "fieldname": "customer_name", "fieldtype": "Data", "width": 220},
		# Whether the PDF is actually fetched yet — a download can only pull rows that have one.
		{"label": _("PDF Ready"), "fieldname": "pdf_ready", "fieldtype": "Data", "width": 90},
	]

	conditions = [
		"IFNULL(so.custom_invoice_no, '') <> ''",
		"IFNULL(so.custom_invoice_downloaded, 0) = 0",
		"so.docstatus < 2",
	]
	params = {}
	if filters.get("from_date"):
		conditions.append("so.transaction_date >= %(from_date)s")
		params["from_date"] = filters["from_date"]
	if filters.get("to_date"):
		conditions.append("so.transaction_date <= %(to_date)s")
		params["to_date"] = filters["to_date"]
	if filters.get("customer"):
		conditions.append("so.customer = %(customer)s")
		params["customer"] = filters["customer"]

	rows = frappe.db.sql(
		"""
		SELECT so.name AS sales_order,
			so.custom_invoice_no AS invoice_id,
			COALESCE(NULLIF(so.po_no, ''), NULLIF(so.custom_po_number, ''), '') AS customer_po_no,
			so.customer_name AS customer_name,
			CASE WHEN IFNULL(so.custom_invoice_pdf, '') <> '' THEN 'Yes' ELSE 'No' END AS pdf_ready
		FROM `tabSales Order` so
		WHERE {conditions}
		ORDER BY so.transaction_date DESC, so.name DESC
		""".format(conditions=" AND ".join(conditions)),
		params,
		as_dict=True,
	)

	names = [r.sales_order for r in rows]
	pl_map, lr_map = {}, {}
	if names:
		for p in frappe.get_all(
			"Pick List",
			filters={"custom_sales_order_id": ["in", names], "docstatus": ["<", 2]},
			fields=["name", "custom_sales_order_id"],
			order_by="modified asc",
		):
			pl_map[p.custom_sales_order_id] = p.name
		for d in frappe.get_all(
			"Delivery Note",
			filters={"custom_sales_order_id": ["in", names], "docstatus": ["<", 2], "is_return": 0},
			fields=["custom_sales_order_id", "custom_lr_gr_no"],
			order_by="modified asc",
		):
			if d.get("custom_lr_gr_no"):
				lr_map[d.custom_sales_order_id] = d.custom_lr_gr_no

	for r in rows:
		r["pick_list"] = pl_map.get(r.sales_order, "")
		r["lr_number"] = lr_map.get(r.sales_order, "")

	return columns, rows
