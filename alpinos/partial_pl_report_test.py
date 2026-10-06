"""Changes(HP) #63: a partially dispatched order reports each part on its own.

Run:  bench --site alpinos.test execute alpinos.partial_pl_report_test.run

    "If Part 1 contains SKU-A = 100 Qty and Part 2 contains SKU-A = 50 Qty, the report
     should show 100 against Part 1 and 50 against Part 2, not 150 on either part."

The three symptoms the ticket lists are each a check here: Part 1's invoice number leaking
onto Part 2, Part 2's dispatch date overwriting Part 1's, and the quantities merging.
Fixtures are rolled back.
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
	from alpinos.alpinos_development.report.accounts_format_report import (
		accounts_format_report as R,
	)

	tag = "P63" + frappe.generate_hash(length=4).upper()
	company = frappe.defaults.get_global_default("company")
	item = frappe.db.get_value("Item", {"disabled": 0}, "name")
	_assert(item, "no item on this site")

	so = _insert("Sales Order", name=f"SO63-{tag}", docstatus=1, company=company,
		customer="__Test Customer", customer_name="__Test Customer",
		transaction_date=today(), custom_dispatch_date="2026-10-01",
		custom_invoice_no="INV-PART-ONE", status="To Deliver and Bill")
	_insert("Sales Order Item", name=f"SOI63-{tag}", parent=so, parenttype="Sales Order",
		parentfield="items", idx=1, docstatus=1, item_code=item, qty=150, stock_qty=150,
		rate=10, amount=1500, conversion_factor=1, delivered_qty=0)

	def _part(suffix, qty, dispatch_date, invoice=None):
		pl = _insert("Pick List", name=f"PL63-{tag}-{suffix}", docstatus=1, company=company,
			custom_sales_order_id=so, custom_dispatch_date=dispatch_date,
			custom_invoice_no=invoice, purpose="Delivery", custom_total_box=qty / 10)
		_insert("Pick List Item", name=f"PLI63-{tag}-{suffix}", parent=pl,
			parenttype="Pick List", parentfield="locations", idx=1, docstatus=1,
			item_code=item, qty=qty, picked_qty=qty, stock_qty=qty, sales_order=so,
			custom_source_table="Items", custom_box=qty / 10)
		return pl

	# Part 1 shipped 100 on 1 Oct and is invoiced. Part 2 shipped 50 on 5 Oct, not yet.
	part1 = _part("A", 100, "2026-10-01", invoice="INV-PART-ONE")
	part2 = _part("B", 50, "2026-10-05", invoice=None)

	def _the_parts_are_found_oldest_first():
		parts = R._submitted_parts(so)
		_assert([p["name"] for p in parts] == [part1, part2],
			f"parts came back in the wrong order: {[p['name'] for p in parts]}")

	check("#63 the order's parts are listed oldest dispatch first",
		_the_parts_are_found_oldest_first)

	def _each_part_reports_its_own_quantity():
		whole = R._picklist_map(so)
		_assert(whole[(item, "Items")].qty == 150,
			f"the unscoped map should still total 150: {whole[(item, 'Items')].qty}")
		one = R._picklist_map(so, part1)
		two = R._picklist_map(so, part2)
		_assert(one[(item, "Items")].qty == 100,
			f"Part 1 reports {one[(item, 'Items')].qty}, expected 100")
		_assert(two[(item, "Items")].qty == 50,
			f"Part 2 reports {two[(item, 'Items')].qty}, expected 50")

	check("#63 each part reports its own quantity, never the merged total",
		_each_part_reports_its_own_quantity)

	def _an_uninvoiced_part_shows_no_invoice_number():
		parts = {p["name"]: p for p in R._submitted_parts(so)}
		_assert(R._part_invoice_no(parts[part1]) == "INV-PART-ONE",
			f"Part 1 lost its invoice: {R._part_invoice_no(parts[part1])}")
		_assert(R._part_invoice_no(parts[part2]) == "",
			f"Part 2 carries Part 1's invoice: {R._part_invoice_no(parts[part2])!r}")

	check("#63 a part with no invoice of its own shows a blank, not Part 1's number",
		_an_uninvoiced_part_shows_no_invoice_number)

	def _each_part_keeps_its_own_dispatch_date():
		parts = {p["name"]: p for p in R._submitted_parts(so)}
		so_doc = frappe.get_doc("Sales Order", so)
		d1 = str(R._part_dispatch_date(parts[part1], so_doc))
		d2 = str(R._part_dispatch_date(parts[part2], so_doc))
		_assert(d1.startswith("2026-10-01"), f"Part 1's dispatch date is {d1}")
		_assert(d2.startswith("2026-10-05"), f"Part 2's dispatch date is {d2}")
		_assert(d1 != d2, "both parts report the same dispatch date")

	check("#63 each part keeps its own dispatch date", _each_part_keeps_its_own_dispatch_date)

	def _the_header_totals_belong_to_the_part():
		h1 = R._pl_header(so, part1)
		h2 = R._pl_header(so, part2)
		_assert(h1["total_box"] == 10, f"Part 1 box total {h1['total_box']}, expected 10")
		_assert(h2["total_box"] == 5, f"Part 2 box total {h2['total_box']}, expected 5")
		whole = R._pl_header(so)
		_assert(whole["total_box"] == 15,
			f"the unscoped header should still total 15: {whole['total_box']}")

	check("#63 box and weight totals belong to the part, not the whole order",
		_the_header_totals_belong_to_the_part)

	def _the_report_emits_both_parts():
		rows = R._get_data(frappe._dict({
			"from_date": "2026-09-01", "to_date": "2026-10-31",
			"sales_order": so, "show_all": 1,
		}))
		mine = [r for r in rows if r.get("sales_order_id") == so]
		_assert(mine, "the order produced no rows at all")
		dates = {r.get("dispatch_date") for r in mine}
		_assert(len(dates) == 2, f"both parts should appear with their own dates: {dates}")
		invoices = {r.get("invoice_no") for r in mine}
		_assert("" in invoices,
			f"no row has a blank invoice; Part 2 is carrying one: {invoices}")
		units = sorted(r.get("unit") for r in mine if r.get("unit"))
		_assert(units == [50, 100] or units == [50.0, 100.0],
			f"quantities are {units}, expected 100 against one part and 50 against the other")

	check("#63 the report emits both parts, each with its own date, invoice and quantity",
		_the_report_emits_both_parts)

	def _a_single_part_order_is_unchanged():
		"""The overwhelming majority of orders have one Pick List and must not shift."""
		so2 = _insert("Sales Order", name=f"SO63-{tag}-S", docstatus=1, company=company,
			customer="__Test Customer", customer_name="__Test Customer",
			transaction_date=today(), custom_dispatch_date="2026-10-02",
			custom_invoice_no="INV-SINGLE", status="To Deliver and Bill")
		_insert("Sales Order Item", name=f"SOI63-{tag}-S", parent=so2, parenttype="Sales Order",
			parentfield="items", idx=1, docstatus=1, item_code=item, qty=20, stock_qty=20,
			rate=10, amount=200, conversion_factor=1, delivered_qty=0)
		pl = _insert("Pick List", name=f"PL63-{tag}-S", docstatus=1, company=company,
			custom_sales_order_id=so2, custom_dispatch_date="2026-10-02", purpose="Delivery")
		_insert("Pick List Item", name=f"PLI63-{tag}-S", parent=pl, parenttype="Pick List",
			parentfield="locations", idx=1, docstatus=1, item_code=item, qty=20,
			picked_qty=20, stock_qty=20, sales_order=so2, custom_source_table="Items")

		rows = R._get_data(frappe._dict({
			"from_date": "2026-09-01", "to_date": "2026-10-31",
			"sales_order": so2, "show_all": 1,
		}))
		mine = [r for r in rows if r.get("sales_order_id") == so2]
		_assert(mine, "the single-part order produced no rows")
		_assert(all(r.get("invoice_no") == "INV-SINGLE" for r in mine),
			f"a one-part order lost its invoice number: {[r.get('invoice_no') for r in mine]}")

	check("#63 a single-part order still reports exactly as before",
		_a_single_part_order_is_unchanged)

	def _invoice_search_finds_the_part_that_carries_it():
		"""Changes(HP) #60, and it has to work with #63: searching an invoice number must
		find the part that carries it, not the whole order."""
		rows = R._get_data(frappe._dict({
			"from_date": "2026-09-01", "to_date": "2026-10-31",
			"invoice_no": "INV-PART-ONE", "show_all": 1,
		}))
		mine = [r for r in rows if r.get("sales_order_id") == so]
		_assert(mine, "the invoice search found nothing for an invoice that exists")
		_assert(all(r.get("invoice_no") == "INV-PART-ONE" for r in mine),
			f"the search returned other parts too: {[r.get('invoice_no') for r in mine]}")
		dates = {r.get("dispatch_date") for r in mine}
		_assert(dates == {"01-10-2026"},
			f"only Part 1 carries that invoice, so only its date should appear: {dates}")

	check("#60 an Invoice No. search returns the part that carries it, not the whole order",
		_invoice_search_finds_the_part_that_carries_it)

	def _an_unknown_invoice_returns_nothing():
		rows = R._get_data(frappe._dict({
			"from_date": "2026-09-01", "to_date": "2026-10-31",
			"invoice_no": "INV-NO-SUCH-THING", "show_all": 1,
		}))
		_assert(not rows, f"an unknown invoice number returned {len(rows)} rows")

	check("#60 an unknown Invoice No. returns nothing rather than everything",
		_an_unknown_invoice_returns_nothing)
