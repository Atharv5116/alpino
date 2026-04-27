"""Python API for the Offline Buyer Items page."""

import json

import frappe
from frappe.utils import flt


@frappe.whitelist()
def get_buyer_items():
	"""Return every active sales item merged with current data from the
	'Offline Buyer Items' Single DocType.

	Each row: item_code, item_name, item_group, mrp, margin_percent, selling_rate, selected
	"""
	# All active, saleable items
	items = frappe.get_all(
		"Item",
		filters={"disabled": 0, "is_sales_item": 1},
		fields=["name", "item_name", "item_group", "standard_rate"],
		order_by="item_group, item_name",
	)

	# Load saved data from Single DocType (keyed by item_code)
	saved: dict = {}
	try:
		doc = frappe.get_single("Offline Buyer Items")
		for row in doc.get("items") or []:
			if row.item_code:
				saved[row.item_code] = row
	except Exception:
		pass

	result = []
	for item in items:
		row = saved.get(item.name)
		mrp = flt(row.mrp if row else item.standard_rate)
		margin_pct = flt(row.margin_percent if row else 0)
		selling_rate = flt(mrp * (1 - margin_pct / 100), 2) if mrp else 0

		result.append(
			{
				"item_code": item.name,
				"item_name": item.item_name,
				"item_group": item.item_group or "",
				"mrp": mrp,
				"margin_percent": margin_pct,
				"selling_rate": selling_rate,
				"selected": bool(row),
			}
		)

	return result


@frappe.whitelist()
def save_buyer_items(items):
	"""Save the selected items to the 'Offline Buyer Items' Single DocType.

	Only selected rows are persisted; everything else is cleared.
	"""
	if isinstance(items, str):
		items = json.loads(items)

	doc = frappe.get_single("Offline Buyer Items")
	doc.set("items", [])

	for item in items:
		if not item.get("selected"):
			continue
		mrp = flt(item.get("mrp", 0))
		margin_pct = flt(item.get("margin_percent", 0))
		selling_rate = flt(mrp * (1 - margin_pct / 100), 2) if mrp else 0

		doc.append(
			"items",
			{
				"item_code": item["item_code"],
				"item_name": item.get("item_name", ""),
				"item_group": item.get("item_group", ""),
				"mrp": mrp,
				"margin_percent": margin_pct,
				"selling_rate": selling_rate,
			},
		)

	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"saved": len(doc.items)}
