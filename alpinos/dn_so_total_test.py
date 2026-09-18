"""Delivery Note value vs Sales Order value.

A Sales Order line stores the amount the customer agreed, rounded once from the
GST-inclusive price, so its rate (that amount per unit, rounded to paise) times the
quantity need not come back to the same figure.  ERPNext rebuilds every Delivery Note
line as rate x qty, so a fully delivered order used to produce a Delivery Note whose
grand total drifted from the Sales Order's by that residue, grown by the quantity and
by GST.  alpinos.delivery_note_hooks._align_value_with_sales_order closes that gap.

Every case builds its own Sales Order (written straight to the tables, so the Sales
Order's own pricing hooks cannot rewrite the crafted rounding), then runs the REAL
Sales Order -> Delivery Note path and saves the Delivery Note.  One transaction,
rolled back at the end; commits made by the code under test are ignored while it runs.

Run:  bench --site alpinos.test execute alpinos.dn_so_total_test.run
"""

import frappe
from frappe.utils import flt, today

R = []


def check(label, fn):
	try:
		fn()
		R.append(("PASS", label, ""))
	except AssertionError as e:
		R.append(("FAIL", label, str(e)))
	except Exception as e:
		R.append(("ERROR", label, f"{type(e).__name__}: {str(e)[:300]}"))


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


# ------------------------------------------------------------------ fixtures


def _template_so():
	"""A submitted Sales Order of the site to copy the shape (items, taxes, party) from."""
	name = frappe.db.sql(
		"""
		SELECT so.name
		FROM `tabSales Order` so
		WHERE so.docstatus = 1
			AND EXISTS (SELECT 1 FROM `tabSales Order Item` i WHERE i.parent = so.name AND i.qty > 0)
			AND EXISTS (SELECT 1 FROM `tabSales Taxes and Charges` t
				WHERE t.parent = so.name AND t.parenttype = 'Sales Order'
					AND t.charge_type = 'On Net Total' AND t.rate > 0)
		ORDER BY so.creation DESC LIMIT 1
		"""
	)
	return name[0][0] if name else None


def _make_sales_order(template, tag, qty, rate, amount):
	"""Copy the template's first line into a fresh submitted Sales Order carrying
	qty/rate/amount exactly as given (amount need not be rate x qty)."""
	src = frappe.get_doc("Sales Order", template)
	so_name = f"SOTOT-{tag}"

	data = src.as_dict()
	for key in ("name", "creation", "modified", "owner", "modified_by", "amended_from", "naming_series"):
		data.pop(key, None)
	data.pop("items", None)
	data.pop("taxes", None)
	data.pop("packed_items", None)
	doc = frappe.get_doc(dict(data, doctype="Sales Order"))
	doc.name = so_name
	doc.docstatus = 1
	doc.status = "To Deliver and Bill"
	doc.per_delivered = 0
	doc.transaction_date = today()
	doc.delivery_date = today()
	doc.custom_cash_discount = 0
	doc.apply_discount_on = "Grand Total"
	doc.additional_discount_percentage = 0
	doc.discount_amount = 0
	doc.db_insert()

	src_item = src.items[0]
	item_data = src_item.as_dict()
	for key in ("name", "creation", "modified", "owner", "modified_by"):
		item_data.pop(key, None)
	item = frappe.get_doc(dict(item_data, doctype="Sales Order Item"))
	item.name = f"SOTOTI-{tag}"
	item.parent = so_name
	item.parenttype = "Sales Order"
	item.parentfield = "items"
	item.idx = 1
	item.docstatus = 1
	item.qty = item.stock_qty = qty
	item.conversion_factor = 1
	item.rate = item.base_rate = item.net_rate = item.base_net_rate = rate
	item.price_list_rate = item.base_price_list_rate = rate
	item.amount = item.base_amount = item.net_amount = item.base_net_amount = amount
	item.delivered_qty = 0
	item.returned_qty = 0
	item.billed_amt = 0
	item.discount_percentage = 0
	item.discount_amount = 0
	item.db_insert()

	rate_pct = 0.0
	for idx, src_tax in enumerate(src.taxes, start=1):
		tax_data = src_tax.as_dict()
		for key in ("name", "creation", "modified", "owner", "modified_by"):
			tax_data.pop(key, None)
		tax = frappe.get_doc(dict(tax_data, doctype="Sales Taxes and Charges"))
		tax.name = f"SOTOTT-{tag}-{idx}"
		tax.parent = so_name
		tax.parenttype = "Sales Order"
		tax.parentfield = "taxes"
		tax.idx = idx
		tax.docstatus = 1
		if tax.charge_type == "On Net Total":
			rate_pct += flt(tax.rate)
			tax.tax_amount = tax.base_tax_amount = flt(amount * flt(tax.rate) / 100.0, 2)
		tax.tax_amount_after_discount_amount = tax.tax_amount
		tax.base_tax_amount_after_discount_amount = tax.tax_amount
		tax.total = tax.base_total = flt(amount + tax.tax_amount, 2)
		tax.db_insert()

	taxes = flt(amount * rate_pct / 100.0, 2)
	grand = flt(amount + taxes, 2)
	frappe.db.set_value(
		"Sales Order",
		so_name,
		{
			"total": amount, "base_total": amount, "net_total": amount, "base_net_total": amount,
			"total_taxes_and_charges": taxes, "base_total_taxes_and_charges": taxes,
			"grand_total": grand, "base_grand_total": grand,
			"rounded_total": flt(round(grand), 2), "base_rounded_total": flt(round(grand), 2),
			"rounding_adjustment": flt(round(grand) - grand, 2),
			"total_qty": qty,
		},
		update_modified=False,
	)
	return frappe.get_doc("Sales Order", so_name)


