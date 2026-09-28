"""Print formats for Material Management: the MR, the Issue Slip and the Return Slip.

Header, rows, signature lines -- the same boxed layout as the Sub PO Job Card, so the store
and the floor read one family of sheets. Created through the same upsert the other print
formats use, so re-running on migrate changes nothing unless the HTML did.
"""

from alpinos.purchase.print_formats import _upsert_print_format

MR_PF_NAME = "Material Request Slip"
ISSUE_PF_NAME = "Material Issue Slip"
RETURN_PF_NAME = "Material Return Slip"

_STYLE = """
<style>
	table.mm { width: 100%; border-collapse: collapse; margin-bottom: 10px; }
	table.mm th, table.mm td { border: 1px solid #000; padding: 3px 5px; font-size: 8.5pt;
		vertical-align: top; }
	table.mm th { background: #eee; font-weight: 700; text-align: left; }
	.mm-head td.lbl { background: #f6f6f6; font-weight: 600; width: 16%; white-space: nowrap; }
	.mm-title { text-align: center; font-size: 15pt; font-weight: 700; letter-spacing: .5px;
		margin: 0 0 2px; }
	.mm-sub { text-align: center; font-size: 8pt; color: #555; margin: 0 0 10px; }
	.mm-num { text-align: right; white-space: nowrap; }
	.mm-sign td { height: 46px; vertical-align: bottom; font-size: 8pt; }
	.mm-draft { position: fixed; top: 38%; left: 0; right: 0; text-align: center;
		font-size: 78pt; font-weight: 700; letter-spacing: 8px; color: rgba(0, 0, 0, 0.09);
		transform: rotate(-24deg); z-index: 0; pointer-events: none; }
	.avoid { page-break-inside: avoid; }
</style>
{%- macro q(v) -%}{{ "%.3f"|format(frappe.utils.flt(v)) }}{%- endmacro -%}
{%- macro dt(v) -%}{% if v %}{{ frappe.utils.format_date(v, "dd-MM-yyyy") }}{% else %}&mdash;{% endif %}{%- endmacro -%}
{%- macro who(u) -%}{{ (frappe.db.get_value("User", u, "full_name") or u) if u else "" }}{%- endmacro -%}
{%- if doc.docstatus == 0 %}<div class="mm-draft">DRAFT</div>{%- endif %}
{%- if doc.docstatus == 2 %}<div class="mm-draft">CANCELLED</div>{%- endif %}
<div class="mm-sub">{{ frappe.db.get_value("Company", doc.company, "company_name") or doc.company or "" }}</div>
"""

