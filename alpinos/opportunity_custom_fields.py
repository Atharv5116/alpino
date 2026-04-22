"""
Opportunity customization for Alpinos.

Rules followed:
- Existing Opportunity/Opportunity Item fields are updated via Property Setters.
- New fields are created via Custom Field.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


SKU_OPTIONS = """NT-CR-1000 - Peanut Butter Natural Crunch 1 KG
NT-CR-400 - Peanut Butter Natural Crunch 400 GM
NT-SM-1000 - Peanut Butter Natural Smooth 1 KG
NT-SM-400 - Peanut Butter Natural Smooth 400 GM
CL-CR-1000 - Peanut Butter Classic+ Crunch 1 KG
CL-CR-400 - Peanut Butter Classic+ Crunch 400 GM
CH-CR-1000 - Peanut Butter Chocolate Crunch 1 KG
CH-CR-400 - Peanut Butter Chocolate Crunch 400 GM
CH-SM-1000 - Peanut Butter Chocolate Smooth 1 KG
CH-SM-400 - Peanut Butter Chocolate Smooth 400 GM
SP-CH-1000 - Peanut Butter Chocolate Super Crunch 1 KG
DC-CR-1000 - Peanut Butter High Protein Dark Chocolate Crunch 1 KG
DC-CP-1000 - Peanut Butter High Protein Dark Chocolate Crisp 1 KG
DC-CR-500 - Peanut Butter High Protein Dark Chocolate Crunch 500 GM
PC-HO-200 - Peanut Crackers Chipotle Honey 200 GM
PC-BB-200 - Peanut Crackers BBQ 200 GM
PC-HO-60 - Peanut Crackers Chipotle Honey 60 GM
PC-BB-60 - Peanut Crackers BBQ 60 GM
SB-CC-40 - Super Bar Cookies & Cream 40 GM
SB-CH-40 - Super Bar Chocolate 40 GM
SB-CF-40 - Super Bar Coffee 40 GM
SM-BC-400 - Super Muesli Berry Crunch 400 GM
DM-NB-400 - Diet Muesli Nuts & Berries 400 GM
MM-ND-400 - Millet Muesli Nuts Delight 400 GM
HM-DC-400 - High Protein Muesli Dark Chocolate 400 GM
HM-CF-400 - High Protein Muesli Cold Coffee 400 GM
HM-DC-2000 - High Protein Muesli Dark Chocolate 2 KG
SM-ST-1000 - Super Muesli Strawberry & Nuts 1 KG
MFN 750 - MUESLI FRUIT & NUT 750
MND 750 - MUESLI NUT DELIGHT 750
MCH 750 - MUESLI CHOCOLATE 750
MFN400 - MUESLI FRUIT & NUT 400
MND400 - MUESLI NUT DELIGHT 400
MCH400 - MUESLI CHOCOLATE 400
MCF400 - MUESLI COFFEE 400
MO-HM-400 - Masala Oats Hot Mexicana 400 GM
MO-KF-400 - Masala Oats Korean Fire 400 GM
MO-IM-400 - Masala Oats Indian Masala 400 GM
SO-US-1000 - Super Oats Unsweetened 1 KG
SO-CH-2500 - Super Oats Chocolate 2.5 KG
SO-CH-1000 - Super Oats Chocolate 1 KG
SO-CH-400 - Super Oats Chocolate 400 GM
SO-HO-400 - Super Oats Honey 400 GM
SO-CF-2000 - Super Oats Classic Coffee 2 KG
SO-CF-1000 - Super Oats Classic Coffee 1 KG
SO-CF-400 - Super Oats Classic Coffee 400 GM
HO-DC-2000 - High Protein Oats Dark Chocolate 2 KG
HO-DC-1000 - High Protein Oats Dark Chocolate 1 KG
HO-DC-400 - High Protein Oats Dark Chocolate 400 GM
CF-CH-750 - Corn Flakes Chocolate 750 GM
AS-PW-220 - Supernatural Peanut Protein (Pack of 6) 220 GM
SP-DC-1000 - Supernatural Peanut Protein Dark Chocolate 1 KG
SP-DC-36 - Supernatural Peanut Protein Dark Chocolate 36 GM
SP-CF-1000 - Supernatural Peanut Protein Cold Coffee 1 KG
SP-CF-37 - Supernatural Peanut Protein Cold Coffee 37 GM
SP-TF-1000 - Supernatural Peanut Protein Thandai Fusion 1 KG
SP-TF-37 - Supernatural Peanut Protein Thandai Fusion 37 GM
SP-KM-1000 - Supernatural Peanut Protein Kesar Mango 1 KG
SP-KM-37 - Supernatural Peanut Protein Kesar Mango 37 GM
AC-VI-500 - Organic Apple Cider Vinegar 500 ML
SV-AB-60 - Active B-Complex 60 Tablets
SV-MV-60 - Daily Multivitamin 60 Tablets
SV-DK-60 - Vitamin D3+K2 60 Tablets
SV-MZ-60 - Magnesium Bisglycinate + Zinc 60 Tablets
SV-OD-60 - Omega 3 Fish Oil + D3 60 Softgels
SV-TO-60 - Triple Strength Omega 3 60 Softgels
CM-LE-300 - Nano Particle Creatine Monohydrate Lemonade 300 GM
CM-UF-300 - Nano Particle Creatine Monohydrate Unflavoured 300 GM
DN-MB-360 - Daily Complete Nutrition+ Mix Berries 360 GM
DN-MB-12 - Daily Complete Nutrition+ Mix Berries 12 GM"""


def setup_opportunity_custom_fields():
	custom_fields = {
		"Opportunity": [
			dict(
				fieldname="custom_order_type",
				label="Order Type",
				fieldtype="Select",
				options="\nGT\nMT\nGYM & NUTRITION\nHoReCa",
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
				default="0.5",
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
				fieldname="custom_sku_with_name",
				label="SKU with Name",
				fieldtype="Select",
				options=SKU_OPTIONS,
				insert_after="item_code",
				reqd=1,
				in_list_view=1,
			),
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
				fieldname="custom_flat_discount",
				label="Flat Discount %",
				fieldtype="Percent",
				insert_after="custom_mrp",
			),
			dict(
				fieldname="custom_offer",
				label="Offer",
				fieldtype="Data",
				insert_after="custom_flat_discount",
			),
			dict(
				fieldname="custom_additional_discount",
				label="Additional Discount",
				fieldtype="Currency",
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
	_setup_opportunity_property_setters()
	frappe.clear_cache(doctype="Opportunity")
	frappe.clear_cache(doctype="Opportunity Item")


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
			field_name="qty",
			property="label",
			value="Quantity (Units)",
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
