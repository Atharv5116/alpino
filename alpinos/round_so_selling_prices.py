"""One-time bulk fix: re-sync EXISTING Sales Order amounts to their (2-dp) selling price.

The problem: custom_selling_price is a Currency field, which Frappe auto-rounds to 2 dp on
save. Older orders computed rate/amount/custom_item_tax from an UN-rounded price (e.g.
49.0033 fed back from the buyer catalogue) and only THEN did the save round the price field
to 49.00 — so the price shows a clean 49.00 while the stored amount still reflects 49.0033
(e.g. 5,880.40 instead of 5,880.00). The on-save fix rounds the price before computing, so
new/re-saved orders are clean; this cleans the ones already saved.

Per order: recompute each line with the SAME engine the entry page uses
(_calculate_sales_order_line_values, which rounds the price to 2 dp) and, where the stored
rate/amount differs, write the recomputed rate / amount / custom_item_tax and roll up the
header with calculate_taxes_and_totals(). Writes are DIRECT DB (db_update) — no doc.save(),
so no validate/on_update/notification hooks fire and submitted orders update in place. Any
sub-paise selling price (there shouldn't be any) is rounded too, and the buyer catalogue's
selling_rate is rounded.

DRY-RUN by default. Preview:  bench --site SITE execute alpinos.round_so_selling_prices.run
Commit:  bench --site SITE execute alpinos.round_so_selling_prices.run --kwargs "{'commit': True}"
Inspect one order:  bench --site SITE execute alpinos.round_so_selling_prices.diagnose --kwargs "{'name': 'SOR-...'}"

Only orders whose stored amount actually differs from the recompute are touched; clean
orders are skipped and never rewritten.
"""

import frappe
from frappe.utils import flt

_TOL = 0.01  # a line is "out of sync" if rate or amount differs by >= 1 paisa


def _recalc(row):
	from alpinos.sales_order_api import _calculate_sales_order_line_values

	return _calculate_sales_order_line_values(row)


def _out_of_sync(row, calc=None):
	"""Recomputing from the stored (2-dp) selling price would change this line -> its
	stored amount was computed from a pre-rounding price. Returns the calc, else None."""
	calc = calc or _recalc(row)
	if not calc["rate"] and not calc["amount"]:
		return None
	if abs(flt(calc["amount"]) - flt(row.amount)) >= _TOL or abs(flt(calc["rate"]) - flt(row.rate)) >= _TOL:
		return calc
	return None


def diagnose(name):
	"""Show, per line of one Sales Order, the stored vs recomputed rate/amount/tax so you
	can see where the stray paise live before running the bulk fix."""
	doc = frappe.get_doc("Sales Order", name)
	lines = []
	for r in doc.items:
		calc = _recalc(r)
		lines.append(
			{
				"item": r.item_code,
				"qty": flt(r.qty),
				"selling_price": flt(r.custom_selling_price),
				"stored_rate": flt(r.rate),
				"stored_amount": flt(r.amount),
				"stored_tax": flt(r.custom_item_tax),
				"recalc_rate": flt(calc["rate"]),
				"recalc_amount": flt(calc["amount"]),
				"recalc_tax": flt(calc.get("gst_amount")),
				"out_of_sync": bool(_out_of_sync(r, calc)),
			}
		)
	return {
		"order": name,
		"docstatus": doc.docstatus,
		"stored_grand": flt(doc.rounded_total or doc.grand_total),
		"lines": lines,
	}


def run(commit=False, limit=None, names=None):
	from alpinos.sales_order_api import _apply_calculated_item_values

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
	line_samples = []   # (order, item, old_amount -> new_amount)
	order_samples = []  # (order, docstatus, old_grand -> new_grand)

	for name in names:
		doc = frappe.get_doc("Sales Order", name)

		# Belt-and-suspenders: round any sub-paise selling price (normally none survive).
		for r in doc.items:
			if flt(r.custom_selling_price, 2) != flt(r.custom_selling_price):
				r.custom_selling_price = flt(r.custom_selling_price, 2)

		dirty_lines = []
		for r in doc.items:
			calc = _out_of_sync(r)
			if calc:
				dirty_lines.append((r, calc))
		if not dirty_lines:
			continue

		for r, calc in dirty_lines:
			lines_changed += 1
			if len(line_samples) < 25:
				line_samples.append((name, r.item_code, flt(r.amount), flt(calc["amount"])))

		before_grand = flt(doc.rounded_total or doc.grand_total)
		doc.ignore_pricing_rule = 1
		for row in doc.items:
			calc = _recalc(row)
			if not calc["rate"] and not calc["amount"]:
				continue
			if calc.get("gst_amount") is not None:
				row.custom_item_tax = flt(calc.get("gst_amount"))
			_apply_calculated_item_values(row, calc)
		if hasattr(doc, "calculate_taxes_and_totals"):
			doc.calculate_taxes_and_totals()

		after_grand = flt(doc.rounded_total or doc.grand_total)
		orders_changed += 1
		if len(order_samples) < 25:
			order_samples.append((name, doc.docstatus, before_grand, after_grand))

		if commit:
			for row in doc.items:
				row.db_update()
			for tax in doc.get("taxes") or []:
				tax.db_update()
			doc.db_update()

	# Buyer catalogue: round any selling_rate carrying sub-paise precision (full runs only).
	catalog_dirty = 0
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
	if commit:
		frappe.db.commit()

	result = {
		"mode": "COMMIT" if commit else "DRY-RUN (nothing written)",
		"targeted": targeted,
		"orders_scanned": len(names),
		"orders_changed": orders_changed,
		"lines_changed": lines_changed,
		"catalog_rows_to_round": catalog_dirty,
		"line_samples": line_samples,      # (order, item, old_amount -> new_amount)
		"order_samples": order_samples,    # (order, docstatus, old_grand -> new_grand)
	}
	frappe.logger("alpinos").info("round_so_selling_prices: %s", result)
	return result
