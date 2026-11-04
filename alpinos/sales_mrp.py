"""Sales Order side of the Multiple MRP FRD (alpinos.item_mrp holds the MRP table).

- validate: one MRP per SKU in a Sales Order (BR-09); on submit, and on every row of an
  import, each line's MRP must be an applicable MRP of its SKU (BR-02 / BR-10 / BR-11).
  A draft saved from the entry screen is not refused here (the screen asks for the MRP),
  and a submitted order is never re-checked, so later changes to the MRP table do not
  touch existing orders (BR-19).
- on_submit: the Buyer Catalog gets the line's price for that SKU + MRP, created when the
  buyer has none for that MRP (FRD 6). Drafts no longer touch the catalogue (6.3).
"""

import frappe
from frappe import _
from frappe.utils import flt

from alpinos import item_mrp as IM


def _item_rows(doc):
	return [r for r in doc.get("items") or [] if r.get("item_code")]


def validate_sales_order_mrps(doc, method=None):
	if doc.docstatus == 2 or (doc.docstatus == 1 and doc.get("_action") != "submit"):
		return
	by_sku = {}
	for row in _item_rows(doc):
		if IM.applicable(row.item_code).tracked:
			by_sku.setdefault(row.item_code, set()).add(IM.q(row.get("custom_customer_mrp")))
	for sku, mrps in by_sku.items():
		if len(mrps) > 1:
			frappe.throw(
				_("SKU {0} is on this Sales Order with more than one MRP ({1}). Only one MRP per SKU is allowed in a Sales Order.").format(
					sku, ", ".join(IM.money(m) for m in sorted(mrps))
				),
				title=_("One MRP per SKU"),
			)

	importing = bool(frappe.flags.in_import)
	if not (importing or doc.get("_action") == "submit"):
		return
	if doc.get("custom_is_freebie_po"):
		# An entire-PO-free e-com order carries no MRP on its lines.
		return
	for row in _item_rows(doc):
		error = IM.line_mrp_error(row.item_code, row.get("custom_customer_mrp"), imported=importing)
		if error:
			frappe.throw(_("Row #{0}: {1}").format(row.idx, error), title=_("MRP"))


def update_buyer_catalog_on_submit(doc, method=None):
	"""Keep the buyer's catalogue in step with the submitted order, per SKU + MRP.

	Same reach as before (offline entry orders of a Buyer Master customer; e-com orders never
	wrote to the catalogue), only moved from every draft save to the submission."""
	if (doc.get("custom_channel") or "").strip() == "E-com" or not doc.get("customer"):
		return
	from alpinos.sales_order_offline_buyer import (
		update_offline_buyer_margin_if_changed,
		upsert_buyer_catalog_selling_rate,
	)

	for row in _item_rows(doc):
		mrp = flt(row.get("custom_customer_mrp"))
		update_offline_buyer_margin_if_changed(doc.customer, row.item_code, flt(row.get("custom_flat_discount")), mrp=mrp)
		upsert_buyer_catalog_selling_rate(doc.customer, row.item_code, flt(row.get("custom_selling_price"), 2), mrp=mrp)
