"""
Partial Dispatch — cumulative qty ledger + over-dispatch guards.

An SO with custom_partial_order_allowed = 1 may be fulfilled over several Pick List
/ Delivery Note rounds. The one hard rule (Hetvi): the SUM of dispatched qty per SKU
across ALL rounds must never exceed the ordered qty (ordered 30 -> all partials <= 30).

Everything here is gated on is_partial_order() for the cumulative behaviour, so plain
(offline / non-partial) orders are completely unaffected. The single-PL lock is the
one rule that applies to non-partial orders (spec: only one PL when partial not allowed).

Qty is keyed per SKU:
  - ordered   = SUM(Sales Order Item.qty)                  (main order lines)
  - committed = SUM(Pick List Item.qty)  across non-cancelled PLs of the SO
  - dispatched= SUM(Delivery Note Item.qty) across submitted DNs of the SO
  - remaining = ordered - committed
Only SKUs present in the ordered map are guarded (freebies / bundle components are
not order lines and are left to the existing per-row / box-multiple checks).
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

_EPS = 1e-6


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------
def is_partial_order(sales_order) -> bool:
	if not sales_order:
		return False
	return bool(cint(frappe.db.get_value("Sales Order", sales_order, "custom_partial_order_allowed")))


# ---------------------------------------------------------------------------
# Per-SKU qty maps
# ---------------------------------------------------------------------------
def ordered_qty_by_sku(sales_order) -> dict:
	# Combo/bundle SO lines carry the combo SKU (e.g. PB-CHCR-1000x2), but the
	# Pick List and Delivery Note carry the EXPLODED component SKUs. Explode the
	# ordered map to components too, so committed/dispatched line up — otherwise a
	# fully-picked combo order never matches, leaving a phantom "remaining qty"
	# and blocking auto-completion.
	from alpinos.sales_order_api import _bundle_components

	rows = frappe.db.sql(
		"SELECT item_code, SUM(qty) q FROM `tabSales Order Item` WHERE parent=%s GROUP BY item_code",
		(sales_order,), as_dict=True,
	)
	out = {}
	for r in rows:
		if not r.item_code:
			continue
		comps = _bundle_components(r.item_code)
		if comps:
			for c in comps:
				out[c.item] = out.get(c.item, 0.0) + flt(r.q) * flt(c.base_qty)
		else:
			out[r.item_code] = out.get(r.item_code, 0.0) + flt(r.q)
	return out


def committed_pl_qty_by_sku(sales_order, exclude_pl=None) -> dict:
	"""Sum of Pick List Item qty across non-cancelled Pick Lists of the SO."""
	params = {"so": sales_order}
	excl = ""
	if exclude_pl:
		excl = "AND pl.name != %(excl)s"
		params["excl"] = exclude_pl
	rows = frappe.db.sql(
		f"""
		SELECT pli.item_code, SUM(pli.qty) q
		FROM `tabPick List Item` pli
		INNER JOIN `tabPick List` pl ON pl.name = pli.parent
		WHERE pl.custom_sales_order_id = %(so)s AND pl.docstatus < 2 {excl}
		GROUP BY pli.item_code
		""",
		params, as_dict=True,
	)
	return {r.item_code: flt(r.q) for r in rows if r.item_code}


def dispatched_qty_by_sku(sales_order, exclude_dn=None) -> dict:
	"""Sum of Delivery Note Item qty across submitted DNs of the SO."""
	params = {"so": sales_order}
	excl = ""
	if exclude_dn:
		excl = "AND dn.name != %(excl)s"
		params["excl"] = exclude_dn
	rows = frappe.db.sql(
		f"""
		SELECT dni.item_code, SUM(dni.qty) q
		FROM `tabDelivery Note Item` dni
		INNER JOIN `tabDelivery Note` dn ON dn.name = dni.parent
		WHERE dn.custom_sales_order_id = %(so)s AND dn.docstatus = 1 AND IFNULL(dn.is_return,0)=0 {excl}
		GROUP BY dni.item_code
		""",
		params, as_dict=True,
	)
	return {r.item_code: flt(r.q) for r in rows if r.item_code}


def remaining_qty_by_sku(sales_order, exclude_pl=None) -> dict:
	"""ordered - committed (>= 0), per ordered SKU. Basis for 'Create PL for Remaining'."""
	ordered = ordered_qty_by_sku(sales_order)
	committed = committed_pl_qty_by_sku(sales_order, exclude_pl=exclude_pl)
	return {sku: max(flt(oq) - flt(committed.get(sku, 0)), 0.0) for sku, oq in ordered.items()}


def has_remaining_qty(sales_order) -> bool:
	return any(v > _EPS for v in remaining_qty_by_sku(sales_order).values())


# ---------------------------------------------------------------------------
# Coverage / completion
# ---------------------------------------------------------------------------
def committed_covers_ordered(sales_order) -> bool:
	"""True when the non-cancelled Pick Lists already cover the full ordered qty."""
	ordered = ordered_qty_by_sku(sales_order)
	committed = committed_pl_qty_by_sku(sales_order)
	return bool(ordered) and all(flt(committed.get(sku, 0)) + _EPS >= flt(oq) for sku, oq in ordered.items())


def so_fully_dispatched(sales_order) -> bool:
	"""True when submitted DNs cover the full ordered qty for every SKU."""
	ordered = ordered_qty_by_sku(sales_order)
	dispatched = dispatched_qty_by_sku(sales_order)
	return bool(ordered) and all(flt(dispatched.get(sku, 0)) + _EPS >= flt(oq) for sku, oq in ordered.items())


def is_partial_round(sales_order) -> bool:
	"""Partial order that isn't yet fully covered by its Pick Lists -> partial statuses."""
	return is_partial_order(sales_order) and not committed_covers_ordered(sales_order)


