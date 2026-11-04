"""Sales-side Multiple MRP: the Item MRPs tab, filled once for the Items that are sold.

Items with Batch / MRP stock get those MRPs; other sold Items get their Item valuation rate,
the MRP the Sales Order used until now, marked "Opening" for review."""

import frappe


def execute():
	from alpinos import item_mrp

	frappe.reload_doc("alpinos_development", "doctype", "item_mrp")
	item_mrp.setup()
	stats = item_mrp.seed()
	print(f"[item_mrp] opening MRPs: {stats}")
