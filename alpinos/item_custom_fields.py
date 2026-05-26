"""
Item master customization for Alpinos.

- Existing Item fields are adjusted through Property Setters.
- New Item fields are created as Custom Fields (e.g. SKU No, Pack Type, freebie flags).
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def setup_item_custom_fields():
	custom_fields = {
		"Item": [
			dict(
				fieldname="custom_sequence",
				label="Sequence",
				fieldtype="Int",
				insert_after="item_code",
				in_list_view=1,
			),
			dict(
				fieldname="custom_sku_no",
				label="SKU No",
				fieldtype="Data",
				insert_after="item_name",
			),
			dict(
				fieldname="custom_pack_type",
				label="Pack Type",
				fieldtype="Select",
				options="\nJar\nTub\nPouch\nOther",
				insert_after="has_variants",
			),
			dict(
				fieldname="custom_is_freebie",
				label="Is Freebie",
				fieldtype="Check",
				insert_after="is_sales_item",
				default=0,
			),
			dict(
				fieldname="custom_color",
				label="Color",
				fieldtype="Color",
				insert_after="brand",
			),
			dict(
				fieldname="custom_retain_sample",
				label="Retain Sample",
				fieldtype="Check",
				insert_after="has_expiry_date",
				default=0,
			),
		]
	}

	create_custom_fields(custom_fields, update=True)
	_setup_item_property_setters()
	frappe.clear_cache(doctype="Item")


def _setup_item_property_setters():
	property_setters = [
		dict(
			doctype_or_field="DocField",
			doc_type="Item",
			field_name="item_code",
			property="label",
			value="SKU",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Item",
			field_name="image",
			property="label",
			value="Item Photo",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Item",
			field_name="image",
			property="hidden",
			value="0",
			property_type="Check",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Item",
			field_name="uoms",
			property="label",
			value="UOM Table",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Item",
			field_name="purchase_uom",
			property="label",
			value="Default Purchase UOM",
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
