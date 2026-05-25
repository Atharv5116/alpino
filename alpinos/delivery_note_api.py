"""Whitelisted helpers for Delivery Note (Pick List sync)."""

from typing import Optional

import frappe

from alpinos.pick_list_api import resolve_batch_no_from_args


@frappe.whitelist()
def get_pick_list_row_for_delivery(pick_list_item: Optional[str] = None):
	"""Return Pick List Item row fields needed to populate DN line (custom fields optional)."""
	if not pick_list_item or not frappe.db.exists("Pick List Item", pick_list_item):
		return {}

	meta = frappe.get_meta("Pick List Item")
	fields = ["item_code", "batch_no", "serial_and_batch_bundle", "picked_qty", "qty", "parent"]
	for fname in ("custom_box", "custom_mfg_date", "custom_expiry_date", "custom_sample_quantity"):
		if meta.get_field(fname):
			fields.append(fname)

	row = frappe.db.get_value("Pick List Item", pick_list_item, fields, as_dict=True) or {}
	bn = resolve_batch_no_from_args(row.get("batch_no"), row.get("serial_and_batch_bundle"))
	if bn and (
		not row.get("custom_mfg_date")
		or not row.get("custom_expiry_date")
	):
		batch_doc = frappe.db.get_value(
			"Batch",
			bn,
			["manufacturing_date", "expiry_date"],
			as_dict=True,
		) or {}
		if meta.get_field("custom_mfg_date") and not row.get("custom_mfg_date"):
			row["custom_mfg_date"] = batch_doc.get("manufacturing_date")
		if meta.get_field("custom_expiry_date") and not row.get("custom_expiry_date"):
			row["custom_expiry_date"] = batch_doc.get("expiry_date")
	return row
