"""The Job Card print format on BOM (FRD pages 5, 6 and 10).

Three things the FRD asks for, and where each is done below:

    page 5   an ISO document-control header block from the BOM Header fields
    page 6   the body grouped by Process Stage, to match the physical paper format
    page 10  a stage with no rows must not render AT ALL -- not an empty table, gone

The last one is the reason the stage loop builds its rows first and only then decides
whether to open a table. Rendering the heading and testing emptiness inside it would
leave a stray title on the sheet, which is exactly the shop-floor confusion the FRD
calls out.

Time / Temp / Fan Speed print only inside SYREP. They are documented as SYREP machine
settings, so showing three permanently blank columns on the other stages would waste the
width they need for material names.
"""

import json

from alpinos.production import constants as C
from alpinos.purchase.print_formats import _upsert_print_format

JOB_CARD_PF_NAME = "Job Card"
JOB_CARD_DOC_TYPE = "BOM"

#: Stage order on the printed sheet. Injected into the template below as __STAGES__ so
#: the print and the screen read the same list -- hardcoding it here would drift the
#: moment a stage is added. Anything carrying an unrecognised stage is collected at the
#: end rather than dropped: a row must never vanish silently from a work instruction.
_STAGES = list(C.BOM_PROCESS_STAGES)

_JOB_CARD_HTML = """
<style>
	.jc-title { text-align: center; font-size: 15pt; font-weight: 700; letter-spacing: .5px;
		margin: 0 0 2px; }
	.jc-sub { text-align: center; font-size: 8pt; color: #555; margin: 0 0 10px; }
	table.jc { width: 100%; border-collapse: collapse; margin-bottom: 10px; }
	table.jc th, table.jc td { border: 1px solid #000; padding: 3px 5px; font-size: 8.5pt;
		vertical-align: top; }
	table.jc th { background: #eee; font-weight: 700; text-align: left; }
	.jc-head td.lbl { background: #f6f6f6; font-weight: 600; width: 16%; white-space: nowrap; }
	.jc-stage { margin-top: 12px; }
	.jc-stage-name { font-size: 9.5pt; font-weight: 700; text-transform: uppercase;
		letter-spacing: .4px; margin: 0 0 3px; padding: 3px 5px; background: #ddd;
		border: 1px solid #000; border-bottom: none; }
	.jc-num { text-align: right; white-space: nowrap; }
	.jc-sign { margin-top: 18px; }
	.jc-sign td { height: 46px; vertical-align: bottom; font-size: 8pt; }
	.avoid { page-break-inside: avoid; }
	/* A draft recipe must not be mistaken for a live work instruction once it is on
	   paper and away from the screen that said Draft. Fixed rather than absolute so that
	   wkhtmltopdf repeats it on every page of a long recipe. */
	.jc-draft { position: fixed; top: 38%; left: 0; right: 0; text-align: center;
		font-size: 78pt; font-weight: 700; letter-spacing: 8px; color: rgba(0, 0, 0, 0.09);
		transform: rotate(-24deg); z-index: 0; pointer-events: none; }
</style>

{%- set stages = __STAGES__ -%}

{%- if doc.docstatus == 0 %}<div class="jc-draft">DRAFT</div>{%- endif %}
{%- set rows = doc.items or [] -%}

{#- A weighed quantity prints to three decimals and a counted one prints whole.

    "%g" alone was wrong for the scale: it dropped the trailing zeros, so 0.500 Kg reached
    the operator as "0.5" and 2.000 Kg as "2" -- the same number, but not the same
    instruction, and it hid the precision the recipe was written to. "%g" is still right
    for Nos and Pcs, where "12.000 Pcs" is noise. -#}
{%- macro qty(v, uom) -%}
	{%- if (uom or "")|lower|trim in __WEIGHED__ -%}
		{{ "%.3f"|format(frappe.utils.flt(v)) }}
	{%- else -%}
		{{ "%g"|format(frappe.utils.flt(v)) }}
	{%- endif -%}
{%- endmacro -%}

{#- The item name only earns its space when it says something the code does not. Most
    of this catalogue names an item after its own code, which printed as
    "TEST-RM-001 - TEST-RM-001 (...)". -#}
{%- macro item_label(code, name) -%}
	{%- if name and code not in name and name not in code -%}
		{{ code }} &mdash; {{ name }}
	{%- else -%}
		{{ code }}
	{%- endif -%}
{%- endmacro -%}

<div class="jc-title">JOB CARD</div>
<div class="jc-sub">
	{{ frappe.db.get_value("Company", doc.company, "company_name") or doc.company or "" }}
</div>

<!-- ============ page 5: ISO document control header, from the BOM Header ============ -->
<table class="jc jc-head avoid">
	<tr>
		<td class="lbl">BOM ID</td><td>{{ doc.name }}</td>
		<td class="lbl">FG Item</td><td>{{ doc.item }}</td>
	</tr>
	<tr>
		{#- The name, always. Hiding it when it matched the code left the cell blank on most
		    of this catalogue, and a labelled box with nothing in it reads as missing data
		    rather than as "the same as the code". -#}
		<td class="lbl">Item Name</td>
		<td>{{ doc.item_name or doc.item or "" }}</td>
		<td class="lbl">BOM Variation</td>
		<td>{{ doc.custom_bom_variation_name or "" }}</td>
	</tr>
	<tr>
		{#- "Batch", not doc.uom. A BOM here is written for exactly one batch (Base Batch
		    Size is locked to 1), which is what the shop floor reads. ERPNext keeps its own
		    doc.uom as the FG item stock UOM for its internal quantity maths -- printing
		    that instead gave "1 Nos", which says nothing about a batch. -#}
		<td class="lbl">Base Batch Size</td>
		<td>{{ qty(doc.quantity, "") }} Batch</td>
		<td class="lbl">Is Default</td>
		<td>{{ "Yes" if doc.is_default else "No" }}</td>
	</tr>
	<tr>
		<td class="lbl">Status</td>
		<td>{{ "Active" if doc.is_active else "Inactive" }}{% if doc.docstatus == 0 %} (Draft){% endif %}</td>
		<td class="lbl">Printed On</td>
		<td>{{ frappe.utils.format_datetime(frappe.utils.now(), "dd-MM-yyyy HH:mm") }}</td>
	</tr>
</table>

<!-- ==== pages 6 + 10: grouped by Process Stage; an empty stage renders nothing ==== -->
{%- for stage in stages %}
	{%- set stage_rows = [] -%}
	{%- for row in rows -%}
		{%- if (row.custom_process_stage or "") == stage -%}
			{%- set _ = stage_rows.append(row) -%}
		{%- endif -%}
	{%- endfor -%}

	{#- the whole block is inside this test, so a stage with no rows prints nothing
	    at all -- no heading, no empty table (FRD page 10) -#}
	{%- if stage_rows %}
	<div class="jc-stage avoid">
		<div class="jc-stage-name">{{ stage }}</div>
		<table class="jc">
			<thead>
				<tr>
					<th style="width:34px;">#</th>
					<th style="width:94px;">Type</th>
					<th>Raw Materials</th>
					<th style="width:78px;" class="jc-num">Batch</th>
					<th style="width:62px;">UOM</th>
					{%- if stage == "SYREP" %}
					<th style="width:68px;">Time</th>
					<th style="width:68px;">Temp</th>
					<th style="width:74px;">Fan Speed</th>
					{%- endif %}
				</tr>
			</thead>
			<tbody>
			{%- for row in stage_rows %}
				<tr>
					<td>{{ loop.index }}</td>
					<td>{{ row.custom_material_type or "" }}</td>
					<td>{{ item_label(row.item_code, row.item_name) }}</td>
					<td class="jc-num">{{ qty(row.qty, row.uom) }}</td>
					<td>{{ row.uom or "" }}</td>
					{%- if stage == "SYREP" %}
					<td>{{ row.custom_time or "" }}</td>
					<td>{{ row.custom_temp or "" }}</td>
					<td>{{ row.custom_fan_speed or "" }}</td>
					{%- endif %}
				</tr>
			{%- endfor %}
			</tbody>
		</table>
	</div>
	{%- endif %}
{%- endfor %}

<!-- Anything carrying a stage this format does not know about, or none at all. Printed
     rather than dropped: a material missing from a work instruction is worse than an
     extra section. -->
{%- set loose = [] -%}
{%- for row in rows -%}
	{%- if (row.custom_process_stage or "") not in stages -%}
		{%- set _ = loose.append(row) -%}
	{%- endif -%}
{%- endfor -%}
{%- if loose %}
<div class="jc-stage avoid">
	<div class="jc-stage-name">Unassigned Stage</div>
	<table class="jc">
		<thead>
			<tr>
				<th style="width:34px;">#</th>
				<th style="width:94px;">Type</th>
				<th>Raw Materials</th>
				<th style="width:78px;" class="jc-num">Batch</th>
				<th style="width:62px;">UOM</th>
			</tr>
		</thead>
		<tbody>
		{%- for row in loose %}
			<tr>
				<td>{{ loop.index }}</td>
				<td>{{ row.custom_material_type or "" }}</td>
				<td>{{ item_label(row.item_code, row.item_name) }}</td>
				<td class="jc-num">{{ qty(row.qty, row.uom) }}</td>
				<td>{{ row.uom or "" }}</td>
			</tr>
		{%- endfor %}
		</tbody>
	</table>
</div>
{%- endif %}

{%- if not rows %}
<table class="jc"><tr><td style="text-align:center;padding:14px;">
	This BOM has no materials.
</td></tr></table>
{%- endif %}

<table class="jc jc-sign avoid">
	<tr>
		<td style="width:33%;">Prepared By</td>
		<td style="width:33%;">Checked By</td>
		<td>Approved By</td>
	</tr>
</table>
"""


