"""Custom fields + client script for Delivery Note (Alpinos dispatch sheet)."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def setup_delivery_note_alpinos():
	frappe.reload_doc("alpinos_development", "doctype", "alpinos_dn_dispatch_to")

	custom_fields = {
		"Delivery Note": [
			dict(
				fieldname="custom_dn_delivery_section",
				label="Delivery Information",
				fieldtype="Section Break",
				insert_after="customer_name",
				depends_on="eval:!doc.is_return",
			),
			dict(
				fieldname="custom_sales_order_id",
				label="Sales Order ID",
				fieldtype="Link",
				options="Sales Order",
				insert_after="custom_dn_delivery_section",
				reqd=1,
				depends_on="eval:!doc.is_return",
			),
			dict(
				fieldname="custom_dn_so_customer_name",
				label="Customer Name",
				fieldtype="Data",
				insert_after="custom_sales_order_id",
				fetch_from="custom_sales_order_id.customer_name",
				read_only=1,
				reqd=1,
				depends_on="eval:!doc.is_return",
			),
			dict(
				fieldname="custom_dispatch_date",
				label="Dispatch Date",
				fieldtype="Datetime",
				insert_after="custom_dn_so_customer_name",
				default="Now",
				reqd=1,
				depends_on="eval:!doc.is_return",
			),
			dict(
				fieldname="custom_delivery_date",
				label="Delivery Date",
				fieldtype="Datetime",
				insert_after="custom_dispatch_date",
				default="Now",
				reqd=1,
				depends_on="eval:!doc.is_return",
			),
			dict(
				fieldname="custom_assigned_to",
				label="Assigned To",
				fieldtype="Link",
				options="User",
				insert_after="custom_delivery_date",
				in_list_view=1,
				in_standard_filter=1,
				depends_on="eval:!doc.is_return",
				allow_on_submit=1,
			),
			dict(
				fieldname="custom_transporter_section",
				label="Transporter Information",
				fieldtype="Section Break",
				insert_after="vehicle_no",
				depends_on="eval:!doc.is_return",
			),
			dict(
				fieldname="custom_transporter_name",
				label="Transporter",
				fieldtype="Data",
				insert_after="custom_transporter_section",
				reqd=1,
				depends_on="eval:!doc.is_return",
				read_only=1,
				description="Fetched from the linked Pick List's Transporter — not editable on the Delivery Note.",
			),
			dict(
				fieldname="custom_lr_gr_no",
				label="LR No. (GR No.)",
				fieldtype="Data",
				insert_after="custom_transporter_name",
				reqd=1,
				depends_on="eval:!doc.is_return",
			),
			dict(
				fieldname="custom_dispatch_from",
				label="Dispatch From",
				fieldtype="Small Text",
				insert_after="custom_lr_gr_no",
				reqd=1,
				depends_on="eval:!doc.is_return",
			),
			dict(
				fieldname="custom_dispatch_to_section",
				fieldtype="Section Break",
				label="Dispatch To",
				insert_after="custom_dispatch_from",
				depends_on="eval:!doc.is_return",
			),
			dict(
				fieldname="custom_dispatch_to",
				label="Dispatch To",
				fieldtype="Table",
				options="Alpinos DN Dispatch To",
				insert_after="custom_dispatch_to_section",
				depends_on="eval:!doc.is_return",
			),
			dict(
				fieldname="custom_alpinos_order_total_section",
				label="Order Total",
				fieldtype="Section Break",
				insert_after="section_break_31",
				depends_on="eval:!doc.is_return",
			),
			dict(
				fieldname="custom_total_boxes",
				label="Total Boxes",
				fieldtype="Float",
				insert_after="custom_alpinos_order_total_section",
				read_only=1,
				default="0",
				reqd=1,
				depends_on="eval:!doc.is_return",
			),
			dict(
				fieldname="custom_dn_order_gross_weight",
				label="Gross Weight",
				fieldtype="Float",
				insert_after="custom_total_boxes",
				read_only=1,
				default="0",
				reqd=1,
				depends_on="eval:!doc.is_return",
			),
			dict(
				fieldname="custom_total_units_dn",
				label="Total Units",
				fieldtype="Float",
				insert_after="custom_dn_order_gross_weight",
				read_only=1,
				default="0",
				reqd=1,
				depends_on="eval:!doc.is_return",
			),
			dict(
				fieldname="custom_removed_items",
				label="Removed Items",
				fieldtype="Table",
				options="Alpinos Removed Pick List Item",
				insert_after="custom_total_units_dn",
				read_only=1,
				collapsible=1,
				depends_on="eval:!doc.is_return",
				description="Audit log of SKUs removed from this Delivery Note before submit, with the reason supplied at removal.",
			),
		],
		"Delivery Note Item": [
			dict(
				fieldname="custom_remark",
				label="Remark",
				fieldtype="Data",
				insert_after="qty",
				description="Mandatory when this DN qty is less than the Pick List qty.",
			),
			dict(
				fieldname="custom_box",
				label="Box",
				fieldtype="Float",
				insert_after="qty",
				read_only=1,
				default="0",
				reqd=0,
			),
			dict(
				fieldname="custom_batch_code",
				label="Batch Code",
				fieldtype="Data",
				insert_after="batch_no",
				read_only=1,
				description="Pick List batch code (free text) — mirrored from Pick List Item so manually-entered batch numbers persist even when no Batch master exists.",
			),
			dict(
				fieldname="custom_mfg_date",
				label="MFG Date",
				fieldtype="Datetime",
				insert_after="custom_batch_code",
				read_only=1,
				reqd=0,
			),
			dict(
				fieldname="custom_expiry_date",
				label="Expiry Date",
				fieldtype="Datetime",
				insert_after="custom_mfg_date",
				read_only=1,
				reqd=0,
			),
		],
	}

	create_custom_fields(custom_fields, update=True)

	property_setters = [
		{
			"doctype_or_field": "DocField",
			"doc_type": "Delivery Note Item",
			"field_name": "item_code",
			"property": "label",
			"value": "SKU",
			"property_type": "Data",
		},
		{
			"doctype_or_field": "DocField",
			"doc_type": "Delivery Note Item",
			"field_name": "item_name",
			"property": "label",
			"value": "SKU No.",
			"property_type": "Data",
		},
		{
			"doctype_or_field": "DocField",
			"doc_type": "Delivery Note Item",
			"field_name": "qty",
			"property": "label",
			"value": "Quantity",
			"property_type": "Data",
		},
		# vehicle_no is re-purposed to carry the Pick List PO No. value
		# (fetched from Pick List.custom_po_no). Renaming the label keeps the
		# data column in place — no migration needed.
		{
			"doctype_or_field": "DocField",
			"doc_type": "Delivery Note",
			"field_name": "vehicle_no",
			"property": "label",
			"value": "Picklist PO No.",
			"property_type": "Data",
		},
		# Transporter Name is now free text (mirrors Pick List.custom_transporter
		# which is itself a Data field).
		{
			"doctype_or_field": "DocField",
			"doc_type": "Delivery Note",
			"field_name": "custom_transporter_name",
			"property": "fieldtype",
			"value": "Data",
			"property_type": "Select",
		},
		{
			"doctype_or_field": "DocField",
			"doc_type": "Delivery Note",
			"field_name": "custom_transporter_name",
			"property": "options",
			"value": "",
			"property_type": "Text",
		},
	]

	for ps_data in property_setters:
		existing = frappe.db.exists(
			"Property Setter",
			{
				"doc_type": ps_data["doc_type"],
				"field_name": ps_data["field_name"],
				"property": ps_data["property"],
			},
		)
		if existing:
			ps = frappe.get_doc("Property Setter", existing)
			ps.value = ps_data["value"]
			ps.save(ignore_permissions=True)
		else:
			frappe.get_doc({"doctype": "Property Setter", **ps_data}).insert(ignore_permissions=True)

	frappe.db.commit()

	from alpinos.delivery_note_client_script import create_delivery_note_client_script

	create_delivery_note_client_script()
