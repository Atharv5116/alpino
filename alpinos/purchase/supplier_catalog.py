"""Supplier Catalog page: supplier-wise list of the items each supplier supplies.

Once a supplier has items ticked here, a Purchase Order for that supplier offers only those
items in its item list (inward_api.po_type_item_query). A supplier without a catalog offers
no items at all, so the catalog has to be set up before ordering from a supplier.
Only the item list is narrowed: saving an order is not checked against the catalog.

Edit: Purchase Inward Manager, Purchase Inward Admin, System Manager (DocPerm on Supplier
Catalog). Purchase Inward User can open the page and read it.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint

from alpinos.company_scope.helpers import tagged_condition

DOCTYPE = "Supplier Catalog"
CHILD = "Supplier Catalog Item"


def catalog_item_codes(supplier):
	"""Item codes in the supplier's catalog (empty when it has none)."""
	if not supplier:
		return []
	return frappe.get_all(CHILD, filters={"parenttype": DOCTYPE, "parent": supplier}, pluck="item_code")


def catalog_condition(supplier, alias=None):
	"""SQL ' and <item> in the supplier's catalog', for an Item query. No catalog, no rows."""
	column = f"`{alias}`.`name`" if alias else "`name`"
	return (
		f" and {column} in (select sci.item_code from `tab{CHILD}` sci"
		f" where sci.parenttype = 'Supplier Catalog' and sci.parent = {frappe.db.escape(supplier or '')})"
	)


@frappe.whitelist()
def catalog_summary(supplier=None):
	"""For the Purchase Order screen's hint under the item lines."""
	if not supplier:
		return {"supplier": None, "count": 0}
	return {
		"supplier": supplier,
		"supplier_name": frappe.db.get_value("Supplier", supplier, "supplier_name"),
		"count": frappe.db.count(CHILD, {"parenttype": DOCTYPE, "parent": supplier}),
		"can_edit": 1 if frappe.has_permission(DOCTYPE, "write") else 0,
	}


@frappe.whitelist()
def get_suppliers():
	"""Every enabled supplier the user may see, with how many items its catalog holds."""
	frappe.has_permission(DOCTYPE, "read", throw=True)
	suppliers = frappe.get_list(
		"Supplier",
		filters={"disabled": 0},
		fields=["name", "supplier_name", "supplier_group"],
		order_by="supplier_name asc",
		limit_page_length=0,
	)
	counts = dict(
		frappe.db.sql(
			f"""select parent, count(*) from `tab{CHILD}` where parenttype = %s group by parent""", DOCTYPE
		)
	)
	updated = dict(frappe.db.sql(f"select name, modified from `tab{DOCTYPE}`"))
	for s in suppliers:
		s["item_count"] = cint(counts.get(s.name))
		s["has_catalog"] = 1 if s.name in updated else 0
		s["modified"] = str(updated[s.name]) if s.name in updated else None
	return {"suppliers": suppliers, "can_edit": 1 if frappe.has_permission(DOCTYPE, "write") else 0}


@frappe.whitelist()
def get_catalog(supplier):
	"""All items that can be bought (the same rule as the Purchase Order item list: enabled,
	not a combo, not a template), each flagged when it is in the supplier's catalog."""
	frappe.has_permission(DOCTYPE, "read", throw=True)
	if not frappe.db.exists("Supplier", supplier):
		frappe.throw(_("Supplier {0} not found.").format(supplier))
	selected = {
		r.item_code: r.additional_info or ""
		for r in frappe.get_all(
			CHILD,
			filters={"parenttype": DOCTYPE, "parent": supplier},
			fields=["item_code", "additional_info"],
		)
	}
	items = frappe.db.sql(
		"""
		select name as item_code, item_name, item_group, stock_uom
		from `tabItem`
		where ifnull(disabled, 0) = 0
		  and ifnull(custom_is_bundle, 0) = 0
		  and ifnull(has_variants, 0) = 0{tagged}
		order by item_group, name
		""".format(tagged=tagged_condition("Item")),
		as_dict=True,
	)
	listed = {i.item_code for i in items}
	# An item put in the catalog and later disabled still shows, so it can be taken out.
	for code in set(selected) - listed:
		row = frappe.db.get_value("Item", code, ["name as item_code", "item_name", "item_group", "stock_uom"], as_dict=True)
		if row:
			row["unavailable"] = 1
			items.append(row)
	for i in items:
		i["selected"] = 1 if i.item_code in selected else 0
		i["additional_info"] = selected.get(i.item_code, "")
	return {
		"supplier": supplier,
		"supplier_name": frappe.db.get_value("Supplier", supplier, "supplier_name"),
		"items": items,
		"can_edit": 1 if frappe.has_permission(DOCTYPE, "write") else 0,
	}


@frappe.whitelist()
def save_catalog(supplier, items):
	"""Replace the supplier's catalog with `items` ([{item_code, additional_info}])."""
	if isinstance(items, str):
		items = json.loads(items or "[]")
	if not frappe.db.exists("Supplier", supplier):
		frappe.throw(_("Supplier {0} not found.").format(supplier))
	if frappe.db.exists(DOCTYPE, supplier):
		doc = frappe.get_doc(DOCTYPE, supplier)
		doc.check_permission("write")
	else:
		frappe.has_permission(DOCTYPE, "create", throw=True)
		doc = frappe.new_doc(DOCTYPE)
		doc.supplier = supplier

	codes, rows = set(), []
	for it in items or []:
		code = (it.get("item_code") or "").strip()
		if not code or code in codes:
			continue
		if not frappe.db.exists("Item", code):
			frappe.throw(_("Item {0} not found.").format(code))
		codes.add(code)
		rows.append({"item_code": code, "additional_info": (it.get("additional_info") or "").strip()})
	doc.set("items", rows)
	doc.save()
	return {"supplier": supplier, "count": len(rows), "modified": str(doc.modified)}
