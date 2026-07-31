"""
Quotation customization for Alpinos.

- Existing Quotation/Quotation Item fields are updated via Property Setters.
- New fields are created via Custom Field.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def setup_quotation_custom_fields():
	_force_quotation_fieldtype_sync()
	_delete_obsolete_quotation_custom_fields()
	# Apply property setters before creating/updating custom fields, otherwise doctype
	# validation can fail (e.g. Quotation.order_type default still being ERPNext's "Sales").
	_setup_quotation_property_setters()

	custom_fields = {
		"Quotation": [
			dict(
				fieldname="custom_resolved_customer",
				label="Resolved Customer",
				fieldtype="Link",
				options="Customer",
				insert_after="party_name",
				hidden=1,
				read_only=1,
			),
			dict(
				fieldname="custom_order_no",
				label="Order No.",
				fieldtype="Data",
				insert_after="order_type",
				read_only=1,
				fetch_from="name",
			),
			dict(
				fieldname="custom_other_details_section",
				label="Other Details",
				fieldtype="Section Break",
				insert_after="items",
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
				fieldname="custom_payment_section",
				label="Payment",
				fieldtype="Section Break",
				insert_after="custom_additional_units_damage_items",
			),
			dict(
				fieldname="custom_payment_mode",
				label="Payment Mode",
				fieldtype="Select",
				options="\nAdvance\nDebit\nPartial",
				insert_after="custom_payment_section",
				reqd=1,
			),
			dict(
				fieldname="custom_advance_amount",
				label="Advance Amount",
				fieldtype="Currency",
				insert_after="custom_payment_mode",
				reqd=0,
				depends_on='eval:doc.custom_payment_mode=="Partial"',
				mandatory_depends_on='eval:doc.custom_payment_mode=="Partial"',
			),
			dict(
				fieldname="custom_attachment_proof",
				label="Attachment (Proof)",
				fieldtype="Attach",
				insert_after="custom_advance_amount",
				reqd=0,
				depends_on='eval:doc.custom_payment_mode=="Advance" || doc.custom_payment_mode=="Partial"',
				mandatory_depends_on='eval:doc.custom_payment_mode=="Advance" || doc.custom_payment_mode=="Partial"',
			),
			dict(
				fieldname="custom_transaction_id",
				label="Transaction ID",
				fieldtype="Data",
				insert_after="custom_attachment_proof",
			),
			dict(
				fieldname="custom_expected_payment_date",
				label="Expected Payment Date",
				fieldtype="Date",
				insert_after="custom_transaction_id",
				reqd=1,
			),
			dict(
				fieldname="custom_remaining_amount",
				label="Remaining Amount",
				fieldtype="Currency",
				insert_after="custom_expected_payment_date",
				read_only=1,
			),
			dict(
				fieldname="custom_total_section",
				label="Total",
				fieldtype="Section Break",
				insert_after="custom_remaining_amount",
			),
			dict(
				fieldname="custom_cash_discount",
				label="Cash Discount %",
				fieldtype="Percent",
				insert_after="custom_total_section",
				default="0",
			),
			dict(
				fieldname="custom_sub_total",
				label="Sub Total",
				fieldtype="Currency",
				insert_after="custom_cash_discount",
				read_only=1,
			),
			dict(
				fieldname="custom_over_discount",
				label="Over Discount",
				fieldtype="Currency",
				insert_after="custom_sub_total",
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
			dict(
				fieldname="custom_total_payable",
				label="Total",
				fieldtype="Currency",
				insert_after="custom_gst_total",
				read_only=1,
			),
		],
		"Quotation Item": [
			dict(
				fieldname="custom_remarks",
				label="Remarks",
				fieldtype="Data",
				insert_after="qty",
				description="Mandatory when this quotation qty is less than the Opportunity qty.",
			),
			dict(
				fieldname="custom_boxes",
				label="Box",
				fieldtype="Int",
				insert_after="qty",
				reqd=1,
			),
			dict(
				fieldname="custom_mrp",
				label="MRP",
				fieldtype="Currency",
				insert_after="rate",
				reqd=1,
			),
			dict(
				fieldname="custom_buyer_margin_percent",
				label="Buyer Margin %",
				fieldtype="Percent",
				insert_after="custom_mrp",
				description="Buyer margin applied before Flat / Offer / Additional Discount (same logic as Opportunity).",
			),
		dict(
			fieldname="custom_discount_type",
			label="Discount Type",
			fieldtype="Select",
			options="\nPercentage\nAmount",
			insert_after="custom_buyer_margin_percent",
			default="Percentage",
			reqd=1,
		),
			dict(
				fieldname="custom_flat_discount",
				label="Flat Discount",
				fieldtype="Float",
				insert_after="custom_discount_type",
				reqd=1,
			),
			dict(
				fieldname="custom_offer",
				label="Offer %",
				fieldtype="Float",
				insert_after="custom_flat_discount",
			),
			dict(
				fieldname="custom_additional_discount_type",
				label="Additional Discount Type",
				fieldtype="Select",
				options="\nPercentage\nAmount",
				insert_after="custom_offer",
				default="Percentage",
				reqd=1,
			),
			dict(
				fieldname="custom_additional_discount",
				label="Additional Discount %",
				fieldtype="Percent",
				insert_after="custom_additional_discount_type",
			),
			dict(
				fieldname="custom_item_tax_percent",
				label="Tax %",
				fieldtype="Percent",
				insert_after="custom_additional_discount",
				fetch_from="item_code.custom_gst_percent",
				reqd=1,
			),
			dict(
				fieldname="custom_item_tax",
				label="Tax",
				fieldtype="Currency",
				insert_after="custom_item_tax_percent",
				read_only=1,
			),
		],
	}

	create_custom_fields(custom_fields, update=True)
	_ensure_quotation_partial_payment_fields_not_always_mandatory()
	_fix_quotation_table_layout()
	frappe.clear_cache(doctype="Quotation")
	frappe.clear_cache(doctype="Quotation Item")


def _setup_quotation_property_setters():
	property_setters = [
		dict(
			doctype_or_field="DocField",
			doc_type="Quotation",
			field_name="items",
			property="label",
			value="Order Items",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Quotation",
			field_name="order_type",
			property="label",
			value="Customer Type",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Quotation",
			field_name="party_name",
			property="label",
			value="Customer",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Quotation",
			field_name="customer_address",
			property="label",
			value="Shipping Address",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Quotation",
			field_name="order_type",
			property="options",
			value="Alpino Customer Type",
			property_type="Text",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Quotation",
			field_name="order_type",
			property="fieldtype",
			value="Link",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Quotation",
			field_name="order_type",
			property="reqd",
			value="1",
			property_type="Check",
		),
		# Clear ERPNext's default ("Sales") because it won't exist after we override options.
		dict(
			doctype_or_field="DocField",
			doc_type="Quotation",
			field_name="order_type",
			property="default",
			value="",
			property_type="Text",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Quotation Item",
			field_name="item_code",
			property="label",
			value="SKU",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Quotation Item",
			field_name="item_name",
			property="label",
			value="SKU Name",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Quotation Item",
			field_name="item_name",
			property="in_list_view",
			value="1",
			property_type="Check",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Quotation Item",
			field_name="qty",
			property="label",
			value="Quantity (Units)",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Quotation Item",
			field_name="qty",
			property="precision",
			value="0",
			property_type="Select",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Quotation Item",
			field_name="qty",
			property="non_negative",
			value="1",
			property_type="Check",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Quotation Item",
			field_name="custom_additional_discount_type",
			property="hidden",
			value="1",
			property_type="Check",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Quotation",
			field_name="naming_series",
			property="options",
			value="QTN-2627-.#####",
			property_type="Text",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Quotation",
			field_name="naming_series",
			property="default",
			value="QTN-2627-.#####",
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


def _ensure_quotation_partial_payment_fields_not_always_mandatory():
	"""mandatory_depends_on is client-side; server only sees Custom Field reqd — keep it 0."""
	for fieldname in ("custom_advance_amount", "custom_attachment_proof"):
		name = frappe.db.get_value("Custom Field", {"dt": "Quotation", "fieldname": fieldname}, "name")
		if not name:
			continue
		if frappe.db.get_value("Custom Field", name, "reqd"):
			frappe.db.set_value("Custom Field", name, "reqd", 0)


def _fix_quotation_table_layout():
	"""Force existing Custom Field rows into the Sales Order Entry sequence."""

	updates = {
		"custom_marketing_freebies": {
			"insert_after": "custom_other_details_section",
			"depends_on": None,
			"mandatory_depends_on": None,
		},
		"custom_scheme_item_table": {
			"insert_after": "custom_marketing_freebies",
			"depends_on": None,
			"mandatory_depends_on": None,
			"options": "Sales Order Scheme Item",
		},
		"custom_additional_units_damage": {
			"insert_after": "custom_scheme_item_table",
			"depends_on": None,
			"mandatory_depends_on": None,
		},
		"custom_additional_units_damage_items": {
			"insert_after": "custom_additional_units_damage",
			"depends_on": "eval:doc.custom_additional_units_damage",
			"mandatory_depends_on": "eval:doc.custom_additional_units_damage",
			"options": "Sales Order Additional Units Item",
		},
		"custom_payment_section": {
			"insert_after": "custom_additional_units_damage_items",
			"depends_on": None,
			"mandatory_depends_on": None,
		},
	}

	for fieldname, values in updates.items():
		name = frappe.db.get_value("Custom Field", {"dt": "Quotation", "fieldname": fieldname}, "name")
		if not name:
			continue
		for key, value in values.items():
			frappe.db.set_value("Custom Field", name, key, value)
	frappe.db.commit()


def _delete_obsolete_quotation_custom_fields():
	"""Drop legacy fields that duplicated standard behaviour (safe if missing)."""
	obsolete = [
		("Quotation", "custom_order_type"),
		("Quotation Item", "custom_sku_with_name"),
		("Quotation Item", "custom_item_mrp"),
	]
	for doctype, fieldname in obsolete:
		name = frappe.db.get_value("Custom Field", {"dt": doctype, "fieldname": fieldname}, "name")
		if name:
			frappe.delete_doc("Custom Field", name, force=1, ignore_permissions=True)
	frappe.db.commit()
	print("✅ Quotation: obsolete fields deleted")


def _force_quotation_fieldtype_sync():
	"""Manually sync field types in the database for Quotation to bypass Frappe validation errors."""
	# Standard field order_type on Quotation (via Property Setter)
	ps_name = frappe.db.get_value("Property Setter", {
		"doc_type": "Quotation",
		"field_name": "order_type",
		"property": "fieldtype"
	}, "name")
	if ps_name:
		frappe.db.set_value("Property Setter", ps_name, "value", "Link", update_modified=False)

	ps_opts = frappe.db.get_value("Property Setter", {
		"doc_type": "Quotation",
		"field_name": "order_type",
		"property": "options"
	}, "name")
	if ps_opts:
		frappe.db.set_value("Property Setter", ps_opts, "value", "Alpino Customer Type", update_modified=False)

	frappe.db.commit()

