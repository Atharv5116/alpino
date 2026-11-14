"""Print Format "Offline Quotation": the buyer-facing Quotation PDF (doc Section 5, 22; W5).

It carries what 22 lists, where it applies: Quotation ID and Date, Buyer, Site, Billing / Shipping
Address, Order Items with prices and discounts, Marketing Freebies, Scheme Items, Additional Units
/ Damage, the totals (commercial total, net total, taxes, cash discount, Grand Total), the Payment
Term with the Partial schedule or the Credit date, and the Quotation Remarks. Never the Activity
Trail, payments received, proofs, SO Eligibility or internal names. It is printed for Draft,
Negotiation, Finalized and Sales Order Created Quotations; a Cancelled one prints a notice only
(A-29). The company block and the bank-details footer follow the earlier "Quotation" format.

Created / refreshed by after_migrate and made the Quotation's default print format.
"""

import frappe

PF_NAME = "Offline Quotation"

HTML = r"""
{%- macro money(v) -%}{{ frappe.utils.fmt_money(v or 0, currency=doc.currency or "INR") }}{%- endmacro -%}
{%- macro address(name) -%}
	{%- if name -%}
		{%- set a = frappe.db.get_value("Address", name, ["address_line1", "address_line2", "city", "state", "pincode"], as_dict=True) or {} -%}
		{{ [a.address_line1, a.address_line2, a.city, a.state, a.pincode] | select | reject("equalto", "N/A") | join(", ") }}
	{%- endif -%}
{%- endmacro -%}
{%- macro side_table(title, rows, extra_label, extra_field) -%}
	{%- set shown = rows | selectattr("item_code") | list -%}
	{%- if shown -%}
	<table>
		<thead>
			<tr><th colspan="4">{{ title }}</th></tr>
			<tr><th style="width:6%;">#</th><th>SKU - SKU Name</th><th class="num" style="width:12%;">Qty</th><th style="width:34%;">{{ extra_label }}</th></tr>
		</thead>
		<tbody>
		{%- for r in shown -%}
			<tr><td>{{ loop.index }}</td><td><b>{{ r.item_code }}</b>{% if r.item_name %} - {{ r.item_name }}{% endif %}</td>
				<td class="num">{{ frappe.utils.flt(r.qty) | int }}</td><td>{{ r.get(extra_field) or "" }}</td></tr>
		{%- endfor -%}
		</tbody>
	</table>
	{%- endif -%}
{%- endmacro -%}
{%- set status = doc.get("custom_quotation_status") or "" -%}
<style>
	@page { size: A4; margin: 10mm; }
	.oq { font-family: Arial, sans-serif; color: #000; font-size: 11px; }
	.oq h1 { font-size: 22px; font-weight: 800; text-align: center; margin: 0 0 10px; letter-spacing: .5px; }
	.oq table { width: 100%; border-collapse: collapse; margin-top: 10px; page-break-inside: auto; }
	.oq tr { page-break-inside: avoid; }
	.oq th, .oq td { border: 1px solid #000; padding: 5px 6px; vertical-align: top; }
	.oq th { background: #f3f3f3; text-align: left; font-weight: 800; }
	.oq .num { text-align: right; }
	.oq .lbl { font-size: 9px; font-weight: 800; text-transform: uppercase; }
	.oq .head td { border: 1px solid #000; }
	.oq .total td { font-weight: 800; }
	.oq .grand td { font-size: 13px; font-weight: 800; background: #f7f7f7; }
	.oq .note { margin-top: 10px; white-space: pre-wrap; }
</style>
<div class="oq">
{%- if status == "Cancelled" %}
	<h1>QUOTATION {{ doc.name }}</h1>
	<p>This Quotation is Cancelled. A cancelled Quotation has no PDF.</p>
{%- else %}
	{%- set company = frappe.get_doc("Company", doc.company) if doc.company else None -%}
	{%- set buyer = frappe.db.get_value("Buyer Master", doc.get("custom_buyer_master"), ["customer_business_name", "gst_type", "contact_no", "email"], as_dict=True) if doc.get("custom_buyer_master") else None -%}
	<h1>QUOTATION</h1>
	<table class="head">
		<tr>
			<td style="width:18%; text-align:center; vertical-align:middle;" rowspan="2">
				{%- if company and company.company_logo -%}<img src="{{ frappe.utils.get_url(company.company_logo) }}" style="max-height:60px; max-width:100%;">{%- endif -%}
			</td>
			<td style="width:42%;"><b style="font-size:14px;">{{ company.company_name if company else doc.company }}</b>
				{%- if doc.get("company_gstin") -%}<br>GSTIN: {{ doc.company_gstin }}{%- endif -%}</td>
			<td style="width:20%;"><span class="lbl">Quotation ID</span><br><b>{{ doc.name }}</b></td>
			<td style="width:20%;"><span class="lbl">Quotation Date</span><br><b>{{ frappe.utils.formatdate(doc.transaction_date, "dd-MM-yyyy") }}</b></td>
		</tr>
		<tr>
			<td colspan="3">{{ doc.get("company_address_display") or "" }}</td>
		</tr>
	</table>
	<table>
		<tr><th style="width:50%;">Bill To</th><th>Ship To</th></tr>
		<tr>
			<td>
				<span class="lbl">Buyer / Customer</span><br><b>{{ (buyer.customer_business_name if buyer else "") or doc.customer_name or doc.party_name }}</b><br>
				<span class="lbl">Site</span><br>{{ doc.get("custom_site_name") or "" }}<br>
				<span class="lbl">Billing Address</span><br>{{ address(doc.customer_address) }}
				{%- if doc.get("custom_billing_gstin") -%}<br><span class="lbl">Billing GSTIN</span> {{ doc.custom_billing_gstin }}{%- endif -%}
			</td>
			<td>
				<span class="lbl">Shipping Address</span><br>{{ address(doc.shipping_address_name) }}
			</td>
		</tr>
	</table>

	<table>
		<thead><tr>
			<th style="width:4%;">#</th><th>SKU - SKU Name</th><th class="num">Qty</th><th class="num">MRP</th>
			<th class="num">Selling Price</th><th class="num">Flat %</th><th class="num">Offer %</th><th class="num">Addl. %</th>
			<th class="num">Amount</th>
		</tr></thead>
		<tbody>
		{%- set ns = namespace(total=0) -%}
		{%- for row in doc.items -%}
			{%- set line = [(row.custom_selling_price or 0) * (row.qty or 0) * (1 - (row.custom_additional_discount or 0) / 100.0), 0] | max -%}
			{%- set ns.total = ns.total + line -%}
			<tr>
				<td>{{ row.idx }}</td>
				<td><b>{{ row.item_code }}</b>{% if row.item_name %} - {{ row.item_name }}{% endif %}</td>
				<td class="num">{{ frappe.utils.flt(row.qty) | int }}</td>
				<td class="num">{{ money(row.custom_mrp) }}</td>
				<td class="num">{{ money(row.custom_selling_price) }}</td>
				<td class="num">{{ "%.2f" | format(row.custom_flat_discount or 0) }}</td>
				<td class="num">{{ "%.2f" | format(row.custom_offer or 0) }}</td>
				<td class="num">{{ "%.2f" | format(row.custom_additional_discount or 0) }}</td>
				<td class="num">{{ money(line) }}</td>
			</tr>
		{%- endfor -%}
		</tbody>
		<tfoot>
			<tr class="total"><td colspan="8" class="num">Commercial Total (GST included)</td><td class="num">{{ money(ns.total) }}</td></tr>
			<tr><td colspan="8" class="num">Net Total (before GST)</td><td class="num">{{ money(doc.net_total) }}</td></tr>
			{%- for tax in doc.taxes or [] -%}
				{%- if tax.tax_amount -%}
				<tr><td colspan="8" class="num">{{ tax.description or tax.account_head }}</td><td class="num">{{ money(tax.tax_amount) }}</td></tr>
				{%- endif -%}
			{%- endfor -%}
			{%- if doc.discount_amount -%}
			<tr><td colspan="8" class="num">Cash Discount ({{ doc.get("custom_cash_discount") or 0 }}%)</td><td class="num">- {{ money(doc.discount_amount) }}</td></tr>
			{%- endif -%}
			<tr class="grand"><td colspan="8" class="num">Grand Total</td><td class="num">{{ money(doc.grand_total) }}</td></tr>
		</tfoot>
	</table>

	{{ side_table("Marketing Freebies", doc.get("custom_marketing_freebies") or [], "Remarks", "remarks") }}
	{{ side_table("Scheme Items", doc.get("custom_scheme_item_table") or [], "Scheme", "scheme") }}
	{%- if doc.get("custom_additional_units_damage") -%}
	{{ side_table("Additional Units / Damage", doc.get("custom_additional_units_damage_items") or [], "Remark", "remarks") }}
	{%- endif -%}

	{%- set term = doc.get("custom_payment_term") or "" -%}
	{%- if term -%}
	<table>
		<tr><th colspan="4">Payment Term: {{ term }}</th></tr>
		{%- if term == "Credit" -%}
			<tr><td colspan="4">
			{%- if doc.get("custom_expected_payment_date") -%}
				Expected Payment Date: <b>{{ frappe.utils.formatdate(doc.custom_expected_payment_date, "dd-MM-yyyy") }}</b>
			{%- else -%}
				Credit of {{ doc.get("custom_credit_days") or 0 }} days from the Quotation's finalization.
			{%- endif -%}
			</td></tr>
		{%- elif term == "Advance" -%}
			<tr><td colspan="4">Full payment of {{ money(doc.grand_total) }} in advance.</td></tr>
		{%- elif term == "Partial" -%}
			<tr><th style="width:8%;">Row</th><th>Payment Term</th><th>Expected Payment Date</th><th class="num">Expected Amount</th></tr>
			{%- for r in doc.get("custom_payment_schedule") or [] -%}
			<tr><td>{{ loop.index }}</td><td>{{ r.payment_term }}</td>
				<td>{{ frappe.utils.formatdate(r.expected_payment_date, "dd-MM-yyyy") if r.expected_payment_date else "" }}</td>
				<td class="num">{{ money(r.expected_amount) }}</td></tr>
			{%- endfor -%}
		{%- endif -%}
	</table>
	{%- endif -%}

	{%- if doc.get("custom_quotation_remarks") -%}
	<table><tr><th>Quotation Remarks</th></tr><tr><td class="note">{{ doc.custom_quotation_remarks }}</td></tr></table>
	{%- endif -%}

	<table>
		<tr><th colspan="2">Bank Details</th></tr>
		<tr><td style="width:35%;"><b>Bank Name</b></td><td>Axis Bank Ltd.</td></tr>
		<tr><td><b>Branch</b></td><td>Surat</td></tr>
		<tr><td><b>Account Name</b></td><td>Alpino Health Foods Pvt. Ltd.</td></tr>
		<tr><td><b>Account Number</b></td><td>919020040914629</td></tr>
		<tr><td><b>IFSC Code</b></td><td>UTIB0000047</td></tr>
	</table>
	<table>
		<tr><td style="text-align:center;">Subject to Surat Jurisdiction only.</td></tr>
		<tr><td style="text-align:center;"><b>Thank you for helping making India Protein Sufficient Nation!</b></td></tr>
	</table>
{%- endif %}
</div>
"""


def execute():
	fields = {
		"doc_type": "Quotation",
		"module": "Alpinos Development",
		"standard": "No",
		"custom_format": 1,
		"print_format_type": "Jinja",
		"html": HTML,
		"disabled": 0,
	}
	if frappe.db.exists("Print Format", PF_NAME):
		pf = frappe.get_doc("Print Format", PF_NAME)
		if not all(pf.get(k) == v for k, v in fields.items()):
			pf.update(fields)
			pf.save(ignore_permissions=True)
	else:
		frappe.get_doc({"doctype": "Print Format", "name": PF_NAME, **fields}).insert(ignore_permissions=True)

	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	if frappe.get_meta("Quotation").default_print_format != PF_NAME:
		make_property_setter("Quotation", None, "default_print_format", PF_NAME, "Data", for_doctype=True)
		frappe.clear_cache(doctype="Quotation")
