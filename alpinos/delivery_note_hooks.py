"""Server-side sync + validation for Alpinos Delivery Note customizations."""

from math import ceil

import frappe
from frappe.utils import flt


def strip_non_batch_item_batches(doc, method=None):
	"""Runs on before_validate (i.e. before ERPNext validates batches): batch_no
	(a Link to Batch) must only carry real Batch masters on batch-tracked items,
	otherwise the Delivery Note fails on submit with "Could not find Batch No: ...".
	The code itself is preserved in custom_batch_code (free text) — the batch
	mention must survive the whole cycle even without a Batch master."""
	if doc.get("is_return"):
		return
	meta_dn_item = frappe.get_meta("Delivery Note Item")
	has_code_field = bool(meta_dn_item.get_field("custom_batch_code"))
	for row in doc.get("items") or []:
		if not row.get("batch_no"):
			continue
		non_batch_item = row.get("item_code") and not frappe.db.get_value(
			"Item", row.item_code, "has_batch_no"
		)
		if non_batch_item or not frappe.db.exists("Batch", row.batch_no):
			if has_code_field and not row.get("custom_batch_code"):
				row.custom_batch_code = row.batch_no
			row.batch_no = None


def validate_delivery_note(doc, method=None):
	if doc.get("is_return"):
		return

	_sync_sales_order_header(doc)
	_sync_items_from_pick_list(doc)
	_recalc_dn_totals(doc)
	_validate_dn_mandatory(doc)


def _sync_sales_order_header(doc):
	so_names = [row.against_sales_order for row in (doc.items or []) if row.against_sales_order]
	if not so_names:
		return

	primary_so = so_names[0]
	if not doc.get("custom_sales_order_id"):
		doc.custom_sales_order_id = primary_so

	if doc.get("custom_sales_order_id"):
		cname = frappe.db.get_value("Sales Order", doc.custom_sales_order_id, "customer_name")
		if cname:
			doc.custom_dn_so_customer_name = cname


def _pick_list_item_fields():
	meta = frappe.get_meta("Pick List Item")
	fields = ["batch_no", "item_code", "picked_qty", "qty"]
	for fname in ("custom_box", "custom_mfg_date", "custom_expiry_date", "custom_batch_code"):
		if meta.get_field(fname):
			fields.append(fname)
	return fields


def _box_factor(item_code):
	if not item_code:
		return None
	v = frappe.db.get_value(
		"UOM Conversion Detail",
		{"parent": item_code, "parenttype": "Item", "uom": "Box"},
		"conversion_factor",
	)
	return flt(v) if v else None


def _sync_items_from_pick_list(doc):
	pl_fields = _pick_list_item_fields()
	meta_dn_item = frappe.get_meta("Delivery Note Item")

	for row in doc.items or []:
		if not row.get("against_pick_list") or not row.get("pick_list_item"):
			continue

		pli = frappe.db.get_value("Pick List Item", row.pick_list_item, pl_fields, as_dict=True)
		if not pli:
			continue

		if pli.get("custom_box") is not None and meta_dn_item.get_field("custom_box"):
			row.custom_box = flt(pli.get("custom_box"))
		elif row.item_code and row.qty:
			f = _box_factor(row.item_code) or 1
			row.custom_box = ceil(flt(row.qty) / f) if flt(row.qty) else 0

		# Free-text batch code always travels with the row; batch_no (Link) only
		# for batch-tracked items with a real Batch master — anything else there
		# fails DN batch validation on submit ("Could not find Batch No: ...").
		if pli.get("custom_batch_code") and meta_dn_item.get_field("custom_batch_code"):
			row.custom_batch_code = pli.get("custom_batch_code")

		has_batch = row.item_code and frappe.db.get_value("Item", row.item_code, "has_batch_no")
		if not has_batch:
			row.batch_no = None
		elif pli.get("batch_no"):
			row.batch_no = pli.get("batch_no")

		if meta_dn_item.get_field("custom_mfg_date"):
			if pli.get("custom_mfg_date"):
				row.custom_mfg_date = pli.get("custom_mfg_date")
			elif row.batch_no:
				row.custom_mfg_date = frappe.db.get_value("Batch", row.batch_no, "manufacturing_date")

		if meta_dn_item.get_field("custom_expiry_date"):
			if pli.get("custom_expiry_date"):
				row.custom_expiry_date = pli.get("custom_expiry_date")
			elif row.batch_no:
				row.custom_expiry_date = frappe.db.get_value("Batch", row.batch_no, "expiry_date")


