"""One-time bulk fix: re-derive EXISTING Sales Order amounts from selling_price x qty.

Problem: ERPNext stores the net rate at 2 dp (49 / 1.05 = 46.6667 -> 46.67) and computes
`amount = rate x qty`, so 46.67 x 120 = 5,600.40 -> 5,880.40 incl, instead of the clean
49 x 120 = 5,880.00. The stray paise live in the stored amount/rate, not the (already
2-dp) selling price.

Fix (matches the save-time behaviour in sales_order_api._apply_clean_gst_amounts): for
each line set net amount = round(selling_price x qty / (1 + gst%/100), 2), recompute rate
and custom_item_tax, then recompute the order totals (net_total, the On-Net-Total GST rows
IGST/CGST+SGST, grand_total, rounded_total). Writes are DIRECT DB (db_update) -- no
doc.save(), so no validate/notification hooks fire and submitted orders update in place.

This CHANGES order grand totals (each affected order drops a few paise to ~1 rupee) --
that is the point (removing the accumulated rounding). Only orders whose stored amount
actually differs from the clean recompute are touched.

DRY-RUN by default.
  Preview:  bench --site SITE execute alpinos.round_so_selling_prices.run
  Commit :  bench --site SITE execute alpinos.round_so_selling_prices.run --kwargs '{"commit": true}'
  Inspect:  bench --site SITE execute alpinos.round_so_selling_prices.diagnose --kwargs '{"name": "SOR-..."}'
"""

import frappe
from frappe.utils import flt

_TOL = 0.01


def diagnose(name):
	"""Show, per line, the stored vs clean-recomputed amount, and the order totals before
	vs after, without writing anything."""
	from alpinos.sales_order_api import _apply_clean_gst_amounts

	doc = frappe.get_doc("Sales Order", name)
	before = {r.name: (flt(r.amount), flt(r.rate), flt(r.custom_item_tax)) for r in doc.items}
	before_totals = {
		"net_total": flt(doc.net_total),
		"total_taxes": flt(doc.total_taxes_and_charges),
		"grand_total": flt(doc.grand_total),
		"rounded_total": flt(doc.rounded_total),
	}
	_apply_clean_gst_amounts(doc)
	lines = []
	for r in doc.items:
		old_amt, old_rate, old_tax = before.get(r.name, (0, 0, 0))
		lines.append(
			{
				"item": r.item_code,
				"qty": flt(r.qty),
				"selling_price": flt(r.custom_selling_price),
				"stored_amount": old_amt,
				"clean_amount": flt(r.amount),
				"stored_tax": old_tax,
				"clean_tax": flt(r.custom_item_tax),
				"changes": abs(flt(r.amount) - old_amt) >= _TOL,
			}
		)
	doc.reload()  # discard the in-memory recompute; nothing written
	return {
		"order": name,
		"docstatus": doc.docstatus,
		"totals_before": before_totals,
		"totals_after": {
			"net_total": flt(doc.net_total),  # reloaded == before; 'after' shown via lines
		},
		"lines": lines,
	}


def run(commit=False, limit=None, names=None, full=False):
	from alpinos.sales_order_api import _apply_clean_gst_amounts

	commit = str(commit).lower() in ("1", "true", "yes") if isinstance(commit, str) else bool(commit)
	full = str(full).lower() in ("1", "true", "yes") if isinstance(full, str) else bool(full)
	cap = 100000 if full else 25
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
	line_samples = []
	order_samples = []

	for name in names:
		doc = frappe.get_doc("Sales Order", name)
		before_amt = {r.name: flt(r.amount) for r in doc.items}
		before_grand = flt(doc.rounded_total or doc.grand_total)

		_apply_clean_gst_amounts(doc)

		changed = [r for r in doc.items if abs(flt(r.amount) - before_amt.get(r.name, 0)) >= _TOL]
		if not changed:
			continue

		after_grand = flt(doc.rounded_total or doc.grand_total)
		orders_changed += 1
		lines_changed += len(changed)
		for r in changed:
			if len(line_samples) < cap:
				# stored NET amount old -> new, and the GST-INCLUSIVE amount shown on the
				# screen/PDF (selling_price x qty) so it can be cross-checked with the view.
				incl = flt(flt(r.custom_selling_price) * flt(r.qty), 2)
				line_samples.append(
					(name, r.item_code, before_amt.get(r.name, 0), flt(r.amount), incl)
				)
		if len(order_samples) < cap:
			order_samples.append((name, doc.docstatus, before_grand, after_grand))

		if commit:
			for r in doc.items:
				r.db_update()
			for tax in doc.get("taxes") or []:
				tax.db_update()
			doc.db_update()

	if commit:
		frappe.db.commit()

	result = {
		"mode": "COMMIT" if commit else "DRY-RUN (nothing written)",
		"targeted": targeted,
		"orders_scanned": len(names),
		"orders_changed": orders_changed,
		"lines_changed": lines_changed,
		# (order, item, old_net_amount, new_net_amount, inclusive_amount = selling_price x qty)
		"line_samples": line_samples,
		"order_samples": order_samples,    # (order, docstatus, old_grand -> new_grand)
	}
	frappe.logger("alpinos").info("round_so_selling_prices: %s", result)
	return result
