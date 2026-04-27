"""
Quotation customization for Alpinos.

- Existing Quotation/Quotation Item fields are updated via Property Setters.
- New fields are created via Custom Field.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def setup_quotation_custom_fields():
	_delete_obsolete_quotation_custom_fields()
	# Apply property setters before creating/updating custom fields, otherwise doctype
	# validation can fail (e.g. Quotation.order_type default still being ERPNext's "Sales").
	_setup_quotation_property_setters()

	custom_fields = {
		"Quotation": [
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
				mandatory_depends_on="eval:doc.custom_additional_units_damage",
			),
			dict(
				fieldname="custom_payment_section",
				label="Payment",
				fieldtype="Section Break",
				insert_after="custom_scheme_item_table",
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
				depends_on='eval:doc.custom_payment_mode=="Partial"',
				mandatory_depends_on='eval:doc.custom_payment_mode=="Partial"',
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
				fieldname="custom_boxes",
				label="Boxes",
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
				fieldname="custom_discount_type",
				label="Discount Type",
				fieldtype="Select",
				options="\nPercentage\nAmount",
				insert_after="custom_mrp",
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
				label="Additional Discount",
				fieldtype="Float",
				insert_after="custom_additional_discount_type",
			),
			dict(
				fieldname="custom_item_tax_percent",
				label="Tax %",
				fieldtype="Percent",
				insert_after="custom_additional_discount",
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
	frappe.clear_cache(doctype="Quotation")
	frappe.clear_cache(doctype="Quotation Item")


def _setup_quotation_property_setters():
	property_setters = [
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
			value="\nGT\nMT\nGYM & NUTRITION\nHoReCa",
			property_type="Text",
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
			field_name="custom_additional_discount_type",
			property="hidden",
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


def _ensure_quotation_partial_payment_fields_not_always_mandatory():
	"""mandatory_depends_on is client-side; server only sees Custom Field reqd — keep it 0."""
	for fieldname in ("custom_advance_amount", "custom_attachment_proof"):
		name = frappe.db.get_value("Custom Field", {"dt": "Quotation", "fieldname": fieldname}, "name")
		if not name:
			continue
		if frappe.db.get_value("Custom Field", name, "reqd"):
			frappe.db.set_value("Custom Field", name, "reqd", 0)


def _delete_obsolete_quotation_custom_fields():
	"""Drop legacy fields that duplicated standard behaviour (safe if missing)."""
	obsolete = [
		("Quotation", "custom_order_type"),
		("Quotation Item", "custom_sku_with_name"),
	]
	for doctype, fieldname in obsolete:
		name = frappe.db.get_value("Custom Field", {"dt": doctype, "fieldname": fieldname}, "name")
		if name:
			frappe.db.delete("Custom Field", {"name": name})
