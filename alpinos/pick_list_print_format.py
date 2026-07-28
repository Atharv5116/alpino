"""Pick List packing / picking sheet print format.

Replicates the customer's reference sheet — a header block of box / weight / unit totals
plus party / PO / transporter / date, then an item grid (SR · SKU · Qty · Box · Sample Qty
· Batch Code · MFG · EXP · Stock) — but lists ONLY the items actually on this Pick List
(doc.locations). The reference is a master sheet pre-printed with every SKU; here we print
just what is picked.

Registered idempotently on every migrate as a custom Jinja Print Format named
"Pick List Packing Sheet" for the "Pick List" doctype.
"""

import frappe

PF_NAME = "Pick List Packing Sheet"
DOC_TYPE = "Pick List"

_HTML = r"""
<style>
  .plps { font-family: Arial, Helvetica, sans-serif; color: #000; font-size: 11px; }
  .plps table { border-collapse: collapse; width: 100%; }
  .plps .hdr td { border: 1px solid #000; padding: 3px 8px; vertical-align: top; }
  .plps .hdr .lbl { font-weight: bold; text-align: right; width: 16%; white-space: nowrap; }
  .plps .hdr .val { width: 34%; font-weight: bold; }
  .plps .hdr .lbl2 { font-weight: bold; width: 16%; }
  .plps .hdr .val2 { width: 34%; }
  .plps .hl { background: #ffff00; }
  .plps .items { margin-top: 8px; }
  .plps .items th, .plps .items td { border: 1px solid #000; padding: 4px 8px; text-align: left; }
  .plps .items th { background: #f0f0f0; font-size: 10px; text-transform: uppercase; }
  .plps .items td.sku { font-weight: bold; }
</style>
<div class="plps">
  <table class="hdr">
    <tr><td class="lbl">ACTUAL BOX</td><td class="val">{{ doc.custom_actual_box if doc.custom_actual_box is not none else "" }}</td>
        <td class="lbl2">QC Attended By</td><td class="val2">{{ doc.custom_qc_attended_by or "" }}</td></tr>
    <tr><td class="lbl">SAMPLE BOX</td><td class="val">{{ doc.custom_sample_box if doc.custom_sample_box is not none else "" }}</td><td></td><td></td></tr>
    <tr><td class="lbl">SAMPLE WEIGHT</td><td class="val">{{ doc.custom_sample_weight if doc.custom_sample_weight is not none else "" }}</td><td></td><td></td></tr>
    <tr><td class="lbl">TOTAL BOX</td><td class="val hl">{{ doc.custom_total_box or 0 }}</td><td></td><td></td></tr>
    <tr><td class="lbl">GROSS WEIGHT</td><td class="val">{{ "%.2f"|format(doc.custom_gross_weight or 0) }}</td><td></td><td></td></tr>
    <tr><td class="lbl">TOTAL UNITS</td><td class="val">{{ doc.custom_total_unit or 0 }}</td><td></td><td></td></tr>
    <tr><td class="lbl">PO NO.</td><td class="val">{{ doc.custom_po_no or "" }}</td><td></td><td></td></tr>
    <tr><td class="lbl">TRANSPORTER</td><td class="val">{{ doc.custom_transporter or "" }}</td><td></td><td></td></tr>
    <tr><td class="lbl">PARTY NAME</td><td class="val">{{ doc.custom_customer_name or "" }}</td>
        <td class="lbl2">PARTY CODE</td><td class="val2">{{ doc.custom_party_code or "" }}</td></tr>
    <tr><td class="lbl">DATE</td><td class="val">{{ frappe.utils.formatdate(doc.custom_order_date, "dd-MM-yyyy") if doc.custom_order_date else "" }}</td><td></td><td></td></tr>
  </table>

  <table class="items">
    <thead>
      <tr>
        <th style="width:5%;">SR.</th>
        <th style="width:20%;">SKU</th>
        <th style="width:15%; white-space:nowrap;">{{ doc.name }}</th>
        <th style="width:7%;">{{ (doc.custom_total_unit | round | int) if doc.custom_total_unit else 0 }}</th>
        <th style="width:10%;">SAMPLE QTY</th>
        <th style="width:15%;">BATCH CODE</th>
        <th style="width:10%;">MFG</th>
        <th style="width:10%;">EXP</th>
        <th style="width:8%;">STOCK</th>
      </tr>
    </thead>
    <tbody>
      {% for row in doc.locations %}
      <tr>
        <td>{{ loop.index }}</td>
        <td class="sku">{{ row.item_code }}</td>
        <td>{{ (row.qty | round | int) if row.qty else "" }}</td>
        <td>{{ (row.custom_box | round | int) if row.custom_box else "" }}</td>
        <td>{{ (row.custom_sample_quantity | round | int) if row.custom_sample_quantity else "" }}</td>
        <td>{{ row.custom_batch_code or row.batch_no or "" }}</td>
        <td>{{ frappe.utils.formatdate(row.custom_mfg_date, "dd-MM-yyyy") if row.custom_mfg_date else "" }}</td>
        <td>{{ frappe.utils.formatdate(row.custom_expiry_date, "dd-MM-yyyy") if row.custom_expiry_date else "" }}</td>
        <td>{{ available_stock(row.item_code) }}</td>
      </tr>
      {% endfor %}
    </tbody>
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
