"""Purchase Inward and QC Inspection print formats (custom Jinja, registered on migrate).

Tasks 296 and 312 of the BRD "Purchase Inward Part -1".

Both formats are owned by this module: execute() diffs the stored html against the
_HTML strings below and re-saves it on every migrate, so an edit made in the Print
Format UI will not survive. Change the template here, never on site.

BR-PI-08 wants the Purchase Order shipment details AND the actual details corrected by
the Store Team retained for traceability, so the inward format prints them side by side
with a per-row verdict rather than letting the corrected value overwrite the planned one.

BR-QC-16 / BR-QC-22 want a QC Report available from the related Purchase Inward; that is
the second format here, on Purchase QC.

`module` is deliberately not set: Frappe backfills it from the target DocType (see
Print Format.validate), and `standard` stays the string "No" so validate() does not
try to export the format back into the repo.
"""

import frappe

from alpinos.purchase import constants as C

INWARD_PF_NAME = "Purchase Inward"
INWARD_DOC_TYPE = "Purchase Inward"

QC_PF_NAME = "QC Inspection Report"
QC_DOC_TYPE = "Purchase QC"

STICKER_PF_NAME = "QC Sample Sticker"
STICKER_DOC_TYPE = "Purchase QC"


def _jinja_dict(mapping):
	"""Render a str->str mapping as a Jinja dict literal, so the vocabulary in
	constants.py stays the single source of truth for the printed labels."""
	items = ", ".join('"%s": "%s"' % (k, str(v).replace('"', "")) for k, v in mapping.items())
	return "{" + items + "}"


_INWARD_TYPE_MAP = _jinja_dict(C.INWARD_TYPE_LABELS)


# Shared Jinja helpers. Every one of them absorbs None so a half-filled draft prints
# without a stack trace and without leaking the word "None" into the PDF.
_MACROS = r"""
{%- macro txt(v) -%}{{ v if v else "-" }}{%- endmacro -%}
{%- macro num(v) -%}{{ "%.2f"|format(frappe.utils.flt(v)) }}{%- endmacro -%}
{%- macro num3(v) -%}{{ "%.3f"|format(frappe.utils.flt(v)) }}{%- endmacro -%}
{%- macro yn(v) -%}{{ "Yes" if frappe.utils.cint(v) else "No" }}{%- endmacro -%}
{%- macro has(v) -%}{{ "Yes" if v else "-" }}{%- endmacro -%}
{%- macro dte(v) -%}{{ frappe.utils.formatdate(v, "dd-MM-yyyy") if v else "-" }}{%- endmacro -%}
{%- macro dtm(v) -%}{{ frappe.utils.format_datetime(v, "dd-MM-yyyy HH:mm") if v else "-" }}{%- endmacro -%}
{%- macro who(v) -%}{{ frappe.get_fullname(v) if v else "-" }}{%- endmacro -%}
"""


# --------------------------------------------------------------------------- 296

