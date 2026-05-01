"""Pick List validate: sync totals and enforce rules."""

from math import ceil

import frappe
from frappe.utils import flt

from alpinos.pick_list_api import get_box_conversion_factor, resolve_batch_no_for_row


def validate_pick_list(doc, method=None):
	_set_pick_list_defaults(doc)
	_sync_order_information(doc)
	_sync_rows_and_totals(doc)
	_validate_pick_list_mandatory(doc)


def _set_pick_list_defaults(doc):
	if not doc.custom_qc_attended_by:
		doc.custom_qc_attended_by = frappe.session.user
	if not doc.custom_order_date:
		doc.custom_order_date = frappe.utils.now_datetime()


def _sync_order_information(doc):
	first_so = next((row.sales_order for row in (doc.locations or []) if row.sales_order), None)
	if first_so:
		doc.custom_sales_order_id = first_so
		doc.custom_customer_name = frappe.db.get_value("Sales Order", first_so, "customer_name") or ""


def _sync_rows_and_totals(doc):
	actual_box = 0.0
	sample_box = 0.0
	sample_weight = 0.0
	gross_weight = 0.0
	total_unit = 0.0

	for row in doc.locations or []:
		qty = flt(row.picked_qty or row.qty)
		sample_qty = flt(row.custom_sample_quantity)
		factor = flt(get_box_conversion_factor(row.item_code)) if row.item_code else 0
		factor = factor or 1

		row.custom_box = ceil(qty / factor) if qty else 0
		row.custom_sample_box = ceil(sample_qty / factor) if sample_qty else 0

		resolved_batch = resolve_batch_no_for_row(row)
		if resolved_batch:
			batch_details = frappe.db.get_value(
				"Batch",
				resolved_batch,
				["manufacturing_date", "expiry_date"],
				as_dict=True,
			) or {}
			if frappe.get_meta("Pick List Item").get_field("custom_mfg_date"):
				row.custom_mfg_date = batch_details.get("manufacturing_date")
			if frappe.get_meta("Pick List Item").get_field("custom_expiry_date"):
				row.custom_expiry_date = batch_details.get("expiry_date")

		wpb = flt(row.custom_weight_per_box)
		actual_box += flt(row.custom_box)
		sample_box += flt(row.custom_sample_box)
		sample_weight += flt(row.custom_sample_box) * wpb
		gross_weight += (flt(row.custom_box) + flt(row.custom_sample_box)) * wpb
		total_unit += qty + sample_qty

	doc.custom_actual_box = actual_box
	doc.custom_sample_box = sample_box
	doc.custom_sample_weight = sample_weight
	doc.custom_total_box = actual_box + sample_box
	doc.custom_gross_weight = gross_weight
	doc.custom_total_unit = total_unit


def _validate_pick_list_mandatory(doc):
	if not doc.custom_sales_order_id:
		frappe.throw("Sales Order ID is mandatory.")
	if not doc.custom_customer_name:
		frappe.throw("Customer Name is mandatory.")
	if not doc.custom_order_date:
		frappe.throw("Date is mandatory.")
	if not doc.custom_qc_attended_by:
		frappe.throw("QC Attended By is mandatory.")

	meta = frappe.get_meta("Pick List Item")
	for row in doc.locations or []:
		if not row.item_code:
			frappe.throw(f"Row #{row.idx}: Item is mandatory.")
		if not flt(row.picked_qty or row.qty):
			frappe.throw(f"Row #{row.idx}: Quantity is mandatory.")
		resolved_batch = resolve_batch_no_for_row(row)
		if resolved_batch and meta.get_field("custom_mfg_date") and not row.get("custom_mfg_date"):
			frappe.throw(f"Row #{row.idx}: MFG Date is mandatory when a batch is selected.")
		if resolved_batch and meta.get_field("custom_expiry_date") and not row.get("custom_expiry_date"):
			frappe.throw(f"Row #{row.idx}: Expiry Date is mandatory when a batch is selected.")
