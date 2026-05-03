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

	bm = flt(_rget(row, "custom_buyer_margin_percent"))
	unit_base = mrp * (1.0 - bm / 100.0)
	gross = qty * unit_base

	discount_type = _rget(row, "custom_discount_type") or "Percentage"
	flat_in = flt(_rget(row, "custom_flat_discount"))
	if discount_type == "Percentage":
		flat_amt = gross * flat_in / 100.0
	else:
		flat_amt = flat_in

	after_flat = gross - flat_amt
	offer_amt = after_flat * flt(_rget(row, "custom_offer") or 0) / 100.0
	after_offer = after_flat - offer_amt

	add_pct = flt(_rget(row, "custom_additional_discount"))
	additional_amt = after_offer * add_pct / 100.0
	taxable = after_offer - additional_amt
	return max(taxable, 0.0)


def recalculate_quotation_item_row(doc, row) -> None:
	"""Set rate/amount/custom_item_tax on a Quotation Item child row."""

	qty = flt(_rget(row, "qty"))
	taxable = quotation_line_taxable_net(row)

	if not flt(_rget(row, "custom_mrp")):
		return

	tax_pct = flt(_rget(row, "custom_item_tax_percent"))
	tax_amt = taxable * tax_pct / 100.0 if taxable > 0 else 0

	row.custom_item_tax = flt(tax_amt, 2)
	row.rate = flt(taxable / qty, 2) if qty else 0.0
	row.amount = flt(taxable, 2)
	row.base_rate = row.rate
	row.base_amount = row.amount


def infer_line_tax_percent(amt_pre_tax: float, item_tax_currency: float) -> float:
	if flt(amt_pre_tax) <= 0 or flt(item_tax_currency) < 0:
		return 0.0
	return flt(flt(item_tax_currency) / flt(amt_pre_tax) * 100.0, 6)
