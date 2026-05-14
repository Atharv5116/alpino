"""
Opportunity customization for Alpinos.

Rules followed:
- Existing Opportunity/Opportunity Item fields are updated via Property Setters.
- New fields are created via Custom Field.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def setup_opportunity_custom_fields():
	_force_opportunity_fieldtype_sync()
	_delete_obsolete_opportunity_custom_fields()
	_cleanup_opportunity_from_property_setters()

	custom_fields = {
		"Opportunity": [
			dict(
				fieldname="custom_order_type",
				label="Customer Type",
				fieldtype="Link",
				options="Offline Buyer Customer Type",
				insert_after="party_name",
				reqd=1,
			),
		dict(
			fieldname="custom_billing_address",
			label="Billing Address",
			fieldtype="Link",
			options="Address",
			insert_after="custom_order_type",
			depends_on="eval:doc.opportunity_from === 'Offline Buyer Master'",
		),
		dict(
			fieldname="custom_other_details_section",
			label="Other Details",
			fieldtype="Section Break",
			insert_after="items",
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
			fieldname="custom_scheme_item_table",
			label="Scheme Item Table",
			fieldtype="Table",
			options="Sales Order Scheme Item",
			insert_after="custom_marketing_freebies",
			depends_on=None,
			mandatory_depends_on=None,
		),
		dict(
			fieldname="custom_additional_units_damage",
			label="Additional Units - Damage",
			fieldtype="Check",
			insert_after="custom_scheme_item_table",
		),
		dict(
			fieldname="custom_additional_units_damage_items",
			label="Additional Units - Damage Items",
			fieldtype="Table",
			options="Sales Order Additional Units Item",
			insert_after="custom_additional_units_damage",
			depends_on="eval:doc.custom_additional_units_damage",
			mandatory_depends_on="eval:doc.custom_additional_units_damage",
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
		# Move Shipping Address to header (before items tab) - visible only for OBM
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity",
			field_name="customer_address",
			property="insert_after",
			value="custom_billing_address",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity",
			field_name="customer_address",
			property="depends_on",
			value="eval:doc.opportunity_from === 'Offline Buyer Master'",
			property_type="Data",
		),
		# Remove the more_info Property Setter override - let it stay in its default position
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity",
			field_name="more_info",
			property="insert_after",
			value="items",
			property_type="Data",
		),
		# Hide the empty 'Details' tab when OBM is selected
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity",
			field_name="custom_details_tab",
			property="depends_on",
			value="eval:doc.opportunity_from !== 'Offline Buyer Master'",
			property_type="Data",
		),
		# Hide the 'Contacts' tab when OBM is selected
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity",
			field_name="contact_info",
			property="depends_on",
			value="eval:doc.opportunity_from !== 'Offline Buyer Master'",
			property_type="Data",
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
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity",
			field_name="naming_series",
			property="options",
			value="OPP-2627-.#####",
			property_type="Text",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity",
			field_name="naming_series",
			property="default",
			value="OPP-2627-.#####",
			property_type="Text",
		),
		dict(
			doctype_or_field="DocType",
			doc_type="Opportunity",
			property="default_print_format",
			value="Final Opportunity",
			property_type="Text",
		),
	]

	for ps_data in property_setters:
		existing = frappe.db.exists(
			"Property Setter",
			{
				"doc_type": ps_data["doc_type"],
				"field_name": ps_data.get("field_name"),
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
	frappe.db.commit()
	print("✅ Opportunity: obsolete fields deleted")


def _force_opportunity_fieldtype_sync():
	"""Manually sync field types in the database for Opportunity to bypass Frappe validation errors."""
	# Custom field custom_order_type on Opportunity
	cf_name = frappe.db.get_value("Custom Field", {"dt": "Opportunity", "fieldname": "custom_order_type"}, "name")
	if cf_name:
		frappe.db.set_value("Custom Field", cf_name, {
			"fieldtype": "Link",
			"options": "Offline Buyer Customer Type"
		}, update_modified=False)
	frappe.db.commit()

