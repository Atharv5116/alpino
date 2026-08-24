"""Audit / fix: Delivery Note dispatch date must equal its Pick List's dispatch date.

A Delivery Note is built from a Pick List; its custom_dispatch_date should mirror the
Pick List's custom_dispatch_date (see create_delivery_note_from_pick_list). Older DNs can
drift (e.g. they took the order date). This finds every DN whose dispatch date differs from
its Pick List's, and — when apply=1 — rewrites the DN's dispatch date to the Pick List's.

Run:
    bench --site <site> execute alpinos.dn_pl_dispatch_date_audit.run                 # dry-run report
    bench --site <site> execute alpinos.dn_pl_dispatch_date_audit.run --kwargs "{'apply': 1}"   # fix
"""

import frappe
from frappe.utils import getdate


def _pick_list_for_dn(dn_name, so_id):
	"""The Pick List a DN came from: distinct against_pick_list on its items; falling back to
	the SO's single submitted Pick List. Returns (pl_name, ambiguous) — ambiguous=True when the
	DN spans more than one Pick List (dispatch date can't be uniquely inferred)."""
	pls = frappe.db.sql_list(
		"""SELECT DISTINCT against_pick_list FROM `tabDelivery Note Item`
		   WHERE parent = %s AND IFNULL(against_pick_list, '') <> ''""",
		dn_name,
	)
	if not pls and so_id:
		pls = frappe.db.sql_list(
			"SELECT name FROM `tabPick List` WHERE custom_sales_order_id = %s AND docstatus = 1",
			so_id,
		)
	if not pls:
		return None, False
	if len(pls) > 1:
		return None, True
	return pls[0], False


def run(apply=0, include_drafts=1):
	"""Report (and optionally fix) DNs whose dispatch date != their Pick List's dispatch date."""
	apply = int(apply)
	docstatus = ["<", 2] if int(include_drafts) else 1

	dns = frappe.get_all(
		"Delivery Note",
		filters={"docstatus": docstatus, "is_return": 0},
		fields=["name", "custom_dispatch_date", "custom_sales_order_id", "docstatus"],
		order_by="creation desc",
	)

	mismatches, fixed, ambiguous, no_pl = [], 0, [], 0
	for dn in dns:
		pl_name, is_ambiguous = _pick_list_for_dn(dn.name, dn.custom_sales_order_id)
		if is_ambiguous:
			ambiguous.append(dn.name)
			continue
		if not pl_name:
			no_pl += 1
			continue
		pl_date = frappe.db.get_value("Pick List", pl_name, "custom_dispatch_date")
		dn_date = dn.custom_dispatch_date

		# Compare on the DATE level (dispatch DATE, ignore any time component).
		pd = getdate(pl_date) if pl_date else None
		dd = getdate(dn_date) if dn_date else None
		if pd == dd:
			continue

		mismatches.append({
			"delivery_note": dn.name,
			"docstatus": dn.docstatus,
			"pick_list": pl_name,
			"dn_dispatch_date": str(dn_date or ""),
			"pl_dispatch_date": str(pl_date or ""),
		})
		if apply and pl_date:
			# db.set_value works regardless of docstatus (data correction, no re-validation).
			frappe.db.set_value("Delivery Note", dn.name, "custom_dispatch_date", pl_date, update_modified=False)
			fixed += 1

	if apply:
		frappe.db.commit()

	print("=" * 72)
	print(f"Delivery Notes scanned      : {len(dns)}")
	print(f"Dispatch-date MISMATCHES    : {len(mismatches)}")
	print(f"DNs spanning multiple PLs   : {len(ambiguous)} (skipped — {ambiguous[:5]}{'...' if len(ambiguous) > 5 else ''})")
	print(f"DNs with no resolvable PL   : {no_pl} (skipped)")
	if apply:
		print(f"FIXED (DN set to PL date)   : {fixed}")
	else:
		print("DRY RUN — nothing changed. Re-run with apply=1 to set each DN to its PL's date.")
	print("=" * 72)
	for m in mismatches[:200]:
		print(f"  {m['delivery_note']:22} ds={m['docstatus']}  PL {m['pick_list']:22}  DN={m['dn_dispatch_date'][:10] or '-':<12} PL={m['pl_dispatch_date'][:10] or '-'}")
	if len(mismatches) > 200:
		print(f"  ... and {len(mismatches) - 200} more")
	return {"scanned": len(dns), "mismatches": mismatches, "fixed": fixed if apply else 0}
