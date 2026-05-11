"""API helpers for Quotation → Sales Order Entry desk page."""

import frappe
from frappe import _
from frappe.utils import flt


@frappe.whitelist()
def get_sales_order_entry_payload_from_quotation(quotation):
	"""Build JSON for the custom Sales Order Entry page from a submitted Quotation."""

	doc = frappe.get_doc("Quotation", quotation)
	if doc.docstatus != 1:
		frappe.throw(_("Only submitted quotations can be used to open Sales Order Entry"))

	customer = None
	if doc.quotation_to == "Customer":
		customer = doc.party_name
	elif doc.quotation_to == "Offline Buyer Master":
		customer = frappe.db.get_value("Offline Buyer Master", doc.party_name, "customer")

	if not customer:
		frappe.throw(_("Could not resolve Customer for this quotation"))

	header_delivery = doc.get("delivery_date") or doc.get("scheduled_date")

	items = []
	for row in doc.items or []:
		if getattr(row, "is_alternative", 0):
			continue
		img = row.get("image")
		buyer_margin = flt(row.get("custom_buyer_margin_percent"))
		flat_discount = flt(row.get("custom_flat_discount")) or buyer_margin
		items.append(
			{
				"item_code": row.item_code,
				"item_name": row.get("item_name") or "",
				"description": row.get("description") or "",
				"warehouse": row.get("warehouse") or "",
				"uom": row.get("uom") or "",
				"stock_uom": row.get("stock_uom") or "",
				"conversion_factor": flt(row.get("conversion_factor")),
				"delivery_date": row.get("delivery_date") or header_delivery,
				"qty": flt(row.qty),
				"box": flt(row.get("custom_boxes")),
				"mrp": flt(row.get("custom_mrp")),
				"flat_discount": flat_discount,
				"offer": flt(row.get("custom_offer") or 0),
				"additional_discount": flt(row.get("custom_additional_discount")),
				"buyer_margin_percent": buyer_margin,
				"item_tax_percent": flt(row.get("custom_item_tax_percent")),
				"rate": flt(row.rate),
				"amount": flt(row.amount),
				"custom_item_tax": flt(row.get("custom_item_tax")),
				"image": img,
				# mirror discount semantics from quotation rows
				"discount_type": row.get("custom_discount_type") or "",
			}
		)

	freebies = []
	for r in doc.get("custom_marketing_freebies") or []:
		freebies.append(
			{
				"item_code": r.item_code,
				"qty": flt(r.qty),
				"remarks": r.get("remarks") or "",
			}
		)

	scheme_items = []
	add_units = []
	for r in doc.get("custom_scheme_item_table") or []:
		# Scheme-only rows (damage lines live on custom_additional_units_damage_items).
		if not (r.get("scheme") or "").strip():
			continue
		scheme_items.append(
			{
				"item_code": r.item_code,
				"qty": flt(r.qty),
				"scheme": r.get("scheme") or "",
			}
		)

	if doc.get("custom_additional_units_damage"):
		damage_rows = doc.get("custom_additional_units_damage_items") or []
		# Legacy quotations: damage rows still on scheme child with blank scheme.
		if not damage_rows:
			for r in doc.get("custom_scheme_item_table") or []:
				if not (r.get("scheme") or "").strip() and r.item_code:
					damage_rows.append(r)
		for r in damage_rows:
			add_units.append(
				{
					"item_code": r.item_code,
					"qty": flt(r.qty),
					"previous_order_id": r.get("previous_order_id") or "",
					"remarks": r.get("remarks") or "",
				}
			)

	return {
		"quotation": doc.name,
		"customer": customer,
		"order_type": doc.order_type,
		"delivery_date": doc.get("delivery_date"),
		"custom_cash_discount": flt(doc.get("custom_cash_discount")),
		"billing_address": doc.get("customer_address"),
		"shipping_address": doc.get("shipping_address_name"),
		"items": items,
		"freebies": freebies,
		"scheme_items": scheme_items,
		"additional_units_damage": 1 if doc.get("custom_additional_units_damage") else 0,
		"additional_units_items": add_units,
	}
