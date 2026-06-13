"""Bridge the custom Item bundle mapping to ERPNext's native Product Bundle.

The Alpinos "bundle" is authored on the Item itself (`custom_is_bundle` +
`custom_product_mapping`), which drives the custom pick-list explosion and the
COMBO table. But the *stock* side — deduct the component items, not the bundle,
at the Delivery Note — is exactly what ERPNext's native Product Bundle already
does (bundle = priced non-stock line item, components = `packed_items` that hit
the stock ledger; `delivered_qty`/billing track on the bundle).

So rather than re-implement packing-list + SLE logic, we keep one native
**Product Bundle** in lock-step with each Item's custom mapping:

  * `custom_is_bundle` ticked  -> the Item is forced non-stock (a bundle must
    never hold its own stock, else the DN double-counts), and a Product Bundle
    (`new_item_code` = the Item, `items` = the mapping with `qty` = `base_qty`)
    is created/refreshed.
  * unticked / mapping cleared -> the Product Bundle is removed.

With that in place, any SO/DN/SI carrying the bundle SKU explodes into component
`packed_items` natively, and component stock moves at the Delivery Note.
"""

import frappe
from frappe.utils import flt


def _existing_bundle(item_code):
	return frappe.db.get_value("Product Bundle", {"new_item_code": item_code}, "name")


def force_bundle_non_stock(doc, method=None):
	"""Item validate hook: a bundle SKU must be a non-stock item.

	Runs on validate so the change is persisted with the save. If the item
	already carries stock, ERPNext's own is_stock_item guard raises a clear
	error — we don't try to override that.
	"""
	if doc.get("custom_is_bundle") and doc.get("is_stock_item"):
		doc.is_stock_item = 0


def sync_item_product_bundle(doc, method=None):
	"""Item on_update hook: keep the native Product Bundle in sync with the mapping."""
	is_bundle = bool(doc.get("custom_is_bundle"))
	mapping = [m for m in (doc.get("custom_product_mapping") or []) if m.get("item") and flt(m.get("base_qty"))]
	existing = _existing_bundle(doc.name)

	if is_bundle and mapping:
		pb = frappe.get_doc("Product Bundle", existing) if existing else frappe.new_doc("Product Bundle")
		pb.new_item_code = doc.name
		if not pb.get("description"):
			pb.description = doc.get("item_name") or doc.name
		pb.set("items", [])
		for m in mapping:
			pb.append("items", {"item_code": m.item, "qty": flt(m.base_qty)})
		pb.flags.ignore_permissions = True
		pb.save()
	elif existing:
		# No longer a bundle (or mapping emptied) — drop the native bundle.
		# Best-effort: if it's locked by existing transactions, leave it and log.
		try:
			frappe.delete_doc("Product Bundle", existing, force=1, ignore_permissions=True)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"Could not remove Product Bundle {existing}")


def backfill_product_bundles():
	"""after_migrate: sync every bundle Item, and remove orphaned Product Bundles.

	Safe to run repeatedly.
	"""
	if not frappe.db.exists("DocType", "Product Bundle"):
		return

	bundle_items = frappe.get_all(
		"Item",
		filters={"custom_is_bundle": 1},
		fields=["name"],
	)
	synced = 0
	for row in bundle_items:
		try:
			doc = frappe.get_doc("Item", row.name)
			# Mirror the validate guard for items migrated/imported as stock bundles.
			if doc.is_stock_item and not frappe.db.exists(
				"Stock Ledger Entry", {"item_code": doc.name, "is_cancelled": 0}
			):
				frappe.db.set_value("Item", doc.name, "is_stock_item", 0)
				doc.is_stock_item = 0
			sync_item_product_bundle(doc)
			synced += 1
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"Product Bundle backfill failed for {row.name}")

	frappe.db.commit()
	return synced