def _make_delivery_note(so_name, qty=None, rate=None):
	from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note

	dn = make_delivery_note(so_name)
	if qty is not None:
		dn.items[0].qty = qty
	if rate is not None:
		dn.items[0].rate = rate
	dn.custom_dispatch_date = today()
	dn.custom_delivery_date = today()
	dn.flags.ignore_mandatory = True
	dn.flags.ignore_permissions = True
	dn.insert(ignore_permissions=True)
	return dn


# --------------------------------------------------------------------- cases


def _residue_case(template, tag, aligned=True):
	"""24 x 355.67 = 8536.08, but the order says 8536.00 -- the rounding this is about."""
	so = _make_sales_order(template, tag, qty=24, rate=355.67, amount=8536.00)
	dn = _make_delivery_note(so.name)
	return so, dn


def run():
	R.clear()
	frappe.set_user("Administrator")
	real_commit = frappe.db.commit
	frappe.db.commit = lambda *args, **kwargs: None
	from alpinos import delivery_note_hooks as dnh
	real_align = dnh._align_value_with_sales_order
	try:
		template = _template_so()
		if not template:
			R.append(("SKIP", "delivery note value vs sales order value", "no submitted taxed Sales Order on this site to copy"))
			return _report()

		def full_delivery():
			so, dn = _residue_case(template, frappe.generate_hash(length=5).upper())
			_assert(flt(dn.total) == flt(so.total),
				f"DN total {dn.total} != SO total {so.total}")
			_assert(flt(dn.grand_total) == flt(so.grand_total),
				f"DN grand total {dn.grand_total} != SO grand total {so.grand_total}")
			_assert(flt(dn.items[0].amount) == 8536.00,
				f"line amount {dn.items[0].amount} != 8536.00")

		def taxes_follow():
			so, dn = _residue_case(template, frappe.generate_hash(length=5).upper())
			total_tax = flt(sum(flt(t.tax_amount) for t in dn.taxes), 2)
			_assert(flt(dn.total_taxes_and_charges) == total_tax,
				f"total_taxes_and_charges {dn.total_taxes_and_charges} != sum of rows {total_tax}")
			_assert(flt(dn.grand_total) == flt(flt(dn.net_total) + total_tax, 2),
				f"grand {dn.grand_total} != net {dn.net_total} + taxes {total_tax}")
			_assert(flt(dn.total_taxes_and_charges) == flt(so.total_taxes_and_charges),
				f"DN tax {dn.total_taxes_and_charges} != SO tax {so.total_taxes_and_charges}")

		def rounded_total_follows():
			so, dn = _residue_case(template, frappe.generate_hash(length=5).upper())
			if dn.get("disable_rounded_total"):
				_assert(not flt(dn.rounded_total), "rounded total set although rounding is disabled")
				return
			_assert(flt(dn.rounded_total) == flt(round(flt(dn.grand_total)), 2),
				f"rounded total {dn.rounded_total} does not round grand total {dn.grand_total}")
			_assert(flt(dn.rounding_adjustment) == flt(flt(dn.rounded_total) - flt(dn.grand_total), 2),
				"rounding adjustment does not match rounded total")

		def part_delivery_is_proportional():
			tag = frappe.generate_hash(length=5).upper()
			so = _make_sales_order(template, tag, qty=24, rate=355.67, amount=8536.00)
			dn = _make_delivery_note(so.name, qty=12)
			_assert(flt(dn.items[0].amount) == 4268.00,
				f"half delivery line amount {dn.items[0].amount} != 4268.00")
			_assert(flt(dn.total) == 4268.00, f"half delivery total {dn.total} != 4268.00")
			_assert(flt(dn.grand_total) < flt(so.grand_total),
				"a half delivery must not be forced up to the order's grand total")

		def repriced_line_is_left_alone():
			tag = frappe.generate_hash(length=5).upper()
			so = _make_sales_order(template, tag, qty=24, rate=355.67, amount=8536.00)
			dn = _make_delivery_note(so.name, rate=400.00)
			_assert(flt(dn.items[0].amount) == 9600.00,
				f"repriced line amount {dn.items[0].amount} != 9600.00 -- the alignment overwrote a real difference")
			_assert(flt(dn.total) == 9600.00, f"repriced DN total {dn.total} != 9600.00")

		def exact_order_is_untouched():
			tag = frappe.generate_hash(length=5).upper()
			so = _make_sales_order(template, tag, qty=10, rate=90.00, amount=900.00)
			dn = _make_delivery_note(so.name)
			_assert(flt(dn.items[0].amount) == 900.00, f"line amount {dn.items[0].amount} != 900.00")
			_assert(flt(dn.grand_total) == flt(so.grand_total),
				f"DN grand total {dn.grand_total} != SO grand total {so.grand_total}")

		def without_the_fix_it_drifts():
			"""Mutation check: with the alignment switched off the old gap must come back."""
			dnh._align_value_with_sales_order = lambda doc: None
			try:
				so, dn = _residue_case(template, frappe.generate_hash(length=5).upper())
			finally:
				dnh._align_value_with_sales_order = real_align
			_assert(flt(dn.items[0].amount) == 8536.08,
				f"unaligned line amount {dn.items[0].amount} != 8536.08 (rate x qty)")
			_assert(flt(dn.grand_total) != flt(so.grand_total),
				"unaligned DN grand total already matches the SO -- the test proves nothing")

		check("full delivery: DN grand total == SO grand total", full_delivery)
		check("GST follows the corrected net total", taxes_follow)
		check("rounded total / rounding adjustment follow", rounded_total_follows)
		check("part delivery keeps its proportional share", part_delivery_is_proportional)
		check("a repriced DN line is left alone", repriced_line_is_left_alone)
		check("an order with no rounding residue is untouched", exact_order_is_untouched)
		check("MUTATION: without the alignment the totals drift", without_the_fix_it_drifts)
		return _report()
	finally:
		dnh._align_value_with_sales_order = real_align
		frappe.db.commit = real_commit
		frappe.db.rollback()
		frappe.set_user("Administrator")


def _report():
	width = max(len(r[1]) for r in R)
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in R if r[0] == 'PASS')}/{sum(1 for r in R if r[0] != 'SKIP')} passed"
	      + (f", {sum(1 for r in R if r[0] == 'SKIP')} skipped" if any(r[0] == "SKIP" for r in R) else ""))
	return R
