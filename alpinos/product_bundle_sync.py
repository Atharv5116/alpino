"""Keep a native Product Bundle in sync with each Item's custom bundle mapping."""

import frappe
from frappe.utils import flt


def _existing_bundle(item_code):
	return frappe.db.get_value("Product Bundle", {"new_item_code": item_code}, "name")


def _product_bundle_in_use(item_code):
	"""True if the bundle SKU is on any submitted transaction (mirrors Product Bundle on_trash)."""
	for item_dt in (
		"Sales Order Item",
		"Delivery Note Item",
		"Sales Invoice Item",
		"POS Invoice Item",
		"Quotation Item",
	):
		if frappe.db.exists(item_dt, {"item_code": item_code, "docstatus": 1}):
			return True
	return False


def force_bundle_non_stock(doc, method=None):
	"""Item validate hook: a bundle SKU must be a non-stock item."""
	if doc.get("custom_is_bundle") and doc.get("is_stock_item"):
		doc.is_stock_item = 0


def sync_item_product_bundle(doc, method=None):
	"""Item on_update hook: keep the native Product Bundle in sync with the mapping."""
	is_bundle = bool(doc.get("custom_is_bundle"))
	mapping = [m for m in (doc.get("custom_product_mapping") or []) if m.get("item") and flt(m.get("base_qty"))]
	existing = _existing_bundle(doc.name)
	desired = [(m.item, flt(m.base_qty)) for m in mapping]

	if is_bundle and mapping:
		if existing:
			pb = frappe.get_doc("Product Bundle", existing)
			current = [(i.item_code, flt(i.qty)) for i in pb.items]
			# Nothing changed: don't re-save the bundle when only other Item fields were edited.
			if pb.new_item_code == doc.name and current == desired:
				return
		else:
			pb = frappe.new_doc("Product Bundle")
			pb.new_item_code = doc.name
		if not pb.get("description"):
			pb.description = doc.get("item_name") or doc.name
		pb.set("items", [])
		for m in mapping:
			pb.append("items", {"item_code": m.item, "qty": flt(m.base_qty)})
		pb.flags.ignore_permissions = True
		pb.save()
	elif existing:
		# No longer a bundle: drop the native bundle, unless a submitted transaction still uses it.
		if not _product_bundle_in_use(doc.name):
			try:
				frappe.delete_doc("Product Bundle", existing, force=1, ignore_permissions=True)
			except Exception:
				frappe.log_error(frappe.get_traceback(), f"Could not remove Product Bundle {existing}")


def backfill_product_bundles():
	"""after_migrate: sync every bundle Item and remove orphaned Product Bundles. Idempotent."""
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
