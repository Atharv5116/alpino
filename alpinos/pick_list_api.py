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

	# Suppress the default ERPNext msgprint during DN creation
	_original_msgprint = frappe.msgprint
	def _silent_msgprint(*args, **kwargs):
		if "raise_exception" in kwargs and kwargs["raise_exception"]:
			raise_exception = kwargs["raise_exception"]
			if isinstance(raise_exception, type) and issubclass(raise_exception, Exception):
				raise raise_exception(args[0] if args else "Validation Error")
			else:
				raise frappe.ValidationError(args[0] if args else "Validation Error")
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
						
						# Fetch missing item fields from Item master
						item_details = frappe.db.get_value(
							"Item",
							custom_doc.item_code,
							["item_group", "item_name", "brand", "description", "stock_uom"],
							as_dict=True,
						) or {}
						for key, val in item_details.items():
							if not getattr(custom_doc, key, None):
								setattr(custom_doc, key, val)

						if not getattr(custom_doc, "uom", None):
							custom_doc.uom = custom_doc.stock_uom or "Nos"
						if not getattr(custom_doc, "conversion_factor", None):
							custom_doc.conversion_factor = 1.0
						if not getattr(custom_doc, "stock_uom", None):
							custom_doc.stock_uom = custom_doc.uom
						if not getattr(custom_doc, "rate", None):
							custom_doc.rate = 0.0
						if not getattr(custom_doc, "delivered_qty", None):
							custom_doc.delivered_qty = 0.0
						if not getattr(custom_doc, "delivered_by_supplier", None):
							custom_doc.delivered_by_supplier = 0
						return custom_doc
				return None
		return _original_get_doc(*args, **kwargs)

	# Monkeypatch frappe.get_all to fetch details for masqueraded Sales Order Items from custom tables
	_original_get_all = frappe.get_all
	def _custom_get_all(*args, **kwargs):
		doctype = args[0] if args else kwargs.get("doctype")
		filters = kwargs.get("filters")
		if doctype == "Sales Order Item" and filters and "name" in filters:
			name_filter = filters["name"]
			names_to_query = []
			if isinstance(name_filter, (list, tuple)):
				if len(name_filter) == 2 and name_filter[0] == "in" and isinstance(name_filter[1], (list, tuple)):
					names_to_query = list(name_filter[1])
				elif len(name_filter) == 2 and isinstance(name_filter[1], str):
					names_to_query = [name_filter[1]]
			elif isinstance(name_filter, str):
				names_to_query = [name_filter]

			results = _original_get_all(*args, **kwargs)
			found_names = {r.name if hasattr(r, "name") else r.get("name") for r in results}
			missing_names = [n for n in names_to_query if n not in found_names]

			if missing_names:
				fields = kwargs.get("fields") or ["name"]
				fields_list = fields if isinstance(fields, list) else [fields]
				custom_results = []
				for custom_doctype in [
					"Sales Order Marketing Freebie",
					"Sales Order Scheme Item",
					"Sales Order Additional Units Item"
				]:
					missing_in_custom = [n for n in missing_names if frappe.db.exists(custom_doctype, n)]
					if missing_in_custom:
						valid_fields = [f.fieldname for f in frappe.get_meta(custom_doctype).fields] + ["name", "parent"]
						query_fields = [f for f in fields_list if f in valid_fields]
						custom_records = _original_get_all(
							custom_doctype,
							filters={"name": ("in", missing_in_custom)},
							fields=query_fields
						)
						for r in custom_records:
							for f in fields_list:
								if f not in r:
									r[f] = 1.0 if f == "conversion_factor" else (0.0 if f in ["rate", "qty", "delivered_qty"] else None)
						custom_results.extend(custom_records)
				results.extend(custom_results)
			return results
		return _original_get_all(*args, **kwargs)

	frappe.get_doc = _custom_get_doc
	frappe.get_all = _custom_get_all

	try:
		# Call standard erpnext mapper to create Delivery Note
		dn = create_delivery_note(pick_list_name)
	finally:
		# Restore original msgprint, get_doc, and get_all
		frappe.msgprint = _original_msgprint
		frappe.get_doc = _original_get_doc
		frappe.get_all = _original_get_all

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

