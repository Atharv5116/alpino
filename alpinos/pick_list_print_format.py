"""Pick List packing sheet print format (custom Jinja, registered on migrate)."""

import frappe

PF_NAME = "Pick List Packing Sheet"
DOC_TYPE = "Pick List"

_HTML = r"""
<style>
  /* Page margins. Frappe reads margin-* ONLY from a top-level .print-format rule and
     hands them to wkhtmltopdf as the page margins (default 15mm). The same rule would
     also be a real CSS margin on the element, so it is cancelled for print and for the
     on-screen preview below. */
  .print-format { margin-top: 5mm; margin-bottom: 5mm; margin-left: 5mm; margin-right: 5mm; }
  @media print { .print-format { margin: 0 !important; } }
  @media screen { .print-format { margin: auto !important; } }

  /* wkhtmltopdf shrinks the page by roughly 0.78, so these sizes print at about 12px. */
  .plps { font-family: Arial, Helvetica, sans-serif; color: #000; font-size: 16px; line-height: 1.3; }
  .plps table { border-collapse: collapse; width: 100%; table-layout: fixed; margin: 0; }
  /* Frappe forces padding and vertical-align on every print cell with !important. */
  .print-format .plps td, .print-format .plps th {
    border: 1px solid #000; padding: 7px 6px !important; vertical-align: middle !important;
    text-align: center; word-wrap: break-word; overflow: hidden;
  }
  .plps .lbl { font-weight: bold; }
  .plps .val { font-weight: bold; }
  /* Frappe greys print table headings; black reads better on paper. */
  .print-format .plps th { font-size: 14px; font-weight: bold !important; text-transform: uppercase; color: #000 !important; background: none !important; }
  .plps td.sku { font-weight: bold; }
  .plps .items { margin-top: -1px; }
  .plps .gap td { height: 22px; }
  .plps .bundle { font-size: 12px; font-weight: normal; }
</style>
<div class="plps">
  <!-- ===== header block: label | value | label | value (as the reference sheet) ===== -->
  <table class="head">
    <colgroup>
      <col style="width:22%"><col style="width:21%"><col style="width:15%"><col style="width:22%"><col style="width:20%">
    </colgroup>
    <tr>
      <td class="lbl">QC Attended By</td>
      <td colspan="2" class="val">{{ doc.custom_qc_attended_by or "" }}</td>
      <td class="lbl">ACTUAL BOX</td>
      <td class="val">{{ (doc.custom_actual_box | round | int) if doc.custom_actual_box is not none else "" }}</td>
    </tr>
    <tr>
      <td class="lbl">PO NO.</td>
      <td colspan="2" class="val">{{ doc.custom_po_no or "" }}</td>
      <td class="lbl">SAMPLE BOX</td>
      <td class="val">{{ (doc.custom_sample_box | round | int) if doc.custom_sample_box else "" }}</td>
    </tr>
    <tr>
      <td class="lbl">TRANSPORTER</td>
      <td colspan="2" class="val">{{ doc.custom_transporter or "" }}</td>
      <td class="lbl">SAMPLE WEIGHT</td>
      <td class="val">{{ ("%.2f"|format(doc.custom_sample_weight)) if doc.custom_sample_weight else "" }}</td>
    </tr>
    <tr>
      <td class="lbl">PARTY NAME</td>
      <td colspan="2" class="val">{{ doc.custom_customer_name or "" }}</td>
      <td class="lbl">TOTAL BOX</td>
      <td class="val">{{ (doc.custom_total_box | round | int) if doc.custom_total_box is not none else 0 }}</td>
    </tr>
    <tr>
      <td class="lbl">PARTY CODE</td>
      <td colspan="2" class="val">{{ (frappe.db.get_value("Sales Order", doc.custom_sales_order_id, "po_no") if doc.custom_sales_order_id else "") or doc.custom_customer_name or doc.custom_party_code or "" }}</td>
      <td class="lbl">GROSS WEIGHT</td>
      <td class="val">{{ "%.2f"|format(doc.custom_gross_weight or 0) }}</td>
    </tr>
    <tr>
      <td class="lbl">Sales Order ID</td>
      <td colspan="2" class="val">{{ doc.custom_sales_order_id or "" }}</td>
      <td class="lbl">TOTAL UNITS</td>
      <td class="val">{{ (doc.custom_total_unit | round | int) if doc.custom_total_unit is not none else 0 }}</td>
    </tr>
    <tr>
      <td colspan="2" class="lbl">DATE</td>
      <td colspan="3" class="val">{{ frappe.utils.formatdate(doc.custom_order_date, "dd-MM-yyyy") if doc.custom_order_date else "" }}</td>
    </tr>
  </table>

  <!-- ===== items ===== -->
  <table class="items">
    <colgroup>
      <col style="width:6%">   <!-- SR -->
      <col style="width:15%">  <!-- SKU -->
      <col style="width:9%">   <!-- SKU NO -->
      <col style="width:7%">   <!-- QTY -->
      <col style="width:7%">   <!-- BOX -->
      <col style="width:12%">  <!-- SAMPLE QTY -->
      <col style="width:15%">  <!-- BATCH CODE -->
      <col style="width:14%">  <!-- MFG -->
      <col style="width:14%">  <!-- EXP -->
    </colgroup>
    <tr class="gap"><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td></tr>
    <tr>
      <th>SR.</th>
      <th>SKU</th>
      <th>SKU NO</th>
      <th>QTY</th>
      <th>BOX</th>
      <th>SAMPLE QTY</th>
      <th>BATCH CODE</th>
      <th>MFG</th>
      <th>EXP</th>
    </tr>

    <!-- item rows (only what is on this Pick List), ascending by SKU No -->
    {% for row in sort_locations_by_sku(doc.locations) %}
    {# Sample rows (marketing freebies / scheme / additional units) show their picked qty
       in the Sample Qty column; the main Qty column stays empty for them. #}
    {% set _is_sample = row.custom_source_table in ['Marketing Freebies', 'Scheme Table', 'Additional Units'] %}
    <tr>
      <td>{{ loop.index }}</td>
      <td class="sku">{{ row.item_code }}{% if row.custom_bundle_parent %}<div class="bundle">&#8627; {{ row.custom_bundle_parent }}</div>{% endif %}</td>
      <td class="sku">{{ frappe.db.get_value("Item", row.item_code, "custom_sku_no") or "" }}</td>
      <td>{{ (row.qty | round | int) if (row.qty and not _is_sample) else "" }}</td>
      <td>{{ (row.custom_box | round | int) if row.custom_box else "" }}</td>
      <td>{{ (row.qty | round | int) if (row.qty and _is_sample) else "" }}</td>
      <td>{{ row.custom_batch_code or row.batch_no or "" }}</td>
      <td>{{ frappe.utils.formatdate(row.custom_mfg_date, "dd-MM-yyyy") if row.custom_mfg_date else "" }}</td>
      <td>{{ frappe.utils.formatdate(row.custom_expiry_date, "dd-MM-yyyy") if row.custom_expiry_date else "" }}</td>
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
