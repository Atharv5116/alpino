"""Item SKU colors (Item.custom_color) for row tinting in stock reports and
the Item list. One bulk map keeps report rendering to a single extra call."""

import frappe


@frappe.whitelist()
def get_item_color_map():
	"""{item_code: '#rrggbb'} for every enabled Item with a color set."""
	rows = frappe.get_list(
		"Item",
		filters=[["custom_color", "is", "set"], ["disabled", "=", 0]],
		fields=["name", "custom_color"],
	)
	return {r.name: r.custom_color for r in rows}
