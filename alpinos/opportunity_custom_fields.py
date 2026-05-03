"""
Opportunity customization for Alpinos.

Rules followed:
- Existing Opportunity/Opportunity Item fields are updated via Property Setters.
- New fields are created via Custom Field.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def setup_opportunity_custom_fields():
	_delete_obsolete_opportunity_custom_fields()
	_cleanup_opportunity_from_property_setters()

	custom_fields = {
		"Opportunity": [
			dict(
				fieldname="custom_order_type",
				label="Customer Type",
				fieldtype="Select",
				options="\nGENERAL TRADE\nHORECA TRADE\nINSTITUTIONAL TRADE\nMODERN TRADE\nNUTRITIONAL TRADE\nOTHERS\nGT\nMT\nGYM & NUTRITION\nHoReCa",
				insert_after="party_name",
				reqd=1,
			),
			dict(
				fieldname="custom_billing_address",
				label="Billing Address",
				fieldtype="Link",
				options="Address",
				insert_after="customer_address",
			),
			dict(
				fieldname="custom_other_details_section",
				label="Other Details",
				fieldtype="Section Break",
				insert_after="contact_display",
			),
			dict(
				fieldname="custom_details_tab",
				label="Details",
				fieldtype="Tab Break",
				insert_after="transaction_date",
			),
			dict(
				fieldname="custom_marketing_freebies",
				label="Marketing Freebies",
				fieldtype="Table",
				options="Sales Order Marketing Freebie",
				insert_after="custom_other_details_section",
			),
			dict(
				fieldname="custom_additional_units_damage",
				label="Additional Units - Damage",
				fieldtype="Check",
				insert_after="custom_marketing_freebies",
			),
			dict(
				fieldname="custom_scheme_item_table",
				label="Scheme Item Table",
				fieldtype="Table",
				options="Sales Order Scheme Item",
				insert_after="custom_additional_units_damage",
				depends_on="eval:doc.custom_additional_units_damage",
			),
			dict(
				fieldname="custom_cash_discount",
				label="Cash Discount (%)",
				fieldtype="Percent",
				insert_after="total",
				default="0",
			),
			dict(
				fieldname="custom_over_discount",
				label="Over Discount",
				fieldtype="Currency",
				insert_after="custom_cash_discount",
				read_only=1,
			),
			dict(
				fieldname="custom_additional_discount_total",
				label="Additional Discount",
				fieldtype="Currency",
				insert_after="custom_over_discount",
				read_only=1,
			),
			dict(
				fieldname="custom_gst_total",
				label="GST",
				fieldtype="Currency",
				insert_after="custom_additional_discount_total",
				read_only=1,
			),
		],
		"Opportunity Item": [
			dict(
				fieldname="custom_boxes",
				label="Boxes",
				fieldtype="Float",
				insert_after="qty",
			),
			dict(
				fieldname="custom_mrp",
				label="MRP",
				fieldtype="Currency",
				insert_after="rate",
			),
			dict(
				fieldname="custom_buyer_margin_percent",
				label="Buyer Margin %",
				fieldtype="Percent",
				insert_after="custom_mrp",
				description="From Offline Buyer Master / catalog when applicable; applied before Flat % / Offer / Additional Discount.",
			),
			dict(
				fieldname="custom_flat_discount",
				label="Flat Discount %",
				fieldtype="Percent",
				insert_after="custom_buyer_margin_percent",
			),
			dict(
				fieldname="custom_offer",
				label="Offer %",
				fieldtype="Data",
				insert_after="custom_flat_discount",
			),
			dict(
				fieldname="custom_additional_discount",
				label="Additional Discount %",
				fieldtype="Percent",
				insert_after="custom_offer",
			),
			dict(
				fieldname="custom_item_tax",
				label="Tax",
				fieldtype="Currency",
				insert_after="custom_additional_discount",
			),
		],
	}

	create_custom_fields(custom_fields, update=True)
	_clear_opportunity_stale_defaults()
	_setup_opportunity_property_setters()
	frappe.clear_cache(doctype="Opportunity")
	frappe.clear_cache(doctype="Opportunity Item")


def _cleanup_opportunity_from_property_setters():
	"""Remove bad overrides: opportunity_from is Link -> DocType; options must stay 'DocType'."""
	for prop in ("options", "default"):
		frappe.db.delete(
			"Property Setter",
			{
				"doc_type": "Opportunity",
				"field_name": "opportunity_from",
				"property": prop,
			},
		)


def _clear_opportunity_stale_defaults():
	"""Clear defaults that used to have wrong values."""
	frappe.db.set_value(
		"Custom Field",
		{"dt": "Opportunity", "fieldname": "custom_cash_discount"},
		"default",
		"0",
	)


def _setup_opportunity_property_setters():
	property_setters = [
		# Existing fields adjusted via property setter
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity",
			field_name="party_name",
			property="label",
			value="Customer",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity",
			field_name="party_name",
			property="reqd",
			value="1",
			property_type="Check",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity",
			field_name="job_title",
			property="hidden",
			value="1",
			property_type="Check",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity",
			field_name="items_section",
			property="insert_after",
			value="custom_details_tab",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity",
			field_name="more_info",
			property="insert_after",
			value="items",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity",
			field_name="transaction_date",
			property="label",
			value="Date",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity",
			field_name="customer_address",
			property="label",
			value="Shipping Address",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity",
			field_name="customer_address",
			property="hidden",
			value="0",
			property_type="Check",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity Item",
			field_name="item_code",
			property="label",
			value="SKU",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity Item",
			field_name="item_name",
			property="label",
			value="SKU Name",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity Item",
			field_name="item_name",
			property="in_list_view",
			value="1",
			property_type="Check",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity Item",
			field_name="qty",
			property="label",
			value="Quantity (Units)",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity Item",
			field_name="qty",
			property="precision",
			value="0",
			property_type="Select",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity Item",
			field_name="qty",
			property="non_negative",
			value="1",
			property_type="Check",
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


def _delete_obsolete_opportunity_custom_fields():
	"""Drop legacy fields that duplicated standard behaviour (safe if missing)."""
	obsolete = [
		("Opportunity Item", "custom_sku_with_name"),
	]
	for doctype, fieldname in obsolete:
		name = frappe.db.get_value("Custom Field", {"dt": doctype, "fieldname": fieldname}, "name")
		if name:
			frappe.db.delete("Custom Field", {"name": name})
