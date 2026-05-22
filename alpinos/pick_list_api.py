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

	# TEMPORARY DEBUG INFO
	debug_info = []
	for d in pick_list.locations:
		so_item = frappe.db.get_value("Sales Order Item", d.sales_order_item, ["parent", "qty", "delivered_qty"], as_dict=True) if d.sales_order_item else None
		debug_info.append(
			f"Item: {d.item_code} | Picked: {d.picked_qty} | Delivered: {d.delivered_qty} | PL Item Name: {d.name} | SO Item Ref: {d.sales_order_item} | SO Qty: {so_item.qty if so_item else 'N/A'} | SO Delivered: {so_item.delivered_qty if so_item else 'N/A'} | SO Name: {so_item.parent if so_item else 'N/A'}"
		)
	# Check if there is any Delivery Note linked to this Pick List
	linked_dns = frappe.get_all("Delivery Note Item", filters={"against_pick_list": pick_list_name}, fields=["parent", "item_code", "qty"])
	debug_info.append(f"Linked DNs: {linked_dns}")
	
	frappe.throw("<br>".join(debug_info))

	# Ensure Pick List is submitted
	if pick_list.docstatus != 1:
		frappe.throw("Pick List must be submitted to create a Delivery Note.")

	# Suppress the default ERPNext msgprint during DN creation
	_original_msgprint = frappe.msgprint
	def _silent_msgprint(*args, **kwargs):
		pass
	frappe.msgprint = _silent_msgprint

	# Monkeypatch frappe.get_doc to handle custom SO child tables mapping
	_original_get_doc = frappe.get_doc
	def _custom_get_doc(*args, **kwargs):
		doctype = None
		name = None
		if args:
			if isinstance(args[0], str):
				doctype = args[0]
				if len(args) > 1:
					name = args[1]
			elif isinstance(args[0], dict):
				doctype = args[0].get("doctype")
				name = args[0].get("name")
		
		if not doctype and kwargs:
			doctype = kwargs.get("doctype")
			name = kwargs.get("name")

		if doctype == "Sales Order Item" and name:
			if not frappe.db.exists("Sales Order Item", name):
				for custom_doctype in [
					"Sales Order Marketing Freebie",
					"Sales Order Scheme Item",
					"Sales Order Additional Units Item"
				]:
					if frappe.db.exists(custom_doctype, name):
						custom_doc = _original_get_doc(custom_doctype, name)
						# Masquerade custom table doc as a Sales Order Item
						custom_doc.doctype = "Sales Order Item"
						if not getattr(custom_doc, "uom", None):
							custom_doc.uom = frappe.db.get_value("Item", custom_doc.item_code, "stock_uom") or "Nos"
						if not getattr(custom_doc, "conversion_factor", None):
							custom_doc.conversion_factor = 1.0
						if not getattr(custom_doc, "stock_uom", None):
							custom_doc.stock_uom = custom_doc.uom
						return custom_doc
				return None
		return _original_get_doc(*args, **kwargs)

	frappe.get_doc = _custom_get_doc

	try:
		# Call standard erpnext mapper to create Delivery Note
		dn = create_delivery_note(pick_list_name)
	finally:
		# Restore original msgprint and get_doc
		frappe.msgprint = _original_msgprint
		frappe.get_doc = _original_get_doc

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

