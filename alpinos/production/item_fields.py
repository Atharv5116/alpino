"""Custom fields the Item Master needs that ERPNext does not already ship.

Deliberately short. Almost every field the Item Master spec asks for already exists on
Item and is reused as-is rather than duplicated:

    Item SKU Code      item_code            (a Property Setter already relabels it "SKU")
    Item Name          item_name
    Item Group         item_group
    Description        description
    Stock/Purchase/
    Sales UOM          stock_uom / purchase_uom / sales_uom
    Maintain Stock     is_stock_item
    Batch No Tracking  has_batch_no
    Expiry Tracking    has_expiry_date
    Shelf Life In Days shelf_life_in_days
    QC Required        inspection_required_before_purchase
    Lead Time Days     lead_time_days
    Disabled           disabled
    Default Warehouse  Item Default.default_warehouse   (child table `item_defaults`)
    Preferred Supplier Item Default.default_supplier    (child table `item_defaults`)

The last two live in the `item_defaults` child table because they are per-company in
ERPNext. The Item Master screen reads and writes them there rather than shadowing them
with a second copy on Item, which would give two answers to one question.

Every field below is optional on purpose — hundreds of items already exist and none of
them carry a Material Type yet, so making one mandatory would block every save of an
existing item until somebody had classified all of them.
"""

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from alpinos.production import constants as C

MATERIAL_TYPE_FIELD = "custom_material_type"
MATERIAL_CATEGORY_FIELD = "custom_material_category"
#: The Item's HSN is India Compliance's own field (a Link to "GST HSN Code"). The module's
#: former Data field "custom_hsn_code" is retired (retire_custom_hsn below); HSN_FIELD stays
#: as a name so existing imports keep working, and now simply IS the India Compliance field.
GST_HSN_FIELD = "gst_hsn_code"
HSN_FIELD = GST_HSN_FIELD
RETIRED_HSN_FIELD = "custom_hsn_code"
#: Retired. Kept only so the note below can name it and an old import does not break --
#: nothing creates or reads this field any more. The GST rate is LEGACY_GST_PERCENT_FIELD.
TAX_RATE_FIELD = "custom_tax_rate"
LOSS_PERCENT_FIELD = "custom_loss_percent"
TARGET_SKU_NAME_FIELD = "custom_target_sku_name"
ALLOWED_CATEGORIES_FIELD = "custom_allowed_filling_categories"

#: The GST rate, and the ONLY one. `custom_gst_percent` pre-dates this module and 135 items
#: already carry a real rate in it.
#:
#: TAX_RATE_FIELD above was added as a second, Data-typed place for the same number, and the
#: split promptly caused a bug: the screens read and wrote this one while the server
#: whitelisted the other, so a rate typed into the form was accepted, dropped, and came back
#: 0. One number, one field. TAX_RATE_FIELD is no longer created (see _custom_fields) and
#: nothing reads it; the existing column is left in place rather than dropped, because
#: deleting a custom field takes its data with it.
LEGACY_GST_PERCENT_FIELD = "custom_gst_percent"


