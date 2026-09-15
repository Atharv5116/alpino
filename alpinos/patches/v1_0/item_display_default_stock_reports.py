"""Keep the stock reports' Item colour tint, now as an Item Display Configuration.

Before Changes(HP) #39 six stock reports were tinted by Item colour from a hard-coded
list in public/js/item_row_colors.js. That script is replaced by the configurable
item_display.js, so the same six become a configuration the admin can now edit.
"""

import frappe

REPORTS = (
	"Stock Ledger",
	"Stock Balance",
	"Stock Projected Qty",
	"Item-wise Sales Register",
	"Item-wise Delivery Notes",
	"Stock Ageing",
)
NAME = "Stock Reports - Item Colour"


def execute():
	if not frappe.db.table_exists("Item Display Configuration") or frappe.db.exists("Item Display Configuration", NAME):
		return
	reports = [r for r in REPORTS if frappe.db.exists("Report", r)]
	if not reports:
		return
	taken = set(frappe.get_all("Item Display Report", filters={"parenttype": "Item Display Configuration"}, pluck="report"))
	reports = [r for r in reports if r not in taken]
	if not reports:
		return
	doc = frappe.get_doc({
		"doctype": "Item Display Configuration",
		"config_name": NAME,
		"enabled": 1,
		"reports": [{"report": r} for r in reports],
		"sku_field": "item_code",
		"apply_item_color": 1,
		"color_display": "Entire row",
		"apply_item_sequence": 0,
	})
	doc.insert(ignore_permissions=True)
