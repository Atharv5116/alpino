"""Repair Invoice Nos truncated by the last-four rule (the 10000 rollover).

	bench --site SITE execute alpinos.invoice_no_repair.run
	bench --site SITE execute alpinos.invoice_no_repair.run --kwargs "{'apply':1}"

Until 09-10 the upload took the last FOUR characters of the Invoice No cell, so the first
five-digit invoices were stored a digit short: 10000 became 0000. This restores the digit.

IT INFERS. Nothing on the Sales Order records what the sheet actually said -- the Invoice
Sync Log is written after the truncation, so it holds the short number too. The repair
therefore reasons from the shape of the damage: a run of leading-zero four-digit numbers
starting at 0000 is 1 + itself. That is sound for this rollover and for no other, so the
script refuses anything it cannot explain that way, and dry-runs by default.

RE-UPLOADING THE SHEET IS BETTER where the sheet is to hand. It takes the number from the
source instead of inferring it, and it also fetches the PDF, which failed for every one of
these orders -- this script only fixes the number.
"""

import re

import frappe

#: What the truncation leaves behind: four digits with a leading zero.
TRUNCATED = re.compile(r"^0[0-9]{3}$")


def _repaired(stored):
	"""0000 -> 10000. The digit the last-four rule dropped."""
	return "1" + stored


def run(apply=0):
	apply = int(apply)
	rows = frappe.db.sql(
		"""
		SELECT name, custom_invoice_no AS inv, IFNULL(custom_invoice_pdf, '') AS pdf, modified
		FROM `tabSales Order`
		WHERE custom_invoice_no REGEXP '^0[0-9]{3}$'
		ORDER BY custom_invoice_no
		""",
		as_dict=True,
	)
	if not rows:
		print("Nothing matches the truncation signature. Nothing to do.")
		return []

	# Every number the repair would write, checked against what is already on the books.
	wanted = {_repaired(r.inv) for r in rows}
	taken = {
		r[0]
		for r in frappe.db.sql(
			"""SELECT custom_invoice_no FROM `tabSales Order`
			   WHERE custom_invoice_no IN %(w)s AND docstatus < 2""",
			{"w": tuple(wanted)},
		)
	}

	plan, refused = [], []
	for r in rows:
		new = _repaired(r.inv)
		if not TRUNCATED.match(r.inv):
			refused.append((r.name, r.inv, "does not match the truncation signature"))
		elif new in taken:
			# The damaging case the fix was written for: a five-digit invoice collapsing
			# onto a number that already belongs to somebody. Never guess past this.
			refused.append((r.name, r.inv, f"{new} already belongs to another order"))
		else:
			plan.append((r.name, r.inv, new, "attached" if r.pdf else "no PDF"))

	width = max(len(p[0]) for p in plan + [(x[0], 0, 0) for x in refused])
	print(f"\n{'Sales Order'.ljust(width)}  {'stored':>7}  ->  {'repaired':<9}  PDF")
	print("-" * (width + 36))
	for name, old, new, pdf in plan:
		print(f"{name.ljust(width)}  {old:>7}  ->  {new:<9}  {pdf}")
	for name, old, why in refused:
		print(f"{name.ljust(width)}  {old:>7}  --  REFUSED: {why}")

	print(f"\n{len(plan)} to repair, {len(refused)} refused.")
	if not apply:
		print("Dry run. Re-run with --kwargs \"{'apply':1}\" to write.")
		return plan

	for name, old, new, _pdf in plan:
		frappe.db.set_value("Sales Order", name, "custom_invoice_no", new, update_modified=False)
		frappe.db.commit()
		print(f"  {name}: {old} -> {new}")
	print(f"\nWrote {len(plan)} invoice number(s).")
	print("The PDFs are still unattached: re-upload the sheet, or re-run the Drive fetch.")
	return plan
