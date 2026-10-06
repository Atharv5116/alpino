"""The Pick List sticker carries the Buyer Master ID, not the customer name.

Run:  bench --site alpinos.test execute alpinos.pick_list_sticker_buyer_test.run

The warehouse matches a box to an account by ID, and two sites of one chain can share a
name. The Pick List does not hold the Buyer Master, so it is resolved through the order --
and where there is none, the customer name is kept rather than leaving a blank line on a box
somebody has to act on. Fixtures roll back.
"""

import frappe
from frappe.utils import today

RES = []


def check(label, fn):
	try:
		fn()
		RES.append(("PASS", label, ""))
	except AssertionError as e:
		RES.append(("FAIL", label, str(e)))
	except Exception as e:
		RES.append(("ERROR", label, f"{type(e).__name__}: {e}"))


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


def _insert(doctype, **values):
	doc = frappe.get_doc(dict(doctype=doctype, **values))
	doc.flags.ignore_mandatory = True
	doc.flags.ignore_validate = True
	doc.db_insert()
	return doc.name


def run():
	RES.clear()
	frappe.set_user("Administrator")
	real_commit = frappe.db.commit
	frappe.db.commit = lambda *a, **k: None
	try:
		_run()
	finally:
		frappe.db.commit = real_commit
		frappe.db.rollback()
		frappe.set_user("Administrator")

	width = max(len(r[1]) for r in RES)
	for status, label, detail in RES:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in RES if r[0] == 'PASS')}/{len(RES)} passed")
	return RES


def _run():
	from alpinos.pick_list_api import _buyer_master_id, _collect_pick_list_stickers

	tag = "STK" + frappe.generate_hash(length=4).upper()
	wh = frappe.db.get_value("Warehouse", {"is_group": 0}, ["name", "company"], as_dict=True)
	company = wh.company if wh else frappe.defaults.get_global_default("company")
	item = frappe.db.get_value("Item", {"disabled": 0}, "name")

	buyer = _insert("Buyer Master", name=f"{tag}-OBM", customer_business_name=f"{tag} Chain",
		channel="Offline")

	def _pick_list(suffix, with_buyer=True):
		so = _insert("Sales Order", name=f"SOSTK-{tag}-{suffix}", docstatus=1, company=company,
			customer="Cust", customer_name=f"{tag} Printed Name", transaction_date=today(),
			custom_offline_buyer_master=(buyer if with_buyer else None))
		pl = _insert("Pick List", name=f"PLSTK-{tag}-{suffix}", docstatus=1, company=company,
			custom_sales_order_id=so, purpose="Delivery",
			custom_customer_name=f"{tag} Printed Name", custom_po_no=f"PO-{suffix}",
			custom_gate="G-3")
		_insert("Pick List Item", name=f"PLISTK-{tag}-{suffix}", parent=pl,
			parenttype="Pick List", parentfield="locations", idx=1, docstatus=1,
			item_code=item, qty=10, picked_qty=10, stock_qty=10, sales_order=so,
			custom_source_table="Items", custom_box=2, warehouse=wh.name if wh else None)
		return pl

	with_buyer = _pick_list("A", with_buyer=True)
	without_buyer = _pick_list("B", with_buyer=False)

	def _the_buyer_master_resolves_through_the_order():
		doc = frappe.get_doc("Pick List", with_buyer)
		_assert(_buyer_master_id(doc) == buyer,
			f"the Buyer Master did not resolve: {_buyer_master_id(doc)!r}")

	check("the Buyer Master ID resolves through the Sales Order",
		_the_buyer_master_resolves_through_the_order)

	def _the_sticker_prints_the_id_not_the_name():
		stickers = _collect_pick_list_stickers(frappe.get_doc("Pick List", with_buyer))
		_assert(stickers, "no stickers were produced")
		for s in stickers:
			_assert(s["party_name"] == buyer,
				f"the sticker shows {s['party_name']!r}, expected the Buyer Master ID {buyer}")
			_assert(f"{tag} Printed Name" != s["party_name"],
				"the sticker is still showing the customer name")

	check("the sticker prints the Buyer Master ID instead of the customer name",
		_the_sticker_prints_the_id_not_the_name)

	def _every_box_of_the_pick_carries_it():
		stickers = _collect_pick_list_stickers(frappe.get_doc("Pick List", with_buyer))
		_assert(len(stickers) == 2, f"two boxes expected, got {len(stickers)}")
		_assert({s["party_name"] for s in stickers} == {buyer},
			"not every box carries the ID")

	check("every box of the pick carries it", _every_box_of_the_pick_carries_it)

	def _an_order_with_no_buyer_master_keeps_the_name():
		stickers = _collect_pick_list_stickers(frappe.get_doc("Pick List", without_buyer))
		_assert(stickers, "no stickers were produced")
		_assert(stickers[0]["party_name"] == f"{tag} Printed Name",
			f"a box with no Buyer Master should keep the name, got "
			f"{stickers[0]['party_name']!r} -- a blank line on a box is worse")

	check("an order with no Buyer Master keeps the customer name rather than printing blank",
		_an_order_with_no_buyer_master_keeps_the_name)

	def _the_other_sticker_fields_are_untouched():
		stickers = _collect_pick_list_stickers(frappe.get_doc("Pick List", with_buyer))
		s = stickers[0]
		_assert(s["po_no"] == "PO-A", f"the PO number changed: {s['po_no']}")
		_assert(s["dispatch_area"] == "G-3", f"the gate changed: {s['dispatch_area']}")
		_assert(s["total_box"] == 2 and s["box_index"] == 1,
			f"the box numbering changed: {s['box_index']} of {s['total_box']}")

	check("the rest of the sticker is untouched", _the_other_sticker_fields_are_untouched)
