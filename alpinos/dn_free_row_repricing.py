"""Take the charge for free rows off Delivery Notes made before they stopped being priced.

Until 76685a8, Marketing Freebies / Scheme / Additional Units rows reached a Delivery Note
with rate 0 but no price_list_rate, so ERPNext priced them from the Item Price list: the
note charged list price plus GST for samples the order never bills, and its grand total
ran above the order's (SOR-2627-02828: order 47,416.80, note 51,327.36). New notes carry
price_list_rate 0; this corrects the notes already made.

Each note is corrected on its OWN lines: the free rows go to 0 and the totals are
re-derived exactly as a save derives them (ERPNext's calculation, then the Sales Order
alignment). A part delivery therefore keeps its own share -- nothing is set to the
order's total. A note is only rewritten when that same calculation, run with the free
rows untouched, reproduces its stored totals, so the free rows are the only thing that
can move; a note that does not is listed for review and left alone.

What copied the old total is restated too: the Post Dispatch rows raised from the note,
and the order's Total Invoice Value.

  bench --site SITE execute alpinos.dn_free_row_repricing.run                         (dry run)
  bench --site SITE execute alpinos.dn_free_row_repricing.run --kwargs "{'apply': 1}"
"""

import frappe
from frappe.utils import flt

FREE_TABLES = (
	"Sales Order Marketing Freebie",
	"Sales Order Scheme Item",
	"Sales Order Additional Units Item",
)

# Every price field a free row can carry on a Delivery Note Item.
_PRICE_FIELDS = (
	"price_list_rate", "base_price_list_rate",
	"margin_rate_or_amount", "rate_with_margin", "base_rate_with_margin",
	"discount_percentage", "discount_amount", "distributed_discount_amount",
	"rate", "base_rate", "net_rate", "base_net_rate", "stock_uom_rate",
	"amount", "base_amount", "net_amount", "base_net_amount",
)

_TOTALS = (
	"total", "net_total", "total_taxes_and_charges", "discount_amount",
	"grand_total", "rounded_total",
)

# A row is free when it was mapped from one of the free tables, or when the Pick List row
# it was picked on says it came from one (a row picked outside the order's Items table).
_FREE_ROW_SQL = """
	(
		EXISTS (SELECT 1 FROM `tabSales Order Marketing Freebie` f WHERE f.name = dni.so_detail)
		OR EXISTS (SELECT 1 FROM `tabSales Order Scheme Item` s WHERE s.name = dni.so_detail)
		OR EXISTS (SELECT 1 FROM `tabSales Order Additional Units Item` a WHERE a.name = dni.so_detail)
		OR EXISTS (SELECT 1 FROM `tabPick List Item` pli WHERE pli.name = dni.pick_list_item
		           AND IFNULL(pli.custom_source_table, 'Items') NOT IN ('', 'Items'))
	)
"""


def affected_notes():
	"""Non-return Delivery Notes (draft or submitted) with a free row that carries a price."""
	return frappe.db.sql(
		f"""
		SELECT DISTINCT dn.name
		FROM `tabDelivery Note Item` dni
		JOIN `tabDelivery Note` dn ON dn.name = dni.parent
		WHERE dn.docstatus < 2 AND IFNULL(dn.is_return, 0) = 0
		  AND (IFNULL(dni.amount, 0) <> 0 OR IFNULL(dni.rate, 0) <> 0
		       OR IFNULL(dni.price_list_rate, 0) <> 0)
		  AND {_FREE_ROW_SQL}
		ORDER BY dn.name
		""",
		pluck="name",
	)


def _free_row_names(delivery_note):
	return set(
		frappe.db.sql(
			f"""
			SELECT dni.name FROM `tabDelivery Note Item` dni
			WHERE dni.parent = %s AND {_FREE_ROW_SQL}
			""",
			delivery_note,
			pluck="name",
		)
	)


def _totals(doc):
	return {f: flt(doc.get(f), 2) for f in _TOTALS}