def job_card_html():
	"""The rendered template. A function so the stage list is read at call time."""
	return (
		_JOB_CARD_HTML
		.replace("__STAGES__", json.dumps(_STAGES))
		.replace("__WEIGHED__", json.dumps(list(C.WEIGHED_UOMS)))
	)


def setup_job_card_print_format():
	_upsert_print_format(JOB_CARD_PF_NAME, JOB_CARD_DOC_TYPE, job_card_html())


# --- Task C version 2: the same sheet, printed for a Sub PO ------------------

SUB_JOB_CARD_PF_NAME = "Sub PO Job Card"
SUB_JOB_CARD_DOC_TYPE = "Work Order"

#: The Sub PO header, then the BOM sheet underneath it. The body is IDENTICAL on purpose --
#: the shop floor reads one layout, and a second one drawn slightly differently is how a
#: stage gets missed. The difference is the header, which answers "which run is this?", and
#: a Total Required Qty column, which answers "how much for THIS sub order?" rather than
#: per batch.
_SUB_JOB_CARD_HTML = """
<style>
	.sjc-head td.lbl { background: #f6f6f6; font-weight: 600; width: 16%; white-space: nowrap; }
	table.sjc { width: 100%; border-collapse: collapse; margin-bottom: 10px; }
	table.sjc th, table.sjc td { border: 1px solid #000; padding: 3px 5px; font-size: 8.5pt;
		vertical-align: top; }
	.sjc-title { text-align: center; font-size: 15pt; font-weight: 700; letter-spacing: .5px;
		margin: 0 0 2px; }
	.sjc-sub { text-align: center; font-size: 8pt; color: #555; margin: 0 0 10px; }
	.sjc-lock { display: inline-block; border: 1px solid #000; padding: 1px 6px;
		font-size: 7.5pt; font-weight: 700; letter-spacing: .5px; }
	.sjc-num { text-align: right; white-space: nowrap; }
	/* The same stage banding as the BOM Job Card, so the two sheets read as one format. */
	.sjc-stage { margin-top: 12px; }
	.sjc-stage-name { font-size: 9.5pt; font-weight: 700; text-transform: uppercase;
		letter-spacing: .4px; margin: 0 0 3px; padding: 3px 5px; background: #ddd;
		border: 1px solid #000; border-bottom: none; }
	.avoid { page-break-inside: avoid; }
</style>

{%- set parent_name = doc.custom_parent_production_order -%}
{%- set parent = frappe.get_doc("Production Order", parent_name) if parent_name else None -%}
{%- set share = (doc.qty / parent.production_qty_kg) if (parent and parent.production_qty_kg) else 1 -%}

<div class="sjc-title">JOB CARD &mdash; SUB PRODUCTION ORDER</div>
<div class="sjc-sub">
	{{ frappe.db.get_value("Company", doc.company, "company_name") or doc.company or "" }}
</div>

<table class="sjc sjc-head avoid">
	<tr>
		<td class="lbl">Sub PO</td><td>{{ doc.name }}</td>
		<td class="lbl">Parent PO</td><td>{{ parent_name or "" }}</td>
	</tr>
	<tr>
		<td class="lbl">Batch Number</td><td>{{ doc.custom_batch_number or "" }}</td>
		<td class="lbl">Production Type</td><td>{{ doc.custom_production_type or "" }}</td>
	</tr>
	<tr>
		<td class="lbl">Client</td><td>{{ doc.custom_client_name or "&mdash;" }}</td>
		<td class="lbl">FG Item</td>
		<td>{{ doc.production_item }}{% if doc.item_name and doc.item_name != doc.production_item %}
			&mdash; {{ doc.item_name }}{% endif %}</td>
	</tr>
	<tr>
		{#- KG, not doc.stock_uom. A Production Order is written in kilograms throughout --
		    Production Quantity (KG) on the Parent, and the sub order carries its share --
		    whereas stock_uom is the FG item unit, which is Nos for a pouched product. It
		    printed "2500 Nos" for 2500 KG. -#}
		<td class="lbl">Target Qty</td>
		<td>{{ "%g"|format(frappe.utils.flt(doc.qty)) }} KG</td>
		<td class="lbl">Total Batches</td>
		<td>
			{%- if parent and parent.total_batches -%}
				{{ "%g"|format(frappe.utils.flt(parent.total_batches) * share) }}
			{%- else -%}
				{#- Says WHERE to fix it rather than printing a bare dash: the number lives on
				    the Parent, and the formula that would calculate it is not agreed yet. -#}
				<span style="color:#777;">not set on {{ parent_name or "the parent order" }}</span>
			{%- endif -%}
		</td>
	</tr>
	<tr>
		<td class="lbl">Planned Date</td>
		<td>{% if doc.custom_planned_date %}{{ frappe.utils.format_date(doc.custom_planned_date, "dd-MM-yyyy") }}{% else %}&mdash;{% endif %}</td>
		<td class="lbl">Process</td>
		<td>{% if doc.custom_assigned_process %}{{ frappe.db.get_value("Process Master", doc.custom_assigned_process, "process_name") or doc.custom_assigned_process }}{% else %}Unassigned{% endif %}</td>
	</tr>
	<tr>
		<td class="lbl">Machine</td>
		<td>{% if doc.custom_assigned_machine %}{{ frappe.db.get_value("Machine", doc.custom_assigned_machine, "machine_name") or doc.custom_assigned_machine }}{% else %}&mdash;{% endif %}</td>
		<td class="lbl">Printed On</td>
		<td>{{ frappe.utils.format_datetime(frappe.utils.now(), "dd-MM-yyyy HH:mm") }}</td>
	</tr>
	<tr>
		<td class="lbl">Status</td>
		<td>{{ doc.custom_execution_status or "" }}
			{% if doc.custom_is_locked %}<span class="sjc-lock">LOCKED</span>{% endif %}</td>
		<td class="lbl">Split From</td>
		<td>{{ doc.custom_split_from or "&mdash;" }}</td>
	</tr>
</table>

{#- The body is the BOM Job Card, section for section: grouped by Process Stage, the same
    Type / Material / Batch / UOM columns, the same SYREP-only Time, Temp and Fan Speed, and
    a stage with no rows printing nothing at all (FRD page 10).

    Two sources, because neither has everything. The BOM rows carry the stage, the material
    type, the per-batch quantity and the machine settings. The sub order's own
    required_items carry Total Required Qty, already scaled to THIS sub order by
    work_order_naming.set_required_items. They are matched on item code. -#}
{%- set stages = __STAGES__ -%}
{%- set bom_rows = frappe.get_all("BOM Item", filters={"parent": doc.bom_no},
	fields=["item_code", "item_name", "uom", "qty", "custom_process_stage",
	        "custom_material_type", "custom_time", "custom_temp", "custom_fan_speed"],
	order_by="idx asc") if doc.bom_no else [] -%}
{%- set required = {} -%}
{%- for r in doc.required_items -%}
	{%- set _ = required.update({r.item_code: frappe.utils.flt(r.required_qty)}) -%}
{%- endfor -%}

{%- macro qty(v, uom) -%}
	{%- if (uom or "")|lower|trim in __WEIGHED__ -%}
		{{ "%.3f"|format(frappe.utils.flt(v)) }}
	{%- else -%}
		{{ "%g"|format(frappe.utils.flt(v)) }}
	{%- endif -%}
{%- endmacro -%}

{%- macro item_label(code, name) -%}
	{%- if name and code not in name and name not in code -%}
		{{ code }} &mdash; {{ name }}
	{%- else -%}
		{{ code }}
	{%- endif -%}
{%- endmacro -%}

{%- macro stage_table(stage, rows) %}
<div class="sjc-stage avoid">
	<div class="sjc-stage-name">{{ stage }}</div>
	<table class="sjc">
		<thead>
			<tr>
				<th style="width:34px;">#</th>
				<th style="width:84px;">Type</th>
				<th>Raw Materials</th>
				<th style="width:70px;" class="sjc-num">Batch</th>
				<th style="width:58px;">UOM</th>
				<th style="width:96px;" class="sjc-num">Total Required</th>
				{%- if stage == "SYREP" %}
				<th style="width:62px;">Time</th>
				<th style="width:62px;">Temp</th>
				<th style="width:68px;">Fan Speed</th>
				{%- endif %}
				<th style="width:110px;">Issued</th>
			</tr>
		</thead>
		<tbody>
		{%- for row in rows %}
			<tr>
				<td>{{ loop.index }}</td>
				<td>{{ row.custom_material_type or "" }}</td>
				<td>{{ item_label(row.item_code, row.item_name) }}</td>
				<td class="sjc-num">{{ qty(row.qty, row.uom) }}</td>
				<td>{{ row.uom or "" }}</td>
				<td class="sjc-num">{{ qty(required.get(row.item_code, 0), row.uom) }}</td>
				{%- if stage == "SYREP" %}
				<td>{{ row.custom_time or "" }}</td>
				<td>{{ row.custom_temp or "" }}</td>
				<td>{{ row.custom_fan_speed or "" }}</td>
				{%- endif %}
				<td></td>
			</tr>
		{%- endfor %}
		</tbody>
	</table>
</div>
{%- endmacro -%}

{%- for stage in stages %}
	{%- set stage_rows = [] -%}
	{%- for row in bom_rows -%}
		{%- if (row.custom_process_stage or "") == stage -%}
			{%- set _ = stage_rows.append(row) -%}
		{%- endif -%}
	{%- endfor -%}
	{%- if stage_rows %}{{ stage_table(stage, stage_rows) }}{% endif %}
{%- endfor %}

{#- Anything on a stage this sheet does not know about, or none at all. Printed rather than
    dropped: a material missing from a work instruction is worse than an extra section. -#}
{%- set loose = [] -%}
{%- for row in bom_rows -%}
	{%- if (row.custom_process_stage or "") not in stages -%}
		{%- set _ = loose.append(row) -%}
	{%- endif -%}
{%- endfor -%}
{%- if loose %}{{ stage_table("Unassigned Stage", loose) }}{% endif %}

<table class="sjc sjc-sign avoid" style="margin-top:18px;">
	<tr>
		<td style="height:46px;vertical-align:bottom;font-size:8pt;">Issued By</td>
		<td style="height:46px;vertical-align:bottom;font-size:8pt;">Operator</td>
		<td style="height:46px;vertical-align:bottom;font-size:8pt;">Supervisor</td>
		<td style="height:46px;vertical-align:bottom;font-size:8pt;">QC</td>
	</tr>
</table>
"""


def sub_job_card_html():
	return (
		_SUB_JOB_CARD_HTML
		.replace("__STAGES__", json.dumps(_STAGES))
		.replace("__WEIGHED__", json.dumps(list(C.WEIGHED_UOMS)))
	)


def setup_sub_job_card_print_format():
	_upsert_print_format(SUB_JOB_CARD_PF_NAME, SUB_JOB_CARD_DOC_TYPE, sub_job_card_html())


def execute():
	setup_job_card_print_format()
	setup_sub_job_card_print_format()
