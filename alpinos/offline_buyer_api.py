"""Python API for the Offline Buyer Catalog page."""

import json

import frappe
from frappe.utils import flt, now_datetime


@frappe.whitelist()
def get_all_records():
	"""Return all Offline Buyer Items records for the list view."""
	records = frappe.db.sql(
		"""
		SELECT
			obi.name,
			obi.title,
			obi.buyer,
			obi.modified,
			COUNT(obil.name) AS item_count
		FROM `tabOffline Buyer Items` obi
		LEFT JOIN `tabOffline Buyer Item` obil ON obil.parent = obi.name
		GROUP BY obi.name
		ORDER BY obi.modified DESC
		""",
		as_dict=True,
	)
	return records


@frappe.whitelist()
def get_buyer_items(record_name):
	"""Return every active sales item merged with saved data from a specific record.

	Each row: item_code, item_name, item_group, mrp, margin_percent, selling_rate, selected
	"""
	# All active, saleable items from Item master
	items = frappe.get_all(
		"Item",
		filters={"disabled": 0, "is_sales_item": 1},
		fields=["name", "item_name", "item_group", "standard_rate"],
		order_by="item_group, item_name",
	)

	# Load saved rows from the specific record (keyed by item_code)
	saved: dict = {}
	if frappe.db.exists("Offline Buyer Items", record_name):
		doc = frappe.get_doc("Offline Buyer Items", record_name)
		for row in doc.get("items") or []:
			if row.item_code:
				saved[row.item_code] = row

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
def save_buyer_items(record_name, items):
	"""Save selected items back to the specified Offline Buyer Items record."""
	if isinstance(items, str):
		items = json.loads(items)

	if not frappe.db.exists("Offline Buyer Items", record_name):
		frappe.throw(f"Record {record_name} not found")

	doc = frappe.get_doc("Offline Buyer Items", record_name)
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


@frappe.whitelist()
def create_record(title, buyer=None, description=None):
	"""Create a new Offline Buyer Items record and return its name."""
	doc = frappe.new_doc("Offline Buyer Items")
	doc.title = title
	if buyer:
		doc.buyer = buyer
	if description:
		doc.description = description
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return doc.name