def _recalc_dn_totals(doc):
	total_boxes = 0.0
	total_units = 0.0
	gross = 0.0

	pl_gross_done = set()
	meta_pl = frappe.get_meta("Pick List")

	for row in doc.items or []:
		total_boxes += flt(row.get("custom_box"))
		total_units += flt(row.get("qty"))

		if row.get("against_pick_list") and meta_pl.get_field("custom_gross_weight"):
			pl = row.against_pick_list
			if pl and pl not in pl_gross_done:
				gross += flt(frappe.db.get_value("Pick List", pl, "custom_gross_weight"))
				pl_gross_done.add(pl)

	if frappe.get_meta("Delivery Note").get_field("custom_total_boxes"):
		doc.custom_total_boxes = total_boxes
	if frappe.get_meta("Delivery Note").get_field("custom_total_units_dn"):
		doc.custom_total_units_dn = total_units
	if frappe.get_meta("Delivery Note").get_field("custom_dn_order_gross_weight"):
		doc.custom_dn_order_gross_weight = gross


def _validate_dn_mandatory(doc):
	if doc.flags.ignore_mandatory:
		return

	if not doc.get("custom_sales_order_id"):
		frappe.throw("Sales Order ID is mandatory.")
	if not doc.get("custom_dn_so_customer_name"):
		frappe.throw("Customer Name is mandatory.")
	if not doc.get("custom_dispatch_date"):
		frappe.throw("Dispatch Date is mandatory.")
	if not doc.get("custom_delivery_date"):
		frappe.throw("Delivery Date is mandatory.")
	if not doc.get("custom_transporter_name"):
		frappe.throw("Transporter is mandatory.")
	if not doc.get("vehicle_no"):
		frappe.throw("Picklist PO No. is mandatory.")
	if doc.docstatus == 1 and doc.get("custom_lr_gr_no") in (None, ""):
		frappe.throw("LR No. (GR No.) is mandatory.")
	if not doc.get("custom_dispatch_from"):
		frappe.throw("Dispatch From is mandatory.")
	if not (doc.get("custom_dispatch_to") or []):
		frappe.throw("At least one Dispatch To row is required.")

	meta_dn_item = frappe.get_meta("Delivery Note Item")
	for row in doc.items or []:
		if not row.item_code:
			frappe.throw(f"Row #{row.idx}: SKU is mandatory.")
		if not flt(row.qty):
			frappe.throw(f"Row #{row.idx}: Quantity is mandatory.")
		if meta_dn_item.get_field("custom_box") and flt(row.qty) and not flt(row.custom_box):
			frappe.throw(f"Row #{row.idx}: Box is mandatory.")
		# Check if the item is batched in the Item master
		has_batch_no = frappe.db.get_value("Item", row.item_code, "has_batch_no") if row.item_code else 0
		if has_batch_no:
			if not row.batch_no:
				frappe.throw(f"Row #{row.idx}: Batch No. is mandatory.")
			if meta_dn_item.get_field("custom_mfg_date") and not row.get("custom_mfg_date"):
				frappe.throw(f"Row #{row.idx}: MFG Date is mandatory.")
			if meta_dn_item.get_field("custom_expiry_date") and not row.get("custom_expiry_date"):
				frappe.throw(f"Row #{row.idx}: Expiry Date is mandatory.")
		# Expiry must be on or after MFG whenever both are present (catches manual entry on the page).
		if row.get("custom_mfg_date") and row.get("custom_expiry_date"):
			from frappe.utils import getdate
			if getdate(row.custom_expiry_date) < getdate(row.custom_mfg_date):
				frappe.throw(
					f"Row #{row.idx} ({row.item_code}): Expiry Date ({row.custom_expiry_date}) cannot be earlier than Manufacturing Date ({row.custom_mfg_date})."
				)