# Padding is forced to 6px by frappe/templates/styles/standard.css with !important, and
# vertical-align to top; the two-class selectors below outrank that on specificity so the
# 12-column grid still fits A4. Top alignment is left alone on purpose.
_INWARD_HTML_RAW = r"""
<style>
  .piw { font-family: Arial, Helvetica, sans-serif; color: #000; font-size: 10px; }
  .piw table { border-collapse: collapse; width: 100%; table-layout: fixed;
      margin-bottom: 9px; font-size: 10px; }
  .piw table td, .piw table th { border: 1px solid #000; padding: 4px 5px !important;
      word-wrap: break-word; overflow: hidden; }
  .piw table.g td { padding: 3px 4px !important; font-size: 9px; }
  .piw table.g th { padding: 3px 4px !important; font-size: 8px; }
  .piw th { background: #ececec; font-size: 9px; text-transform: uppercase; text-align: center;
      font-weight: bold; }
  .piw .sec { background: #d9d9d9; font-weight: bold; text-transform: uppercase; font-size: 10px;
      letter-spacing: 0.6px; }
  .piw .lbl { background: #f6f6f6; font-weight: bold; }
  .piw .c { text-align: center; }
  .piw .r { text-align: right; }
  .piw .b { font-weight: bold; }
  .piw .mut { color: #666; }
  .piw .sub { font-size: 9px; color: #555; font-weight: normal; }
  .piw .warn { color: #a30000; font-weight: bold; }
  .piw .tot td { background: #f0f0f0; font-weight: bold; }
  .piw .title { font-size: 17px; font-weight: bold; text-align: center; letter-spacing: 1.5px; }
  .piw .subtitle { text-align: center; font-size: 10px; color: #555; margin: 2px 0 8px; }
  .piw .avoid { page-break-inside: avoid; }
  .piw .sign { height: 40px; border-bottom: 1px solid #666; margin: 8px 0 3px; }
  .piw .tag { font-size: 8px; border: 1px solid #a30000; color: #a30000; padding: 0 2px;
      margin-left: 3px; }
</style>
{% set _inward_types = __INWARD_TYPES__ %}
<div class="piw">

  <div class="title">PURCHASE INWARD</div>
  <div class="subtitle">{{ doc.name or "" }}{% if doc.company %} &middot; {{ doc.company }}{% endif %}</div>

  <!-- ===== header block: BRD 2.1.1, frozen once the inward is submitted ===== -->
  <table class="avoid">
    <colgroup><col style="width:20%"><col style="width:30%"><col style="width:20%"><col style="width:30%"></colgroup>
    <tr><td class="sec" colspan="4">Purchase Inward Details</td></tr>
    <tr>
      <td class="lbl">Inward ID</td><td class="b">{{ txt(doc.name) }}</td>
      <td class="lbl">Inward Date &amp; Time</td><td>{{ dtm(doc.inward_datetime) }}</td>
    </tr>
    <tr>
      <td class="lbl">Purchase Order No.</td><td class="b">{{ txt(doc.purchase_order) }}</td>
      <td class="lbl">Inward Type</td>
      <td>{{ _inward_types.get(doc.inward_type, doc.inward_type) if doc.inward_type else "-" }}</td>
    </tr>
    <tr>
      <td class="lbl">Vendor</td>
      <td>{{ txt(doc.supplier_name or doc.supplier) }}
        {% if doc.supplier and doc.supplier_name and doc.supplier != doc.supplier_name %}
        <div class="sub">{{ doc.supplier }}</div>{% endif %}</td>
      <td class="lbl">Supplier Order No.</td><td>{{ txt(doc.supplier_order_no) }}</td>
    </tr>
    <tr>
      <td class="lbl">Invoice No.</td><td>{{ txt(doc.invoice_number) }}</td>
      <td class="lbl">Invoice Date</td><td>{{ dte(doc.invoice_date) }}</td>
    </tr>
    <tr>
      <td class="lbl">Challan No.</td><td>{{ txt(doc.challan_no) }}</td>
      <td class="lbl">Gross Weight</td>
      <td>{{ num3(doc.gross_weight) if doc.gross_weight else "-" }}</td>
    </tr>
    <tr>
      <td class="lbl">Status</td><td class="b">{{ txt(doc.inward_status) }}</td>
      <td class="lbl">QC / GRN Status</td>
      <td>{{ txt(doc.qc_status) }} / {{ txt(doc.grn_status) }}</td>
    </tr>
    <tr>
      <td class="lbl">Created By</td><td>{{ who(doc.owner) }}</td>
      <td class="lbl">Attachment</td>
      <td>{{ has(doc.attachment) }}{% if doc.dispute_attachments %}
        <span class="sub">({{ doc.dispute_attachments|length }} discrepancy
        file{% if doc.dispute_attachments|length > 1 %}s{% endif %})</span>{% endif %}</td>
    </tr>
    {% if doc.purchase_qc or doc.purchase_receipt or doc.purchase_invoice or doc.debit_note %}
    <tr>
      <td class="lbl">Linked Documents</td>
      <td colspan="3">
        {% if doc.purchase_qc %}QC: {{ doc.purchase_qc }}{% endif %}
        {% if doc.purchase_receipt %} &middot; GRN: {{ doc.purchase_receipt }}{% endif %}
        {% if doc.purchase_invoice %} &middot; Invoice: {{ doc.purchase_invoice }}{% endif %}
        {% if doc.debit_note %} &middot; Debit Note: {{ doc.debit_note }}{% endif %}
      </td>
    </tr>
    {% endif %}
    {% if doc.merged_into or doc.original_invoice_number %}
    <tr>
      <td class="lbl">Merged Into</td><td>{{ txt(doc.merged_into) }}</td>
      <td class="lbl">Original Invoice No.</td><td>{{ txt(doc.original_invoice_number) }}</td>
    </tr>
    {% endif %}
  </table>

  <!-- ===== planned vs actual shipment: BR-PI-06 / BR-PI-07 / BR-PI-08 ===== -->
  <table class="avoid">
    <colgroup><col style="width:25%"><col style="width:28%"><col style="width:28%"><col style="width:19%"></colgroup>
    <tr><td class="sec" colspan="4">Shipment Verification</td></tr>
    <tr>
      <th style="text-align:left;">Detail</th>
      <th>Planned (Purchase Order)</th>
      <th>Actual (Store Verified)</th>
      <th>Verification</th>
    </tr>
    <tr>
      <td class="lbl">Vehicle Number</td>
      <td>{{ txt(doc.po_vehicle_no) }}</td>
      <td class="b">{{ txt(doc.actual_vehicle_no) }}</td>
      <td class="c">{{ vstat(doc.po_vehicle_no, doc.actual_vehicle_no) }}</td>
    </tr>
    <tr>
      <td class="lbl">Driver Contact Number</td>
      <td>{{ txt(doc.po_driver_contact_no) }}</td>
      <td class="b">{{ txt(doc.actual_driver_contact_no) }}</td>
      <td class="c">{{ vstat(doc.po_driver_contact_no, doc.actual_driver_contact_no) }}</td>
    </tr>
    <tr>
      <td class="lbl">Arrival Date &amp; Time</td>
      <td>{{ dtm(doc.po_estimated_arrival) }}</td>
      <td class="b">{{ dtm(doc.actual_arrival_datetime) }}</td>
      <td class="c">{% if doc.actual_arrival_datetime %}Recorded{% else %}<span class="mut">Not recorded</span>{% endif %}</td>
    </tr>
    <tr>
      <td class="lbl">Location</td>
      <td>{{ txt(doc.delivery_location) }}</td>
      <td class="b">{{ txt(doc.target_warehouse) }}</td>
      <td class="c">{{ vstat(doc.delivery_location, doc.target_warehouse) }}</td>
    </tr>
    <tr>
      <td class="lbl">Vehicle Details Verified</td>
      <td class="mut">-</td>
      <td class="b">{{ yn(doc.vehicle_details_verified) }}</td>
      <td class="c">{% if frappe.utils.cint(doc.vehicle_details_verified) %}Corrected by Store{% else %}As per PO{% endif %}</td>
    </tr>
    <tr>
      <td class="lbl">Excess Quantity Allowed</td>
      <td class="mut">-</td>
      <td class="b">{{ yn(doc.allow_excess_qty) }}</td>
      <td class="c">{% if frappe.utils.flt(doc.total_excess_qty) > 0 %}<span class="warn">Excess received</span>{% else %}-{% endif %}</td>
    </tr>
  </table>

  <!-- ===== item grid: BRD 2.2.2 (purchase) + 2.2.1 (store receiving) ===== -->
  <table class="g">
    <colgroup>
      <col style="width:3.5%">
      <col style="width:17%">
      <col style="width:5.5%">
      <col style="width:7.5%">
      <col style="width:8%">
      <col style="width:7.5%">
      <col style="width:8%">
      <col style="width:6.5%">
      <col style="width:11%">
      <col style="width:9%">
      <col style="width:8%">
      <col style="width:8.5%">
    </colgroup>
    <thead>
      <tr><th class="sec" colspan="12" style="text-align:left;">Item Details</th></tr>
      <tr>
        <th>Sr.</th>
        <th style="text-align:left;">Item</th>
        <th>UOM</th>
        <th>Order Qty</th>
        <th>Prev. Recd</th>
        <th>Pending</th>
        <th>Received</th>
        <th>Excess</th>
        <th>Target Location</th>
        <th>Batch</th>
        <th>Mfg</th>
        <th>Expiry</th>
      </tr>
    </thead>
    {% for row in doc.items %}
    <tr>
      <td class="c">{{ loop.index }}</td>
      <td>
        <span class="b">{{ txt(row.item_code) }}</span>
        {% if row.item_name and row.item_name != row.item_code %}
        <div class="sub">{{ row.item_name }}</div>{% endif %}
        {% if row.usp or row.mrp %}
        <div class="sub">
          {% if row.usp %}USP: {{ row.usp }}{% endif %}
          {% if row.mrp %}{% if row.usp %} &middot; {% endif %}MRP: {{ num(row.mrp) }}{% endif %}
        </div>{% endif %}
      </td>
      <td class="c">{{ txt(row.uom) }}</td>
      <td class="r">{{ num(row.order_qty) }}</td>
      <td class="r">{{ num(row.previously_received_qty) }}</td>
      <td class="r">{{ num(row.pending_qty) }}</td>
      <td class="r b">{{ num(row.received_qty) }}</td>
      <td class="r{% if frappe.utils.flt(row.excess_qty) > 0 %} warn{% endif %}">{{ num(row.excess_qty) }}</td>
      <td>{{ txt(row.target_warehouse) }}</td>
      <td>{{ txt(row.batch_no) }}{% if frappe.utils.cint(row.quarantine) %}<span class="tag">QRTN</span>{% endif %}</td>
      <td class="c">{{ dte(row.manufacturing_date) }}</td>
      <td class="c">{{ dte(row.expiry_date) }}</td>
    </tr>
    {% endfor %}
    {% if not doc.items %}
    <tr><td colspan="12" class="c mut">No items recorded on this Purchase Inward.</td></tr>
    {% endif %}
    <tr class="tot">
      <td colspan="3" class="r">Total ({{ frappe.utils.cint(doc.total_items) }} items)</td>
      <td class="r">{{ num(doc.total_order_qty) }}</td>
      <td class="r">{{ num(doc.total_previously_received_qty) }}</td>
      <td class="r">{{ num(doc.total_pending_qty) }}</td>
      <td class="r">{{ num(doc.total_received_qty) }}</td>
      <td class="r{% if frappe.utils.flt(doc.total_excess_qty) > 0 %} warn{% endif %}">{{ num(doc.total_excess_qty) }}</td>
      <td colspan="4"></td>
    </tr>
  </table>

  <!-- ===== item-level remarks, only when something was written ===== -->
  {% set _ns = namespace(item_remarks=false, quarantine=false) %}
  {% for row in doc.items %}
    {% if row.remarks %}{% set _ns.item_remarks = true %}{% endif %}
    {% if frappe.utils.cint(row.quarantine) %}{% set _ns.quarantine = true %}{% endif %}
  {% endfor %}
  {% if _ns.item_remarks %}
  <table class="g avoid">
    <colgroup><col style="width:5%"><col style="width:25%"><col style="width:70%"></colgroup>
    <tr><td class="sec" colspan="3">Item Remarks</td></tr>
    {% for row in doc.items %}{% if row.remarks %}
    <tr>
      <td class="c">{{ row.idx }}</td>
      <td>{{ txt(row.item_code) }}</td>
      <td>{{ row.remarks }}</td>
    </tr>
    {% endif %}{% endfor %}
  </table>
  {% endif %}

  {% if _ns.quarantine %}
  <table class="g avoid">
    <colgroup><col style="width:5%"><col style="width:20%"><col style="width:15%"><col style="width:60%"></colgroup>
    <tr><td class="sec" colspan="4">Quarantine</td></tr>
    <tr><th>Sr.</th><th style="text-align:left;">Item</th><th>Status</th><th style="text-align:left;">Reason</th></tr>
    {% for row in doc.items %}{% if frappe.utils.cint(row.quarantine) %}
    <tr>
      <td class="c">{{ row.idx }}</td>
      <td>{{ txt(row.item_code) }}</td>
      <td class="c">{{ txt(row.quarantine_status) }}</td>
      <td>{{ txt(row.quarantine_reason) }}</td>
    </tr>
    {% endif %}{% endfor %}
  </table>
  {% endif %}

  <!-- ===== remarks ===== -->
  <table class="avoid">
    <colgroup><col style="width:50%"><col style="width:50%"></colgroup>
    <tr><td class="sec" colspan="2">Remarks</td></tr>
    <tr>
      <th style="text-align:left;">Purchase Remarks</th>
      <th style="text-align:left;">Receiving Remarks (Store)</th>
    </tr>
    <tr>
      <td style="height:38px;">{{ txt(doc.remarks) }}</td>
      <td style="height:38px;">{{ txt(doc.receiving_remarks) }}</td>
    </tr>
  </table>

  {% if doc.dispute_attachments %}
  <table class="g avoid">
    <colgroup><col style="width:5%"><col style="width:15%"><col style="width:45%"><col style="width:20%"><col style="width:15%"></colgroup>
    <tr><td class="sec" colspan="5">Photos &amp; Videos (Discrepancies / Disputes)</td></tr>
    <tr><th>Sr.</th><th>Kind</th><th style="text-align:left;">Description</th><th>Uploaded By</th><th>Uploaded On</th></tr>
    {% for row in doc.dispute_attachments %}
    <tr>
      <td class="c">{{ loop.index }}</td>
      <td class="c">{{ txt(row.kind) }}</td>
      <td>{{ txt(row.description) }}</td>
      <td class="c">{{ who(row.uploaded_by) }}</td>
      <td class="c">{{ dtm(row.uploaded_on) }}</td>
    </tr>
    {% endfor %}
  </table>
  {% endif %}

  <!-- ===== signatures ===== -->
  <table class="avoid">
    <colgroup><col style="width:50%"><col style="width:50%"></colgroup>
    <tr><th>Purchase Team</th><th>Store Team</th></tr>
    <tr>
      <td>
        Prepared By: <span class="b">{{ who(doc.owner) }}</span>
        <div class="sub">On {{ dtm(doc.inward_datetime) }}</div>
        <div class="sign"></div>
        <div class="sub">Signature</div>
      </td>
      <td>
        Received By: <span class="b">{{ who(doc.received_by) }}</span>
        <div class="sub">On {{ dtm(doc.receiving_datetime or doc.actual_arrival_datetime) }}</div>
        <div class="sign"></div>
        <div class="sub">Signature</div>
      </td>
    </tr>
  </table>

</div>
"""

