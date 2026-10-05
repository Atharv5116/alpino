"""Changes(HP) #54 and #55: Pick List column widths, and the FSN under the SKU for Flipkart.

Run:  bench --site alpinos.test execute alpinos.pick_list_fsn_test.run

#55 is the one with logic in it: the FSN belongs under the SKU for Flipkart and nowhere
else, because for any other customer type it is a number that means nothing to the picker.
The widths in #54 are CSS and are checked by their presence, not by rendering. Fixtures roll
back.
"""

import frappe
import io
import os

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


def _app_file(*parts):
	base = os.path.dirname(os.path.abspath(__file__))
	return os.path.join(base, *parts)


def _run():
	from alpinos.alpinos_development.page.pick_list_entry.pick_list_entry import (
		get_pick_list_data,
	)

	tag = "FSN" + frappe.generate_hash(length=4).upper()
	wh = frappe.db.get_value("Warehouse", {"is_group": 0}, ["name", "company"], as_dict=True)
	company = wh.company if wh else frappe.defaults.get_global_default("company")

	item = _insert("Item", name=f"{tag}-SKU", item_code=f"{tag}-SKU",
		item_name=f"{tag} Product", item_group=frappe.db.get_value("Item Group", {}, "name"),
		stock_uom="Nos", disabled=0, custom_fsn_no="JKHBHAJ78687698")

	def _pick_list_for(customer_type, suffix):
		so = _insert("Sales Order", name=f"SOFSN-{tag}-{suffix}", docstatus=1, company=company,
			customer="Cust", order_type=customer_type)
		pl = _insert("Pick List", name=f"PLFSN-{tag}-{suffix}", docstatus=1, company=company,
			custom_sales_order_id=so, purpose="Delivery")
		_insert("Pick List Item", name=f"PLIFSN-{tag}-{suffix}", parent=pl,
			parenttype="Pick List", parentfield="locations", idx=1, docstatus=1,
			item_code=item, qty=4, picked_qty=4, stock_qty=4, sales_order=so,
			custom_source_table="Items", warehouse=wh.name if wh else None)
		return pl

	flipkart = _pick_list_for("Flipkart", "FK")
	other = _pick_list_for("Reliance Retail", "RR")

	def _the_flipkart_order_is_recognised():
		data = get_pick_list_data(flipkart)
		_assert(data.get("is_flipkart") == 1,
			f"a Flipkart Pick List was not recognised: {data.get('custom_customer_type')!r}")

	check("#55 a Flipkart Pick List is recognised by its customer type",
		_the_flipkart_order_is_recognised)

	def _another_customer_type_is_not():
		data = get_pick_list_data(other)
		_assert(data.get("is_flipkart") == 0,
			f"a non-Flipkart order was treated as Flipkart: {data.get('custom_customer_type')!r}")

	check("#55 another customer type is not treated as Flipkart", _another_customer_type_is_not)

	def _the_fsn_rides_with_the_row():
		data = get_pick_list_data(flipkart)
		row = (data.get("locations") or [])[0]
		_assert(row.get("custom_fsn_no") == "JKHBHAJ78687698",
			f"the FSN did not reach the row: {row.get('custom_fsn_no')!r}")

	check("#55 the FSN is carried on the row for the page to show",
		_the_fsn_rides_with_the_row)

	def _the_page_only_draws_it_for_flipkart():
		js = io.open(_app_file("alpinos_development", "page", "pick_list_entry",
			"pick_list_entry.js"), encoding="utf-8").read()
		_assert("this_is_flipkart && row.custom_fsn_no" in js,
			"the SKU cell does not gate the FSN on the customer type")
		_assert("sku-fsn" in js, "the FSN line has no class to style")

	check("#55 the page draws the FSN only for Flipkart", _the_page_only_draws_it_for_flipkart)

	def _the_pdf_does_the_same():
		pf = io.open(_app_file("pick_list_print_format.py"), encoding="utf-8").read()
		_assert("_is_flipkart" in pf, "the PDF does not resolve the customer type")
		_assert("(FSN - " in pf, "the PDF does not print the FSN")
		_assert('custom_fsn_no") if _is_flipkart' in pf,
			"the PDF fetches the FSN regardless of customer type")

	check("#55 the PDF prints the FSN under the SKU, Flipkart only", _the_pdf_does_the_same)

	def _the_columns_were_resized():
		css = io.open(_app_file("alpinos_development", "page", "pick_list_entry",
			"pick_list_entry.html"), encoding="utf-8").read()
		for cls in ("col-sku", "col-qty", "col-box"):
			_assert(f".sku-table th.{cls}" in css, f"{cls} has no width rule")
		js = io.open(_app_file("alpinos_development", "page", "pick_list_entry",
			"pick_list_entry.js"), encoding="utf-8").read()
		for cls in ('class="col-sku"', 'class="col-qty"', 'class="col-box"'):
			_assert(cls in js, f"the table never uses {cls}")

	check("#54 the SKU, Qty and Box columns carry their new widths",
		_the_columns_were_resized)
