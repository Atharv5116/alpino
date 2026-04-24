"""
Custom Fields for Sales Order and Customer DocTypes
Adds fields as per Sales Order requirements:
- Order Type (auto from Customer), Cash Discount
- Item table: Box, MRP, Flat Discount, Offer, Additional Discount, Tax
- Relabel Item Code → SKU
- Customer: Item MRP table, Order Type
- Other Details: Marketing Freebies, Scheme Items, Additional Units - Damage
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def setup_sales_order_custom_fields():
	"""Create all custom fields for Sales Order customization"""

	custom_fields = {
		# ============================================================
		# CUSTOMER: Add Order Type + Item MRP table
		# ============================================================
		"Customer": [
			dict(
				fieldname="custom_order_type",
				label="Order Type",
				fieldtype="Select",
				options="\nGT\nMT\nGYM & NUTRITION\nHoReCa",
				insert_after="customer_group",
				description="Auto-fetched into Sales Order",
			),
			dict(
				fieldname="custom_item_mrp_section",
				label="Item MRP",
				fieldtype="Section Break",
				insert_after="companies",
				collapsible=1,
			),
			dict(
				fieldname="custom_item_mrp",
				label="Item MRP",
				fieldtype="Table",
				options="Customer Item MRP",
				insert_after="custom_item_mrp_section",
				description="Customer-specific MRP for items. This will be auto-fetched into Sales Order.",
			),
		],

		# ============================================================
		# SALES ORDER: Main form fields
		# ============================================================
		"Sales Order": [
			# Order Type (already exists as standard field, we override its options via Property Setter)
			# Cash Discount in totals section
			# Cash Discount section (visible in Totals area)
			dict(
				fieldname="custom_cash_discount_section",
				label="Cash Discount",
				fieldtype="Section Break",
				insert_after="grand_total",
			),
			dict(
				fieldname="custom_cash_discount",
				label="Cash Discount (%)",
				fieldtype="Percent",
				insert_after="custom_cash_discount_section",
				default="0",
				description="Cash discount percentage applied on the order",
			),
			dict(
				fieldname="custom_cash_discount_col",
				fieldtype="Column Break",
				insert_after="custom_cash_discount",
			),
			dict(
				fieldname="custom_cash_discount_amount",
				label="Cash Discount Amount",
				fieldtype="Currency",
				insert_after="custom_cash_discount_col",
				read_only=1,
				description="Auto-calculated cash discount amount",
			),

			# Other Details Section (after packing_list on Details tab)
			dict(
				fieldname="custom_other_details_section",
				label="Other Details",
				fieldtype="Section Break",
				insert_after="packing_list",
				collapsible=0,
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
				label="Scheme Items",
				fieldtype="Table",
				options="Sales Order Scheme Item",
				insert_after="custom_additional_units_damage",
				depends_on="eval:doc.custom_additional_units_damage",
				mandatory_depends_on="eval:doc.custom_additional_units_damage",
			),
		],

		# ============================================================
		# SALES ORDER ITEM: Additional fields
		# ============================================================
		"Sales Order Item": [
			dict(
				fieldname="custom_product_image",
				label="Product Image",
				fieldtype="Attach Image",
				insert_after="idx",
				fetch_from="item_code.image",
				read_only=1,
			),
			# Box field (after qty)
			dict(
				fieldname="custom_box",
				label="Box",
				fieldtype="Float",
				insert_after="qty",
				description="Number of boxes. Auto-calculated from Qty using Item UOM conversion.",
			),
			# Customer MRP (after price_list_rate)
			dict(
				fieldname="custom_customer_mrp",
				label="MRP",
				fieldtype="Currency",
				insert_after="price_list_rate",
				description="MRP from Customer master. Editable.",
			),
			# Flat Discount % (after discount_amount)
			dict(
				fieldname="custom_flat_discount",
				label="Flat Discount %",
				fieldtype="Percent",
				insert_after="discount_amount",
				description="Flat discount percentage. If set, rate is calculated as MRP - (MRP * Flat Discount % / 100).",
			),
			# Offer
			dict(
				fieldname="custom_offer",
				label="Offer",
				fieldtype="Data",
				insert_after="custom_flat_discount",
			),
			# Additional Discount
			dict(
				fieldname="custom_additional_discount",
				label="Additional Discount",
				fieldtype="Currency",
				insert_after="custom_offer",
			),
			# Tax
			dict(
				fieldname="custom_item_tax",
				label="Tax",
				fieldtype="Currency",
				insert_after="custom_additional_discount",
				description="Auto-calculated or editable tax amount per item.",
			),
		],
	}

	create_custom_fields(custom_fields, update=True)
	print("✅ Sales Order custom fields created")

	# Set Property Setters for label changes and Order Type options
	_setup_property_setters()

	print("✅ Sales Order setup complete")


def _setup_property_setters():
	"""Set property setters for label overrides and field options"""

	property_setters = [
		# Relabel Item Code → SKU in Sales Order Item
		{
			"doctype_or_field": "DocField",
			"doc_type": "Sales Order Item",
			"field_name": "item_code",
			"property": "label",
			"value": "SKU",
			"property_type": "Data",
		},
		# Relabel item_name → SKU No.
		{
			"doctype_or_field": "DocField",
			"doc_type": "Sales Order Item",
			"field_name": "item_name",
			"property": "label",
			"value": "SKU Name",
			"property_type": "Data",
		},
		# Show item table as "Order Items" in Sales Order form
		{
			"doctype_or_field": "DocField",
			"doc_type": "Sales Order",
			"field_name": "items",
			"property": "label",
			"value": "Order Items",
			"property_type": "Data",
		},
		# Rename order_type label to Customer Type
		{
			"doctype_or_field": "DocField",
			"doc_type": "Sales Order",
			"field_name": "order_type",
			"property": "label",
			"value": "Customer Type",
			"property_type": "Data",
		},
		# Update Sales Order order_type options
		{
			"doctype_or_field": "DocField",
			"doc_type": "Sales Order",
			"field_name": "order_type",
			"property": "options",
			"value": "\nGT\nMT\nGYM & NUTRITION\nHoReCa",
			"property_type": "Text",
		},
		# Make order_type mandatory
		{
			"doctype_or_field": "DocField",
			"doc_type": "Sales Order",
			"field_name": "order_type",
			"property": "reqd",
			"value": "1",
			"property_type": "Check",
		},
		# Remove ERPNext default "Sales" because options are overridden.
		{
			"doctype_or_field": "DocField",
			"doc_type": "Sales Order",
			"field_name": "order_type",
			"property": "default",
			"value": "",
			"property_type": "Text",
		},
		# Hide Company on standard Sales Order form.
		{
			"doctype_or_field": "DocField",
			"doc_type": "Sales Order",
			"field_name": "company",
			"property": "hidden",
			"value": "1",
			"property_type": "Check",
		},
		# Hide Total Quantity on standard Sales Order form.
		{
			"doctype_or_field": "DocField",
			"doc_type": "Sales Order",
			"field_name": "total_qty",
			"property": "hidden",
			"value": "1",
			"property_type": "Check",
		},
		# Hide custom tax column in Sales Order Item form grid.
		{
			"doctype_or_field": "DocField",
			"doc_type": "Sales Order Item",
			"field_name": "custom_item_tax",
			"property": "hidden",
			"value": "1",
			"property_type": "Check",
		},
		# Make item_name (SKU No.) visible in grid
		{
			"doctype_or_field": "DocField",
			"doc_type": "Sales Order Item",
			"field_name": "item_name",
			"property": "in_list_view",
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
			}
		)

		if existing:
			ps = frappe.get_doc("Property Setter", existing)
			ps.value = ps_data["value"]
			ps.save(ignore_permissions=True)
		else:
			ps = frappe.get_doc({
				"doctype": "Property Setter",
				**ps_data,
			})
			ps.insert(ignore_permissions=True)

	frappe.db.commit()
	print("✅ Property setters applied (SKU labels, Order Type options)")