# Verdict shown beside each planned/actual pair so the Store verification is auditable.
_VSTAT_MACRO = r"""
{%- macro vstat(planned, actual) -%}
{%- if not actual -%}<span class="mut">Not recorded</span>
{%- elif planned and (actual|string|trim) == (planned|string|trim) -%}Matches PO
{%- else -%}<span class="warn">Corrected</span>
{%- endif -%}
{%- endmacro -%}
"""

_INWARD_HTML = (
	_MACROS + _VSTAT_MACRO + _INWARD_HTML_RAW.replace("__INWARD_TYPES__", _INWARD_TYPE_MAP)
)


# --------------------------------------------------------------------------- 312

# Every inspection section is wrapped in a truthiness test on its child table, per the
# BRD 4 note that inspections run in parallel and independently: a section with no rows
# was not applicable to this inward and must not print an empty grid.
_QC_HTML_RAW = r"""
<style>
  .qcr { font-family: Arial, Helvetica, sans-serif; color: #000; font-size: 10px; }
  .qcr table { border-collapse: collapse; width: 100%; table-layout: fixed;
      margin-bottom: 9px; font-size: 10px; }
  .qcr table td, .qcr table th { border: 1px solid #000; padding: 4px 5px !important;
      word-wrap: break-word; overflow: hidden; }
  .qcr table.g td { padding: 3px 4px !important; font-size: 9px; }
  .qcr table.g th { padding: 3px 4px !important; font-size: 8px; }
  .qcr th { background: #ececec; font-size: 9px; text-transform: uppercase; text-align: center;
      font-weight: bold; }
  .qcr .sec { background: #d9d9d9; font-weight: bold; text-transform: uppercase; font-size: 10px;
      letter-spacing: 0.6px; }
  .qcr .lbl { background: #f6f6f6; font-weight: bold; }
  .qcr .c { text-align: center; }
  .qcr .r { text-align: right; }
  .qcr .b { font-weight: bold; }
  .qcr .mut { color: #666; }
  .qcr .sub { font-size: 9px; color: #555; font-weight: normal; }
  .qcr .warn { color: #a30000; font-weight: bold; }
  .qcr .ok { color: #17632a; font-weight: bold; }
  .qcr .tot td { background: #f0f0f0; font-weight: bold; }
  .qcr .title { font-size: 17px; font-weight: bold; text-align: center; letter-spacing: 1.5px; }
  .qcr .subtitle { text-align: center; font-size: 10px; color: #555; margin: 2px 0 8px; }
  .qcr .avoid { page-break-inside: avoid; }
  .qcr .sign { height: 40px; border-bottom: 1px solid #666; margin: 8px 0 3px; }
  .qcr .note { font-size: 9px; color: #666; margin: -4px 0 9px; }
  .qcr .tag { font-size: 8px; border: 1px solid #a30000; color: #a30000; padding: 0 2px;
      margin-left: 3px; }
  /* dates carry hyphens, which are break opportunities; keep each fragment whole */
  .qcr .nb { white-space: nowrap; }
</style>
{% set _inward_types = __INWARD_TYPES__ %}
{% set _rejected = "__QC_REJECTED__" %}
{% set _approved = "__QC_APPROVED__" %}
{% set _damaged = "__CONDITION_DAMAGED__" %}
<div class="qcr">

  <div class="title">QC INSPECTION REPORT</div>
  <div class="subtitle">{{ doc.name or "" }}{% if doc.company %} &middot; {{ doc.company }}{% endif %}</div>

  <!-- ===== BRD 4.1.1 Purchase Inward Information (read only) ===== -->
  <table class="avoid">
    <colgroup><col style="width:20%"><col style="width:30%"><col style="width:20%"><col style="width:30%"></colgroup>
    <tr><td class="sec" colspan="4">Purchase Inward Information</td></tr>
    <tr>
      <td class="lbl">QC ID</td><td class="b">{{ txt(doc.name) }}</td>
      <td class="lbl">Purchase Inward ID</td><td class="b">{{ txt(doc.purchase_inward) }}</td>
    </tr>
    <tr>
      <td class="lbl">Vendor</td>
      <td>{{ txt(doc.supplier_name or doc.supplier) }}
        {% if doc.supplier and doc.supplier_name and doc.supplier != doc.supplier_name %}
        <div class="sub">{{ doc.supplier }}</div>{% endif %}</td>
      <td class="lbl">Supplier Order No.</td><td>{{ txt(doc.supplier_order_no) }}</td>
    </tr>
    <tr>
      <td class="lbl">Invoice Number</td><td>{{ txt(doc.invoice_number) }}</td>
      <td class="lbl">Inward Type</td>
      <td>{{ _inward_types.get(doc.inward_type, doc.inward_type) if doc.inward_type else "-" }}</td>
    </tr>
    <tr>
      <td class="lbl">Received Quantity</td><td class="b">{{ num(doc.received_qty) }}</td>
      <td class="lbl">Inspection Date</td><td>{{ dtm(doc.inspection_date) }}</td>
    </tr>
    <tr>
      <td class="lbl">Inspector</td><td>{{ who(doc.inspector) }}</td>
      <td class="lbl">Current Status</td><td class="b">{{ txt(doc.qc_status) }}</td>
    </tr>
    <tr>
      <td class="lbl">QC SLA</td>
      <td>{{ dtm(doc.sla_start) }} &rarr; {{ dtm(doc.sla_due) }}</td>
      <td class="lbl">SLA Breached</td>
      <td class="{% if frappe.utils.cint(doc.sla_breached) %}warn{% endif %}">{{ yn(doc.sla_breached) }}</td>
    </tr>
    {% if doc.purchase_receipt or doc.debit_note %}
    <tr>
      <td class="lbl">Linked Documents</td>
      <td colspan="3">
        {% if doc.purchase_receipt %}GRN: {{ doc.purchase_receipt }}{% endif %}
        {% if doc.debit_note %}{% if doc.purchase_receipt %} &middot; {% endif %}Debit Note: {{ doc.debit_note }}{% endif %}
      </td>
    </tr>
    {% endif %}
  </table>

  <!-- ===== BRD 4.1.2 Vehicle Inspection ===== -->
  {% if doc.vehicle_inspection %}
  <table class="g avoid">
    <colgroup>
      <col style="width:5%"><col style="width:16%"><col style="width:11%"><col style="width:8%">
      <col style="width:27%"><col style="width:7%"><col style="width:26%">
    </colgroup>
    <tr><td class="sec" colspan="7">Vehicle Inspection
      <span class="sub">({{ "Complete" if frappe.utils.cint(doc.vehicle_inspection_done) else "Incomplete" }})</span></td></tr>
    <tr>
      <th>Sr.</th><th>Vehicle Number</th><th>Condition</th><th>Damage</th>
      <th style="text-align:left;">Damage Reason</th><th>Attach</th><th style="text-align:left;">Inspector Remarks</th>
    </tr>
    {% for row in doc.vehicle_inspection %}
    <tr>
      <td class="c">{{ loop.index }}</td>
      <td class="c">{{ txt(row.vehicle_no) }}</td>
      <td class="c{% if row.vehicle_condition == _damaged %} warn{% endif %}">{{ txt(row.vehicle_condition) }}</td>
      <td class="c{% if frappe.utils.cint(row.vehicle_damage) %} warn{% endif %}">{{ yn(row.vehicle_damage) }}</td>
      <td>{{ txt(row.damage_reason) }}</td>
      <td class="c">{{ has(row.attachment) }}</td>
      <td>{{ txt(row.inspector_remarks) }}</td>
    </tr>
    {% endfor %}
  </table>
  {% endif %}

  <!-- ===== BRD 4.1.3 Material Inspection ===== -->
  {% if doc.material_inspection %}
  <table class="g avoid">
    <colgroup>
      <col style="width:5%"><col style="width:22%"><col style="width:11%"><col style="width:8%">
      <col style="width:9%"><col style="width:23%"><col style="width:22%">
    </colgroup>
    <tr><td class="sec" colspan="7">Material Inspection
      <span class="sub">({{ "Complete" if frappe.utils.cint(doc.material_inspection_done) else "Incomplete" }})</span></td></tr>
    <tr>
      <th>Sr.</th><th style="text-align:left;">Item</th><th>Condition</th><th>Damage</th>
      <th>Damaged Qty</th><th style="text-align:left;">Damage Reason</th><th style="text-align:left;">Inspector Remarks</th>
    </tr>
    {% for row in doc.material_inspection %}
    <tr>
      <td class="c">{{ loop.index }}</td>
      <td><span class="b">{{ txt(row.item_code) }}</span>
        {% if row.item_name and row.item_name != row.item_code %}
        <div class="sub">{{ row.item_name }}</div>{% endif %}</td>
      <td class="c{% if row.material_condition == _damaged %} warn{% endif %}">{{ txt(row.material_condition) }}</td>
      <td class="c{% if frappe.utils.cint(row.material_damage) %} warn{% endif %}">{{ yn(row.material_damage) }}</td>
      <td class="r">{{ num(row.damaged_qty) }}</td>
      <td>{{ txt(row.damage_reason) }}</td>
      <td>{{ txt(row.inspector_remarks) }}</td>
    </tr>
    {% endfor %}
  </table>
  {% endif %}

  <!-- ===== BRD 4.1.4 Packaging / Box Inspection ===== -->
  {% if doc.packaging_inspection %}
  <table class="g avoid">
    <colgroup>
      <col style="width:5%"><col style="width:21%"><col style="width:10%"><col style="width:8%">
      <col style="width:9%"><col style="width:22%"><col style="width:6%"><col style="width:19%">
    </colgroup>
    <tr><td class="sec" colspan="8">Packaging / Box Inspection
      <span class="sub">({{ "Complete" if frappe.utils.cint(doc.packaging_inspection_done) else "Incomplete" }})</span></td></tr>
    <tr>
      <th>Sr.</th><th style="text-align:left;">Item</th><th>Condition</th><th>Damage</th>
      <th>Damaged Qty</th><th style="text-align:left;">Damage Reason</th><th>Attach</th>
      <th style="text-align:left;">Inspector Remarks</th>
    </tr>
    {% for row in doc.packaging_inspection %}
    <tr>
      <td class="c">{{ loop.index }}</td>
      <td><span class="b">{{ txt(row.item_code) }}</span>
        {% if row.item_name and row.item_name != row.item_code %}
        <div class="sub">{{ row.item_name }}</div>{% endif %}</td>
      <td class="c{% if row.packaging_condition == _damaged %} warn{% endif %}">{{ txt(row.packaging_condition) }}</td>
      <td class="c{% if frappe.utils.cint(row.packaging_damage) %} warn{% endif %}">{{ yn(row.packaging_damage) }}</td>
      <td class="r">{{ num(row.damaged_qty) }}</td>
      <td>{{ txt(row.damage_reason) }}</td>
      <td class="c">{{ has(row.attachment) }}</td>
      <td>{{ txt(row.inspector_remarks) }}</td>
    </tr>
    {% endfor %}
  </table>
  {% endif %}

  <!-- ===== BRD 4.1.5 Sample Testing ===== -->
  {% if doc.sample_testing %}
  <table class="g avoid">
    <colgroup>
      <col style="width:4%"><col style="width:17%"><col style="width:12%"><col style="width:14%">
      <col style="width:9%"><col style="width:7%"><col style="width:14%"><col style="width:23%">
    </colgroup>
    <tr><td class="sec" colspan="8">Sample Testing
      <span class="sub">({{ "Complete" if frappe.utils.cint(doc.sample_testing_done) else "Incomplete" }})</span></td></tr>
    <tr>
      <th>Sr.</th><th style="text-align:left;">SKU</th><th>Supplier Batch</th><th>Internal Batch</th>
      <th>Sample Qty</th><th>UOM</th><th>RMID / PMID</th><th style="text-align:left;">Remarks</th>
    </tr>
    {% for row in doc.sample_testing %}
    <tr>
      <td class="c">{{ loop.index }}</td>
      <td><span class="b">{{ txt(row.item_code) }}</span>
        {% if row.item_name and row.item_name != row.item_code %}
        <div class="sub">{{ row.item_name }}</div>{% endif %}</td>
      <td class="c">{{ txt(row.supplier_batch_no) }}</td>
      <td class="c">{{ txt(row.internal_batch_no) }}</td>
      <td class="r">{{ num(row.sample_qty) }}</td>
      <td class="c">{{ txt(row.uom) }}</td>
      <td class="c">{{ txt(row.sample_id) }}</td>
      <td>{{ txt(row.remarks) }}</td>
    </tr>
    {% endfor %}
  </table>
  {% endif %}

  <!-- ===== BRD 4.1.6 Control Sample ===== -->
  {% if doc.control_sample %}
  <table class="g avoid">
    <colgroup>
      <col style="width:4%"><col style="width:7%"><col style="width:18%"><col style="width:13%">
      <col style="width:9%"><col style="width:16%"><col style="width:11%"><col style="width:22%">
    </colgroup>
    <tr><td class="sec" colspan="8">Control Sample</td></tr>
    <tr>
      <th>Sr.</th><th>Taken</th><th style="text-align:left;">SKU</th><th>Batch</th>
      <th>Qty</th><th>Storage Location</th><th>Retain Until</th><th style="text-align:left;">Remarks</th>
    </tr>
    {% for row in doc.control_sample %}
    <tr>
      <td class="c">{{ loop.index }}</td>
      <td class="c">{{ yn(row.control_sample_taken) }}</td>
      <td><span class="b">{{ txt(row.item_code) }}</span>
        {% if row.item_name and row.item_name != row.item_code %}
        <div class="sub">{{ row.item_name }}</div>{% endif %}</td>
      <td class="c">{{ txt(row.batch_no) }}</td>
      <td class="r">{{ num(row.control_sample_qty) }}</td>
      <td>{{ txt(row.storage_location) }}</td>
      <td class="c">{{ dte(row.retention_until) }}</td>
      <td>{{ txt(row.remarks) }}</td>
    </tr>
    {% endfor %}
  </table>
  {% endif %}

  {% set _ns = namespace(skipped="") %}
  {% if not doc.vehicle_inspection %}{% set _ns.skipped = _ns.skipped + "Vehicle, " %}{% endif %}
  {% if not doc.material_inspection %}{% set _ns.skipped = _ns.skipped + "Material, " %}{% endif %}
  {% if not doc.packaging_inspection %}{% set _ns.skipped = _ns.skipped + "Packaging, " %}{% endif %}
  {% if not doc.sample_testing %}{% set _ns.skipped = _ns.skipped + "Sample Testing, " %}{% endif %}
  {% if not doc.control_sample %}{% set _ns.skipped = _ns.skipped + "Control Sample, " %}{% endif %}
  {% if _ns.skipped %}
  <div class="note">No inspection recorded for: {{ _ns.skipped[:-2] }}.</div>
  {% endif %}

  <!-- ===== BRD 4.6 QC Decision ===== -->
  <table class="g">
    <colgroup>
      <col style="width:4%"><col style="width:20%"><col style="width:6%"><col style="width:9%">
      <col style="width:8%"><col style="width:8%"><col style="width:9%"><col style="width:9%">
      <col style="width:12%"><col style="width:15%">
    </colgroup>
    <thead>
      <tr><th class="sec" colspan="10" style="text-align:left;">QC Decision</th></tr>
      <tr>
        <th>Sr.</th><th style="text-align:left;">Item</th><th>UOM</th><th>Received</th>
        <th>Sample</th><th>Control</th><th>Approved</th><th>Rejected</th>
        <th>QC Result</th><th style="text-align:left;">Rejection Reason</th>
      </tr>
    </thead>
    {% for row in doc.items %}
    <tr>
      <td class="c">{{ loop.index }}</td>
      <td>
        <span class="b">{{ txt(row.item_code) }}</span>
        {% if row.item_name and row.item_name != row.item_code %}
        <div class="sub">{{ row.item_name }}</div>{% endif %}
        {% if row.internal_batch_no or row.manufacturing_date or row.expiry_date or row.target_warehouse %}
        <div class="sub">
          {% if row.internal_batch_no %}<span class="nb">Batch: {{ row.internal_batch_no }}</span>{% endif %}
          {% if row.manufacturing_date %} &middot; <span class="nb">Mfg: {{ dte(row.manufacturing_date) }}</span>{% endif %}
          {% if row.expiry_date %} &middot; <span class="nb">Exp: {{ dte(row.expiry_date) }}</span>{% endif %}
          {% if row.target_warehouse %} &middot; To: {{ row.target_warehouse }}{% endif %}
        </div>{% endif %}
        {% if frappe.utils.cint(row.quarantine) %}<span class="tag">QRTN</span>{% endif %}
      </td>
      <td class="c">{{ txt(row.uom) }}</td>
      <td class="r b">{{ num(row.received_qty) }}</td>
      <td class="r">{{ num(row.sample_qty) }}</td>
      <td class="r">{{ num(row.control_sample_qty) }}</td>
      <td class="r">{{ num(row.approved_qty) }}</td>
      <td class="r{% if frappe.utils.flt(row.rejected_qty) > 0 %} warn{% endif %}">{{ num(row.rejected_qty) }}</td>
      <td class="c{% if row.qc_result == _rejected %} warn{% elif row.qc_result == _approved %} ok{% endif %}">{{ txt(row.qc_result) }}</td>
      <td>{{ txt(row.rejection_reason) }}</td>
    </tr>
    {% endfor %}
    {% if not doc.items %}
    <tr><td colspan="10" class="c mut">No item-wise QC decision recorded.</td></tr>
    {% endif %}
    <tr class="tot">
      <td colspan="3" class="r">Total</td>
      <td class="r">{{ num(doc.total_received_qty) }}</td>
      <td class="r">{{ num(doc.total_sample_qty) }}</td>
      <td class="r">{{ num(doc.total_control_sample_qty) }}</td>
      <td class="r">{{ num(doc.total_approved_qty) }}</td>
      <td class="r{% if frappe.utils.flt(doc.total_rejected_qty) > 0 %} warn{% endif %}">{{ num(doc.total_rejected_qty) }}</td>
      <td colspan="2" class="c">QC Result:
        <span class="{% if doc.qc_result == _rejected %}warn{% elif doc.qc_result == _approved %}ok{% endif %}">{{ txt(doc.qc_result) }}</span>
      </td>
    </tr>
  </table>
  <div class="note">QC Result is derived by the system from Approved and Rejected quantity against the received quantity (BRD 4.6.2).</div>

  <!-- ===== remarks ===== -->
  <table class="avoid">
    <colgroup><col style="width:22%"><col style="width:78%"></colgroup>
    <tr><td class="sec" colspan="2">Remarks</td></tr>
    <tr><td class="lbl">Rejection Reason</td><td style="height:30px;">{{ txt(doc.rejection_reason) }}</td></tr>
    <tr><td class="lbl">Final QC Remarks</td><td style="height:30px;">{{ txt(doc.final_qc_remarks) }}</td></tr>
    <tr><td class="lbl">Overall Remarks</td><td style="height:30px;">{{ txt(doc.overall_remarks) }}</td></tr>
  </table>

  <!-- ===== signatures ===== -->
  <table class="avoid">
    <colgroup><col style="width:50%"><col style="width:50%"></colgroup>
    <tr><th>QC Inspector</th><th>QC Manager</th></tr>
    <tr>
      <td>
        Inspected By: <span class="b">{{ who(doc.inspector) }}</span>
        <div class="sub">On {{ dtm(doc.inspection_date) }}</div>
        <div class="sign"></div>
        <div class="sub">Signature</div>
      </td>
      <td>
        Approved By:
        <div class="sub">&nbsp;</div>
        <div class="sign"></div>
        <div class="sub">Signature</div>
      </td>
    </tr>
  </table>

</div>
"""