def _recalculate(doc):
	"""The value part of a Delivery Note save, without the rest of validate."""
	from alpinos.delivery_note_hooks import _align_value_with_sales_order

	doc.calculate_taxes_and_totals()
	_align_value_with_sales_order(doc)


def _sales_orders_of(doc):
	names = {(doc.get("custom_sales_order_id") or "").strip()}
	names.update(row.against_sales_order for row in doc.items if row.get("against_sales_order"))
	names.discard("")
	names.discard(None)
	return names


def reprice(delivery_note, apply=False):
	"""Correct one note. Returns what happened to it (and writes only when apply)."""
	doc = frappe.get_doc("Delivery Note", delivery_note)
	stored = _totals(doc)
	free = _free_row_names(delivery_note)
	rows = [r for r in doc.items if r.name in free]
	if not rows:
		return {"delivery_note": delivery_note, "status": "no free rows"}

	# Guard: the same calculation over the untouched note must give back what is stored.
	# If it does not, the note was changed some other way, and rewriting it would move
	# more than the free rows.
	_recalculate(doc)
	recomputed = _totals(doc)
	drift = {f: (stored[f], recomputed[f]) for f in _TOTALS if abs(stored[f] - recomputed[f]) > 0.005}
	if drift:
		return {"delivery_note": delivery_note, "status": "review", "drift": drift}

	charged = flt(sum(flt(r.amount) for r in rows), 2)
	for row in rows:
		for field in _PRICE_FIELDS:
			if row.meta.has_field(field):
				row.set(field, 0)
	_recalculate(doc)
	if hasattr(doc, "set_total_in_words"):
		doc.set_total_in_words()
	after = _totals(doc)

	result = {
		"delivery_note": delivery_note,
		"status": "corrected" if apply else "would correct",
		"docstatus": doc.docstatus,
		"free_rows": len(rows),
		"free_rows_charged": charged,
		"old_grand_total": stored["grand_total"],
		"new_grand_total": after["grand_total"],
		"sales_orders": sorted(_sales_orders_of(doc)),
	}
	if not apply:
		return result

	# Selling values only: a Delivery Note posts stock at valuation, so no ledger moves.
	doc.db_update()
	for row in list(doc.items) + list(doc.get("taxes") or []):
		row.db_update()
	doc.add_comment(
		"Info",
		"Free rows (Marketing Freebies / Scheme / Additional Units) had been priced from the "
		"Item Price list; {0} row(s), {1} before GST, set to 0. Grand total {2} -> {3}.".format(
			len(rows),
			frappe.format_value(charged, {"fieldtype": "Currency"}),
			frappe.format_value(stored["grand_total"], {"fieldtype": "Currency"}),
			frappe.format_value(after["grand_total"], {"fieldtype": "Currency"}),
		),
	)
	return result


def run(apply=0):
	"""Correct every affected note, then restate Post Dispatch and the orders' value."""
	from alpinos.so_invoice_value import (
		refresh_for_sales_order,
		refresh_post_dispatch_for_delivery_note,
	)

	apply = bool(int(apply))
	results = [reprice(name, apply=apply) for name in affected_notes()]
	fixed = [r for r in results if r["status"] in ("corrected", "would correct")]
	review = [r for r in results if r["status"] == "review"]

	orders = sorted({so for r in fixed for so in r["sales_orders"]})
	post_dispatch_rows = 0
	if apply:
		for r in fixed:
			post_dispatch_rows += refresh_post_dispatch_for_delivery_note(r["delivery_note"])
		for so in orders:
			refresh_for_sales_order(so)
		frappe.db.commit()

	return {
		"mode": "APPLY" if apply else "DRY-RUN",
		"notes_with_priced_free_rows": len(results),
		"corrected": len(fixed),
		"overcharge_removed_before_gst": flt(sum(r["free_rows_charged"] for r in fixed), 2),
		"grand_total_removed": flt(sum(r["old_grand_total"] - r["new_grand_total"] for r in fixed), 2),
		"sales_orders_restated": len(orders),
		"post_dispatch_rows_restated": post_dispatch_rows,
		"left_for_review": review,
		"notes": fixed[:50],
	}
