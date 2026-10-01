"""Batch No. on the standard Stock Ledger report, on its ordinary rows.

ERPNext v15 no longer writes the batch onto the Stock Ledger Entry itself: a batch-tracked
item keeps it in the linked Serial and Batch Bundle, so the report's Batch column stayed
blank unless "Segregate Serial / Batch Bundle" was ticked (which splits every row). Items
that are not batch-tracked carry their batch only on the transaction line -- for a GRN,
the Internal Batch No. the Inward / QC flow writes onto each Purchase Receipt Item.

This wraps the report's execute() and fills the Batch column AFTER ERPNext has built the
rows, from, in order:

    1. the row's Serial and Batch Bundle (every batch in it, comma separated)
    2. the transaction line's own batch_no
    3. the transaction line's custom_internal_batch_no (GRN lines)
    4. for a release out of quarantine, the Purchase Quarantine line's batch

It also skips ledger entries whose Item has been deleted, which otherwise crash the whole
report with a KeyError (see get_stock_ledger_entries in patch()).

Read-only: nothing is written anywhere, and ERPNext's files are not edited. Rows that
already have a batch, the opening row, and the segregated view are left exactly as
ERPNext produced them.

Applied from the before_request / before_job hooks, so every web worker and background
worker (a large ledger runs as a prepared report) has it; patch() is idempotent.
"""

import frappe

REPORT_MODULE = "erpnext.stock.report.stock_ledger.stock_ledger"

#: voucher type -> child doctype holding the stock lines
_CHILD = {
	"Purchase Receipt": "Purchase Receipt Item",
	"Purchase Invoice": "Purchase Invoice Item",
	"Delivery Note": "Delivery Note Item",
	"Sales Invoice": "Sales Invoice Item",
	"Stock Entry": "Stock Entry Detail",
	"Stock Reconciliation": "Stock Reconciliation Item",
}


def patch(*args, **kwargs):
	try:
		module = frappe.get_module(REPORT_MODULE)
	except Exception:
		return
	if getattr(module.execute, "_alpinos_batch", False):
		return
	original = module.execute

	# Ledger entries whose Item no longer exists (a deleted item's entries are left behind)
	# made ERPNext's execute() raise KeyError on item_details[sle.item_code] and the whole
	# report failed to open. Those rows are skipped instead; they have no item to show.
	original_sles = module.get_stock_ledger_entries

	def get_stock_ledger_entries(filters, items):
		sles = original_sles(filters, items)
		codes = list({s.item_code for s in sles if s.get("item_code")})
		if not codes:
			return sles
		existing = set(frappe.get_all("Item", filters={"name": ("in", codes)}, pluck="name"))
		if len(existing) == len(codes):
			return sles
		return [s for s in sles if s.get("item_code") in existing]

	module.get_stock_ledger_entries = get_stock_ledger_entries

	def execute(filters=None):
		result = original(filters)
		try:
			if not (filters or {}).get("segregate_serial_batch_bundle"):
				if fill_batches(result[1]):
					# An Internal Batch No. or a comma-joined list is not a Batch record, so
					# the column shows plain text instead of a link that leads nowhere.
					for col in result[0] or []:
						if isinstance(col, dict) and col.get("fieldname") == "batch_no":
							col["fieldtype"] = "Data"
							col.pop("options", None)
		except Exception:
			# A report must still open if this enrichment fails.
			frappe.log_error(frappe.get_traceback(), "Stock Ledger: batch column")
		return result

	execute._alpinos_batch = True
	module.execute = execute


def _join(values):
	seen = []
	for v in values:
		if v and v not in seen:
			seen.append(v)
	return ", ".join(seen)


def fill_batches(data):
	"""Fill the empty batch cells in place. Returns how many were filled."""
	rows = [r for r in data or [] if isinstance(r, dict) and r.get("voucher_no") and not r.get("batch_no")]
	if not rows:
		return 0

	# 1. bundles
	bundles = list({r.get("serial_and_batch_bundle") for r in rows if r.get("serial_and_batch_bundle")})
	by_bundle = {}
	if bundles:
		for e in frappe.get_all(
			"Serial and Batch Entry",
			filters={"parent": ("in", bundles), "batch_no": ("is", "set")},
			fields=["parent", "batch_no"],
			order_by="idx asc",
		):
			by_bundle.setdefault(e.parent, []).append(e.batch_no)

	# 2 + 3. transaction lines, keyed by (voucher_no, item_code, warehouse)
	by_line = {}
	pending = [r for r in rows if not by_bundle.get(r.get("serial_and_batch_bundle"))]
	vouchers = {}
	for r in pending:
		if r.get("voucher_type") in _CHILD:
			vouchers.setdefault(r["voucher_type"], set()).add(r["voucher_no"])
	for vtype, names in vouchers.items():
		sles = frappe.get_all(
			"Stock Ledger Entry",
			filters={"voucher_type": vtype, "voucher_no": ("in", list(names)), "is_cancelled": 0},
			fields=["voucher_no", "item_code", "warehouse", "voucher_detail_no"],
		)
		details = list({s.voucher_detail_no for s in sles if s.voucher_detail_no})
		if not details:
			continue
		child = _CHILD[vtype]
		cols = set(frappe.db.get_table_columns(child))
		fields = ["name"] + [f for f in ("batch_no", "custom_internal_batch_no") if f in cols]
		if len(fields) == 1:
			continue
		lines = {
			l.name: l for l in frappe.get_all(child, filters={"name": ("in", details)}, fields=fields)
		}
		for s in sles:
			l = lines.get(s.voucher_detail_no)
			if not l:
				continue
			batch = l.get("batch_no") or l.get("custom_internal_batch_no")
			if batch:
				by_line.setdefault((s.voucher_no, s.item_code, s.warehouse), []).append(batch)

	# 4. a release out of quarantine: its Stock Entry carries only an ERPNext batch, so a
	# non-batch-tracked item came out blank. The Purchase Quarantine line holds the QC's
	# Internal Batch No. and the Stock Entry that released it.
	se_names = list({r["voucher_no"] for r in rows if r.get("voucher_type") == "Stock Entry"
	                 and not by_line.get((r.get("voucher_no"), r.get("item_code"), r.get("warehouse")))})
	if se_names and frappe.db.exists("DocType", "Purchase Quarantine Item"):
		for q in frappe.get_all(
			"Purchase Quarantine Item",
			filters={"release_stock_entry": ("in", se_names), "batch_no": ("is", "set")},
			fields=["release_stock_entry", "item_code", "batch_no"],
		):
			by_line.setdefault((q.release_stock_entry, q.item_code, None), []).append(q.batch_no)

	filled = 0
	for r in rows:
		batch = _join(by_bundle.get(r.get("serial_and_batch_bundle")) or [])
		if not batch:
			batch = _join(by_line.get((r.get("voucher_no"), r.get("item_code"), r.get("warehouse"))) or [])
		if not batch:
			# Quarantine release: both the out-of-Quarantine and the into-store row.
			batch = _join(by_line.get((r.get("voucher_no"), r.get("item_code"), None)) or [])
		if batch:
			r["batch_no"] = batch
			filled += 1
	return filled
