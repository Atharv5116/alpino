"""Whitelisted helpers for Delivery Note (Pick List sync)."""

from typing import Optional

import frappe


@frappe.whitelist()
def get_pick_list_row_for_delivery(pick_list_item: Optional[str] = None):
	"""Return Pick List Item row fields needed to populate DN line (custom fields optional)."""
	if not pick_list_item or not frappe.db.exists("Pick List Item", pick_list_item):
		return {}

	meta = frappe.get_meta("Pick List Item")
	fields = ["item_code", "batch_no", "picked_qty", "qty", "parent"]
	for fname in ("custom_box", "custom_mfg_date", "custom_expiry_date", "custom_sample_quantity"):
		if meta.get_field(fname):
			fields.append(fname)

	return frappe.db.get_value("Pick List Item", pick_list_item, fields, as_dict=True) or {}
