"""Stock reservation across the Pick List -> Delivery Note flow, on top of
ERPNext's native Stock Reservation Entry (SRE).

Rules:
1. When a Pick List is created, reserve the **Sales Order** quantity for each
   picked stock item (an SRE against the SO, sourced from this Pick List).
2. The Delivery Note submission deducts stock natively for the picked qty and
   consumes the matching reservation.
3. Whatever was reserved but not delivered (SO qty - delivered qty) is released
   right after the Delivery Note is submitted.

Cancelling the Pick List releases its reservations too.
"""

import frappe
from frappe.utils import flt


def enable_stock_reservation():
	"""Turn on native stock reservation site-wide. Idempotent; run on migrate."""
	ss = frappe.get_single("Stock Settings")
	changed = False
	if not ss.get("enable_stock_reservation"):
		ss.enable_stock_reservation = 1
		changed = True
	if not ss.get("allow_partial_reservation"):
		ss.allow_partial_reservation = 1
		changed = True
	if changed:
		ss.save(ignore_permissions=True)
		frappe.db.commit()


def _reservation_enabled():
	return bool(frappe.db.get_single_value("Stock Settings", "enable_stock_reservation"))


def reserve_for_pick_list(doc, method=None):
	"""On Pick List creation: reserve the Sales Order qty for each picked stock
	item (rule 1)."""
	if doc.docstatus != 0 or not _reservation_enabled():
		return

	from erpnext.stock.doctype.stock_reservation_entry.stock_reservation_entry import (
		create_stock_reservation_entries_for_so_items,
		has_reserved_stock,
	)

	# Group the Pick List rows by their Sales Order.
	by_so = {}
	for row in doc.get("locations") or []:
		so = row.get("sales_order")
		so_item = row.get("sales_order_item")
		# Need a real SO line + warehouse, and a stock item (skip bundles/samples
		# that don't carry stock or a direct SO line).
		if not so or not so_item or not row.get("warehouse"):
			continue
		if not frappe.db.get_value("Item", row.get("item_code"), "is_stock_item"):
			continue
		by_so.setdefault(so, []).append(row)

	for so_name, rows in by_so.items():
		# Don't double-reserve if the order already has reservations.
		if has_reserved_stock("Sales Order", so_name):
			continue
		so_doc = frappe.get_doc("Sales Order", so_name)
		items_details = []
		for row in rows:
			so_qty = flt(frappe.db.get_value("Sales Order Item", row.sales_order_item, "qty"))
			if so_qty <= 0:
				continue
			items_details.append({
				"sales_order_item": row.sales_order_item,
				"warehouse": row.warehouse,
				"qty_to_reserve": so_qty,  # reserve the full SO qty (rule 1)
				"from_voucher_no": doc.name,
				"from_voucher_detail_no": row.name,
			})
		if not items_details:
			continue
		try:
			create_stock_reservation_entries_for_so_items(
				sales_order=so_doc,
				items_details=items_details,
				from_voucher_type="Pick List",
				notify=False,
			)
		except Exception:
			frappe.log_error(title="Stock reservation failed for Pick List {0}".format(doc.name))


def release_pick_list_reservation(pick_list):
	"""Release any still-reserved (not yet delivered) SREs sourced from this Pick
	List. Used on Pick List cancel and to release leftovers after a DN."""
	if not _reservation_enabled() or not pick_list:
		return
	from erpnext.stock.doctype.stock_reservation_entry.stock_reservation_entry import (
		cancel_stock_reservation_entries,
	)
	try:
		# Skips entries already fully "Delivered"; cancels the undelivered balance.
		cancel_stock_reservation_entries(
			from_voucher_type="Pick List", from_voucher_no=pick_list, notify=False
		)
	except Exception:
		frappe.log_error(title="Release reservation failed for Pick List {0}".format(pick_list))


def release_leftover_after_delivery_note(doc, method=None):
	"""After a Delivery Note is submitted (rule 3): the delivered qty has consumed
	its reservation; release the remaining SO-vs-PL difference."""
	if doc.get("is_return") or not _reservation_enabled():
		return
	pick_lists = {row.get("against_pick_list") for row in (doc.get("items") or []) if row.get("against_pick_list")}
	for pl in pick_lists:
		release_pick_list_reservation(pl)


def release_for_cancelled_pick_list(doc, method=None):
	"""When a Pick List is cancelled, release its reservations."""
	release_pick_list_reservation(doc.name)
