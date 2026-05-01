"""Whitelisted helpers for Pick List UI."""

from typing import Optional

import frappe
from frappe.utils import flt


def resolve_batch_no_for_row(row) -> Optional[str]:
	"""Batch may live on row.batch_no (legacy fields) or inside Serial and Batch Bundle."""
	bn = getattr(row, "batch_no", None)
	if bn:
		return bn
	bundle = getattr(row, "serial_and_batch_bundle", None)
	if not bundle:
		return None
	r = frappe.db.sql(
		"""
		SELECT batch_no FROM `tabSerial and Batch Entry`
		WHERE parent = %s AND IFNULL(batch_no, '') != ''
		LIMIT 1
		""",
		(bundle,),
	)
	return r[0][0] if r else None


def resolve_batch_no_from_args(batch_no=None, serial_and_batch_bundle=None) -> Optional[str]:
	if batch_no:
		return batch_no
	if not serial_and_batch_bundle:
		return None
	r = frappe.db.sql(
		"""
		SELECT batch_no FROM `tabSerial and Batch Entry`
		WHERE parent = %s AND IFNULL(batch_no, '') != ''
		LIMIT 1
		""",
		(serial_and_batch_bundle,),
	)
	return r[0][0] if r else None


@frappe.whitelist()
def get_box_conversion_factor(item_code):
	if not item_code:
		return None
	v = frappe.db.get_value(
		"UOM Conversion Detail",
		{"parent": item_code, "parenttype": "Item", "uom": "Box"},
		"conversion_factor",
	)
	return flt(v) if v else None


@frappe.whitelist()
def resolve_batch_dates_for_row(batch_no=None, serial_and_batch_bundle=None):
	"""Return resolved batch + manufacturing / expiry for a Pick List Item row."""
	bn = resolve_batch_no_from_args(batch_no=batch_no, serial_and_batch_bundle=serial_and_batch_bundle)
	if not bn:
		return {"batch_no": None, "manufacturing_date": None, "expiry_date": None}
	d = (
		frappe.db.get_value(
			"Batch",
			bn,
			["manufacturing_date", "expiry_date"],
			as_dict=True,
		)
		or {}
	)
	return {
		"batch_no": bn,
		"manufacturing_date": d.get("manufacturing_date"),
		"expiry_date": d.get("expiry_date"),
	}
