"""One-time bulk fix: round custom_selling_price to 2 decimals on EXISTING Sales Orders.

Older orders stored the selling price with sub-paise precision (e.g. 49.0033 shown as
"49.00"), fed back from the buyer catalogue, so "selling price x qty" didn't tie out.
The on-save rounding fix only affects new/re-saved orders; this cleans the ones already
saved (all statuses).

Per order: round each line's custom_selling_price to 2 dp, then recompute rate / amount /
custom_item_tax with the SAME engine the entry page uses (_calculate_sales_order_line_values
+ _apply_calculated_item_values) and roll up the header with calculate_taxes_and_totals().
Writes are DIRECT DB (db_update) — no doc.save(), so no validate/on_update/notification
hooks fire and submitted orders can be updated in place. Also rounds the buyer catalogue's
selling_rate so the stray precision can't come back.

DRY-RUN by default. Preview first:
    bench --site SITE execute alpinos.round_so_selling_prices.run
Then commit:
    bench --site SITE execute alpinos.round_so_selling_prices.run --kwargs "{'commit': True}"

Only orders that actually have an un-rounded selling price are touched; already-clean
orders are skipped and never rewritten.
"""

import frappe
from frappe.utils import flt


def _needs_round(row):
	cur = flt(row.get("custom_selling_price"))
	return cur and flt(cur, 2) != cur


def run(commit=False, limit=None, names=None):
	from alpinos.sales_order_api import (
		_calculate_sales_order_line_values,
		_apply_calculated_item_values,
	)

	commit = str(commit).lower() in ("1", "true", "yes") if isinstance(commit, str) else bool(commit)
	targeted = bool(names)
	if names:
		if isinstance(names, str):
			names = [n.strip() for n in names.split(",") if n.strip()]
	else:
		names = frappe.get_all("Sales Order", pluck="name", order_by="creation asc")
	if limit:
		names = names[: int(limit)]

	orders_changed = 0
	lines_changed = 0
	line_samples = []   # (order, item, old_sp -> new_sp)
	order_samples = []  # (order, docstatus, old_grand -> new_grand)

	for name in names:
		doc = frappe.get_doc("Sales Order", name)
		to_round = [r for r in doc.items if _needs_round(r)]
		if not to_round:
			continue

		for r in to_round:
			old_sp = flt(r.custom_selling_price)
			r.custom_selling_price = flt(old_sp, 2)
			lines_changed += 1
			if len(line_samples) < 20:
				line_samples.append((name, r.item_code, old_sp, flt(r.custom_selling_price)))

		before_grand = flt(doc.rounded_total or doc.grand_total)

		# Recompute exactly like the entry page (minus tax-template re-derivation): keep the
		# order's existing taxes, just recompute line values off the rounded price + totals.
		doc.ignore_pricing_rule = 1
		for row in doc.items:
			calc = _calculate_sales_order_line_values(row)
			if not calc["rate"] and not calc["amount"]:
				continue
			if calc.get("gst_amount") is not None:
				row.custom_item_tax = flt(calc.get("gst_amount"))
			_apply_calculated_item_values(row, calc)
		if hasattr(doc, "calculate_taxes_and_totals"):
			doc.calculate_taxes_and_totals()

		after_grand = flt(doc.rounded_total or doc.grand_total)
		orders_changed += 1
		if len(order_samples) < 20:
			order_samples.append((name, doc.docstatus, before_grand, after_grand))

		if commit:
			for row in doc.items:
				row.db_update()
			for tax in doc.get("taxes") or []:
				tax.db_update()
			doc.db_update()

	# Buyer catalogue: round any selling_rate carrying sub-paise precision. Only in a
	# full run (skipped when specific order names are targeted).
	catalog_dirty = frappe.db.count(
		"Buyer Item",
		{"selling_rate": [">", 0]},
	)
	if not targeted:
		catalog_dirty = len(
			frappe.db.sql(
				"""SELECT name FROM `tabBuyer Item`
				   WHERE selling_rate IS NOT NULL AND selling_rate <> ROUND(selling_rate, 2)"""
			)
		)
		if commit and catalog_dirty:
			frappe.db.sql(
				"""UPDATE `tabBuyer Item`
				   SET selling_rate = ROUND(selling_rate, 2)
				   WHERE selling_rate IS NOT NULL AND selling_rate <> ROUND(selling_rate, 2)"""
			)
			frappe.db.commit()

	result = {
		"mode": "COMMIT" if commit else "DRY-RUN (nothing written)",
		"targeted": targeted,
		"orders_scanned": len(names),
		"orders_changed": orders_changed,
		"lines_changed": lines_changed,
		"catalog_rows_to_round": catalog_dirty,
		"line_samples": line_samples,
		"order_samples": order_samples,
	}
	frappe.logger("alpinos").info("round_so_selling_prices: %s", result)
	return result
