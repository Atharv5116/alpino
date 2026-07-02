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
				fieldname="custom_tally_item_name",
				label="Tally Item Name",
				fieldtype="Data",
				insert_after="custom_sku_no",
			),
			# Accounts/Tally billing export fields
			dict(
				fieldname="custom_tally_sku",
				label="Tally SKU",
				fieldtype="Data",
				insert_after="custom_tally_item_name",
				description="SKU code as per Tally; used in the Accounts Format (billing export) report.",
			),
			dict(
				fieldname="custom_ean_no",
				label="EAN No.",
				fieldtype="Data",
				insert_after="custom_tally_sku",
				description="EAN barcode. Used for Amazon billing exports.",
			),
			dict(
				fieldname="custom_fsn_no",
				label="FSN No.",
				fieldtype="Data",
				insert_after="custom_ean_no",
				description="Flipkart FSN. Used for Flipkart billing exports.",
			),
			dict(
				fieldname="custom_is_billable",
				label="Is Billable",
				fieldtype="Check",
				insert_after="custom_is_freebie",
				default="1",
				description="Whether this item is billable (shown as Yes/No in the Accounts Format report).",
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
				default="0",
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
				default="0",
			),
			dict(
				fieldname="custom_gross_weight",
				label="Gross Weight (per Box)",
				fieldtype="Float",
				insert_after="weight_uom",
				description="Used by Pick List as Std Weight / Box and for gross weight totals.",
			),
			# --- Product Bundle ---
			# Anchored in the Details tab (after `description`), NOT the Inventory tab —
			# a bundle is forced non-stock, which hides the Inventory tab, so the section
			# must live outside it or it would vanish the moment Is Bundle is ticked.
			dict(
				fieldname="custom_product_bundle_section",
				label="Product Bundle",
				fieldtype="Section Break",
				insert_after="description",
				collapsible=1,
			),
			dict(
				fieldname="custom_is_bundle",
				label="Is Bundle",
				fieldtype="Check",
				insert_after="custom_product_bundle_section",
				default="0",
				description="This SKU is a bundle/combo. On save it is automatically set as a non-stock item (ERPNext requires bundles to be non-stock), so the Inventory tab is hidden — stock moves on the component items in Product Mapping below, not on this SKU. Batches, expiry, Box UOM etc. live on those component items.",
			),
			dict(
				fieldname="custom_product_mapping",
				label="Product Mapping",
				fieldtype="Table",
				options="Product Bundle Mapping",
				insert_after="custom_is_bundle",
				depends_on="eval:doc.custom_is_bundle",
			),
			# --- Allowed Customer Types (new tab) ---
			# Channel-grouped selection of which Alpino Customer Types may use this item.
			# Empty selection = available to ALL customer types (default). The grouped
			# checkbox widget is rendered into the HTML field by the Item client script.
			dict(
				fieldname="custom_customer_access_tab",
				label="Allowed Customer Types",
				fieldtype="Tab Break",
				insert_after="custom_product_mapping",
			),
			dict(
				fieldname="custom_customer_access_html",
				label="Customer Type Access",
				fieldtype="HTML",
				insert_after="custom_customer_access_tab",
			),
			dict(
				fieldname="custom_allowed_channels",
				label="Allowed Channels",
				fieldtype="Table",
				options="Item Allowed Channel",
				insert_after="custom_customer_access_html",
				hidden=1,
			),
			dict(
				fieldname="custom_allowed_customer_types",
				label="Allowed Customer Types",
				fieldtype="Table",
				options="Item Allowed Customer Type",
				insert_after="custom_allowed_channels",
				hidden=1,
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
		# Valuation Rate is the default price the Sales Order falls back to (when the buyer
		# has no Offline Buyer catalogue MRP). ERPNext hides it for non-stock items, but a
		# bundle is forced non-stock — so show it for bundles too, giving them a default price.
		dict(
			doctype_or_field="DocField",
			doc_type="Item",
			field_name="valuation_rate",
			property="depends_on",
			value="eval:doc.is_stock_item || doc.custom_is_bundle",
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
		dict(
			doctype_or_field="DocField",
			doc_type="Item",
			field_name="shelf_life_in_days",
			property="hidden",
			value="0",
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
