"""Sections 16-21: the Sales Order Activity Trail, and Previous Sales Orders beside it.

Run:  bench --site alpinos.test execute alpinos.sales_order_trail_test.run

Section 18 is the one that matters most: "Activity logging must not begin only after Sales
Order submission. Changes made while the Sales Order is in Draft must also be tracked." The
app logged only post-submission changes before this. Fixtures roll back.
"""

import frappe
from frappe.utils import add_days, today

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
		frappe.clear_cache()
		frappe.set_user("Administrator")

	width = max(len(r[1]) for r in RES)
	for status, label, detail in RES:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in RES if r[0] == 'PASS')}/{len(RES)} passed")
	return RES


def _run():
	from alpinos import sales_order_trail as T

	tag = "TRL" + frappe.generate_hash(length=4).upper()
	wh = frappe.db.get_value("Warehouse", {"is_group": 0}, ["name", "company"], as_dict=True)
	_assert(wh, "no warehouse on this site")
	company, warehouse = wh.company, wh.name
	items = frappe.get_all("Item", filters={"disabled": 0}, pluck="name", limit=2)
	_assert(len(items) >= 2, "this site needs two items for the add/remove check")
	item, item2 = items[0], items[1]

	customer = _insert("Customer", name=f"{tag}-CUST", customer_name=f"{tag} Customer",
		customer_type="Company", disabled=0)
	buyer = _insert("Buyer Master", name=f"{tag}-OBM", customer_business_name=f"{tag} Party",
		channel="Offline", customer=customer, gst_type="Unregistered Business")
	site = f"{tag} Site"
	_insert("Buyer Address", name=f"{tag}-ADDR", parent=buyer, parenttype="Buyer Master",
		parentfield="addresses", idx=1, site_name=site, address_line="1 Test Road",
		city="Ahmedabad", state="Gujarat", pincode="380001", country="India",
		is_primary=1, is_shipping=1, address_label="Main")

	def _order(suffix):
		doc = frappe.get_doc({
			"doctype": "Sales Order", "company": company, "customer": customer,
			"transaction_date": today(), "delivery_date": add_days(today(), 3),
			"custom_offline_buyer_master": buyer, "custom_site_name": site,
			"custom_workflow_status": "Draft", "set_warehouse": warehouse,
			"custom_dispatch_date": add_days(today(), 2),
			"order_type": frappe.db.get_value("Alpino Customer Type", {}, "name") or "Sales",
			"custom_billing_gstin": "24AAACC1206D1ZM",
			"custom_shipping_gstin": "24AAACC1206D1ZM",
			"items": [{"item_code": item, "qty": 5, "rate": 100, "warehouse": warehouse,
			           "delivery_date": add_days(today(), 3), "conversion_factor": 1}],
		})
		doc.name = f"TRL-{tag}-{suffix}"
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		return doc

	order = _order("A")

	def _creating_a_draft_is_recorded():
		rows = T.get_activity_trail(order.name)
		_assert(any(r["action"] == "Created" for r in rows),
			f"creating the order left no trail entry: {[r['action'] for r in rows]}")

	check("§17 creating the order is recorded", _creating_a_draft_is_recorded)

	def _a_draft_price_change_is_recorded():
		"""Section 18: the draft stage is exactly where the negotiation happens."""
		doc = frappe.get_doc("Sales Order", order.name)
		doc.items[0].rate = 90
		doc.flags.ignore_permissions = True
		doc.save(ignore_permissions=True)

		rows = T.get_activity_trail(order.name)
		price = [r for r in rows if r["field_label"] == "Selling Price"]
		_assert(price, f"a draft price change was not logged: {[r['field_label'] for r in rows]}")
		r = price[0]
		_assert(str(r["previous_value"]).startswith("100") and str(r["new_value"]).startswith("90"),
			f"the values are wrong: {r['previous_value']} -> {r['new_value']}")
		_assert(r["item_code"] == item, f"the SKU was not recorded: {r['item_code']}")
		_assert(not r["after_submit"], "a draft change was marked as post-submission")

	check("§18 a price change made while Draft is recorded, with its SKU",
		_a_draft_price_change_is_recorded)

	def _a_quantity_change_is_recorded():
		doc = frappe.get_doc("Sales Order", order.name)
		doc.items[0].qty = 8
		doc.flags.ignore_permissions = True
		doc.save(ignore_permissions=True)
		rows = T.get_activity_trail(order.name)
		qty = [r for r in rows if r["field_label"] == "Quantity"]
		_assert(qty, "a quantity change was not logged")
		_assert(str(qty[0]["new_value"]).startswith("8"),
			f"the new quantity is wrong: {qty[0]['new_value']}")

	check("§17 a quantity change is recorded", _a_quantity_change_is_recorded)

	def _the_entry_carries_who_and_which_role():
		rows = T.get_activity_trail(order.name)
		_assert(rows, "no trail at all")
		r = rows[0]
		_assert(r["changed_by"], "no user recorded")
		_assert(r["changed_by_name"], "the user's name was not resolved for display")
		_assert(r["user_role"], f"no role recorded: {r['user_role']!r}")
		_assert(r["changed_on"], "no timestamp")

	check("§17 every entry carries who, which role and when",
		_the_entry_carries_who_and_which_role)

	def _adding_and_removing_a_line_is_recorded():
		doc = frappe.get_doc("Sales Order", order.name)
		doc.append("items", {"item_code": item2, "qty": 2, "rate": 50, "warehouse": warehouse,
			"delivery_date": add_days(today(), 3), "conversion_factor": 1})
		doc.flags.ignore_permissions = True
		doc.save(ignore_permissions=True)
		rows = T.get_activity_trail(order.name)
		_assert(any(r["field_label"] == "Item Added" for r in rows),
			"adding a line was not recorded")

		doc = frappe.get_doc("Sales Order", order.name)
		doc.items.pop()
		doc.flags.ignore_permissions = True
		doc.save(ignore_permissions=True)
		rows = T.get_activity_trail(order.name)
		_assert(any(r["field_label"] == "Item Removed" for r in rows),
			"removing a line was not recorded")

	check("§17 adding and removing a line are both recorded",
		_adding_and_removing_a_line_is_recorded)

	def _an_untouched_save_records_nothing():
		"""A trail that logged every recalculated total would bury what matters."""
		before = len(T.get_activity_trail(order.name))
		doc = frappe.get_doc("Sales Order", order.name)
		doc.flags.ignore_permissions = True
		doc.save(ignore_permissions=True)
		after = len(T.get_activity_trail(order.name))
		_assert(after == before, f"a save that changed nothing added {after - before} entries")

	check("§17 a save that changes nothing adds nothing to the trail",
		_an_untouched_save_records_nothing)

	def _previous_orders_are_separate_from_the_trail():
		second = _order("B")
		prev = T.get_previous_sales_orders(second.name)
		names = {p["name"] for p in prev}
		_assert(order.name in names,
			f"the Buyer's earlier order is missing: {names}")
		_assert(second.name not in names, "the order lists itself as a previous order")
		p = next(p for p in prev if p["name"] == order.name)
		for field in ("transaction_date", "grand_total", "status", "created_by_name"):
			_assert(field in p, f"the previous-orders row is missing {field}")

	check("§19-20 Previous Sales Orders lists the Buyer's other orders, not this one",
		_previous_orders_are_separate_from_the_trail)

	def _the_two_lists_do_not_overlap():
		trail = T.get_activity_trail(order.name)
		prev = T.get_previous_sales_orders(order.name)
		_assert(not ({r.get("name") for r in trail} & {p["name"] for p in prev}),
			"the trail and the previous-orders list share records; section 21 separates them")

	check("§21 the trail and Previous Sales Orders stay separate",
		_the_two_lists_do_not_overlap)
