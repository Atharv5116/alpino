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
		doc.custom_qc_attended_by = doc.get("custom_assigned_to") or frappe.session.user
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
		row.custom_sample_quantity = 0.0
		row.custom_sample_box = 0.0
		
		factor = flt(get_box_conversion_factor(row.item_code)) if row.item_code else 0
		factor = factor or 1

		if row.item_code and not flt(row.custom_weight_per_box):
			row.custom_weight_per_box = flt(
				frappe.db.get_value("Item", row.item_code, "custom_gross_weight")
			)

		table_name = row.custom_source_table or "Items"
		if not flt(row.custom_box):
			if table_name == "Items":
				row.custom_box = int(ceil(qty / factor)) if qty else 0
			else:
				row.custom_box = 0
		else:
			row.custom_box = int(round(flt(row.custom_box)))

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
		row_box = flt(row.custom_box)

		if table_name == "Items":
			actual_box += row_box
		else:
			sample_box += row_box
			sample_weight += row_box * row_weight_per_box

		gross_weight += row_box * row_weight_per_box
		total_unit += qty

	doc.custom_actual_box = int(round(actual_box))
	doc.custom_sample_box = int(round(sample_box))
	doc.custom_sample_weight = flt(sample_weight, 2)
	doc.custom_total_box = int(round(actual_box + sample_box))
	doc.custom_gross_weight = flt(gross_weight, 2)
	doc.custom_total_unit = flt(total_unit, 2)


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
		qty = flt(row.qty)
		ordered = flt(row.custom_ordered_qty)
		
		if ordered and qty > ordered:
			frappe.throw(f"Row #{row.idx} ({row.item_code}): Picked Qty ({qty}) cannot be greater than Ordered Qty ({ordered}).")

		if doc.docstatus == 1:
			if not row.qty:
				frappe.throw(f"Row #{row.idx}: Quantity is mandatory.")
			if row.batch_no and not row.custom_mfg_date:
				frappe.throw(f"Row #{row.idx}: MFG Date is mandatory for selected batch.")
			if row.batch_no and not row.custom_expiry_date:
				frappe.throw(f"Row #{row.idx}: Expiry Date is mandatory for selected batch.")
