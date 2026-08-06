# One-off correction: change Flipkart Sales Order line Flat Discount 38% -> 37%.
#
# The 13 Flipkart Sales Orders (SOR-2627-00097 .. 00109, dated 2026-08-03) were
# imported with a 38% flat discount; the correct Flipkart Minutes margin is 37%
# (supplier_app_amount = MRP x 0.63). Flat discount drives the line rate
# (rate = MRP x (1 - flat/100)), so this resets each 38% line to 37%, recomputes
# selling price + rate = MRP x 0.63, and recomputes the Sales Order totals + GST.
#
# Safe because these orders are 0% delivered / 0% billed (no Delivery Note or
# Sales Invoice yet). Dry run by default — nothing is written until apply=1.
#
#   bench --site <site> execute alpinos.flipkart_flat_discount_fix.run            # dry run
#   bench --site <site> execute alpinos.flipkart_flat_discount_fix.run --kwargs "{'apply': 1}"

import frappe
from frappe.utils import flt

FLIPKART_SO_IDS = [
	"SOR-2627-00097", "SOR-2627-00098", "SOR-2627-00099", "SOR-2627-00100",
	"SOR-2627-00101", "SOR-2627-00102", "SOR-2627-00103", "SOR-2627-00104",
	"SOR-2627-00105", "SOR-2627-00106", "SOR-2627-00107", "SOR-2627-00108",
	"SOR-2627-00109",
]

FLIPKART_CUSTOMER = "Flipkart India Private Limited"

OLD_FLAT = 38.0
NEW_FLAT = 37.0


def _new_price(mrp):
	return flt(flt(mrp) * (1 - NEW_FLAT / 100.0), 2)


def run_margin(apply=0, customer=None):
	"""Update the buyer's catalog margins 38% -> 37% so NEW orders use 37%.

	Covers both stores get_offline_buyer_item_rate reads: the Buyer Items catalog
	(Buyer Item rows, keyed by Buyer Items.buyer = customer) and the Buyer Margin
	fallback (child of the Buyer Master). Dry run by default."""
	apply = int(apply or 0)
	customer = customer or FLIPKART_CUSTOMER
	n_item = n_margin = 0

	item_rows = frappe.db.sql(
		"""
		SELECT obil.name, obil.item_code, obil.mrp, obil.margin_percent, obil.selling_rate
		FROM `tabBuyer Item` obil
		INNER JOIN `tabBuyer Items` obi ON obi.name = obil.parent AND obil.parenttype = 'Buyer Items'
		WHERE obi.buyer = %(c)s AND ROUND(IFNULL(obil.margin_percent, 0)) = %(old)s
		""",
		{"c": customer, "old": int(OLD_FLAT)},
		as_dict=True,
	)
	for r in item_rows:
		vals = {"margin_percent": NEW_FLAT}
		note = ""
		if flt(r.selling_rate) > 0:
			vals["selling_rate"] = _new_price(r.mrp)
			note = f", selling_rate {r.selling_rate} -> {vals['selling_rate']}"
		print(f"Buyer Item  {r.item_code:<16} margin {r.margin_percent} -> {NEW_FLAT}{note}")
		if apply:
			frappe.db.set_value("Buyer Item", r.name, vals, update_modified=False)
		n_item += 1

	for obm in frappe.get_all("Buyer Master", filters={"customer": customer}, pluck="name"):
		for m in frappe.get_all(
			"Buyer Margin", filters={"parent": obm, "parenttype": "Buyer Master"},
			fields=["name", "sku", "margin_percent"],
		):
			if int(round(flt(m.margin_percent))) != int(OLD_FLAT):
				continue
			print(f"Buyer Margin {obm} / {m.sku}: {m.margin_percent} -> {NEW_FLAT}")
			if apply:
				frappe.db.set_value("Buyer Margin", m.name, "margin_percent", NEW_FLAT, update_modified=False)
			n_margin += 1

	if apply:
		frappe.db.commit()
		print(f"\nAPPLIED margin: {n_item} Buyer Item + {n_margin} Buyer Margin row(s) -> {NEW_FLAT}%.")
	else:
		print(f"\nDRY RUN margin: {n_item} Buyer Item + {n_margin} Buyer Margin row(s) would change.")


def run(apply=0, so_ids=None):
	"""Preview (default) or apply the 38% -> 37% flat-discount fix on the Flipkart SOs."""
	apply = int(apply or 0)
	so_ids = so_ids or FLIPKART_SO_IDS

	total_orders, total_lines = 0, 0
	for name in so_ids:
		if not frappe.db.exists("Sales Order", name):
			print("SKIP  not found:", name)
			continue
		so = frappe.get_doc("Sales Order", name)

		# Guard: skip if anything is already delivered or billed (downstream docs exist).
		if flt(so.per_delivered) > 0 or flt(so.per_billed) > 0:
			print("SKIP  delivered/billed:", name,
				  "per_delivered", so.per_delivered, "per_billed", so.per_billed)
			continue

		old_gt = flt(so.grand_total)
		changed = []
		for it in so.items:
			if int(round(flt(it.custom_flat_discount))) != int(OLD_FLAT):
				continue
			mrp = flt(it.custom_customer_mrp)
			old_sp = flt(it.custom_selling_price)
			new_sp = _new_price(mrp)
			# Flat discount drives the rate; clear any margin/discount so the rate
			# is exactly the new selling price and the amount recomputes cleanly.
			it.custom_flat_discount = NEW_FLAT
			it.custom_selling_price = new_sp
			it.price_list_rate = new_sp
			it.rate = new_sp
			it.discount_amount = 0
			it.discount_percentage = 0
			it.margin_type = ""
			it.margin_rate_or_amount = 0
			changed.append((it.item_code, mrp, old_sp, new_sp, flt(it.qty)))

		if not changed:
			print("----  no 38% lines:", name)
			continue

		so.calculate_taxes_and_totals()
		new_gt = flt(so.grand_total)
		print(f"==== {name}: {len(changed)} line(s), grand_total {old_gt} -> {new_gt}")
		for ic, mrp, osp, nsp, q in changed:
			print(f"       {ic:<16} MRP {mrp:>8}  sell {osp:>8} -> {nsp:>8}  x{q:g}")
		total_orders += 1
		total_lines += len(changed)

		if apply:
			so.flags.ignore_validate_update_after_submit = True
			so.db_update()
			for it in so.items:
				it.db_update()
			for tx in (so.taxes or []):
				tx.db_update()

	if apply:
		frappe.db.commit()
		print(f"\nAPPLIED: {total_lines} line(s) across {total_orders} order(s) set to {NEW_FLAT}%.")
	else:
		print(f"\nDRY RUN: {total_lines} line(s) across {total_orders} order(s) would change. "
			  "Re-run with --kwargs \"{'apply': 1}\" to write.")
