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


@frappe.whitelist()
def bulk_edit_transporter(pick_lists, transporter):
	import json
	if isinstance(pick_lists, str):
		pick_lists = json.loads(pick_lists)

	if not pick_lists or not isinstance(pick_lists, list):
		frappe.throw("No Pick Lists selected or invalid input format.")

	for pl in pick_lists:
		frappe.db.set_value("Pick List", pl, "custom_transporter", transporter)

	frappe.db.commit()
	return {"status": "success"}


@frappe.whitelist()
def create_delivery_note_from_pick_list(pick_list_name):
	from erpnext.stock.doctype.pick_list.pick_list import create_delivery_note
	import json

	# Load Pick List to get its custom fields
	pick_list = frappe.get_doc("Pick List", pick_list_name)

	# Ensure Pick List is submitted
	if pick_list.docstatus != 1:
		frappe.throw("Pick List must be submitted to create a Delivery Note.")

	# Call standard erpnext mapper to create Delivery Note
	dn = create_delivery_note(pick_list_name)

	if not dn:
		frappe.throw("Could not create Delivery Note from Pick List.")

	if isinstance(dn, str):
		dn = frappe.get_doc("Delivery Note", dn)

	# Map custom fields from Pick List to Delivery Note
	dn.custom_sales_order_id = pick_list.custom_sales_order_id
	dn.custom_dn_so_customer_name = pick_list.custom_customer_name
	dn.custom_dispatch_date = pick_list.custom_order_date or frappe.utils.now_datetime()
	dn.custom_delivery_date = pick_list.custom_order_date or frappe.utils.now_datetime()

	# Map transporter
	pt = pick_list.custom_transporter
	valid_transporters = ["Local", "Own Vehicle", "Third Party", "Other"]
	if pt in valid_transporters:
		dn.custom_transporter_name = pt
	elif pt:
		dn.custom_transporter_name = "Third Party"
		dn.transporter = pt
	else:
		dn.custom_transporter_name = "Third Party"

	# Save updated Delivery Note bypassing validations for Draft
	dn.flags.ignore_mandatory = True
	dn.save(ignore_permissions=True)
	frappe.db.commit()

	return dn.name

