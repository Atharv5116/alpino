"""Serve the Item Display Configurations to the browser (Changes(HP) #39).

The rules and each Item's colour / sequence travel in the boot payload, so the page
script can colour and order rows synchronously while a report or page renders. Only
sent when at least one configuration is enabled; nothing is added otherwise.
"""

import frappe
from frappe.utils import cint

CACHE_KEY = "alpinos_item_display_rules"


def clear_cache():
	frappe.cache.delete_value(CACHE_KEY)


def get_rules():
	"""{"reports": {name: rule}, "pages": {name: rule}} for every enabled configuration."""
	rules = frappe.cache.get_value(CACHE_KEY)
	if rules is not None:
		return rules
	rules = {"reports": {}, "pages": {}}
	if frappe.db.table_exists("Item Display Configuration"):
		for name in frappe.get_all("Item Display Configuration", filters={"enabled": 1}, pluck="name"):
			doc = frappe.get_doc("Item Display Configuration", name)
			rule = {
				"config": doc.name,
				"sku_field": doc.sku_field,
				"color": cint(doc.apply_item_color),
				"color_display": doc.color_display or "Entire row",
				"sequence": cint(doc.apply_item_sequence),
				"sort_dir": doc.sort_direction or "Ascending",
			}
			for row in doc.reports:
				rules["reports"][row.report] = rule
			for row in doc.pages:
				rules["pages"][row.page] = rule
	frappe.cache.set_value(CACHE_KEY, rules)
	return rules


def get_item_meta():
	"""{item_code: [color, sequence]} for enabled Items carrying either."""
	rows = frappe.db.sql(
		"""
		SELECT name, IFNULL(custom_color, '') AS color, IFNULL(custom_sequence, 0) AS seq
		FROM `tabItem`
		WHERE disabled = 0 AND (IFNULL(custom_color, '') <> '' OR IFNULL(custom_sequence, 0) > 0)
		""",
		as_dict=True,
	)
	return {r.name: [r.color, cint(r.seq)] for r in rows}


def payload():
	rules = get_rules()
	if not (rules["reports"] or rules["pages"]):
		return None
	return {"rules": rules, "items": get_item_meta()}


def extend_bootinfo(bootinfo):
	try:
		data = payload()
	except Exception:
		frappe.log_error(title="Item Display Configuration boot failed")
		data = None
	if data:
		bootinfo.alpinos_item_display = data


@frappe.whitelist()
def get_item_display_payload():
	"""The same payload on demand (an Item's colour changed since the page loaded)."""
	return payload()
