# Copyright (c) 2026, Alpinos and contributors
# License: MIT

import frappe
from frappe import _
from frappe.utils import flt, getdate
from frappe.query_builder.functions import Sum


def execute(filters=None):
	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns():
	"""Define report columns based on requirements"""
	return [
		{
			"label": _("Date"),
			"fieldname": "date",
			"fieldtype": "Date",
			"width": 100
		},
		{
			"label": _("Company"),
			"fieldname": "company",
			"fieldtype": "Link",
			"options": "Company",
			"width": 120
		},
		{
			"label": _("Warehouse"),
			"fieldname": "warehouse",
			"fieldtype": "Link",
			"options": "Warehouse",
			"width": 150
		},
		{
			"label": _("SKU"),
			"fieldname": "item_code",
			"fieldtype": "Link",
			"options": "Item",
			"width": 120
		},
		{
			"label": _("SKU No."),
			"fieldname": "item_name",
			"fieldtype": "Data",
			"width": 150
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
			"width": 100
		},
		{
			"label": _("Stock Value (Out Value)"),
			"fieldname": "stock_value",
			"fieldtype": "Currency",
			"width": 150
		}
	]


def get_data(filters):
	"""Fetch stock balance data based on filters"""
	if not filters:
		filters = {}
	
	date = filters.get("date") or getdate()
	company = filters.get("company")
	warehouse = filters.get("warehouse")
	item_code = filters.get("item_code")
	
	# Build conditions
	conditions = ["sle.docstatus < 2", "sle.is_cancelled = 0"]
	values = {"date": date}
	
	if company:
		conditions.append("sle.company = %(company)s")
		values["company"] = company
	
	if warehouse:
		conditions.append("sle.warehouse = %(warehouse)s")
		values["warehouse"] = warehouse
	
	if item_code:
		conditions.append("sle.item_code = %(item_code)s")
		values["item_code"] = item_code
	
	where_clause = " AND ".join(conditions)
	
	# Get stock ledger entries up to the specified date
	query = f"""
		SELECT
			%(date)s as date,
			sle.company,
			sle.warehouse,
			sle.item_code,
			item.item_name,
			SUM(CASE 
				WHEN sle.posting_date < %(date)s THEN sle.actual_qty 
				ELSE 0 
			END) as opening_qty,
			SUM(CASE 
				WHEN sle.posting_date <= %(date)s THEN sle.actual_qty 
				ELSE 0 
			END) as closing_qty,
			SUM(CASE 
				WHEN sle.posting_date <= %(date)s AND sle.actual_qty < 0 
				THEN ABS(sle.stock_value_difference) 
				ELSE 0 
			END) as stock_value,
			item.standard_rate as mrp
		FROM `tabStock Ledger Entry` sle
		INNER JOIN `tabItem` item ON sle.item_code = item.name
		WHERE {where_clause}
		GROUP BY sle.company, sle.warehouse, sle.item_code, item.item_name, item.standard_rate
		HAVING closing_qty != 0
		ORDER BY sle.company, sle.warehouse, sle.item_code
	"""
	
	stock_data = frappe.db.sql(query, values, as_dict=1)
	
	# Get reserved quantities
	reserved_qty_map = get_reserved_qty(date, company, warehouse, item_code)
	
	# Process data
	result = []
	for row in stock_data:
		key = (row.item_code, row.warehouse)
		reserved_qty = reserved_qty_map.get(key, 0.0)
		closing_qty = flt(row.closing_qty)
		available_qty = closing_qty - reserved_qty
		
		result.append({
			"date": row.date,
			"company": row.company,
			"warehouse": row.warehouse,
			"item_code": row.item_code,
			"item_name": row.item_name,
			"opening_qty": flt(row.opening_qty, 0),  # No decimal places
			"reserved_qty": flt(reserved_qty, 0),
			"available_qty": flt(available_qty, 0),
			"total_stock": flt(closing_qty, 0),
			"mrp": flt(row.mrp, 2),
			"stock_value": flt(row.stock_value, 2)
		})
	
	return result


def get_reserved_qty(date, company=None, warehouse=None, item_code=None):
	"""Get reserved stock quantities from Stock Reservation Entry"""
	conditions = ["sre.docstatus = 1", "sre.status != 'Cancelled'"]
	values = {"date": date}
	
	if company:
		conditions.append("sre.company = %(company)s")
		values["company"] = company
	
	if warehouse:
		conditions.append("sre.warehouse = %(warehouse)s")
		values["warehouse"] = warehouse
	
	if item_code:
		conditions.append("sre.item_code = %(item_code)s")
		values["item_code"] = item_code
	
	where_clause = " AND ".join(conditions)
	
	query = f"""
		SELECT
			sre.item_code,
			sre.warehouse,
			SUM(sre.reserved_qty - sre.delivered_qty) as reserved_qty
		FROM `tabStock Reservation Entry` sre
		WHERE {where_clause}
		AND sre.reservation_based_on = 'Stock Reservation Entry'
		GROUP BY sre.item_code, sre.warehouse
	"""
	
	reserved_data = frappe.db.sql(query, values, as_dict=1)
	
	reserved_map = {}
	for row in reserved_data:
		key = (row.item_code, row.warehouse)
		reserved_map[key] = flt(row.reserved_qty)
	
	return reserved_map
