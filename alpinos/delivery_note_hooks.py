"""Server-side sync + validation for Alpinos Delivery Note customizations."""

from math import ceil

import frappe
from frappe.utils import flt


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
	for fname in ("custom_box", "custom_mfg_date", "custom_expiry_date"):
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

		if pli.get("batch_no"):
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
		frappe.throw("Transporter Name is mandatory.")
	if not doc.get("vehicle_no"):
		frappe.throw("Vehicle No. is mandatory.")
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
		if not row.batch_no:
			frappe.throw(f"Row #{row.idx}: Batch No. is mandatory.")
		if meta_dn_item.get_field("custom_mfg_date") and not row.get("custom_mfg_date"):
			frappe.throw(f"Row #{row.idx}: MFG Date is mandatory.")
		if meta_dn_item.get_field("custom_expiry_date") and not row.get("custom_expiry_date"):
			frappe.throw(f"Row #{row.idx}: Expiry Date is mandatory.")
