import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def setup_pick_list_custom_fields():
	custom_fields = {
		"Pick List": [
			dict(
				fieldname="custom_order_info_section",
				label="Order Information",
				fieldtype="Section Break",
				insert_after="purpose",
			),
			dict(
				fieldname="custom_sales_order_id",
				label="Sales Order ID",
				fieldtype="Link",
				options="Sales Order",
				insert_after="custom_order_info_section",
				read_only=1,
				reqd=1,
			),
			dict(
				fieldname="custom_customer_name",
				label="Customer Name",
				fieldtype="Data",
				insert_after="custom_sales_order_id",
				read_only=1,
				reqd=1,
			),
			dict(
				fieldname="custom_order_date",
				label="Date",
				fieldtype="Datetime",
				insert_after="custom_customer_name",
				default="Now",
				reqd=1,
			),
			dict(
				fieldname="custom_qc_attended_by",
				label="QC Attended By",
				fieldtype="Link",
				options="User",
				insert_after="custom_order_date",
				reqd=1,
			),
			dict(
				fieldname="custom_po_no",
				label="PO No.",
				fieldtype="Data",
				insert_after="custom_qc_attended_by",
			),
			dict(
				fieldname="custom_transporter",
				label="Transporter",
				fieldtype="Data",
				insert_after="custom_po_no",
			),
			dict(
				fieldname="custom_party_code",
				label="Party Code",
				fieldtype="Data",
				insert_after="custom_transporter",
			),
			dict(
				fieldname="custom_order_total_section",
				label="Order Total",
				fieldtype="Section Break",
				insert_after="locations",
			),
			dict(
				fieldname="custom_actual_box",
				label="Actual Box",
				fieldtype="Float",
				insert_after="custom_order_total_section",
				read_only=1,
				default="0",
				reqd=1,
			),
			dict(
				fieldname="custom_sample_box",
				label="Sample Box",
				fieldtype="Float",
				insert_after="custom_actual_box",
				read_only=1,
				default="0",
			),
			dict(
				fieldname="custom_sample_weight",
				label="Sample Weight",
				fieldtype="Float",
				insert_after="custom_sample_box",
				read_only=1,
				default="0",
			),
			dict(
				fieldname="custom_total_box",
				label="Total Box",
				fieldtype="Float",
				insert_after="custom_sample_weight",
				read_only=1,
				default="0",
				reqd=1,
			),
			dict(
				fieldname="custom_gross_weight",
				label="Gross Weight",
				fieldtype="Float",
				insert_after="custom_total_box",
				read_only=1,
				default="0",
				reqd=1,
			),
			dict(
				fieldname="custom_total_unit",
				label="Total Unit",
				fieldtype="Float",
				insert_after="custom_gross_weight",
				read_only=1,
				default="0",
				reqd=1,
			),
		],
		"Pick List Item": [
			dict(
				fieldname="custom_ordered_qty",
				label="Ordered Qty",
				fieldtype="Float",
				insert_after="item_name",
				read_only=1,
				default="0",
			),
			dict(
				fieldname="custom_box",
				label="Box",
				fieldtype="Float",
				insert_after="qty",
				read_only=1,
				default="0",
				reqd=1,
			),
			dict(
				fieldname="custom_sample_quantity",
				label="Sample Quantity",
				fieldtype="Float",
				insert_after="custom_box",
				default="0",
			),
			dict(
				fieldname="custom_sample_box",
				label="Sample Box",
				fieldtype="Float",
				insert_after="custom_sample_quantity",
				read_only=1,
				default="0",
			),
			dict(
				fieldname="custom_weight_per_box",
				label="Std Weight / Box",
				fieldtype="Float",
				insert_after="custom_sample_box",
				default="0",
			),
			dict(
				fieldname="custom_mfg_date",
				label="MFG Date",
				fieldtype="Date",
				insert_after="batch_no",
				read_only=1,
				reqd=0,
			),
			dict(
				fieldname="custom_expiry_date",
				label="Expiry Date",
				fieldtype="Date",
				insert_after="custom_mfg_date",
				read_only=1,
				reqd=0,
			),
			dict(
				fieldname="custom_source_table",
				label="Source Table",
				fieldtype="Data",
				insert_after="custom_expiry_date",
				read_only=1,
				hidden=1,
			),
		],
	}

	create_custom_fields(custom_fields, update=True)
	_setup_pick_list_property_setters()
	ensure_pick_list_item_date_fields_optional()
	frappe.db.commit()


def ensure_pick_list_item_date_fields_optional():
	"""Custom Field `update=True` often leaves `reqd` stuck at 1; client then blocks save. Force off in DB + Property Setter."""
	for fieldname in ("custom_mfg_date", "custom_expiry_date"):
		cf_name = frappe.db.get_value(
			"Custom Field", {"dt": "Pick List Item", "fieldname": fieldname}, "name"
		)
		if cf_name:
			frappe.db.set_value("Custom Field", cf_name, "reqd", 0)

	# Property Setter overrides DocField meta (covers edge cases where CF row is stale in cache)
	for fieldname in ("custom_mfg_date", "custom_expiry_date"):
		existing = frappe.db.exists(
			"Property Setter",
			{
				"doc_type": "Pick List Item",
				"field_name": fieldname,
				"property": "reqd",
			},
		)
		ps_data = {
			"doctype_or_field": "DocField",
			"doc_type": "Pick List Item",
			"field_name": fieldname,
			"property": "reqd",
			"value": "0",
			"property_type": "Check",
		}
		if existing:
			ps = frappe.get_doc("Property Setter", existing)
			ps.value = "0"
			ps.save(ignore_permissions=True)
		else:
			frappe.get_doc({"doctype": "Property Setter", **ps_data}).insert(ignore_permissions=True)

	frappe.clear_cache(doctype="Pick List Item")
	frappe.clear_cache(doctype="Pick List")


def _setup_pick_list_property_setters():
	property_setters = [
		{
			"doctype_or_field": "DocField",
			"doc_type": "Pick List Item",
			"field_name": "item_code",
			"property": "label",
			"value": "SKU",
			"property_type": "Data",
		},
		{
			"doctype_or_field": "DocField",
			"doc_type": "Pick List Item",
			"field_name": "item_name",
			"property": "label",
			"value": "SKU No.",
			"property_type": "Data",
		},
		{
			"doctype_or_field": "DocField",
			"doc_type": "Pick List Item",
			"field_name": "qty",
			"property": "label",
			"value": "Quantity",
			"property_type": "Data",
		},
		{
			"doctype_or_field": "DocField",
			"doc_type": "Pick List Item",
			"field_name": "batch_no",
			"property": "reqd",
			"value": "1",
			"property_type": "Check",
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
