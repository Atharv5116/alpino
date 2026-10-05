"""Changes(HP) #58: the Sales Orders behind a Dispatch Report quantity.

Run:  bench --site alpinos.test execute alpinos.dispatch_breakup_test.run

The point of the check below is that the popup and the cell agree. The breakup is collected
by the same pass that builds the grid, so the two are compared directly rather than the
popup being trusted on its own. Fixtures roll back.
"""

import frappe
from frappe.utils import flt, today

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
	from alpinos import dispatch_report_api as D

	tag = "BRK" + frappe.generate_hash(length=4).upper()
	wh = frappe.db.get_value("Warehouse", {"is_group": 0}, ["name", "company"], as_dict=True)
	company = wh.company if wh else frappe.defaults.get_global_default("company")
	day = today()

	item = _insert("Item", name=f"{tag}-SKU", item_code=f"{tag}-SKU", item_name=f"{tag} Product",
		item_group=frappe.db.get_value("Item Group", {}, "name"), stock_uom="Nos",
		disabled=0, custom_sequence=9100)

	def _dispatched(suffix, qty, customer_name):
		so = _insert("Sales Order", name=f"SOBRK-{tag}-{suffix}", docstatus=1, company=company,
			customer="Cust", customer_name=customer_name, transaction_date=day)
		dn = _insert("Delivery Note", name=f"DNBRK-{tag}-{suffix}", docstatus=1,
			company=company, customer="Cust", posting_date=day,
			custom_dispatch_date=f"{day} 09:00:00", custom_sales_order_id=so, is_return=0)
		_insert("Delivery Note Item", name=f"DNIBRK-{tag}-{suffix}", parent=dn,
			parenttype="Delivery Note", parentfield="items", idx=1, docstatus=1,
			item_code=item, qty=qty, stock_qty=qty, against_sales_order=so)
		return so

	so_a = _dispatched("A", 80, "Reliance Retail Ltd.")
	so_b = _dispatched("B", 100, "Reliance Retail Ltd.")

	def _the_breakup_lists_both_orders():
		out = D.get_quantity_breakup(date=day, item_code=item, kind="dispatch")
		names = {r["sales_order"] for r in out["rows"]}
		_assert({so_a, so_b} <= names, f"both orders should appear: {names}")

	check("#58 the breakup lists every order behind the quantity",
		_the_breakup_lists_both_orders)

	def _it_carries_the_customer_and_the_quantity():
		out = D.get_quantity_breakup(date=day, item_code=item, kind="dispatch")
		by_so = {r["sales_order"]: r for r in out["rows"]}
		_assert(flt(by_so[so_a]["qty"]) == 80, f"{by_so[so_a]}")
		_assert(flt(by_so[so_b]["qty"]) == 100, f"{by_so[so_b]}")
		_assert(by_so[so_a]["customer"] == "Reliance Retail Ltd.",
			f"the customer name is missing: {by_so[so_a]}")

	check("#58 each row carries the order, the customer and its quantity",
		_it_carries_the_customer_and_the_quantity)

	def _the_breakup_total_matches_the_cell():
		"""The popup must agree with the number it was opened from."""
		report = D.get_dispatch_report_data(date=day, include_marketing_material=1)
		cell = next((i for i in report["items"] if i["item_code"] == item), None)
		_assert(cell, "the item is not in the report at all")
		out = D.get_quantity_breakup(date=day, item_code=item, kind="dispatch")
		_assert(flt(out["total"]) == flt(cell["today_dispatch"]),
			f"the popup totals {out['total']} but the cell shows {cell['today_dispatch']}")

	check("#58 the breakup total equals the quantity in the cell",
		_the_breakup_total_matches_the_cell)

	def _an_unrelated_item_returns_nothing():
		out = D.get_quantity_breakup(date=day, item_code=f"{tag}-NOT-AN-ITEM", kind="dispatch")
		_assert(out["rows"] == [] and out["total"] == 0, out)

	check("#58 an item with nothing behind it returns an empty breakup",
		_an_unrelated_item_returns_nothing)

	def _the_pending_section_has_its_own_breakup():
		so = _insert("Sales Order", name=f"SOBRK-{tag}-P", docstatus=1, company=company,
			customer="Cust", customer_name="Pending Buyer", transaction_date=day,
			# Pending means APPROVED and unfinished; Warehouse Approval Pending is
			# explicitly excluded, so an approved status is what belongs here.
			custom_workflow_status="Warehouse Approved",
			# status must be set: SQL NULL NOT IN (...) is never true, so a NULL-status
			# order silently drops out of the pending scan.
			status="To Deliver and Bill")
		_insert("Sales Order Item", name=f"SOIBRK-{tag}-P", parent=so, parenttype="Sales Order",
			parentfield="items", idx=1, docstatus=1, item_code=item, qty=25, stock_qty=25,
			rate=10, amount=250, conversion_factor=1, delivered_qty=0)
		out = D.get_quantity_breakup(date=day, item_code=item, kind="pending")
		names = {r["sales_order"] for r in out["rows"]}
		_assert(so in names, f"the pending order is missing from its own breakup: {names}")

	check("#58 the pending section has its own breakup, not the dispatch one",
		_the_pending_section_has_its_own_breakup)

	def _a_column_can_be_narrowed_to_its_customer_type():
		out_all = D.get_quantity_breakup(date=day, item_code=item, kind="dispatch")
		out_other = D.get_quantity_breakup(date=day, item_code=item, kind="dispatch",
			customer_type="A Customer Type That Does Not Exist")
		_assert(out_all["rows"], "the unfiltered breakup is empty")
		_assert(out_other["rows"] == [],
			f"narrowing to an unknown column still returned rows: {out_other['rows']}")

	check("#58 narrowing to one column returns only that column's orders",
		_a_column_can_be_narrowed_to_its_customer_type)