_MR_HTML = _STYLE + """
<div class="mm-title">MATERIAL REQUEST</div>
<table class="mm mm-head avoid">
	<tr><td class="lbl">MR ID</td><td>{{ doc.name }}</td>
		<td class="lbl">Status</td><td>{{ doc.custom_mr_status or "" }} ({{ doc.custom_mr_source or "" }})</td></tr>
	<tr><td class="lbl">Sub PO</td><td>{{ doc.custom_sub_production_order or "" }}</td>
		<td class="lbl">Parent PO</td><td>{{ doc.custom_parent_production_order or "" }}</td></tr>
	<tr><td class="lbl">FG Item</td><td>{{ doc.custom_target_fg_item or "" }}
			{% set fgn = frappe.db.get_value("Item", doc.custom_target_fg_item, "item_name") if doc.custom_target_fg_item else "" %}
			{% if fgn and fgn != doc.custom_target_fg_item %}&mdash; {{ fgn }}{% endif %}</td>
		<td class="lbl">Production Type</td><td>{{ doc.custom_production_type or "" }}</td></tr>
	<tr><td class="lbl">Requested By</td><td>{{ who(doc.owner) }}</td>
		<td class="lbl">Requested Date</td><td>{{ dt(doc.transaction_date) }}</td></tr>
	<tr><td class="lbl">Required Date</td><td>{{ dt(doc.schedule_date) }}</td>
		<td class="lbl">Deliver To</td><td>{{ doc.set_warehouse or "" }}</td></tr>
	{% if doc.custom_remarks %}<tr><td class="lbl">Remarks</td><td colspan="3">{{ doc.custom_remarks }}</td></tr>{% endif %}
</table>
<table class="mm">
	<thead><tr>
		<th style="width:26px;">#</th><th style="width:60px;">Type</th><th>Item</th>
		<th style="width:44px;">UOM</th><th class="mm-num" style="width:70px;">Standard</th>
		<th class="mm-num" style="width:80px;">Required</th><th class="mm-num" style="width:74px;">Available</th>
		<th class="mm-num" style="width:70px;">Shortage</th><th style="width:100px;">From</th>
		<th class="mm-num" style="width:70px;">Issued</th><th class="mm-num" style="width:70px;">Pending</th>
	</tr></thead>
	<tbody>
	{%- for row in doc.items %}
		<tr>
			<td>{{ loop.index }}</td><td>{{ row.custom_material_type or "" }}</td>
			<td>{{ row.item_code }}{% if row.item_name and row.item_name != row.item_code %} &mdash; {{ row.item_name }}{% endif %}
				{% if row.custom_line_remarks %}<br><span style="color:#555;">{{ row.custom_line_remarks }}</span>{% endif %}</td>
			<td>{{ row.uom or "" }}</td><td class="mm-num">{{ q(row.custom_standard_qty) }}</td>
			<td class="mm-num">{{ q(row.qty) }}</td><td class="mm-num">{{ q(row.custom_available_qty) }}</td>
			<td class="mm-num">{{ q(row.custom_shortage_qty) }}</td><td>{{ row.from_warehouse or "" }}</td>
			<td class="mm-num">{{ q(row.custom_issued_qty) }}</td><td class="mm-num">{{ q(row.custom_pending_qty) }}</td>
		</tr>
	{%- endfor %}
	</tbody>
</table>
<table class="mm mm-sign avoid" style="margin-top:18px;">
	<tr><td>Requested By</td><td>Approved By</td><td>Store</td></tr>
</table>
"""

_ISSUE_HTML = _STYLE + """
<div class="mm-title">MATERIAL ISSUE SLIP</div>
<table class="mm mm-head avoid">
	<tr><td class="lbl">MI ID</td><td>{{ doc.name }}</td>
		<td class="lbl">Material Request</td><td>{{ doc.custom_material_request or "" }}</td></tr>
	<tr><td class="lbl">Sub PO</td><td>{{ doc.custom_sub_production_order or "" }}</td>
		<td class="lbl">Parent PO</td><td>{{ doc.custom_parent_production_order or "" }}</td></tr>
	<tr><td class="lbl">FG Item</td><td>{{ doc.custom_target_fg_item or "" }}</td>
		<td class="lbl">Production Type</td><td>{{ doc.custom_production_type or "" }}</td></tr>
	<tr><td class="lbl">Issue Date</td><td>{{ dt(doc.posting_date) }}</td>
		<td class="lbl">Issued By</td><td>{{ who(doc.owner) }}</td></tr>
	{% if doc.remarks %}<tr><td class="lbl">Remarks</td><td colspan="3">{{ doc.remarks }}</td></tr>{% endif %}
</table>
<table class="mm">
	<thead><tr>
		<th style="width:26px;">#</th><th style="width:60px;">Type</th><th>Item</th>
		<th style="width:44px;">UOM</th><th class="mm-num" style="width:80px;">Required</th>
		<th class="mm-num" style="width:80px;">Issued</th><th style="width:100px;">Batch</th>
		<th style="width:100px;">From</th><th style="width:100px;">To</th>
	</tr></thead>
	<tbody>
	{%- for row in doc.items %}
		<tr>
			<td>{{ loop.index }}</td><td>{{ row.custom_material_type or "" }}</td>
			<td>{{ row.item_code }}{% if row.item_name and row.item_name != row.item_code %} &mdash; {{ row.item_name }}{% endif %}
				{% if row.custom_line_remarks %}<br><span style="color:#555;">{{ row.custom_line_remarks }}</span>{% endif %}</td>
			<td>{{ row.stock_uom or row.uom or "" }}</td><td class="mm-num">{{ q(row.custom_required_qty) }}</td>
			<td class="mm-num">{{ q(row.qty) }}</td><td>{{ row.batch_no or "" }}</td>
			<td>{{ row.s_warehouse or "" }}</td><td>{{ row.t_warehouse or "" }}</td>
		</tr>
	{%- endfor %}
	</tbody>
</table>
<table class="mm mm-sign avoid" style="margin-top:18px;">
	<tr><td>Issued By (Store)</td><td>Received By (Production)</td><td>Supervisor</td></tr>
</table>
"""

