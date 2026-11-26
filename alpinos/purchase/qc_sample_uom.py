"""Sample Testing in another unit (purchase notes 26 Nov 2026, point 7).

QC may draw a sample in a unit other than the one the line was received in (grams of a kg
item, pieces of a box). The sample row keeps the quantity as drawn, in its own UOM, with a
conversion to the received unit; the decision line and the stock count the converted figure.
"""

import frappe
from frappe.utils import flt


def _item_factor(item_code, uom):
	"""Units of the item's stock UOM in one `uom`, from the item's own UOM table."""
	if not item_code or not uom:
		return None
	if uom == frappe.get_cached_value("Item", item_code, "stock_uom"):
		return 1.0
	factor = frappe.db.get_value(
		"UOM Conversion Detail", {"parent": item_code, "parenttype": "Item", "uom": uom}, "conversion_factor"
	)
	return flt(factor) or None


@frappe.whitelist()
def get_sample_conversion(item_code=None, sample_uom=None, line_uom=None):
	"""How many `line_uom` one `sample_uom` is: the item's UOM table first, then the UOM
	Conversion Factor master (Gram -> Kg and the like). 0 when nothing says."""
	if not sample_uom or not line_uom:
		return 0
	if sample_uom == line_uom:
		return 1
	a, b = _item_factor(item_code, sample_uom), _item_factor(item_code, line_uom)
	if a and b:
		return flt(a / b, 9)
	from erpnext.stock.doctype.item.item import get_uom_conv_factor

	return flt(get_uom_conv_factor(sample_uom, line_uom), 9) or 0
