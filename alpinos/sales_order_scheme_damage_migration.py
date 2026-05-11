"""Move legacy damage rows out of Sales Order Scheme Item into Sales Order Additional Units Item."""

import frappe
from frappe.utils import cint


def run_sales_order_scheme_damage_split_migration():
	"""Idempotent: for SOs with damage checked, rows still on scheme child with blank scheme are moved."""
	if not frappe.db.has_table("Sales Order Additional Units Item"):
		return
	if not frappe.get_meta("Sales Order").get_field("custom_additional_units_damage_items"):
		return

	pending = frappe.db.sql(
		"""
		SELECT COUNT(*)
		FROM `tabSales Order Scheme Item` chi
		INNER JOIN `tabSales Order` p ON p.name = chi.parent
		WHERE chi.parenttype = 'Sales Order'
			AND chi.parentfield = 'custom_scheme_item_table'
			AND IFNULL(p.custom_additional_units_damage, 0) = 1
			AND IFNULL(TRIM(chi.scheme), '') = ''
			AND IFNULL(chi.item_code, '') != ''
		"""
	)[0][0]
	if not pending:
		return

	names = frappe.get_all(
		"Sales Order",
		filters={"custom_additional_units_damage": 1},
		pluck="name",
	)
	for so_name in names:
		try:
			so = frappe.get_doc("Sales Order", so_name)
		except Exception:
			continue
		to_move = [
			r
			for r in (so.get("custom_scheme_item_table") or [])
			if cint(so.custom_additional_units_damage)
			and not ((r.scheme or "").strip())
			and (r.item_code or "")
		]
		if not to_move:
			continue
		for r in to_move:
			so.append(
				"custom_additional_units_damage_items",
				{
					"item_code": r.item_code,
					"qty": r.qty,
					"previous_order_id": r.previous_order_id or "",
					"remarks": r.remarks or "",
				},
			)
			so.remove(r)
		try:
			so.save(ignore_permissions=True)
		except Exception:
			frappe.db.rollback()
			continue
	frappe.db.commit()