_QC_HTML = (
	_MACROS
	+ _QC_HTML_RAW.replace("__INWARD_TYPES__", _INWARD_TYPE_MAP)
	.replace("__QC_REJECTED__", C.QC_RESULT_REJECTED)
	.replace("__QC_APPROVED__", C.QC_RESULT_APPROVED)
	.replace("__CONDITION_DAMAGED__", C.CONDITION_DAMAGED)
)


# ------------------------------------------------------------------------- 4.1.5

# BRD 4.1.5 wants a sticker generated against the RMID / PMID that purchase_qc mints for
# every sample row (BR-QC-14); the id was minted but nothing ever printed it, so a drawn
# sample reached the lab unlabelled. The BRD says "Sticker format will be defined
# separately", so this prints one plain bordered block per sample id at whatever page size
# the Print Settings already use — no label stationery is invented here. Rows without a
# sample id (a draft QC) print the reason instead of a blank page.
_STICKER_HTML_RAW = r"""
<style>
  .qsk { font-family: Arial, Helvetica, sans-serif; color: #000; font-size: 10px; }
  .qsk table { border-collapse: collapse; width: 100%; table-layout: fixed;
      margin-bottom: 10px; font-size: 10px; }
  .qsk table td { border: 1px solid #000; padding: 4px 5px !important;
      word-wrap: break-word; overflow: hidden; }
  .qsk .sec { background: #d9d9d9; font-weight: bold; text-transform: uppercase; font-size: 10px;
      letter-spacing: 0.6px; }
  .qsk .lbl { background: #f6f6f6; font-weight: bold; }
  .qsk .b { font-weight: bold; }
  .qsk .sub { font-size: 9px; color: #555; }
  .qsk .id { font-size: 20px; font-weight: bold; letter-spacing: 1.5px; text-align: center; }
  .qsk .sign { height: 34px; }
  .qsk .avoid { page-break-inside: avoid; }
  .qsk .note { font-size: 9px; color: #666; }
  /* ids, batch codes and dates carry hyphens, which are break opportunities */
  .qsk .nb { white-space: nowrap; }
</style>
{% set _inward_types = __INWARD_TYPES__ %}
{% set _ns = namespace(printed=0) %}
<div class="qsk">
{% for row in doc.sample_testing or [] %}
{% if row.sample_id %}
{% set _ns.printed = _ns.printed + 1 %}
  <table class="avoid">
    <colgroup><col style="width:18%"><col style="width:32%"><col style="width:18%"><col style="width:32%"></colgroup>
    <tr><td class="sec" colspan="4">Sample Sticker &middot;
      {{ _inward_types.get(doc.inward_type, doc.inward_type) if doc.inward_type else "-" }}</td></tr>
    <tr><td class="lbl">RMID / PMID</td><td class="id nb" colspan="3">{{ row.sample_id }}</td></tr>
    <tr>
      <td class="lbl">SKU</td>
      <td><span class="b">{{ txt(row.item_code) }}</span>
        {% if row.item_name and row.item_name != row.item_code %}
        <div class="sub">{{ row.item_name }}</div>{% endif %}</td>
      <td class="lbl">Sample Qty</td>
      <td class="b">{{ num3(row.sample_qty) }} {{ row.uom or "" }}</td>
    </tr>
    <tr>
      <td class="lbl">Internal Batch</td><td class="nb">{{ txt(row.internal_batch_no) }}</td>
      <td class="lbl">Supplier Batch</td><td class="nb">{{ txt(row.supplier_batch_no) }}</td>
    </tr>
    <tr>
      <td class="lbl">Supplier</td><td>{{ txt(doc.supplier_name or doc.supplier) }}</td>
      <td class="lbl">Invoice No.</td><td class="nb">{{ txt(doc.invoice_number) }}</td>
    </tr>
    <tr>
      <td class="lbl">Purchase Inward</td><td class="nb">{{ txt(doc.purchase_inward) }}</td>
      <td class="lbl">QC Ref.</td>
      <td class="nb">{{ txt(doc.name) }}<div class="sub nb">{{ dte(doc.inspection_date) }}</div></td>
    </tr>
    {% if row.remarks %}
    <tr><td class="lbl">Remarks</td><td colspan="3">{{ row.remarks }}</td></tr>
    {% endif %}
    <tr>
      <td class="lbl">Sampled By</td><td>{{ who(doc.inspector) }}</td>
      <td class="lbl">Sign</td><td class="sign"></td>
    </tr>
  </table>
{% endif %}
{% endfor %}
{% if not _ns.printed %}
  <div class="note">No sample sticker to print: the RMID / PMID is generated when the QC
  inspection is completed (BRD 4.1.5, BR-QC-14).</div>
{% endif %}
</div>
"""