# ---------------------------------------------------------------------------
# Guards (doc_events)
# ---------------------------------------------------------------------------
def apply_partial_future_dispatch(sales_order, future_date, reason=None):
	"""Record the Future Dispatch Date for the remaining qty (short-pick modal ->
	Partial). Reschedules the SO's dispatch date and logs the reason."""
	if not sales_order or not future_date:
		return
	frappe.db.set_value(
		"Sales Order", sales_order,
		{"custom_dispatch_date": future_date, "custom_expected_dispatch_date": future_date},
		update_modified=False,
	)
	frappe.get_doc("Sales Order", sales_order).add_comment(
		"Comment",
		_("Partial dispatch — remaining qty scheduled for {0}.{1}").format(
			future_date, (_(" Reason: {0}.").format(reason) if reason else "")
		),
	)
	from alpinos import so_notifications as son
	son.safe(lambda: son.n13_partial_initiated(sales_order, future_date))


def _rows_qty_by_sku(rows) -> dict:
	agg = {}
	for r in rows or []:
		if r.get("item_code"):
			agg[r.item_code] = agg.get(r.item_code, 0.0) + flt(r.get("qty"))
	return agg


def validate_pick_list_partial(doc, method=None):
	"""Block a 2nd PL when partial isn't allowed, and enforce the cumulative
	committed-qty <= ordered-qty guard per SKU across all Pick Lists of the SO."""
	if doc.docstatus == 2:
		return
	so = doc.get("custom_sales_order_id")
	if not so:
		return

	# Force-closed orders are permanently locked — no NEW Pick List (the PL that
	# enacted the close is submitted before the flag is set, so it isn't blocked).
	if doc.is_new() and frappe.db.get_value("Sales Order", so, "custom_force_closed"):
		frappe.throw(
			_("This order has been Force Closed. No new Pick List can be created."),
			title=_("Order Force Closed"),
		)

	other_active_pl = frappe.db.exists(
		"Pick List",
		{"custom_sales_order_id": so, "docstatus": ["<", 2], "name": ["!=", doc.name or ""]},
	)

	# Single-PL lock for non-partial orders.
	if not is_partial_order(so) and other_active_pl:
		frappe.throw(
			_("Sales Order {0} does not allow partial dispatch — only one Pick List is permitted. "
			  "Enable 'Partial Order Allowed' on the order to split it.").format(frappe.bold(so)),
			title=_("Partial Dispatch Not Allowed"),
		)

	# Cumulative over-dispatch guard (only meaningful once more than one round exists).
	if not other_active_pl:
		return
	ordered = ordered_qty_by_sku(so)
	committed_others = committed_pl_qty_by_sku(so, exclude_pl=doc.name)
	this = _rows_qty_by_sku(doc.get("locations"))
	for sku, q in this.items():
		if sku not in ordered:
			continue  # freebie / bundle component — not an order line
		allowed = flt(ordered[sku])
		already = flt(committed_others.get(sku, 0))
		if already + flt(q) > allowed + _EPS:
			frappe.throw(
				_("SKU {0}: total picked across all Pick Lists ({1}) would exceed the ordered qty ({2}). "
				  "Remaining allowed this round: {3}.").format(
					frappe.bold(sku), already + flt(q), allowed, max(allowed - already, 0)),
				title=_("Over-Dispatch Blocked"),
			)


def validate_delivery_note_partial(doc, method=None):
	"""Enforce cumulative dispatched-qty <= ordered-qty per SKU across all DNs of the SO.

	Gated to partial orders: a non-partial (offline) order has one DN and may carry
	same-SKU freebie top-ups whose qty legitimately exceeds the ordered line qty, so
	the cumulative guard must not run there."""
	if doc.docstatus == 2 or doc.get("is_return"):
		return
	so = doc.get("custom_sales_order_id")
	if not so or not is_partial_order(so):
		return
	ordered = ordered_qty_by_sku(so)
	if not ordered:
		return
	dispatched_others = dispatched_qty_by_sku(so, exclude_dn=doc.name)
	this = _rows_qty_by_sku(doc.get("items"))
	for sku, q in this.items():
		if sku not in ordered:
			continue
		allowed = flt(ordered[sku])
		already = flt(dispatched_others.get(sku, 0))
		if already + flt(q) > allowed + _EPS:
			frappe.throw(
				_("SKU {0}: total dispatched across all Delivery Notes ({1}) would exceed the ordered qty ({2}). "
				  "Remaining allowed: {3}.").format(
					frappe.bold(sku), already + flt(q), allowed, max(allowed - already, 0)),
				title=_("Over-Dispatch Blocked"),
			)
