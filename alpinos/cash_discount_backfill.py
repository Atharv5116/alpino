"""One-time backfill: correct Sales Orders whose CASH DISCOUNT was over-charged.

Older orders computed the cash discount via ERPNext's additional_discount_percentage
on "Grand Total" while the net/GST were mis-stored (gross treated as net, GST added on
top), so the discount base inflated past the item value — e.g. 5% of a 1,74,066 order
became 9,573.65 instead of 8,703.30. Current code stores clean GST-inclusive amounts, so
NEW orders are correct; only the OLD ones need fixing.

Correct cash discount = cash% x the GST-INCLUSIVE item value (selling_price x qty, less
the line's additional discount). This is exactly what a re-save produces today.

Run (ALWAYS dry-run first):
    bench --site <site> execute alpinos.cash_discount_backfill.backfill
    bench --site <site> execute alpinos.cash_discount_backfill.backfill --kwargs "{'dry_run':0}"

Both draft and submitted orders get a surgical correction of just the discount +
grand-total fields (net_total / taxes / item rows are left untouched) — a full re-save is
avoided so unrelated validations can't block the fix. Any order whose net+taxes don't
already reconcile to the item value is SKIPPED and listed for manual review, so this never
guesses at a deeper problem.
"""

import frappe
from frappe.utils import flt

# net_total + taxes must sit within this of the item value for a safe auto-fix.
_TOLERANCE = 0.10

# An order counts as over-charged only if the discount is off by more than ~a rupee. The
# live calc rounds the intermediate net, so a correctly-computed order can sit a paisa or
# two off this script's flat cash% x item_value formula (e.g. 8703.28 vs 8703.30) — that is
# rounding noise, NOT a bug, so it must not be "corrected".
_DISC_TOLERANCE = 1.00


def _item_value(doc):
	"""GST-inclusive order value = sum of selling_price x qty less each line's additional
	discount. selling_price is stored correctly on the rows, so this is the reliable base."""
	total = 0.0
	for it in doc.get("items") or []:
		sp = flt(it.get("custom_selling_price") or it.get("selling_price"), 2)
		qty = flt(it.get("qty"))
		add = flt(it.get("custom_additional_discount"))
		total = flt(total + flt(sp * qty * (1 - add / 100.0), 2), 2)
	return flt(total, 2)


def _apply_correction(doc, item_value, correct_disc):
	"""Surgically fix an order's discount + grand-total fields only (draft or submitted)."""
	new_grand = flt(item_value - correct_disc, 2)
	vals = {
		"discount_amount": correct_disc,
		"base_discount_amount": correct_disc,
		"custom_cash_discount_amount": correct_disc,
		"grand_total": new_grand,
		"base_grand_total": new_grand,
	}
	if doc.get("disable_rounded_total"):
		vals["rounded_total"] = 0
		vals["base_rounded_total"] = 0
		vals["rounding_adjustment"] = 0
		vals["base_rounding_adjustment"] = 0
	else:
		rt = flt(round(new_grand), 2)
		vals["rounded_total"] = rt
		vals["base_rounded_total"] = rt
		vals["rounding_adjustment"] = flt(rt - new_grand, 2)
		vals["base_rounding_adjustment"] = flt(rt - new_grand, 2)
	frappe.db.set_value("Sales Order", doc.name, vals, update_modified=False)


def backfill(dry_run=1, limit=None):
	"""Scan every Sales Order with a cash discount; report/fix the over-charged ones."""
	dry_run = int(dry_run)
	names = frappe.get_all(
		"Sales Order",
		filters={"custom_cash_discount": [">", 0]},
		pluck="name",
		order_by="creation asc",
	)

	fixed, skipped, already_ok = [], [], 0
	for name in names:
		doc = frappe.get_doc("Sales Order", name)
		cash = flt(doc.get("custom_cash_discount"))
		item_value = _item_value(doc)
		correct_disc = flt(item_value * cash / 100.0, 2)
		stored = flt(doc.get("custom_cash_discount_amount"))

		if abs(stored - correct_disc) <= _DISC_TOLERANCE:
			already_ok += 1
			continue

		# Only auto-fix when net+taxes already reconcile to the item value; otherwise the
		# order has a deeper mis-store and is left for manual review.
		reconciles = abs(flt(doc.get("net_total")) + flt(doc.get("total_taxes_and_charges")) - item_value) <= _TOLERANCE
		info = {
			"name": name, "docstatus": doc.docstatus, "cash_pct": cash,
			"stored_disc": stored, "correct_disc": correct_disc,
			"old_grand": flt(doc.get("grand_total")), "new_grand": flt(item_value - correct_disc, 2),
			"reconciles": reconciles,
		}

		if not reconciles:
			skipped.append(info)
			continue

		fixed.append(info)
		if not dry_run:
			_apply_correction(doc, item_value, correct_disc)
		if limit and len(fixed) >= int(limit):
			break

	if not dry_run:
		frappe.db.commit()

	tag = "DRY RUN — would fix" if dry_run else "FIXED"
	print("=" * 78)
	print(f"Orders with a cash discount: {len(names)} | already correct: {already_ok}")
	print(f"{tag}: {len(fixed)} | skipped for manual review (net/taxes off): {len(skipped)}")
	print("-" * 78)
	for i in fixed:
		print(f"  [{i['docstatus']}] {i['name']}: cash {i['cash_pct']}% | "
			f"disc {i['stored_disc']} -> {i['correct_disc']} | grand {i['old_grand']} -> {i['new_grand']}")
	if skipped:
		print("-" * 78)
		print("SKIPPED (net_total + taxes do not reconcile to item value — review by hand):")
		for i in skipped:
			print(f"  [{i['docstatus']}] {i['name']}: stored disc {i['stored_disc']} "
				f"vs expected {i['correct_disc']} | item-value check failed")
	print("=" * 78)
	return {"fixed": fixed, "skipped": skipped, "already_ok": already_ok, "total": len(names)}
