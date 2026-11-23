"""replicate.run: another company set up from Alpino Health Foods with only the Item Master
brought over. Uses Hire Hunt as the target on a TEST site; everything is rolled back.

Run:  ../env/bin/python ~/alpinos-wt/mrp_work/run.py <site> alpinos.company_scope.replicate_test.run
"""

import frappe

from alpinos.company_scope import registry
from alpinos.company_scope import replicate as R

RES = []
SOURCE = R.SOURCE
TARGET = "Hire Hunt"


def check(label, fn):
	try:
		fn()
		RES.append(("PASS", label, ""))
	except AssertionError as e:
		RES.append(("FAIL", label, str(e)))
	except Exception as e:
		RES.append(("ERR ", label, f"{type(e).__name__}: {e}"))


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


def _tagged(doctype, company):
	return set(frappe.get_all(doctype, filters={registry.SCOPE_FIELD: ["like", f"%|{company}|%"]}, pluck="name"))


def _snapshot():
	return frappe._dict(
		masters={dt: _tagged(dt, TARGET) for dt in ("Customer", "Supplier", "Buyer Master", "Machine", "Process Master")},
		employees=frappe.db.count("Employee", {"company": TARGET}),
		orders=frappe.db.count("Sales Order", {"company": TARGET}),
		source_defaults=frappe.db.sql(
			"""SELECT parent, default_warehouse FROM `tabItem Default`
			   WHERE parenttype='Item' AND company=%s ORDER BY parent""", SOURCE),
		source_prices=frappe.db.count("Item Price"),
		source_items=_tagged("Item", SOURCE),
		target_items=_tagged("Item", TARGET),
	)


def run():
	RES.clear()
	frappe.set_user("Administrator")
	real_commit = frappe.db.commit
	try:
		_run()
	finally:
		frappe.db.commit = real_commit
		frappe.db.rollback()
		frappe.clear_cache()
	width = max(len(r[1]) for r in RES)
	for status, label, detail in RES:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in RES if r[0] == 'PASS')}/{len(RES)} passed")


