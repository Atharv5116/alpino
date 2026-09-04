"""Repair Purchase Inwards whose derived values were lost to the post-save hook bug.

Until PurchaseInward moved its derivations into `before_update_after_submit`, every
Store-receiving edit computed expiry dates, previously-received / pending / excess
quantities and the total_* roll-ups in `on_update_after_submit` -- which frappe runs
only after `db_update()` has already flushed the row (document.py:1151 vs :1188). The
values were assigned to an in-memory document nobody saved again, so they were silently
discarded and every submitted inward kept its draft-time numbers.

This re-saves each affected inward so the (now correctly placed) derivations persist.
Run it once after deploying the fix:

    bench --site <site> execute alpinos.purchase.backfill.repair_derived_values
    bench --site <site> execute alpinos.purchase.backfill.repair_derived_values --kwargs "{'dry_run': False}"
"""

import frappe
from frappe.utils import flt


def repair_derived_values(dry_run=True, limit=None):
	"""Re-save submitted Purchase Inwards so derived fields are written.

	dry_run defaults to True: it reports what would change and writes nothing.
	"""
	names = frappe.get_all(
		"Purchase Inward",
		filters={"docstatus": 1},
		pluck="name",
		order_by="creation asc",
		limit_page_length=limit or 0,
	)

	repaired, skipped, failed = [], [], []

	for name in names:
		try:
			doc = frappe.get_doc("Purchase Inward", name)
			before = _snapshot(doc)

			# recompute exactly what before_update_after_submit would
			doc._compute_previously_received()
			doc._apply_default_target_warehouse()
			doc._set_expiry_dates()
			doc._roll_up_totals()
			after = _snapshot(doc)

			if before == after:
				skipped.append(name)
				continue

			if dry_run:
				repaired.append((name, _diff(before, after)))
				continue

			doc.flags.ignore_permissions = True
			doc.save()
			repaired.append((name, _diff(before, after)))
		except Exception as exc:
			failed.append((name, f"{type(exc).__name__}: {exc}"))
			frappe.db.rollback()

	if not dry_run:
		frappe.db.commit()

	print(f"Purchase Inward derived-value backfill ({'DRY RUN' if dry_run else 'APPLIED'})")
	print(f"  scanned  : {len(names)}")
	print(f"  repaired : {len(repaired)}")
	print(f"  unchanged: {len(skipped)}")
	print(f"  failed   : {len(failed)}")
	for name, changes in repaired:
		print(f"    {name}: {changes}")
	for name, err in failed:
		print(f"    FAILED {name}: {err}")

	return {"scanned": len(names), "repaired": len(repaired), "failed": failed}


def _snapshot(doc):
	return {
		"totals": (
			flt(doc.get("total_received_qty")),
			flt(doc.get("total_pending_qty")),
			flt(doc.get("total_excess_qty")),
		),
		"rows": [
			(
				row.name,
				str(row.get("expiry_date") or ""),
				flt(row.get("previously_received_qty")),
				flt(row.get("pending_qty")),
				flt(row.get("excess_qty")),
			)
			for row in doc.get("items") or []
		],
	}


def _diff(before, after):
	bits = []
	if before["totals"] != after["totals"]:
		bits.append(f"totals {before['totals']} -> {after['totals']}")
	changed_rows = sum(1 for b, a in zip(before["rows"], after["rows"]) if b != a)
	if changed_rows:
		bits.append(f"{changed_rows} item row(s)")
	return "; ".join(bits) or "no change"
