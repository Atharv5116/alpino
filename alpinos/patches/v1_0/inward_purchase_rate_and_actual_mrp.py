"""MRP draft: the inward's MRP column becomes the Actual MRP, and the rate moves out of it.

Until now the column labelled MRP held the PO line's pre-tax rate (inward_api.po_line_mrp),
filled in on every line, and the GRN priced each line at the PO rate whatever it said. The
rate now has its own column, Purchase Rate, so:

	purchase_rate  <- the PO rate on the line, which is what every GRN was raised at
	mrp            <- cleared where it is only that default: the line's rate, the PO line's
	                  list rate or its rate incl. GST. A value that matches none of them was
	                  typed by someone and is kept as the Actual MRP.
	usp            <- cleared with it when it was worked out from that rate.

Only these two columns are written, and nothing that is already posted (GRNs, invoices,
stock) is touched.
"""

import frappe
from frappe.utils import flt


def execute():
	if not frappe.db.has_column("Purchase Inward Item", "purchase_rate"):
		return
	rows = frappe.db.sql(
		"""
		SELECT pii.name, pii.item_code, pii.rate, pii.mrp, pii.purchase_rate, pii.usp, pi.company,
			poi.rate AS po_rate, poi.price_list_rate AS po_list_rate,
			{incl} AS po_incl
		FROM `tabPurchase Inward Item` pii
		JOIN `tabPurchase Inward` pi ON pi.name = pii.parent
		LEFT JOIN `tabPurchase Order Item` poi ON poi.name = pii.po_detail
		""".format(
			incl="poi.custom_rate_incl_gst" if frappe.db.has_column("Purchase Order Item", "custom_rate_incl_gst") else "0"
		),
		as_dict=True,
	)
	from alpinos.purchase.inward_api import currency_symbol, format_usp, receiving_item_info

	info = receiving_item_info(list({r.item_code for r in rows if r.item_code}))
	symbols = {}
	rated = cleared = kept = 0
	for row in rows:
		update = {}
		if not flt(row.purchase_rate):
			update["purchase_rate"] = flt(row.rate) or flt(row.po_rate) or flt(row.po_list_rate)
			rated += 1
		mrp = flt(row.mrp)
		if mrp:
			defaults = [flt(v) for v in (row.rate, row.po_rate, row.po_list_rate, row.po_incl) if flt(v)]
			if any(abs(mrp - v) <= 0.01 for v in defaults):
				update["mrp"] = 0
				cleared += 1
				if row.company not in symbols:
					symbols[row.company] = currency_symbol(row.company)
				if row.usp and row.usp == format_usp(mrp, info.get(row.item_code), symbols[row.company]):
					update["usp"] = None
			else:
				kept += 1
		if update:
			frappe.db.set_value("Purchase Inward Item", row.name, update, update_modified=False)
	print(f"[mrp] inward lines: purchase rate set on {rated}, MRP cleared on {cleared}, MRP kept on {kept}")
