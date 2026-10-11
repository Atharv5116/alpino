"""Restate a Sales Order's amount in words and payment schedule from its own total.

On ERPNext 15 an order saved twice had its rate inflated by the margin ERPNext derived from
the "Standard Selling" price, and the amount in words and payment schedule were set from that
inflated total before alpinos.sales_order_api put the rates and totals back (fixed in
_apply_clean_gst_amounts). The totals were always right; only these two derived values were
not, e.g. a 38,280 order "Ninety Thousand, Eight Hundred And Forty only" with a 90,840
schedule. Neither is printed on the Sales Order format, no payment is recorded against an
order schedule, and no Sales Invoice is raised from them. Only orders whose stored figures
disagree with their total are written, without touching their modified time.
"""

import frappe
from frappe.utils import flt, money_in_words


def execute():
	fixed = 0
	for so in frappe.get_all(
		"Sales Order",
		filters={"docstatus": ["<", 2]},
		fields=["name", "company", "currency", "grand_total", "rounded_total", "disable_rounded_total",
		        "base_grand_total", "base_rounded_total", "in_words"],
	):
		total = flt(so.grand_total) if so.disable_rounded_total else flt(so.rounded_total or so.grand_total)
		base_total = flt(so.base_grand_total) if so.disable_rounded_total else flt(so.base_rounded_total or so.base_grand_total)
		changed = False

		in_words = money_in_words(total, so.currency)
		if (so.in_words or "") != in_words:
			company_currency = frappe.get_cached_value("Company", so.company, "default_currency")
			frappe.db.set_value("Sales Order", so.name, {
				"in_words": in_words,
				"base_in_words": money_in_words(base_total, company_currency),
			}, update_modified=False)
			changed = True

		for row in frappe.get_all(
			"Payment Schedule",
			filters={"parenttype": "Sales Order", "parent": so.name},
			fields=["name", "invoice_portion", "payment_amount", "paid_amount", "base_paid_amount"],
		):
			if not flt(row.invoice_portion):
				continue
			amount = flt(total * flt(row.invoice_portion) / 100, 2)
			if abs(amount - flt(row.payment_amount)) < 0.01:
				continue
			base_amount = flt(base_total * flt(row.invoice_portion) / 100, 2)
			frappe.db.set_value("Payment Schedule", row.name, {
				"payment_amount": amount,
				"base_payment_amount": base_amount,
				"outstanding": flt(amount - flt(row.paid_amount), 2),
				"base_outstanding": flt(base_amount - flt(row.base_paid_amount), 2),
			}, update_modified=False)
			changed = True

		fixed += changed
	if fixed:
		print(f"Sales Order amount in words / payment schedule restated on {fixed} orders")