_RETURN_HTML = _STYLE + """
<div class="mm-title">MATERIAL RETURN SLIP</div>
<table class="mm mm-head avoid">
	<tr><td class="lbl">MRT ID</td><td>{{ doc.name }}</td>
		<td class="lbl">Material Issue</td><td>{{ doc.custom_material_issue or "" }}</td></tr>
	<tr><td class="lbl">Sub PO</td><td>{{ doc.custom_sub_production_order or "" }}</td>
		<td class="lbl">Parent PO</td><td>{{ doc.custom_parent_production_order or "" }}</td></tr>
	<tr><td class="lbl">FG Item</td><td>{{ doc.custom_target_fg_item or "" }}</td>
		<td class="lbl">Production Type</td><td>{{ doc.custom_production_type or "" }}</td></tr>
	<tr><td class="lbl">Return Date</td><td>{{ dt(doc.posting_date) }}</td>
		<td class="lbl">Returned By</td><td>{{ who(doc.owner) }}</td></tr>
	{% if doc.remarks %}<tr><td class="lbl">Remarks</td><td colspan="3">{{ doc.remarks }}</td></tr>{% endif %}
</table>
<table class="mm">
	<thead><tr>
		<th style="width:26px;">#</th><th style="width:60px;">Type</th><th>Item</th>
		<th style="width:44px;">UOM</th><th style="width:90px;">Batch</th>
		<th class="mm-num" style="width:70px;">Issued</th><th class="mm-num" style="width:70px;">Prev. Returned</th>
		<th class="mm-num" style="width:70px;">Returned</th><th style="width:110px;">Reason</th>
		<th style="width:90px;">From</th><th style="width:90px;">To</th>
	</tr></thead>
	<tbody>
	{%- for row in doc.items %}
		<tr>
			<td>{{ loop.index }}</td><td>{{ row.custom_material_type or "" }}</td>
			<td>{{ row.item_code }}{% if row.item_name and row.item_name != row.item_code %} &mdash; {{ row.item_name }}{% endif %}</td>
			<td>{{ row.stock_uom or row.uom or "" }}</td><td>{{ row.batch_no or "" }}</td>
			<td class="mm-num">{{ q(row.custom_required_qty) }}</td>
			<td class="mm-num">{{ q(row.custom_previously_returned) }}</td>
			<td class="mm-num">{{ q(row.qty) }}</td>
			<td>{{ row.custom_return_reason or "" }}{% if row.custom_line_remarks %}<br><span style="color:#555;">{{ row.custom_line_remarks }}</span>{% endif %}</td>
			<td>{{ row.s_warehouse or "" }}</td><td>{{ row.t_warehouse or "" }}</td>
		</tr>
	{%- endfor %}
	</tbody>
</table>
<table class="mm mm-sign avoid" style="margin-top:18px;">
	<tr><td>Returned By (Production)</td><td>Received By (Store)</td><td>Supervisor</td></tr>
</table>
"""


def execute():
	_upsert_print_format(MR_PF_NAME, "Material Request", _MR_HTML)
	_upsert_print_format(ISSUE_PF_NAME, "Stock Entry", _ISSUE_HTML)
	_upsert_print_format(RETURN_PF_NAME, "Stock Entry", _RETURN_HTML)
