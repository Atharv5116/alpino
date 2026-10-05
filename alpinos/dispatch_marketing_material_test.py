"""Changes(HP) #62: Marketing Material on the Dispatch Report.

Run:  bench --site alpinos.test execute alpinos.dispatch_marketing_material_test.run

Unchecked (the default) Marketing Material counts for nothing -- not a row, not a quantity,
not a box. Checked, it is included but kept below its own separator rather than mixed into
Finished Goods. Fixtures are rolled back.
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
	from alpinos import dispatch_report_api as D

	tag = "MM" + frappe.generate_hash(length=4).upper()
	company = frappe.defaults.get_global_default("company")
	day = today()

	_assert(frappe.db.exists("Item Group", D.MARKETING_MATERIAL_GROUP),
		f"this site has no '{D.MARKETING_MATERIAL_GROUP}' Item Group")

	fg_group = frappe.db.get_value("Item", {"disabled": 0, "item_group": ["!=", D.MARKETING_MATERIAL_GROUP]}, "item_group")
	fg = _insert("Item", name=f"{tag}-FG", item_code=f"{tag}-FG", item_name=f"{tag} Finished",
		item_group=fg_group, stock_uom="Nos", disabled=0, custom_sequence=9001)
	mm = _insert("Item", name=f"{tag}-MM", item_code=f"{tag}-MM", item_name=f"{tag} Leaflet",
		item_group=D.MARKETING_MATERIAL_GROUP, stock_uom="Nos", disabled=0, custom_sequence=9002)

	so = _insert("Sales Order", name=f"SOMM-{tag}", docstatus=1, company=company,
		customer="__Test Customer", customer_name="__Test Customer", transaction_date=day)
	pl = _insert("Pick List", name=f"PLMM-{tag}", docstatus=1, company=company,
		custom_sales_order_id=so, purpose="Delivery", custom_total_box=12,
		custom_gross_weight=100)
	_insert("Pick List Item", name=f"PLIMM-{tag}-1", parent=pl, parenttype="Pick List",
		parentfield="locations", idx=1, docstatus=1, item_code=fg, qty=100,
		picked_qty=100, stock_qty=100, sales_order=so, custom_box=10)
	_insert("Pick List Item", name=f"PLIMM-{tag}-2", parent=pl, parenttype="Pick List",
		parentfield="locations", idx=2, docstatus=1, item_code=mm, qty=40,
		picked_qty=40, stock_qty=40, sales_order=so, custom_box=2)

	dn = _insert("Delivery Note", name=f"DNMM-{tag}", docstatus=1, company=company,
		customer="__Test Customer", posting_date=day, custom_dispatch_date=f"{day} 10:00:00",
		custom_sales_order_id=so, is_return=0)
	_insert("Delivery Note Item", name=f"DNIMM-{tag}-1", parent=dn, parenttype="Delivery Note",
		parentfield="items", idx=1, docstatus=1, item_code=fg, qty=100, stock_qty=100,
		against_sales_order=so, against_pick_list=pl)
	_insert("Delivery Note Item", name=f"DNIMM-{tag}-2", parent=dn, parenttype="Delivery Note",
		parentfield="items", idx=2, docstatus=1, item_code=mm, qty=40, stock_qty=40,
		against_sales_order=so, against_pick_list=pl)

	def _report(include_mm):
		return D.get_dispatch_report_data(date=day, include_marketing_material=include_mm)

	def _the_group_is_recognised():
		found = D._marketing_material_items()
		_assert(mm in found, "the Marketing Material item was not recognised by its group")
		_assert(fg not in found, "a Finished Goods item was treated as Marketing Material")

	check("#62 Marketing Material is identified by its Item Group",
		_the_group_is_recognised)

	def _by_default_it_is_not_in_the_grid():
		out = _report(0)
		codes = {i["item_code"] for i in out["items"]}
		_assert(fg in codes, "the Finished Goods item is missing from the grid")
		_assert(mm not in codes,
			"Marketing Material appears in the grid although the toggle is off")

	check("#62 unchecked, Marketing Material is not a row at all",
		_by_default_it_is_not_in_the_grid)

	def _by_default_it_is_in_no_total():
		off = _report(0)
		on = _report(1)
		_assert(on["summary"]["dispatch_total"] - off["summary"]["dispatch_total"] == 40,
			f"the 40 leaflets are not the difference: {off['summary']['dispatch_total']} vs "
			f"{on['summary']['dispatch_total']}")

	check("#62 unchecked, its quantity is in no summary total",
		_by_default_it_is_in_no_total)

	def _its_boxes_come_out_of_the_box_total_too():
		off = _report(0)
		on = _report(1)
		_assert(on["summary"]["total_box"] - off["summary"]["total_box"] == 2,
			f"the 2 Marketing Material boxes are not excluded: {off['summary']['total_box']} "
			f"vs {on['summary']['total_box']}")

	check("#62 unchecked, its boxes come out of the box total",
		_its_boxes_come_out_of_the_box_total_too)

	def _checked_it_appears_and_is_flagged():
		out = _report(1)
		rows = {i["item_code"]: i for i in out["items"]}
		_assert(mm in rows, "Marketing Material is missing although the toggle is on")
		_assert(rows[mm]["is_marketing_material"] == 1, "the row is not flagged")
		_assert(rows[fg]["is_marketing_material"] == 0, "a Finished Goods row was flagged")
		_assert(out["has_marketing_material"] == 1, "the payload does not announce it")

	check("#62 checked, it appears and is flagged for the separator",
		_checked_it_appears_and_is_flagged)

	def _checked_it_still_sits_below_the_finished_goods():
		out = _report(1)
		flags = [i["is_marketing_material"] for i in out["items"]]
		first_mm = flags.index(1) if 1 in flags else len(flags)
		_assert(all(f == 1 for f in flags[first_mm:]),
			"Marketing Material is interleaved with Finished Goods instead of grouped last")

	check("#62 checked, every Marketing Material row sits after the normal items",
		_checked_it_still_sits_below_the_finished_goods)