_STICKER_HTML = _MACROS + _STICKER_HTML_RAW.replace("__INWARD_TYPES__", _INWARD_TYPE_MAP)


# ------------------------------------------------------------------ upsert ---


def _upsert_print_format(name, doc_type, html):
	"""Idempotently (re)create one custom Jinja print format.

	`custom_format` and `disabled` stay ints and `standard` stays the string "No" so
	the diff below matches what the DB stores and the format is not re-saved on every
	migrate.
	"""
	if not frappe.db.exists("DocType", doc_type):
		frappe.logger("alpinos").info(
			"Skipped '%s' print format: DocType %s is not installed." % (name, doc_type)
		)
		return

	fields = {
		"doc_type": doc_type,
		"print_format_type": "Jinja",
		"custom_format": 1,
		"standard": "No",
		"disabled": 0,
		"html": html,
	}
	if frappe.db.exists("Print Format", name):
		pf = frappe.get_doc("Print Format", name)
		changed = False
		for k, v in fields.items():
			if pf.get(k) != v:
				pf.set(k, v)
				changed = True
		if changed:
			pf.save(ignore_permissions=True)
			frappe.logger("alpinos").info("Updated '%s' print format." % name)
	else:
		pf = frappe.get_doc({"doctype": "Print Format", "name": name, **fields})
		pf.insert(ignore_permissions=True)
		frappe.logger("alpinos").info("Created '%s' print format." % name)


