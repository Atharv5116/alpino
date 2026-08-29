"""Pick List packing sheet print format (custom Jinja, registered on migrate)."""

import frappe

PF_NAME = "Pick List Packing Sheet"
DOC_TYPE = "Pick List"

_HTML = r"""
<style>
  .plps { font-family: Arial, Helvetica, sans-serif; color: #000; font-size: 12px; }
  .plps table { border-collapse: collapse; width: 100%; table-layout: fixed; }
  .plps td, .plps th { border: 1px solid #000; padding: 5px 8px; word-wrap: break-word; overflow: hidden; }
  .plps .lbl { font-weight: bold; text-align: center; white-space: nowrap; }
  .plps .val { font-weight: bold; }
  .plps .rl  { font-weight: bold; vertical-align: top; }
  .plps .hl  { text-align: center; }
  .plps th   { font-size: 11px; text-transform: uppercase; text-align: center; font-weight: bold; }
  .plps td.sku { font-weight: bold; }
  .plps td.c   { text-align: center; }
</style>
<div class="plps">
  <table>
    <colgroup>
      <col style="width:5%">   <!-- SR -->
      <col style="width:16%">  <!-- SKU (item code) -->
      <col style="width:11%">  <!-- SKU No -->
      <col style="width:13%">  <!-- Sales Order ID / Qty -->
      <col style="width:8%">   <!-- Total Box / Box -->
      <col style="width:10%">  <!-- Sample Qty -->
      <col style="width:14%">  <!-- Batch Code -->
      <col style="width:11%">  <!-- MFG -->
      <col style="width:12%">  <!-- EXP -->
    </colgroup>

    <!-- ===== header block (shares the grid) ===== -->
    <tr>
      <td colspan="2" class="lbl">ACTUAL BOX</td>
      <td colspan="2" class="val">{{ (doc.custom_actual_box | round | int) if doc.custom_actual_box is not none else "" }}</td>
      <td colspan="5" class="rl" rowspan="8">QC Attended By: {{ doc.custom_qc_attended_by or "" }}</td>
    </tr>
    <tr><td colspan="2" class="lbl">SAMPLE BOX</td><td colspan="2" class="val">{{ (doc.custom_sample_box | round | int) if doc.custom_sample_box else "" }}</td></tr>
    <tr><td colspan="2" class="lbl">SAMPLE WEIGHT</td><td colspan="2" class="val">{{ ("%.2f"|format(doc.custom_sample_weight)) if doc.custom_sample_weight else "" }}</td></tr>
    <tr><td colspan="2" class="lbl">TOTAL BOX</td><td colspan="2" class="val">{{ (doc.custom_total_box | round | int) if doc.custom_total_box is not none else 0 }}</td></tr>
    <tr><td colspan="2" class="lbl">GROSS WEIGHT</td><td colspan="2" class="val">{{ "%.2f"|format(doc.custom_gross_weight or 0) }}</td></tr>
    <tr><td colspan="2" class="lbl">TOTAL UNITS</td><td colspan="2" class="val">{{ (doc.custom_total_unit | round | int) if doc.custom_total_unit is not none else 0 }}</td></tr>
    <tr><td colspan="2" class="lbl">PO NO.</td><td colspan="2" class="val">{{ doc.custom_po_no or "" }}</td></tr>
    <tr><td colspan="2" class="lbl">TRANSPORTER</td><td colspan="2" class="val">{{ doc.custom_transporter or "" }}</td></tr>
    <tr>
      <td colspan="2" class="lbl">PARTY NAME</td>
      <td colspan="2" class="val">{{ doc.custom_customer_name or "" }}</td>
      <td colspan="5" class="rl">PARTY CODE: {{ (frappe.db.get_value("Sales Order", doc.custom_sales_order_id, "po_no") if doc.custom_sales_order_id else "") or doc.custom_customer_name or doc.custom_party_code or "" }}</td>
    </tr>
    <tr>
      <td colspan="2" class="lbl">DATE</td>
      <td colspan="2" class="val">{{ frappe.utils.formatdate(doc.custom_order_date, "dd-MM-yyyy") if doc.custom_order_date else "" }}</td>
      <td colspan="5"></td>
    </tr>

    <!-- ===== items header row (same grid) ===== -->
    <tr>
      <th>SR.</th>
      <th>SKU</th>
      <th>SKU NO</th>
      <th>{{ doc.custom_sales_order_id or doc.name }}</th>
      <th class="hl">{{ (doc.custom_total_box | round | int) if doc.custom_total_box is not none else 0 }}</th>
      <th>SAMPLE QTY</th>
      <th>BATCH CODE</th>
      <th>MFG</th>
      <th>EXP</th>
    </tr>

    <!-- ===== item rows (only what's on this Pick List), ascending by SKU No ===== -->
    {% for row in sort_locations_by_sku(doc.locations) %}
    {# Sample rows (marketing freebies / scheme / additional units) show their picked qty
       in the Sample Qty column; the main Qty column stays empty for them. #}
    {% set _is_sample = row.custom_source_table in ['Marketing Freebies', 'Scheme Table', 'Additional Units'] %}
    <tr>
      <td class="c">{{ loop.index }}</td>
      <td class="sku">{{ row.item_code }}{% if row.custom_bundle_parent %}<div style="font-size:10px; font-weight:normal;">&#8627; {{ row.custom_bundle_parent }}</div>{% endif %}</td>
      <td class="sku">{{ frappe.db.get_value("Item", row.item_code, "custom_sku_no") or "" }}</td>
      <td class="c">{{ (row.qty | round | int) if (row.qty and not _is_sample) else "" }}</td>
      <td class="c">{{ (row.custom_box | round | int) if row.custom_box else "" }}</td>
      <td class="c">{{ (row.qty | round | int) if (row.qty and _is_sample) else "" }}</td>
      <td>{{ row.custom_batch_code or row.batch_no or "" }}</td>
      <td class="c">{{ frappe.utils.formatdate(row.custom_mfg_date, "dd-MM-yyyy") if row.custom_mfg_date else "" }}</td>
      <td class="c">{{ frappe.utils.formatdate(row.custom_expiry_date, "dd-MM-yyyy") if row.custom_expiry_date else "" }}</td>
    </tr>
    {% endfor %}
  </table>
</div>
"""


def execute():
	"""Idempotently (re)create the 'Pick List Packing Sheet' custom Jinja print format."""
	fields = {
		"doc_type": DOC_TYPE,
		"print_format_type": "Jinja",
		"custom_format": 1,
		"standard": "No",
		"disabled": 0,
		"html": _HTML,
	}
	if frappe.db.exists("Print Format", PF_NAME):
		pf = frappe.get_doc("Print Format", PF_NAME)
		changed = False
		for k, v in fields.items():
			if pf.get(k) != v:
				pf.set(k, v)
				changed = True
		if changed:
			pf.save(ignore_permissions=True)
			frappe.logger("alpinos").info("Updated '%s' print format." % PF_NAME)
	else:
		pf = frappe.get_doc({"doctype": "Print Format", "name": PF_NAME, **fields})
		pf.insert(ignore_permissions=True)
		frappe.logger("alpinos").info("Created '%s' print format." % PF_NAME)
