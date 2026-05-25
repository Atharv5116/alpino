# Copyright (c) 2026, Alpinos and contributors
# License: MIT

import frappe
from frappe import _
from frappe.utils import flt, getdate

# Import core ERPNext Stock Balance Report
from erpnext.stock.report.stock_balance.stock_balance import StockBalanceReport


def execute(filters=None):
	"""Execute the stock balance report using core ERPNext logic with custom columns"""
	if not filters:
		filters = {}
	
	# Prepare filters for core report (frappe._dict for attribute access)
	core_filters = frappe._dict({
		"company": filters.get("company"),
		"from_date": filters.get("from_date") or getdate(),
		"to_date": filters.get("date") or getdate(),
		"warehouse": [filters.get("warehouse")] if filters.get("warehouse") else None,
		"item_code": [filters.get("item_code")] if filters.get("item_code") else None,
		"valuation_field_type": "Currency",
		"include_zero_stock_items": 0,
	})
	
	# Run core stock balance report
	core_report = StockBalanceReport(core_filters)
	core_columns, core_data = core_report.run()
	
	# Transform to our custom format
	columns = get_columns()
	data = transform_data(core_data, filters.get("date") or getdate())
	
	return columns, data


def get_columns():
	"""Define report columns based on requirements"""
	return [
		{
			"label": _("Date"),
			"fieldname": "date",
			"fieldtype": "Date",
			"width": 100,
			"skip_total_row": 1
		},
		{
			"label": _("Company"),
			"fieldname": "company",
			"fieldtype": "Link",
			"options": "Company",
			"width": 120,
			"skip_total_row": 1
		},
		{
			"label": _("Warehouse"),
			"fieldname": "warehouse",
			"fieldtype": "Link",
			"options": "Warehouse",
			"width": 150,
			"skip_total_row": 1
		},
		{
			"label": _("SKU"),
			"fieldname": "item_code",
			"fieldtype": "Link",
			"options": "Item",
			"width": 120,
			"skip_total_row": 1
		},
		{
			"label": _("SKU No."),
			"fieldname": "item_name",
			"fieldtype": "Data",
			"width": 150,
			"skip_total_row": 1
		},
		{
			"label": _("Opening Qty"),
			"fieldname": "opening_qty",
			"fieldtype": "Float",
			"width": 100
		},
		{
			"label": _("Reserved Qty"),
			"fieldname": "reserved_qty",
			"fieldtype": "Float",
			"width": 100
		},
		{
			"label": _("Available Qty (Closing)"),
			"fieldname": "available_qty",
			"fieldtype": "Float",
			"width": 150
		},
		{
			"label": _("Total Stock (Reserved + Available)"),
			"fieldname": "total_stock",
			"fieldtype": "Float",
			"width": 200
		},
		{
			"label": _("MRP"),
			"fieldname": "mrp",
			"fieldtype": "Currency",
			"width": 100,
			"skip_total_row": 1
		},
		{
			"label": _("Stock Value (Out Value)"),
			"fieldname": "stock_value",
			"fieldtype": "Currency",
			"width": 150
		}
	]


def transform_data(core_data, report_date):
	"""Transform core stock balance data to our custom format"""
	result = []
	
	for row in core_data:
		# Skip if no balance
		if not row.get("bal_qty"):
			continue
		
		bal_qty = flt(row.get("bal_qty", 0))
		reserved_stock = flt(row.get("reserved_stock", 0))
		available_qty = bal_qty - reserved_stock
		
		result.append({
			"date": report_date,
			"company": row.get("company"),
			"warehouse": row.get("warehouse"),
			"item_code": row.get("item_code"),
			"item_name": row.get("item_name"),
			"opening_qty": flt(row.get("opening_qty", 0), 0),  # No decimal places
			"reserved_qty": flt(reserved_stock, 0),
			"available_qty": flt(available_qty, 0),
			"total_stock": flt(bal_qty, 0),
			"mrp": flt(row.get("val_rate", 0), 2),
			"stock_value": flt(row.get("out_val", 0), 2)
		})
	
	return result
