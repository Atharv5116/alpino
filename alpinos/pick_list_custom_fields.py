"""Pick List + Pick List Item custom fields (Alpinos)."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def setup_pick_list_alpinos_fields():
	"""Create/update Pick List custom fields. Safe to run on every migrate."""
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
				fieldname="custom_box",
				label="Box",
				fieldtype="Float",
				insert_after="qty",
				read_only=1,
				default="0",
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
				mandatory_depends_on="eval:doc.batch_no || doc.serial_and_batch_bundle",
			),
			dict(
				fieldname="custom_expiry_date",
				label="Expiry Date",
				fieldtype="Date",
				insert_after="custom_mfg_date",
				read_only=1,
				reqd=0,
				mandatory_depends_on="eval:doc.batch_no || doc.serial_and_batch_bundle",
			),
		],
	}

	create_custom_fields(custom_fields, update=True)

	_remove_batch_no_always_required_setter()
	_ensure_pick_list_item_date_fields_conditional()

	frappe.db.commit()

	from alpinos.pick_list_client_script import create_pick_list_client_script

	create_pick_list_client_script()


def _ensure_pick_list_item_date_fields_conditional():
	"""Existing DB rows may still have reqd=1; force conditional mandatory."""
	for fn in ("custom_mfg_date", "custom_expiry_date"):
		cf_name = frappe.db.get_value("Custom Field", {"dt": "Pick List Item", "fieldname": fn}, "name")
		if not cf_name:
			continue
		cf = frappe.get_doc("Custom Field", cf_name)
		cf.reqd = 0
		cf.mandatory_depends_on = "eval:doc.batch_no || doc.serial_and_batch_bundle"
		cf.save(ignore_permissions=True)


def _remove_batch_no_always_required_setter():
	"""Batch is not always applicable; drop global reqd on batch_no if we added it."""
	for ps_name in frappe.get_all(
		"Property Setter",
		filters={
			"doc_type": "Pick List Item",
			"field_name": "batch_no",
			"property": "reqd",
		},
		pluck="name",
	):
		frappe.delete_doc("Property Setter", ps_name, force=1, ignore_permissions=True)
