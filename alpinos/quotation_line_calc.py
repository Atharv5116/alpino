"""Shared quotation line helpers (server-side; mirrors Desk client calculations)."""

from __future__ import annotations

from frappe.utils import flt


def _rget(row, fieldname):
	if row is None:
		return None
	v = getattr(row, "get", None)
	if callable(v):
		val = row.get(fieldname)
		return val if val is not None else getattr(row, fieldname, None)
	return getattr(row, fieldname, None)


def quotation_line_taxable_net(row) -> float:
	"""Pre-tax taxable line amount (exclusive of GST) after buyer margin & trade discounts."""

	qty = flt(_rget(row, "qty"))
	mrp = flt(_rget(row, "custom_mrp"))
	if not qty or not mrp:
		return 0.0

	flat_discount = flt(_rget(row, "custom_flat_discount"))
	if not flat_discount:
		flat_discount = flt(_rget(row, "custom_buyer_margin_percent"))

	offer_pct = flt(_rget(row, "custom_offer"))
	additional_discount_pct = flt(_rget(row, "custom_additional_discount"))
	gst_pct = flt(_rget(row, "custom_item_tax_percent") or _rget(row, "custom_gst_percent") or _rget(row, "gst_percent") or 0)
	if not gst_pct and _rget(row, "item_code"):
		import frappe
		gst_pct = flt(frappe.db.get_value("Item", _rget(row, "item_code"), "custom_gst_percent"))

	# MRP is GST-inclusive
	gross_incl = mrp * qty
	after_flat = gross_incl - (gross_incl * flat_discount / 100.0)
	after_offer = after_flat - (after_flat * offer_pct / 100.0)
	final_incl = after_offer - (after_offer * additional_discount_pct / 100.0)
	final_incl = max(final_incl, 0)

	div = 1 + (gst_pct / 100.0)
	net_amount = (final_incl / div) if div else final_incl
	return net_amount


def recalculate_quotation_item_row(doc, row) -> None:
	"""Set rate/amount/custom_item_tax on a Quotation Item child row."""

	qty = flt(_rget(row, "qty"))
	taxable = quotation_line_taxable_net(row)

	if not flt(_rget(row, "custom_mrp")):
		return

	# Retrieve GST percent
	gst_pct = flt(_rget(row, "custom_item_tax_percent") or _rget(row, "custom_gst_percent") or _rget(row, "gst_percent") or 0)
	if not gst_pct and _rget(row, "item_code"):
		import frappe
		gst_pct = flt(frappe.db.get_value("Item", _rget(row, "item_code"), "custom_gst_percent"))

	flat_discount = flt(_rget(row, "custom_flat_discount"))
	if not flat_discount:
		flat_discount = flt(_rget(row, "custom_buyer_margin_percent"))

	offer_pct = flt(_rget(row, "custom_offer"))
	additional_discount_pct = flt(_rget(row, "custom_additional_discount"))

	gross_incl = flt(_rget(row, "custom_mrp")) * qty
	after_flat = gross_incl - (gross_incl * flat_discount / 100.0)
	after_offer = after_flat - (after_flat * offer_pct / 100.0)
	final_incl = after_offer - (after_offer * additional_discount_pct / 100.0)
	final_incl = max(final_incl, 0)

	tax_amt = max(final_incl - taxable, 0.0)

	row.custom_item_tax = flt(tax_amt, 2)
	row.rate = flt(taxable / qty, 2) if qty else 0.0
	row.amount = flt(taxable, 2)
	row.base_rate = row.rate
	row.base_amount = row.amount


def infer_line_tax_percent(amt_pre_tax: float, item_tax_currency: float) -> float:
	if flt(amt_pre_tax) <= 0 or flt(item_tax_currency) < 0:
		return 0.0
	return flt(flt(item_tax_currency) / flt(amt_pre_tax) * 100.0, 6)
