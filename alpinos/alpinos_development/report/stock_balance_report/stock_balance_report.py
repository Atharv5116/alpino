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


def get_data(filters):
	"""Fetch stock balance data based on filters"""
	if not filters:
		filters = {}
	
	from frappe.utils import add_days
	
	date = filters.get("date") or getdate()
	from_date = filters.get("from_date") or add_days(date, -30)  # Default to 1 month back
	company = filters.get("company")
	warehouse = filters.get("warehouse")
	item_code = filters.get("item_code")
	
	# Build item-warehouse map
	iwb_map = get_item_warehouse_balance(from_date, date, company, warehouse, item_code)
	
	# Get reserved quantities
	reserved_qty_map = get_reserved_qty(date, company, warehouse, item_code)
	
	# Process data
	result = []
	for key, data in iwb_map.items():
		company_name, item, wh = key
		reserved_qty = reserved_qty_map.get((item, wh), 0.0)
		closing_qty = flt(data.get("bal_qty", 0))
		available_qty = closing_qty - reserved_qty
		
		# Skip if no stock
		if closing_qty == 0:
			continue
		
		result.append({
			"date": date,
			"company": company_name,
			"warehouse": wh,
			"item_code": item,
			"item_name": data.get("item_name"),
			"opening_qty": flt(data.get("opening_qty", 0), 0),  # No decimal places
			"reserved_qty": flt(reserved_qty, 0),
			"available_qty": flt(available_qty, 0),
			"total_stock": flt(closing_qty, 0),
			"mrp": flt(data.get("mrp", 0), 2),
			"stock_value": flt(data.get("out_val", 0), 2)
		})
	
	return result


def get_item_warehouse_balance(from_date, to_date, company=None, warehouse=None, item_code=None):
	"""Calculate item-warehouse balance similar to ERPNext Stock Balance"""
	conditions = ["sle.docstatus < 2", "sle.is_cancelled = 0"]
	values = {"from_date": from_date, "to_date": to_date}
	
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
	
	# Get all stock ledger entries
	sle_data = frappe.db.sql(f"""
		SELECT
			sle.company,
			sle.item_code,
			sle.warehouse,
			sle.posting_date,
			sle.actual_qty,
			sle.stock_value_difference,
			item.item_name,
			item.standard_rate as mrp
		FROM `tabStock Ledger Entry` sle
		INNER JOIN `tabItem` item ON sle.item_code = item.name
		WHERE {where_clause}
		AND sle.posting_date <= %(to_date)s
		ORDER BY sle.posting_date, sle.posting_time, sle.creation
	""", values, as_dict=1)
	
	iwb_map = {}
	
	for row in sle_data:
		key = (row.company, row.item_code, row.warehouse)
		
		if key not in iwb_map:
			iwb_map[key] = {
				"opening_qty": 0.0,
				"in_qty": 0.0,
				"out_qty": 0.0,
				"bal_qty": 0.0,
				"out_val": 0.0,
				"item_name": row.item_name,
				"mrp": row.mrp
			}
		
		qty_dict = iwb_map[key]
		
		# Calculate opening (before from_date)
		if row.posting_date < from_date:
			qty_dict["opening_qty"] += flt(row.actual_qty)
			qty_dict["bal_qty"] += flt(row.actual_qty)
		# Calculate movements (from from_date to to_date)
		elif row.posting_date >= from_date and row.posting_date <= to_date:
			if flt(row.actual_qty) > 0:
				qty_dict["in_qty"] += flt(row.actual_qty)
			else:
				qty_dict["out_qty"] += abs(flt(row.actual_qty))
				# Stock value for outward transactions
				qty_dict["out_val"] += abs(flt(row.stock_value_difference))
			
			qty_dict["bal_qty"] += flt(row.actual_qty)
	
	return iwb_map


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
