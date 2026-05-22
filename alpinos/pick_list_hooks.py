import frappe
from frappe.utils import flt, now_datetime
from math import ceil

from alpinos.sales_order_api import get_box_conversion_factor


def validate_pick_list(doc, method=None):
	"""Server-side enforcement for Alpinos Pick List business rules."""
	_set_defaults(doc)
	_sync_order_information(doc)
	_sync_rows_and_totals(doc)
	_validate_mandatory_rows(doc)


def _set_defaults(doc):
	if not doc.custom_qc_attended_by:
		doc.custom_qc_attended_by = frappe.session.user
	if not doc.custom_order_date:
		doc.custom_order_date = now_datetime()


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
		qty = flt(row.qty)
		sample_qty = flt(row.custom_sample_quantity)
		factor = flt(get_box_conversion_factor(row.item_code)) if row.item_code else 0
		factor = factor or 1

		if not flt(row.custom_box):
			row.custom_box = ceil(qty / factor) if qty else 0
		if not flt(row.custom_sample_box):
			row.custom_sample_box = ceil(sample_qty / factor) if sample_qty else 0

		if row.batch_no:
			batch_details = frappe.db.get_value(
				"Batch",
				row.batch_no,
				["manufacturing_date", "expiry_date"],
				as_dict=True,
			) or {}
			row.custom_mfg_date = batch_details.get("manufacturing_date")
			row.custom_expiry_date = batch_details.get("expiry_date")

		row_weight_per_box = flt(row.custom_weight_per_box)
		actual_box += flt(row.custom_box)
		sample_box += flt(row.custom_sample_box)
		sample_weight += flt(row.custom_sample_box) * row_weight_per_box
		gross_weight += (flt(row.custom_box) + flt(row.custom_sample_box)) * row_weight_per_box
		total_unit += qty + sample_qty

	doc.custom_actual_box = actual_box
	doc.custom_sample_box = sample_box
	doc.custom_sample_weight = sample_weight
	doc.custom_total_box = actual_box + sample_box
	doc.custom_gross_weight = gross_weight
	doc.custom_total_unit = total_unit


def before_validate_pick_list(doc, method):
	# Hack to ensure backend doesn't enforce batch_no mandatory regardless of DB/Cache state
	# Since Frappe's _validate_mandatory checks doc.meta.get("fields", {"reqd": 1}),
	# we strip reqd=1 from batch_no before the validation runs.
	meta = frappe.get_meta("Pick List Item")
	df = meta.get_field("batch_no")
	if df and df.reqd:
		df.reqd = 0


def _validate_mandatory_rows(doc):

	if not doc.custom_sales_order_id:
		frappe.throw("Sales Order ID is mandatory.")
	if not doc.custom_customer_name:
		frappe.throw("Customer Name is mandatory.")
	if not doc.custom_order_date:
		frappe.throw("Date is mandatory.")
	if not doc.custom_qc_attended_by:
		frappe.throw("QC Attended By is mandatory.")

	for row in doc.locations or []:
		if not row.item_code:
			frappe.throw(f"Row #{row.idx}: SKU is mandatory.")
			
		# Quantity validations
		is_sample_only = row.custom_source_table in ["Scheme Table", "Additional Units"]
		qty = flt(row.qty)
		sample_qty = flt(row.custom_sample_quantity)
		ordered = flt(row.custom_ordered_qty)
		
		if not is_sample_only:
			if ordered and qty > ordered:
				frappe.throw(f"Row #{row.idx} ({row.item_code}): Picked Qty ({qty}) cannot be greater than Ordered Qty ({ordered}).")
			if sample_qty > qty:
				frappe.throw(f"Row #{row.idx} ({row.item_code}): Sample Qty ({sample_qty}) cannot be greater than Picked Qty ({qty}).")
		else:
			if ordered and sample_qty > ordered:
				frappe.throw(f"Row #{row.idx} ({row.item_code}): Sample Qty ({sample_qty}) cannot be greater than Ordered Qty ({ordered}).")

		if doc.docstatus == 1:
			if not row.qty and not row.custom_sample_quantity:
				frappe.throw(f"Row #{row.idx}: Quantity or Sample Quantity is mandatory.")
			if row.batch_no and not row.custom_mfg_date:
				frappe.throw(f"Row #{row.idx}: MFG Date is mandatory for selected batch.")
			if row.batch_no and not row.custom_expiry_date:
				frappe.throw(f"Row #{row.idx}: Expiry Date is mandatory for selected batch.")
