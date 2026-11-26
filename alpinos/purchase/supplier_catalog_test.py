"""Supplier Catalog: supplier-wise items; a Purchase Order offers only the supplier's catalog
items (none without a catalog). TEST sites only; everything is rolled back.

Run:  ../env/bin/python ~/alpinos-wt/mrp_work/run.py <site> alpinos.purchase.supplier_catalog_test.run
"""

import frappe

R = []
MANAGER = "spc-manager@example.com"
VIEWER = "spc-viewer@example.com"


def check(label, fn):
	try:
		fn()
		R.append(("PASS", label, ""))
	except AssertionError as e:
		R.append(("FAIL", label, str(e)))
	except Exception as e:
		R.append(("ERR ", label, f"{type(e).__name__}: {e}"))
	finally:
		frappe.set_user("Administrator")


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


def run():
	R.clear()
	frappe.set_user("Administrator")
	real_commit = frappe.db.commit
	frappe.db.commit = lambda *a, **k: None
	try:
		_run()
	finally:
		frappe.db.commit = real_commit
		frappe.db.rollback()
		frappe.set_user("Administrator")
	width = max(len(r[1]) for r in R) if R else 10
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in R if r[0] == 'PASS')}/{len(R)} passed")
	return R


def _user(email, role):
	if not frappe.db.exists("User", email):
		frappe.get_doc({
			"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0,
			"user_type": "System User", "roles": [{"role": role}],
		}).insert(ignore_permissions=True)
	frappe.clear_cache(user=email)
	return email


def _picker(**filters):
	from alpinos.purchase.inward_api import po_type_item_query

	return [r[0] for r in po_type_item_query("Item", "", "name", 0, 500, filters)]


def _run():
	from alpinos.purchase import supplier_catalog as SC

	sup, other = frappe.get_all("Supplier", filters={"disabled": 0}, pluck="name", order_by="name", limit=2)
	for s in (sup, other):
		if frappe.db.exists("Supplier Catalog", s):
			frappe.delete_doc("Supplier Catalog", s, force=True, ignore_permissions=True)
	items = frappe.db.sql(
		"""select name from tabItem where disabled = 0 and ifnull(custom_is_bundle, 0) = 0
		   and ifnull(has_variants, 0) = 0 order by name limit 3""",
		pluck=True,
	)
	_user(MANAGER, "Purchase Inward Manager")
	_user(VIEWER, "Purchase Inward User")

	def _no_catalog_no_items():
		_assert(_picker(supplier="") == [], "no vendor chosen yet: nothing to pick")
		_assert(_picker(supplier=sup) == [], f"{sup} has no catalog but items were offered")
		_assert(len(_picker()) > 3, "a caller that sends no supplier key must be unchanged")

	check("No vendor, or a vendor without a catalog: the PO item list offers nothing", _no_catalog_no_items)

	def _manager_saves():
		frappe.set_user(MANAGER)
		out = SC.save_catalog(sup, [
			{"item_code": items[0], "additional_info": "  500 g pouch  "},
			{"item_code": items[1]},
			{"item_code": items[0], "additional_info": "dup"},
		])
		frappe.set_user("Administrator")
		_assert(out["count"] == 2, out)
		doc = frappe.get_doc("Supplier Catalog", sup)
		_assert([r.item_code for r in doc.items] == items[:2] and doc.item_count == 2, doc.as_dict())
		_assert(doc.items[0].additional_info == "500 g pouch" and doc.items[0].item_name, doc.items[0].as_dict())

	check("A Purchase Inward Manager saves a catalog: items, Additional Information, duplicates dropped", _manager_saves)

	def _picker_follows_catalog():
		_assert(sorted(_picker(supplier=sup)) == sorted(items[:2]), _picker(supplier=sup))
		_assert(_picker(supplier=other) == [], "another vendor's list must not change")
		frappe.set_user(MANAGER)
		SC.save_catalog(sup, [{"item_code": items[2]}])
		frappe.set_user("Administrator")
		_assert(_picker(supplier=sup) == [items[2]], "list follows the catalog after a change")

	check("The PO item list offers exactly the vendor's catalog items, and follows each save", _picker_follows_catalog)

	def _picker_keeps_type_rule():
		from alpinos.purchase import constants as C
		from alpinos.purchase.inward_api import item_inward_type

		kind = item_inward_type(items[2], {})
		other_types = [t for t in (C.INWARD_RM, C.INWARD_PM, C.INWARD_FG) if t != kind]
		if kind:
			_assert(_picker(supplier=sup, po_types=kind) == [items[2]], "own type still offered")
			_assert(_picker(supplier=sup, po_types=other_types[0]) == [], "PO Type rule still applies")

	check("The PO Type rule still applies inside the catalog", _picker_keeps_type_rule)

	def _viewer_reads_only():
		frappe.set_user(VIEWER)
		data = SC.get_catalog(sup)
		_assert(data["can_edit"] == 0, data["can_edit"])
		picked = [i["item_code"] for i in data["items"] if i["selected"]]
		_assert(picked == [items[2]], picked)
		try:
			SC.save_catalog(sup, [{"item_code": items[0]}])
		except frappe.PermissionError:
			frappe.clear_messages()
		else:
			raise AssertionError("a Purchase Inward User saved a catalog")
		try:
			SC.save_catalog(other, [{"item_code": items[0]}])
		except frappe.PermissionError:
			frappe.clear_messages()
		else:
			raise AssertionError("a Purchase Inward User created a catalog")

	check("A Purchase Inward User can open a catalog but not change or create one", _viewer_reads_only)

	def _lists_and_counts():
		frappe.set_user(MANAGER)
		lst = SC.get_suppliers()
		row = next(s for s in lst["suppliers"] if s["name"] == sup)
		_assert(row["item_count"] == 1 and lst["can_edit"] == 1, row)
		_assert(next(s for s in lst["suppliers"] if s["name"] == other)["item_count"] == 0)
		_assert(SC.catalog_summary(sup)["count"] == 1 and SC.catalog_summary(other)["count"] == 0)
		data = SC.get_catalog(sup)
		_assert(len(data["items"]) == len(_picker()) or len(data["items"]) >= len(items), len(data["items"]))

	check("Supplier list shows each catalog's item count; the PO hint gets the same count", _lists_and_counts)

	def _disabled_item_stays_visible():
		frappe.db.set_value("Item", items[2], "disabled", 1)
		data = SC.get_catalog(sup)
		row = next((i for i in data["items"] if i["item_code"] == items[2]), None)
		_assert(row and row["selected"] and row.get("unavailable"), row)
		_assert(_picker(supplier=sup) == [], "a disabled item is never offered on a PO")

	check("An item disabled after it was added stays in the catalog page so it can be taken out", _disabled_item_stays_visible)