def setup_purchase_inward_print_format():
	"""Task 296 — the 'Purchase Inward' print format on Purchase Inward."""
	_upsert_print_format(INWARD_PF_NAME, INWARD_DOC_TYPE, _INWARD_HTML)


def setup_qc_inspection_print_format():
	"""Task 312 — the 'QC Inspection Report' print format on Purchase QC (BR-QC-16)."""
	_upsert_print_format(QC_PF_NAME, QC_DOC_TYPE, _QC_HTML)


def setup_qc_sample_sticker_print_format():
	"""BRD 4.1.5 — the sample sticker printed against the RMID / PMID (BR-QC-14)."""
	_upsert_print_format(STICKER_PF_NAME, STICKER_DOC_TYPE, _STICKER_HTML)


def _set_default_print_format(doc_type, print_format):
	"""Make `print_format` the default the Print button opens for `doc_type`.

	Creating the format is not enough: DocType.default_print_format stays empty, so every
	Print button (inward_client frm.print_doc, the list page's frappe.set_route("print"))
	opened the auto-generated Standard layout and the user had to pick the module format
	from the dropdown every single time.

	Written with a Property Setter rather than doc.save(): saving a DocType in
	developer_mode rewrites its tracked JSON on disk, and Purchase Receipt/Purchase Order
	are ERPNext core files.
	"""
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	if not (frappe.db.exists("DocType", doc_type) and frappe.db.exists("Print Format", print_format)):
		return
	if frappe.db.get_value("DocType", doc_type, "default_print_format") == print_format:
		return
	make_property_setter(
		doc_type, None, "default_print_format", print_format, "Data",
		for_doctype=True, validate_fields_for_doctype=False,
	)


def execute():
	"""Register every Purchase Inward module print format."""
	setup_purchase_inward_print_format()
	setup_qc_inspection_print_format()
	setup_qc_sample_sticker_print_format()
	# Task 296 / 312: the Print button must open the module format, not Standard.
	_set_default_print_format(INWARD_DOC_TYPE, INWARD_PF_NAME)
	_set_default_print_format(QC_DOC_TYPE, QC_PF_NAME)
