# Copyright (c) 2026, Alpinos and contributors
# License: MIT

import frappe
from frappe import _
from frappe.utils import flt, getdate


def execute(filters=None):
	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns():
	"""Define report columns based on requirements"""
	return [
		{
			"label": _("Date"),
			"fieldname": "posting_date",
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
			"label": _("From Warehouse"),
			"fieldname": "from_warehouse",
			"fieldtype": "Link",
			"options": "Warehouse",
			"width": 150
		},
		{
			"label": _("To Warehouse"),
			"fieldname": "to_warehouse",
			"fieldtype": "Link",
			"options": "Warehouse",
			"width": 150
		},
		{
			"label": _("Transferred Qty"),
			"fieldname": "transferred_qty",
			"fieldtype": "Float",
			"width": 120
		},
		{
			"label": _("MRP"),
			"fieldname": "mrp",
			"fieldtype": "Currency",
			"width": 100
		},
		{
			"label": _("Transfer Value"),
			"fieldname": "transfer_value",
			"fieldtype": "Currency",
			"width": 120
		}
	]


def get_data(filters):
	"""Fetch stock transfer data based on filters"""
	if not filters:
		filters = {}
	
	from_date = filters.get("from_date")
	to_date = filters.get("to_date") or getdate()
	company = filters.get("company")
	from_warehouse = filters.get("from_warehouse")
	to_warehouse = filters.get("to_warehouse")
	item_code = filters.get("item_code")
	
	# Build conditions
	conditions = [
		"se.docstatus = 1",
		"se.purpose = 'Material Transfer'",
		"se.posting_date <= %(to_date)s"
	]
	values = {"to_date": to_date}
	
	if from_date:
		conditions.append("se.posting_date >= %(from_date)s")
		values["from_date"] = from_date
	
	if company:
		conditions.append("se.company = %(company)s")
		values["company"] = company
	
	if from_warehouse:
		conditions.append("sed.s_warehouse = %(from_warehouse)s")
		values["from_warehouse"] = from_warehouse
	
	if to_warehouse:
		conditions.append("sed.t_warehouse = %(to_warehouse)s")
		values["to_warehouse"] = to_warehouse
	
	if item_code:
		conditions.append("sed.item_code = %(item_code)s")
		values["item_code"] = item_code
	
	where_clause = " AND ".join(conditions)
	
	# Query stock entries for material transfers
	query = f"""
		SELECT
			se.posting_date,
			se.company,
			sed.item_code,
			item.item_name,
			sed.s_warehouse as from_warehouse,
			sed.t_warehouse as to_warehouse,
			sed.qty as transferred_qty,
			item.standard_rate as mrp,
			sed.amount as transfer_value
		FROM `tabStock Entry` se
		INNER JOIN `tabStock Entry Detail` sed ON se.name = sed.parent
		INNER JOIN `tabItem` item ON sed.item_code = item.name
		WHERE {where_clause}
		AND sed.s_warehouse IS NOT NULL
		AND sed.t_warehouse IS NOT NULL
		ORDER BY se.posting_date DESC, se.company, sed.item_code
	"""
	
	transfer_data = frappe.db.sql(query, values, as_dict=1)
	
	# Process data - ensure no decimal places in Qty as per requirement
	result = []
	for row in transfer_data:
		result.append({
			"posting_date": row.posting_date,
			"company": row.company,
			"item_code": row.item_code,
			"item_name": row.item_name,
			"from_warehouse": row.from_warehouse,
			"to_warehouse": row.to_warehouse,
			"transferred_qty": flt(row.transferred_qty, 0),  # No decimal places
			"mrp": flt(row.mrp, 2),
			"transfer_value": flt(row.transfer_value, 2)
		})
	
	return result
