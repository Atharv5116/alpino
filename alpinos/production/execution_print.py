"""Print format "Production Order Print" on the Parent Production Order (FRD Phase 14).

Header, the material grid (standard / total required qty), the Sub POs with their current
execution status, and signature blocks -- in the same bordered A4 style as the purchase
prints, created with the same idempotent _upsert_print_format helper.
"""

from alpinos.purchase.print_formats import _upsert_print_format

PF_NAME = "Production Order Print"
PF_DOC_TYPE = "Production Order"

_HTML = r"""
<style>
  .pop { color: #000; font-size: 10px; line-height: 14px; }
  .pop table { border-collapse: collapse; width: 100%; table-layout: fixed; margin-bottom: 9px; }
  .pop table td, .pop table th { border: 1px solid #000; padding: 4px 5px !important;
      word-wrap: break-word; vertical-align: top; }
  .pop th { background: #ececec; font-size: 9px; text-transform: uppercase; text-align: center; font-weight: bold; }
  .pop .sec { background: #d9d9d9; font-weight: bold; text-transform: uppercase; letter-spacing: 1px; }
  .pop .lbl { background: #f6f6f6; font-weight: bold; }
  .pop .r { text-align: right; white-space: nowrap; }
  .pop .c { text-align: center; }
  .pop .b { font-weight: bold; }
  .pop .title { font-size: 17px; line-height: 24px; font-weight: bold; text-align: center; letter-spacing: 2px; }
  .pop .subtitle { text-align: center; font-size: 10px; color: #555; margin: 2px 0 8px; }
  .pop .avoid { page-break-inside: avoid; }
  .pop .tot td { background: #f0f0f0; font-weight: bold; }
  .pop .sign td { height: 52px; vertical-align: bottom; text-align: center; font-size: 9px; }
</style>
{%- macro num(v, p=3) -%}{{ ("%." ~ p ~ "f")|format(v or 0) }}{%- endmacro -%}
{%- macro txt(v) -%}{{ v if v not in (None, "") else "-" }}{%- endmacro -%}
{%- macro dte(v) -%}{{ frappe.utils.formatdate(v) if v else "-" }}{%- endmacro -%}
{%- set subs = frappe.get_all("Work Order",
      filters={"custom_parent_production_order": doc.name, "docstatus": ["<", 2]},
      fields=["name", "qty", "custom_batch_number", "custom_execution_status",
              "custom_assigned_process", "custom_assigned_machine", "custom_planned_date", "docstatus"],
      order_by="name asc") -%}
<div class="pop">
  <div class="title">PRODUCTION ORDER</div>
  <div class="subtitle">{{ doc.name }}{% if doc.company %} &middot; {{ doc.company }}{% endif %}</div>

  <table class="avoid">
    <colgroup><col style="width:18%"><col style="width:32%"><col style="width:18%"><col style="width:32%"></colgroup>
    <tr><td class="sec" colspan="4">Order Details</td></tr>
    <tr><td class="lbl">Production Order</td><td class="b">{{ doc.name }}</td>
        <td class="lbl">Status</td><td class="b">{{ txt(doc.status) }}</td></tr>
    <tr><td class="lbl">Creation Date</td><td>{{ dte(doc.creation_date) }}</td>
        <td class="lbl">Production Start</td><td>{{ dte(doc.production_start_date) }}</td></tr>
    <tr><td class="lbl">Production Type</td><td>{{ txt(doc.production_type) }}</td>
        <td class="lbl">Client</td><td>{{ txt(doc.client_name) }}</td></tr>
    <tr><td class="lbl">FG Item</td><td>{{ txt(doc.fg_item) }}{% if doc.fg_item_name and doc.fg_item_name != doc.fg_item %} &mdash; {{ doc.fg_item_name }}{% endif %}</td>
        <td class="lbl">BOM</td><td>{{ txt(doc.bom_no) }}</td></tr>
    <tr><td class="lbl">Batch Number</td><td class="b">{{ txt(doc.batch_number) }}</td>
        <td class="lbl">Delivery Date</td><td>{{ dte(doc.delivery_date) }}</td></tr>
    <tr><td class="lbl">Production Qty (KG)</td><td class="b">{{ num(doc.production_qty_kg) }}</td>
        <td class="lbl">Production Qty (PCS)</td><td>{{ doc.production_qty_pcs or "-" }}</td></tr>
    <tr><td class="lbl">Total Batches</td><td>{{ num(doc.total_batches, 2) }}</td>
        <td class="lbl">Total Material Req.</td><td>{{ num(doc.total_material_requirement) }}</td></tr>
  </table>

  <table>
    <colgroup><col style="width:5%"><col style="width:10%"><col style="width:14%"><col style="width:17%">
      <col style="width:24%"><col style="width:8%"><col style="width:11%"><col style="width:11%"></colgroup>
    <tr><td class="sec" colspan="8">Materials</td></tr>
    <tr><th>#</th><th>Type</th><th>Stage</th><th>Item Code</th><th>Item Name</th><th>UOM</th>
        <th>Std Qty</th><th>Total Req. Qty</th></tr>
    {%- set ns = namespace(total=0) -%}
    {%- for row in doc.items -%}
    {%- set ns.total = ns.total + (row.total_required_qty or 0) -%}
    <tr><td class="c">{{ loop.index }}</td><td class="c">{{ txt(row.material_type) }}</td>
        <td>{{ txt(row.process_stage) }}</td><td>{{ row.item_code }}</td><td>{{ txt(row.item_name) }}</td>
        <td class="c">{{ txt(row.uom) }}</td><td class="r">{{ num(row.standard_qty) }}</td>
        <td class="r">{{ num(row.total_required_qty) }}</td></tr>
    {%- endfor -%}
    <tr class="tot"><td colspan="7" class="r">Total Required</td><td class="r">{{ num(ns.total) }}</td></tr>
  </table>

  <table class="avoid">
    <colgroup><col style="width:16%"><col style="width:16%"><col style="width:12%"><col style="width:18%">
      <col style="width:14%"><col style="width:12%"><col style="width:12%"></colgroup>
    <tr><td class="sec" colspan="7">Sub Production Orders</td></tr>
    <tr><th>Sub PO</th><th>Batch</th><th>Qty (KG)</th><th>Execution Status</th><th>Process</th>
        <th>Machine</th><th>Planned Date</th></tr>
    {%- for s in subs -%}
    <tr><td class="b">{{ s.name }}</td><td>{{ txt(s.custom_batch_number) }}</td><td class="r">{{ num(s.qty) }}</td>
        <td>{{ txt(s.custom_execution_status) }}</td>
        <td>{{ txt(frappe.db.get_value("Process Master", s.custom_assigned_process, "process_name") if s.custom_assigned_process else None) }}</td>
        <td>{{ txt(frappe.db.get_value("Machine", s.custom_assigned_machine, "machine_name") if s.custom_assigned_machine else None) }}</td>
        <td class="c">{{ dte(s.custom_planned_date) }}</td></tr>
    {%- else -%}
    <tr><td colspan="7" class="c">No sub orders yet (they are created when the order is approved).</td></tr>
    {%- endfor -%}
  </table>

  {% if doc.remarks %}
  <table class="avoid"><tr><td class="lbl" style="width:18%">Remarks</td><td>{{ doc.remarks }}</td></tr></table>
  {% endif %}

  <table class="sign avoid">
    <tr>
      <td>{{ frappe.get_fullname(doc.owner) }}<br><b>Prepared By</b></td>
      <td>{{ frappe.get_fullname(doc.approved_by) if doc.approved_by else "" }}<br><b>Approved By</b></td>
      <td>{{ frappe.get_fullname(doc.sent_by) if doc.sent_by else "" }}<br><b>Sent To Store By</b></td>
      <td><br><b>Production Head</b></td>
    </tr>
  </table>
</div>
"""


def production_order_print_html():
	return _HTML


def setup_production_order_print():
	_upsert_print_format(PF_NAME, PF_DOC_TYPE, production_order_print_html())
