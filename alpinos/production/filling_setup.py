"""Setup for Filling (FRD Phase 6/7) and Final QC (Phase 9). Registered after_migrate by
Groundwork as alpinos.production.filling_setup.setup_filling.

    * Batch custom fields: FG traceability (Sub PO, Parent PO, filling line, inward) and the
      FG status FG-Hold / FG-Cleared / QC-Rejected read by Inventory and Dispatch.
    * The "FG Label" print format on Batch (50 x 25 mm, Code128).

Naming (FPL- / FIN- / FQC- / PYR-) is the doctypes' own autoname, so there is no naming
series to append.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from alpinos.production import filling_common as F

FG_LABEL_PF = "FG Label"


def _batch_fields():
	fields = [
		{
			"fieldname": "custom_fg_section",
			"label": "Finished Goods Traceability",
			"fieldtype": "Section Break",
			"insert_after": "reference_name",
			"collapsible": 0,
		},
		{
			"fieldname": F.B_STATUS,
			"label": "FG Status",
			"fieldtype": "Select",
			# Blank first: every batch that is not a filled FG (RM, PM, purchase batches) keeps
			# no FG status and is not touched by the FG rules.
			"options": "\n" + "\n".join(F.FG_STATUSES),
			"insert_after": "custom_fg_section",
			"read_only": 1,
			"no_copy": 1,
			"in_standard_filter": 1,
			"in_list_view": 1,
		},
		{
			"fieldname": F.B_SUB,
			"label": "Sub Production Order",
			"fieldtype": "Link",
			"options": "Work Order",
			"insert_after": F.B_STATUS,
			"read_only": 1,
			"no_copy": 1,
			"in_standard_filter": 1,
		},
		{
			"fieldname": F.B_PARENT,
			"label": "Parent Production Order",
			"fieldtype": "Link",
			"options": "Production Order",
			"insert_after": F.B_SUB,
			"read_only": 1,
			"no_copy": 1,
			"in_standard_filter": 1,
		},
		{
			"fieldname": "custom_fg_col",
			"fieldtype": "Column Break",
			"insert_after": F.B_PARENT,
		},
		{
			"fieldname": F.B_LINE,
			"label": "Filling Line",
			"fieldtype": "Link",
			"options": "Machine",
			"insert_after": "custom_fg_col",
			"read_only": 1,
			"no_copy": 1,
		},
		{
			"fieldname": F.B_INWARD,
			"label": "Filling Inward",
			"fieldtype": "Link",
			"options": "Filling Inward",
			"insert_after": F.B_LINE,
			"read_only": 1,
			"no_copy": 1,
		},
		{
			"fieldname": F.B_BARCODE,
			"label": "FG Barcode",
			"fieldtype": "Long Text",
			"insert_after": F.B_INWARD,
			"read_only": 1,
			"hidden": 1,
			"no_copy": 1,
		},
	]
	if not frappe.db.exists("DocType", F.INWARD):
		fields = [x for x in fields if x["fieldname"] != F.B_INWARD]
		for x in fields:
			if x.get("insert_after") == F.B_INWARD:
				x["insert_after"] = F.B_LINE
	return {"Batch": fields}


# default pending BA confirmation: label stock 50 x 25 mm; copies come from ?copies=N
# (Filling Entry "Generate FG Labels" passes Today's Input pcs).
_FG_LABEL_HTML = """
<style>
	@page { size: 50mm 25mm; margin: 0; }
	.print-format { margin: 0 !important; padding: 0 !important; width: 50mm; }
	@media screen { .print-format { width: 50mm !important; padding: 0 !important; } }
	.fgl { width: 50mm; height: 25mm; box-sizing: border-box; padding: 1mm 1.5mm; overflow: hidden;
		font-family: Arial, Helvetica, sans-serif; page-break-after: always; }
	.fgl:last-child { page-break-after: auto; }
	.fgl-sku { font-size: 7pt; font-weight: 700; line-height: 1.1; white-space: nowrap; overflow: hidden;
		text-overflow: ellipsis; }
	.fgl-bar { height: 10mm; margin: 0.6mm 0 0.2mm; }
	.fgl-bar svg { width: 100%; height: 10mm; display: block; }
	.fgl-code { font-size: 7.5pt; font-weight: 700; letter-spacing: .3px; text-align: center; }
	.fgl-meta { font-size: 6pt; display: flex; justify-content: space-between; }
</style>
{%- set copies = frappe.utils.cint(frappe.form_dict.get("copies")) or 1 -%}
{%- set copies = 500 if copies > 500 else copies -%}
{%- set item = frappe.db.get_value("Item", doc.item, ["item_name"], as_dict=True) or {} -%}
{%- set sku = frappe.db.get_value("Item", doc.item, "custom_target_sku_name") if frappe.get_meta("Item").has_field("custom_target_sku_name") else None -%}
{%- for i in range(copies) %}
<div class="fgl">
	<div class="fgl-sku">{{ sku or item.item_name or doc.item }}</div>
	<div class="fgl-bar">{{ (doc.get("custom_fg_barcode_svg") or "") | safe }}</div>
	<div class="fgl-code">{{ doc.name }}</div>
	<div class="fgl-meta">
		<span>MFG: {{ frappe.utils.formatdate(doc.manufacturing_date) if doc.manufacturing_date else "" }}</span>
		<span>{{ ("EXP: " ~ frappe.utils.formatdate(doc.expiry_date)) if doc.expiry_date else "" }}</span>
	</div>
</div>
{%- endfor %}
"""


def setup_fg_label_print_format():
	from alpinos.purchase.print_formats import _upsert_print_format
	_upsert_print_format(FG_LABEL_PF, "Batch", _FG_LABEL_HTML, page_size=None)


def setup_filling():
	create_custom_fields(_batch_fields(), ignore_validate=True)
	frappe.clear_cache(doctype="Batch")
	try:
		setup_fg_label_print_format()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Filling setup: FG Label print format")
	frappe.db.commit()


def execute():
	setup_filling()
