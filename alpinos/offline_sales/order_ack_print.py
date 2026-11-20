"""Print Format "Buyer Order Request Acknowledgement" (doc Section 2, 5.2).

One layout, two formats: on Quotation (a request is a Draft Quotation since the Opportunity was
skipped, 20 Nov 2026) and on Opportunity (requests made before that keep their acknowledgement).

Generated for every portal submission and emailed to the buyer. It shows the BOR reference,
the request as the buyer sent it, and the doc's footer; it is not a quotation or invoice.
Created / refreshed by after_migrate (the app's print formats are kept in code).
"""

import frappe

PF_NAME = "Buyer Order Request Acknowledgement"
PF_NAME_QUOTATION = "Buyer Order Request Acknowledgement (Quotation)"


def print_format_for(doctype):
	return PF_NAME_QUOTATION if doctype == "Quotation" else PF_NAME

HTML = r"""
{%- macro address(name) -%}
	{%- if name -%}
		{%- set a = frappe.db.get_value("Address", name, ["address_line1", "address_line2", "city", "state", "pincode"], as_dict=True) or {} -%}
		{{ [a.address_line1, a.address_line2, a.city, a.state, a.pincode] | select | reject("equalto", "N/A") | join(", ") }}
	{%- endif -%}
{%- endmacro -%}
{%- set is_q = doc.doctype == "Quotation" -%}
{%- set billing = doc.customer_address if is_q else doc.custom_billing_address -%}
{%- set shipping = doc.shipping_address_name if is_q else doc.customer_address -%}
{%- set customer_type = doc.order_type if is_q else doc.custom_order_type -%}
{%- set remarks = doc.custom_quotation_remarks if is_q else doc.custom_common_remark -%}
{%- set buyer = frappe.db.get_value("Buyer Master", doc.party_name, ["customer_business_name", "customer", "gst_no"], as_dict=True) or {} -%}
{%- set gstin = doc.get("custom_billing_gstin") or buyer.gst_no or "" -%}
<style>
	.bor-ack { font-size: 12px; }
	.bor-ack h2 { font-size: 18px; margin: 0 0 4px; }
	.bor-ack table { width: 100%; border-collapse: collapse; margin-top: 10px; }
	.bor-ack th, .bor-ack td { border: 1px solid #ccc; padding: 5px 6px; }
	.bor-ack th { background: #f3f3f3; text-align: left; }
	.bor-ack .num { text-align: right; }
	.bor-ack .meta td { border: none; padding: 2px 6px 2px 0; vertical-align: top; }
	.bor-ack .foot { margin-top: 18px; font-style: italic; }
</style>
<div class="bor-ack">
	<h2>Order Request Acknowledgement</h2>
	<div>Reference: <b>{{ doc.custom_buyer_order_request_ref or "" }}</b>
		&nbsp;&middot;&nbsp; Submitted: {{ frappe.utils.format_datetime(doc.creation, "dd-MM-yyyy HH:mm") }}</div>
	<table class="meta">
		<tr><td width="22%">Customer</td><td><b>{{ buyer.customer_business_name or buyer.customer or doc.party_name }}</b></td></tr>
		<tr><td>Customer Type</td><td>{{ customer_type or "" }}</td></tr>
		<tr><td>Billing Address</td><td>{{ address(billing) }}</td></tr>
		<tr><td>Billing GSTIN</td><td>{{ gstin }}</td></tr>
		<tr><td>Shipping Address</td><td>{{ address(shipping) }}</td></tr>
		<tr><td>Contact Person</td><td>{{ doc.custom_request_contact_person or "" }}</td></tr>
		<tr><td>Order Remarks</td><td>{{ remarks or "" }}</td></tr>
	</table>
	<table>
		<thead><tr>
			<th>#</th><th>Product SKU</th><th>Product Name</th><th class="num">MRP</th><th class="num">Flat Discount %</th>
			<th class="num">Selling Price</th><th class="num">Quantity</th><th class="num">Item Amount</th>
		</tr></thead>
		<tbody>
		{%- set ns = namespace(total=0) -%}
		{%- for row in doc.items -%}
			{%- set amount = ((row.qty or 0) * (row.custom_selling_price or 0)) if is_q else (row.custom_line_amount or ((row.qty or 0) * (row.custom_selling_price or 0))) -%}
			{%- set ns.total = ns.total + amount -%}
			<tr>
				<td>{{ loop.index }}</td><td>{{ row.item_code }}</td><td>{{ row.item_name or "" }}</td>
				<td class="num">{{ frappe.utils.fmt_money(row.custom_mrp or 0, currency="INR") }}</td>
				<td class="num">{{ "%.2f" | format(row.custom_flat_discount or 0) }}</td>
				<td class="num">{{ frappe.utils.fmt_money(row.custom_selling_price or 0, currency="INR") }}</td>
				<td class="num">{{ (row.qty or 0) | int }}</td>
				<td class="num">{{ frappe.utils.fmt_money(amount, currency="INR") }}</td>
			</tr>
		{%- endfor -%}
		</tbody>
		<tfoot>
			<tr><td colspan="7" class="num"><b>Sub Total</b></td><td class="num"><b>{{ frappe.utils.fmt_money(ns.total, currency="INR") }}</b></td></tr>
			<tr><td colspan="7" class="num"><b>Net Total</b></td><td class="num"><b>{{ frappe.utils.fmt_money(ns.total, currency="INR") }}</b></td></tr>
		</tfoot>
	</table>
	<div class="foot">This is an order request acknowledgement, not a final commercial tax invoice/quotation.</div>
</div>
"""


def execute():
	for name, doctype in ((PF_NAME, "Opportunity"), (PF_NAME_QUOTATION, "Quotation")):
		fields = {
			"doc_type": doctype,
			"module": "Alpinos Development",
			"standard": "No",
			"custom_format": 1,
			"print_format_type": "Jinja",
			"html": HTML,
			"disabled": 0,
		}
		if frappe.db.exists("Print Format", name):
			pf = frappe.get_doc("Print Format", name)
			if all(pf.get(k) == v for k, v in fields.items()):
				continue
			pf.update(fields)
			pf.save(ignore_permissions=True)
		else:
			frappe.get_doc({"doctype": "Print Format", "name": name, **fields}).insert(ignore_permissions=True)
