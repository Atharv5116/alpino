"""Custom fields the BOM Master needs on top of ERPNext's own BOM.

Reused as-is rather than duplicated:

    FG Item          BOM.item          (+ read-only item_name)
    Is Default       BOM.is_default    ERPNext's manage_default_bom() already enforces
                                       one default per FG item on submit/cancel
    Base Batch Size  BOM.quantity      defaulted to 1 by the Production screen
    UOM              BOM.uom
    Is Active        BOM.is_active
    Item Code/Qty/
    UOM (grid)       BOM Item.item_code / qty / uom

What is genuinely missing is the recipe's own vocabulary: which stage of the process a
line belongs to, how it is classified for the Job Card, and the three SYREP machine
settings. All optional — a BOM written before these existed must still save.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from alpinos.production import constants as C

VARIATION_FIELD = "custom_bom_variation_name"
STAGE_FIELD = "custom_process_stage"
MATERIAL_TYPE_FIELD = "custom_material_type"


def _custom_fields():
	return {
		"BOM": [
			dict(
				# ERPNext autonames a BOM "BOM-<item>-###", which cannot tell two recipes
				# for the same finished good apart. This is the human label that does.
				fieldname=VARIATION_FIELD,
				label="BOM Variation Name",
				fieldtype="Data",
				insert_after="item_name",
				in_standard_filter=1,
				description='What makes this recipe different, e.g. "Standard", "Export Recipe", "Peanut-Free".',
			),
		],
		"BOM Item": [
			dict(
				fieldname=STAGE_FIELD,
				label="Process Stage",
				fieldtype="Select",
				options="\n" + C.select_options(C.BOM_PROCESS_STAGES),
				insert_after="item_code",
				in_list_view=1,
				columns=1,
				description="The Job Card print groups its rows by this.",
			),
			dict(
				fieldname=MATERIAL_TYPE_FIELD,
				label="Material Type",
				fieldtype="Select",
				options="\n" + C.select_options(C.BOM_MATERIAL_TYPES),
				insert_after=STAGE_FIELD,
				in_list_view=1,
				columns=1,
			),
			dict(
				fieldname="custom_syrep_section",
				label="Machine Settings",
				fieldtype="Section Break",
				insert_after="uom",
				collapsible=1,
				description="SYREP settings for this line. Free text, printed on the Job Card as written.",
			),
			dict(
				fieldname="custom_time",
				label="Time",
				fieldtype="Data",
				insert_after="custom_syrep_section",
			),
			dict(
				fieldname="custom_temp",
				label="Temp",
				fieldtype="Data",
				insert_after="custom_time",
			),
			dict(
				fieldname="custom_fan_speed",
				label="Fan Speed",
				fieldtype="Data",
				insert_after="custom_temp",
			),
		],
	}


def setup_bom_fields():
	create_custom_fields(_custom_fields(), ignore_validate=True, update=True)
	frappe.db.commit()


def execute():
	setup_bom_fields()