def _run():
	abbr = frappe.db.get_value("Company", TARGET, "abbr")
	before = _snapshot()

	def _dry_run_changes_nothing():
		report = R.run(TARGET)
		_assert(report["mode"].startswith("dry run"), report["mode"])
		_assert(report["items"]["source items"] == len(before.source_items), report["items"])
		_assert(_tagged("Item", TARGET) == before.target_items, "items tagged in a dry run")
		_assert(not frappe.db.exists("Warehouse", f"B2B Warehouse - 1 - {abbr}"), "warehouse created in a dry run")
		_assert(not frappe.db.exists("Price List", f"Standard Selling - {abbr}"), "price list created in a dry run")

	check("Dry run reports the work and saves nothing", _dry_run_changes_nothing)

	frappe.db.commit = lambda *a, **k: None
	frappe.db.set_value("Company", TARGET, "custom_series_code", "", update_modified=False)
	report = R.run(TARGET, apply=1)

	def _series():
		_assert(frappe.db.get_value("Company", TARGET, "custom_series_code") == abbr, report["series_code"])

	check("Series Code set to the abbreviation, so numbers are its own", _series)

	def _warehouses():
		b2b, wip = f"B2B Warehouse - 1 - {abbr}", f"Prod WIP - {abbr}"
		for wh in (b2b, wip):
			_assert(frappe.db.get_value("Warehouse", wh, "company") == TARGET, f"{wh} missing")
		_assert(frappe.db.get_value("Warehouse", b2b, "parent_warehouse") == f"All Warehouses - {abbr}", "B2B parent")
		ahfpl_only = {"Flipkart", "Alpino.Store", "Vesu Office", "Export"}
		made = set(frappe.get_all("Warehouse", {"company": TARGET}, pluck="warehouse_name"))
		_assert(not (made & ahfpl_only), f"extra warehouses copied: {made & ahfpl_only}")

	check("Main warehouses created (B2B Warehouse - 1, Prod WIP), nothing else", _warehouses)

	def _production():
		rows = [r for r in frappe.get_single("Production Settings").company_warehouses if r.company == TARGET]
		_assert(len(rows) == 1, rows)
		_assert(rows[0].main_warehouse == f"B2B Warehouse - 1 - {abbr}" and rows[0].wip_warehouse == f"Prod WIP - {abbr}",
		        (rows[0].main_warehouse, rows[0].wip_warehouse))

	check("Production Settings row points at its own warehouses", _production)

	def _items_tagged():
		now_tagged = _tagged("Item", TARGET)
		_assert(before.source_items <= now_tagged, f"{len(before.source_items - now_tagged)} items not tagged")
		_assert(_tagged("Item", SOURCE) == before.source_items, "source tags changed")

	check("Every Alpino item is tagged to the target as well, source tags kept", _items_tagged)

	def _item_defaults():
		rows = dict(frappe.db.sql(
			"SELECT parent, IFNULL(default_warehouse,'') FROM `tabItem Default` WHERE parenttype='Item' AND company=%s", TARGET))
		_assert(len(rows) >= len(before.source_items), f"{len(rows)} default rows for {len(before.source_items)} items")
		for item, wh in before.source_defaults:
			if wh == "B2B Warehouse - 1 - AHFPL":
				_assert(rows.get(item) == f"B2B Warehouse - 1 - {abbr}", f"{item}: {rows.get(item)}")
				break
		after = frappe.db.sql(
			"SELECT parent, default_warehouse FROM `tabItem Default` WHERE parenttype='Item' AND company=%s ORDER BY parent", SOURCE)
		_assert(after == before.source_defaults, "source Item Defaults changed")

	check("Item Default rows for the target use its own warehouse; Alpino's untouched", _item_defaults)

	def _prices():
		for src in ("Standard Selling", "Standard Buying"):
			if not frappe.db.exists("Price List", src):
				continue
			new = f"{src} - {abbr}"
			_assert(frappe.db.get_value("Price List", new, registry.SCOPE_FIELD) == f"|{TARGET}|", f"{new} tags")
			want = frappe.db.sql(
				"""SELECT COUNT(*) FROM `tabItem Price` WHERE price_list=%s AND IFNULL(customer,'')='' AND IFNULL(supplier,'')=''
				   AND IFNULL(batch_no,'')=''""", src)[0][0]
			got = frappe.db.count("Item Price", {"price_list": new})
			_assert(got == want, f"{new}: {got} prices for {want}")
			one = frappe.get_all("Item Price", {"price_list": src}, ["item_code", "uom", "price_list_rate"], limit=1)
			if one:
				rate = frappe.db.get_value("Item Price", {"price_list": new, "item_code": one[0].item_code, "uom": one[0].uom}, "price_list_rate")
				_assert(rate == one[0].price_list_rate, (rate, one[0].price_list_rate))

	check("Own price lists, tagged to the target only, with the prices copied", _prices)

	def _nothing_else():
		after = _snapshot()
		for dt, names in before.masters.items():
			_assert(after.masters[dt] == names, f"{dt} tags changed")
		_assert(after.employees == before.employees and after.orders == before.orders, "employees / orders changed")

	check("No customer, supplier, buyer, machine, process, employee or order brought over", _nothing_else)

	def _again():
		second = R.run(TARGET, apply=1)
		_assert(second["items"]["tagged to target"] == 0 and second["items"]["item default rows added"] == 0, second["items"])
		_assert(not second["warehouses"]["created"], second["warehouses"])
		for name, r in second["price_lists"].items():
			_assert(r["copied"] == 0, (name, r))
		_assert(second["production_settings"] == "row already there", second["production_settings"])

	check("Running it again changes nothing (no duplicates)", _again)

	def _item_details_work():
		from erpnext.stock.get_item_details import get_item_details

		row = frappe.db.sql(
			"""SELECT ip.item_code, ip.uom, ip.price_list_rate FROM `tabItem Price` ip
			   JOIN `tabItem Default` d ON d.parent = ip.item_code AND d.parenttype = 'Item' AND d.company = %s
			   WHERE ip.price_list = %s AND IFNULL(d.default_warehouse, '') != '' LIMIT 1""",
			(TARGET, f"Standard Selling - {abbr}"), as_dict=True)
		_assert(row, "no priced item with a default warehouse to try")
		r = row[0]
		out = get_item_details({
			"item_code": r.item_code, "company": TARGET, "doctype": "Sales Order", "currency": "INR",
			"price_list_currency": "INR", "conversion_rate": 1, "plc_conversion_rate": 1, "qty": 1,
			"selling_price_list": f"Standard Selling - {abbr}", "transaction_date": frappe.utils.today(), "uom": r.uom,
		})
		_assert(out.get("warehouse") == f"B2B Warehouse - 1 - {abbr}", out.get("warehouse"))
		_assert(float(out.get("price_list_rate") or 0) == float(r.price_list_rate), (out.get("price_list_rate"), r.price_list_rate))

	check("An item picked in the target's order gets its own warehouse and the copied price", _item_details_work)
