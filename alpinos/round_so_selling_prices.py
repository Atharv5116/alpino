"""One-time bulk fix: re-derive existing Sales Order amounts from selling_price x qty.

ERPNext stores the net rate at 2dp and computes amount = rate x qty, leaving stray paise in
the stored amount/rate. This resets each line's net amount to round(selling_price x qty /
(1 + gst%/100), 2), recomputes rate/tax and the order totals, and writes direct to the DB
(db_update, no doc.save()) so submitted orders update in place. Only orders whose stored
amount actually differs from the clean recompute are touched.

DRY-RUN by default:
  bench --site SITE execute alpinos.round_so_selling_prices.run
  bench --site SITE execute alpinos.round_so_selling_prices.run --kwargs '{"commit": true}'
"""

import frappe
from frappe.utils import flt

_TOL = 0.01


def diagnose(name):
	"""Per-line stored vs clean-recomputed amounts and order totals, without writing."""
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
				# old -> new net amount, plus the GST-inclusive amount (selling_price x qty)
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
