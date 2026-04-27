"""
Stock Entry customization for Alpinos.

- Existing Stock Entry / Stock Entry Detail fields are adjusted via Property Setters.
- New row-level fields are created as Custom Fields.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def setup_stock_entry_custom_fields():
	custom_fields = {
		"Stock Entry": [
			dict(
				fieldname="custom_warehouse_section",
				label="Warehouse",
				fieldtype="Section Break",
				insert_after="stock_entry_type",
			),
			dict(
				fieldname="custom_entry_by",
				label="Entry By",
				fieldtype="Link",
				options="User",
				insert_after="remarks",
				read_only=1,
			),
		],
		"Stock Entry Detail": [
			dict(
				fieldname="custom_box",
				label="Box",
				fieldtype="Int",
				insert_after="qty",
			),
			dict(
				fieldname="custom_sku_no",
				label="SKU No",
				fieldtype="Data",
				insert_after="item_name",
				fetch_from="item_code.item_name",
				read_only=1,
			),
			dict(
				fieldname="custom_usp",
				label="USP",
				fieldtype="Currency",
				insert_after="valuation_rate",
			),
			dict(
				fieldname="custom_mrp",
				label="MRP",
				fieldtype="Currency",
				insert_after="custom_usp",
			),
			dict(
				fieldname="custom_mfg_date",
				label="MFG Date",
				fieldtype="Date",
				insert_after="batch_no",
			),
			dict(
				fieldname="custom_exp_date",
				label="EXP Date",
				fieldtype="Date",
				insert_after="custom_mfg_date",
			),
		]
	}

	create_custom_fields(custom_fields, update=True)
	_setup_stock_entry_property_setters()
	frappe.clear_cache(doctype="Stock Entry")
	frappe.clear_cache(doctype="Stock Entry Detail")


def _setup_stock_entry_property_setters():
	property_setters = [
		dict(
			doctype_or_field="DocField",
			doc_type="Stock Entry",
			field_name="stock_entry_type",
			property="label",
			value="Type",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Stock Entry",
			field_name="from_warehouse",
			property="label",
			value="Default Warehouse",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Stock Entry",
			field_name="from_warehouse",
			property="insert_after",
			value="custom_warehouse_section",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Stock Entry",
			field_name="to_warehouse",
			property="label",
			value="Target Warehouse",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Stock Entry",
			field_name="to_warehouse",
			property="insert_after",
			value="from_warehouse",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Stock Entry",
			field_name="remarks",
			property="label",
			value="Notes",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Stock Entry Detail",
			field_name="item_code",
			property="label",
			value="SKU (Item Code)",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Stock Entry Detail",
			field_name="qty",
			property="label",
			value="Quantity",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Stock Entry Detail",
			field_name="retain_sample",
			property="fetch_from",
			value="item_code.custom_retain_sample",
			property_type="Data",
		),
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
			doc = frappe.get_doc("Property Setter", existing)
			doc.value = ps_data["value"]
			doc.property_type = ps_data["property_type"]
			doc.save(ignore_permissions=True)
		else:
			frappe.get_doc({"doctype": "Property Setter", **ps_data}).insert(ignore_permissions=True)

	frappe.db.commit()