def _custom_fields():
	return {
		"Item": [
			dict(
				fieldname="custom_production_section",
				label="Production Classification",
				fieldtype="Section Break",
				insert_after="item_group",
				collapsible=0,
			),
			dict(
				fieldname=MATERIAL_TYPE_FIELD,
				label="Material Type",
				fieldtype="Select",
				options="\n" + C.select_options(C.ITEM_MATERIAL_TYPES),
				insert_after="custom_production_section",
				# Retired: an item's type comes from its Item Group (see production/material_type.py).
				# Hidden, not deleted, so what it held stays; nothing reads or writes it.
				hidden=1,
				in_standard_filter=0,
				description="Retired. The type comes from the Item Group.",
			),
			dict(
				fieldname="custom_production_col_1",
				fieldtype="Column Break",
				insert_after=MATERIAL_TYPE_FIELD,
			),
			dict(
				# Separate from the existing custom_pack_type (Jar/Tub/Pouch/Other), which
				# describes the pack a FINISHED good is sold in. This one classifies a PM
				# item itself, and the two vocabularies are not the same list.
				fieldname=MATERIAL_CATEGORY_FIELD,
				label="Material Category",
				fieldtype="Select",
				options="\n" + C.select_options(C.PM_CATEGORIES),
				insert_after="custom_production_col_1",
				# Shown only for items filed under Packaging Material: the Item form script
				# (public/js/item_material_type.js) toggles it, and item_rules leaves it optional on
				# the server. No depends_on: the type is no longer a field on the form. An
				# empty string, not omitted, so the old expression is cleared on existing sites.
				depends_on="",
				mandatory_depends_on="",
				description="Packaging material only. Optional.",
			),
			# TAX_RATE_FIELD is deliberately NOT created any more -- see the note beside
			# LEGACY_GST_PERCENT_FIELD. The GST rate lives in custom_gst_percent, which the
			# screens, the list and the server now all agree on. An existing custom_tax_rate
			# column is left where it is; removing a custom field deletes its data.
			dict(
				# FRD 5.1.2.1. A Percent field, so 0-100 is the natural range and the
				# control shows the % sign; the bound itself is enforced in item_rules.
				fieldname=LOSS_PERCENT_FIELD,
				label="Loss %",
				fieldtype="Percent",
				insert_after=MATERIAL_CATEGORY_FIELD,
				description="Expected process loss for this item, as a percentage.",
			),
			# --- FRD 4.9 (Phase 8) 8.3: the SKU half of the filling handshake, on an
			# FG item only -- a raw material is never run on a filling line ----------
			dict(
				fieldname="custom_filling_section",
				label="Filling",
				fieldtype="Section Break",
				# Anchored on the GST % this module creates, not on the retired tax-rate field
				# (a fresh site never creates that one, and insert_after pointing at nothing
				# would drop this section at the bottom of the form).
				insert_after=LEGACY_GST_PERCENT_FIELD,
				collapsible=1,
				depends_on="",  # shown for Finished Goods by public/js/item_material_type.js
			),
			dict(
				fieldname=TARGET_SKU_NAME_FIELD,
				label="Target SKU Name",
				fieldtype="Data",
				insert_after="custom_filling_section",
				description="How this SKU is named on the filling line, e.g. 400g Chocolate Oats.",
				depends_on="",
			),
			dict(
				# Table MultiSelect, not a Select: 8.5 requires a new filling process to
				# need only a new row in the category master, so the allowed values can
				# never be a list baked into a field definition.
				fieldname=ALLOWED_CATEGORIES_FIELD,
				label="Allowed Filling Categories",
				fieldtype="Table MultiSelect",
				options="Item Filling Category",
				insert_after=TARGET_SKU_NAME_FIELD,
				description="Which filling lines may run this SKU. Empty means it has not been decided yet.",
				depends_on="",
			),
		]
	}


def retire_custom_hsn():
	"""Drop the module's own "HSN Code" Data field from Item; India Compliance's gst_hsn_code
	is the Item's HSN now.

	A value typed only in the old field is first carried into gst_hsn_code when that is blank
	and the code exists in India Compliance's HSN list; where both hold a code, India
	Compliance's wins. The database column is left in place (a Custom Field delete does not
	drop it), so nothing is lost at the SQL level.
	"""
	name = f"Item-{RETIRED_HSN_FIELD}"
	if not frappe.db.exists("Custom Field", name):
		return
	if frappe.db.has_column("Item", RETIRED_HSN_FIELD) and frappe.get_meta("Item").has_field(GST_HSN_FIELD) and frappe.db.exists("DocType", "GST HSN Code"):
		for row in frappe.db.sql(
			f"""select name, `{RETIRED_HSN_FIELD}` as old from `tabItem`
			where ifnull(`{RETIRED_HSN_FIELD}`, '') != '' and ifnull(`{GST_HSN_FIELD}`, '') = ''""",
			as_dict=True,
		):
			code = (row.old or "").replace(" ", "")
			if frappe.db.exists("GST HSN Code", code):
				frappe.db.set_value("Item", row.name, GST_HSN_FIELD, code, update_modified=False)
	frappe.delete_doc("Custom Field", name, force=True, ignore_permissions=True)
	frappe.clear_cache(doctype="Item")


def setup_item_fields():
	create_custom_fields(_custom_fields(), ignore_validate=True, update=True)
	retire_custom_hsn()
	# Packaging Material and Additive groups (Raw Material / Finished Goods exist already).
	from alpinos.production import material_type as MT

	MT.ensure_category_groups()
	frappe.db.commit()


def execute():
	setup_item_fields()
