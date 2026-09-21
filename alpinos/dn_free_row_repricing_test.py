"""Old Delivery Notes that charged for free rows: corrected on their own lines.

Each fixture takes a real submitted note of the site, records its totals, and then gives
it the defect old notes carry: a free row (Marketing Freebies / Scheme / Additional Units,
or a row whose Pick List line came from one of those tables) with rate 0 and a list
price, re-priced by ERPNext's own calculation exactly as it was before 76685a8. The
correction must bring every note back to the totals it had before -- a full delivery to
the order's total, a part delivery to its own share, two notes on one order each to
theirs -- and restate what copied the old figure.

One transaction, rolled back at the end; commits made by the code under test are
ignored while it runs.

Run:  bench --site alpinos.test execute alpinos.dn_free_row_repricing_test.run
"""

import frappe
from frappe.utils import flt

R = []

LIST_PRICE = 250.0

_SOURCES = {
	"freebie": ("Sales Order Marketing Freebie", "custom_marketing_freebies"),
	"scheme": ("Sales Order Scheme Item", "custom_scheme_item_table"),
	"additional": ("Sales Order Additional Units Item", "custom_additional_units_damage_items"),
}


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


def _orders_by_shape():
	"""Submitted, non-return notes grouped by order: full single note, part, two notes."""
	rows = frappe.db.sql(
		"""
		SELECT dn.custom_sales_order_id AS so,
		       GROUP_CONCAT(DISTINCT dn.name ORDER BY dn.name) AS notes,
		       COUNT(DISTINCT dn.name) AS n,
		       SUM(dni.stock_qty) AS dn_qty,
		       (SELECT SUM(stock_qty) FROM `tabSales Order Item` WHERE parent = dn.custom_sales_order_id) AS so_qty,
		       (SELECT grand_total FROM `tabSales Order` WHERE name = dn.custom_sales_order_id) AS so_grand
		FROM `tabDelivery Note` dn
		JOIN `tabDelivery Note Item` dni ON dni.parent = dn.name
		WHERE dn.docstatus = 1 AND IFNULL(dn.is_return, 0) = 0
		  AND IFNULL(dn.custom_sales_order_id, '') <> ''
		  AND NOT EXISTS (SELECT 1 FROM `tabDelivery Note Item` x
		                  WHERE x.parent = dn.name AND IFNULL(x.so_detail, '') = '')
		GROUP BY dn.custom_sales_order_id
		ORDER BY dn.custom_sales_order_id
		""",
		as_dict=True,
	)
	full, part, two = [], [], []
	for r in rows:
		notes = r.notes.split(",")
		if r.n == 1 and flt(r.dn_qty) == flt(r.so_qty) and flt(
			frappe.db.get_value("Delivery Note", notes[0], "grand_total"), 2
		) == flt(r.so_grand, 2):
			full.append((r.so, notes[0]))
		elif r.n == 1 and flt(r.dn_qty) < flt(r.so_qty):
			part.append((r.so, notes[0]))
		elif r.n == 2 and flt(r.dn_qty) == flt(r.so_qty):
			two.append((r.so, notes))
	return full, part, two


def _snapshot(dn_name):
	doc = frappe.get_doc("Delivery Note", dn_name)
	return {
		"grand_total": flt(doc.grand_total, 2),
		"net_total": flt(doc.net_total, 2),
		"total_taxes_and_charges": flt(doc.total_taxes_and_charges, 2),
		"rounded_total": flt(doc.rounded_total, 2),
		"modified": str(doc.modified),
		"rows": {r.name: (flt(r.rate, 2), flt(r.amount, 2), flt(r.net_amount, 2)) for r in doc.items},
	}


def _add_free_row(dn_name, source, qty=2):
	"""Give the note a free row priced the way old notes were: rate 0, a list price, and
	ERPNext's calculation re-pricing it. Returns the new row's name."""
	from alpinos.dn_free_row_repricing import _recalculate

	dn = frappe.get_doc("Delivery Note", dn_name)
	so = dn.custom_sales_order_id or dn.items[0].against_sales_order
	template = dn.items[0]

	so_detail, pick_list_item = None, None
	if source == "pick list":
		# Known only from the Pick List line it was picked on.
		pli = frappe.get_doc({
			"doctype": "Pick List Item",
			"parent": template.get("against_pick_list") or "PL-FIXTURE",
			"parenttype": "Pick List",
			"parentfield": "locations",
			"item_code": template.item_code,
			"qty": qty,
			"stock_qty": qty,
			"custom_source_table": "Marketing Freebies",
			"docstatus": 1,
		})
		pli.name = "DNFR-" + frappe.generate_hash(length=8)
		pli.db_insert()
		pick_list_item = pli.name
	else:
		table, parentfield = _SOURCES[source]
		src = frappe.get_doc({
			"doctype": table,
			"parent": so,
			"parenttype": "Sales Order",
			"parentfield": parentfield,
			"item_code": template.item_code,
			"item_name": template.item_name,
			"qty": qty,
			"docstatus": 1,
		})
		src.name = "DNFR-" + frappe.generate_hash(length=8)
		src.db_insert()
		so_detail = src.name

	values = template.as_dict(no_default_fields=True)
	values.update({
		"qty": qty, "stock_qty": qty, "so_detail": so_detail, "pick_list_item": pick_list_item,
		"rate": 0, "base_rate": 0, "net_rate": 0, "base_net_rate": 0,
		"amount": 0, "base_amount": 0, "net_amount": 0, "base_net_amount": 0,
		"discount_percentage": 0, "discount_amount": 0, "margin_rate_or_amount": 0,
		"pricing_rules": "", "serial_and_batch_bundle": None,
		# What ERPNext filled from the Item Price list when the field came across as None.
		"price_list_rate": LIST_PRICE, "base_price_list_rate": LIST_PRICE,
	})
	row = dn.append("items", values)
	row.name = "DNFR-" + frappe.generate_hash(length=8)
	row.docstatus = dn.docstatus

	_recalculate(dn)  # the old defect: rate 0 + a list price -> priced at list price
	if hasattr(dn, "set_total_in_words"):
		dn.set_total_in_words()
	dn.db_update()
	for r in list(dn.items) + list(dn.get("taxes") or []):
		if r.name == row.name:
			r.db_insert()
		else:
			r.db_update()
	return row.name


def _free_row_prices(row_name):
	from alpinos.dn_free_row_repricing import _PRICE_FIELDS

	meta = frappe.get_meta("Delivery Note Item")
	fields = [f for f in _PRICE_FIELDS if meta.has_field(f)]
	return frappe.db.get_value("Delivery Note Item", row_name, fields, as_dict=True)


def _comments(dn_name):
	return frappe.get_all(
		"Comment",
		filters={"reference_doctype": "Delivery Note", "reference_name": dn_name,
		         "comment_type": "Info", "content": ["like", "Free rows%"]},
		pluck="name",
	)


# --------------------------------------------------------------------- run


def run():
	R.clear()
	frappe.set_user("Administrator")
	real_commit = frappe.db.commit
	frappe.db.commit = lambda *args, **kwargs: None
	from alpinos import dn_free_row_repricing as fix
	from alpinos import so_invoice_value as siv
	real_fields = fix._PRICE_FIELDS
	try:
		full, part, two = _orders_by_shape()
		if len(full) < 3 or not part or not two:
			R.append(("SKIP", "old notes with priced free rows",
			          f"need 3 fully delivered, 1 part and 1 two-note order; site has {len(full)}/{len(part)}/{len(two)}"))
			return _report()

		(so_full, dn_full), (so_tamper, dn_tamper), (so_ctrl, dn_ctrl) = full[:3]
		so_part, dn_part = part[0]
		so_two, (dn_two_a, dn_two_b) = two[0]
		so_grand = {so: flt(frappe.db.get_value("Sales Order", so, "grand_total"), 2)
		            for so in (so_full, so_part, so_two, so_ctrl)}

		base = {dn: _snapshot(dn) for dn in (dn_full, dn_part, dn_two_a, dn_two_b, dn_ctrl, dn_tamper)}

		# The defect, reached four ways.
		free = {
			dn_full: _add_free_row(dn_full, "freebie"),
			dn_part: _add_free_row(dn_part, "scheme"),
			dn_two_a: _add_free_row(dn_two_a, "additional"),
			dn_two_b: _add_free_row(dn_two_b, "pick list"),
		}
		inflated = {dn: _snapshot(dn) for dn in free}
		_add_free_row(dn_tamper, "freebie")
		frappe.db.set_value("Delivery Note", dn_tamper, "grand_total",
		                    flt(frappe.db.get_value("Delivery Note", dn_tamper, "grand_total")) + 10,
		                    update_modified=False)

		# What the old rules stamped: Post Dispatch from the note, the order from the notes' sum.
		pd = frappe.get_doc({"doctype": "Post Dispatch", "sales_order": so_full, "delivery_note": dn_full,
		                     "total_invoice_value": inflated[dn_full]["grand_total"]})
		pd.name = "DNFR-" + frappe.generate_hash(length=8)
		pd.db_insert()
		for so, notes in ((so_full, [dn_full]), (so_part, [dn_part]), (so_two, [dn_two_a, dn_two_b])):
			frappe.db.set_value("Sales Order", so, "custom_total_invoice_value",
			                    flt(sum(inflated[n]["grand_total"] for n in notes), 2), update_modified=False)

		def defect_reproduced():
			for dn in free:
				_assert(inflated[dn]["grand_total"] > base[dn]["grand_total"] + LIST_PRICE,
				        f"{dn}: fixture did not price the free row ({base[dn]['grand_total']} -> {inflated[dn]['grand_total']})")
			_assert(inflated[dn_full]["grand_total"] > so_grand[so_full],
			        "the full delivery's note should now read above its order, as in SOR-2627-02828")

		def found_all_four_ways():
			found = set(fix.affected_notes())
			for dn, how in ((dn_full, "freebie"), (dn_part, "scheme"), (dn_two_a, "additional units"),
			                (dn_two_b, "pick list source")):
				_assert(dn in found, f"{dn} ({how}) not found")
			_assert(dn_ctrl not in found, "a note with no free rows was listed")

		def dry_run_writes_nothing():
			out = fix.run(apply=0)
			_assert(out["mode"] == "DRY-RUN", out["mode"])
			_assert(out["corrected"] >= 4, f"dry run reported {out['corrected']} notes")
			for dn in free:
				_assert(_snapshot(dn)["grand_total"] == inflated[dn]["grand_total"], f"dry run wrote {dn}")
			_assert(flt(frappe.db.get_value("Post Dispatch", pd.name, "total_invoice_value"), 2)
			        == inflated[dn_full]["grand_total"], "dry run restated Post Dispatch")
			_assert(not _comments(dn_full), "dry run left a comment")

		check("fixtures carry the old defect (free row priced from the Item Price list)", defect_reproduced)
		check("free rows are found by table (freebie, scheme, additional) and by Pick List source", found_all_four_ways)
		check("a dry run writes nothing", dry_run_writes_nothing)

		out = fix.run(apply=1)
		after = {dn: _snapshot(dn) for dn in base}

		def full_back_to_order():
			a = after[dn_full]
			_assert(a["grand_total"] == base[dn_full]["grand_total"],
			        f"{dn_full}: {a['grand_total']} != {base[dn_full]['grand_total']} before the free row")
			_assert(a["grand_total"] == so_grand[so_full],
			        f"{dn_full}: {a['grand_total']} != order total {so_grand[so_full]}")

		def part_keeps_its_share():
			a = after[dn_part]
			_assert(a["grand_total"] == base[dn_part]["grand_total"],
			        f"{dn_part}: {a['grand_total']} != its own {base[dn_part]['grand_total']}")
			_assert(a["grand_total"] < so_grand[so_part],
			        f"{dn_part}: a part delivery was raised to the order total {so_grand[so_part]}")

		def two_notes_each_their_own():
			for dn in (dn_two_a, dn_two_b):
				_assert(after[dn]["grand_total"] == base[dn]["grand_total"],
				        f"{dn}: {after[dn]['grand_total']} != its own {base[dn]['grand_total']}")
				_assert(after[dn]["grand_total"] < so_grand[so_two], f"{dn} was set to the order total")
			both = flt(after[dn_two_a]["grand_total"] + after[dn_two_b]["grand_total"], 2)
			_assert(abs(both - so_grand[so_two]) <= 0.02, f"two notes add to {both}, order {so_grand[so_two]}")

		def free_rows_zero_order_lines_unchanged():
			for dn, row in free.items():
				prices = _free_row_prices(row)
				_assert(all(not flt(v) for v in prices.values()), f"{dn} free row still priced: {prices}")
				for name, vals in base[dn]["rows"].items():
					_assert(after[dn]["rows"].get(name) == vals,
					        f"{dn} order line {name} moved: {vals} -> {after[dn]['rows'].get(name)}")

		def gst_and_rounding_follow():
			for dn in free:
				_assert(after[dn]["net_total"] == base[dn]["net_total"], f"{dn} net total")
				_assert(after[dn]["total_taxes_and_charges"] == base[dn]["total_taxes_and_charges"],
				        f"{dn} GST {after[dn]['total_taxes_and_charges']} != {base[dn]['total_taxes_and_charges']}")
				_assert(after[dn]["rounded_total"] == base[dn]["rounded_total"], f"{dn} rounded total")
				taxes = flt(sum(flt(t) for t in frappe.get_all(
					"Sales Taxes and Charges", filters={"parent": dn, "parenttype": "Delivery Note"},
					pluck="tax_amount")), 2)
				_assert(taxes == after[dn]["total_taxes_and_charges"], f"{dn} tax rows {taxes} vs total")

		def post_dispatch_follows():
			v = flt(frappe.db.get_value("Post Dispatch", pd.name, "total_invoice_value"), 2)
			_assert(v == after[dn_full]["grand_total"], f"Post Dispatch {v} != note {after[dn_full]['grand_total']}")

		def order_value_restated():
			full_v = flt(frappe.db.get_value("Sales Order", so_full, "custom_total_invoice_value"), 2)
			_assert(full_v == so_grand[so_full], f"{so_full} Total Invoice Value {full_v} != order {so_grand[so_full]}")
			part_v = flt(frappe.db.get_value("Sales Order", so_part, "custom_total_invoice_value"), 2)
			_assert(part_v == flt(siv._dispatched_value(so_part), 2) and 0 < part_v < so_grand[so_part],
			        f"{so_part} Total Invoice Value {part_v} (order {so_grand[so_part]})")
			_assert(abs(part_v - after[dn_part]["grand_total"]) <= 1,
			        f"{so_part}: order value {part_v} vs its one note {after[dn_part]['grand_total']}")
			two_v = flt(frappe.db.get_value("Sales Order", so_two, "custom_total_invoice_value"), 2)
			_assert(two_v == so_grand[so_two], f"{so_two} Total Invoice Value {two_v} != order {so_grand[so_two]}")

		def audit_comment():
			for dn in free:
				_assert(len(_comments(dn)) == 1, f"{dn} has {len(_comments(dn))} audit comments")

		def control_untouched():
			_assert(after[dn_ctrl] == base[dn_ctrl], f"{dn_ctrl} changed")
			_assert(not _comments(dn_ctrl), f"{dn_ctrl} got a comment")

		def mismatch_left_for_review():
			_assert(any(r["delivery_note"] == dn_tamper for r in out["left_for_review"]),
			        f"{dn_tamper} not listed for review: {out['left_for_review']}")
			_assert(not _comments(dn_tamper), f"{dn_tamper} was written")
			priced = frappe.db.sql(
				"SELECT COUNT(*) FROM `tabDelivery Note Item` WHERE parent = %s AND amount > 0 AND name LIKE 'DNFR-%%'",
				dn_tamper)[0][0]
			_assert(priced == 1, f"{dn_tamper} free row was re-priced although its totals did not reproduce")

		def second_run_is_a_no_op():
			again = fix.run(apply=1)
			_assert(again["corrected"] == 0, f"second run corrected {again['corrected']}")
			for dn in free:
				_assert(len(_comments(dn)) == 1, f"{dn} commented twice")

		check("full delivery: the note is back to the order's total", full_back_to_order)
		check("part delivery keeps its own share, never the order's total", part_keeps_its_share)
		check("two notes on one order: each back to its own total, together the order's", two_notes_each_their_own)
		check("free rows are 0 on every price field; order lines do not move", free_rows_zero_order_lines_unchanged)
		check("GST, tax rows and rounded total follow", gst_and_rounding_follow)
		check("Post Dispatch is restated from the corrected note", post_dispatch_follows)
		check("the order's Total Invoice Value is restated, part delivery pro rata", order_value_restated)
		check("each corrected note gets one audit comment", audit_comment)
		check("a note without free rows is not touched", control_untouched)
		check("a note whose totals do not reproduce is left for review, not written", mismatch_left_for_review)
		check("running it again changes nothing", second_run_is_a_no_op)

		def patch_restates_every_order():
			from alpinos.patches.v1_0.reprice_free_rows_on_old_delivery_notes import execute
			row = _add_free_row(dn_two_a, "freebie", qty=3)
			frappe.db.set_value("Sales Order", so_ctrl, "custom_total_invoice_value", 1.0, update_modified=False)
			execute()
			_assert(_snapshot(dn_two_a)["grand_total"] == base[dn_two_a]["grand_total"], "patch did not correct the note")
			_assert(not any(flt(v) for v in _free_row_prices(row).values()), "patch left the free row priced")
			v = flt(frappe.db.get_value("Sales Order", so_ctrl, "custom_total_invoice_value"), 2)
			_assert(v == so_grand[so_ctrl], f"patch left {so_ctrl} at {v}, order {so_grand[so_ctrl]}")

		def mutation_rate_only():
			"""Zero the rate but leave the list price: ERPNext re-prices the row from it."""
			before = _snapshot(dn_full)["grand_total"]
			_add_free_row(dn_full, "freebie")
			fix._PRICE_FIELDS = tuple(f for f in real_fields if "price_list_rate" not in f)
			try:
				fix.reprice(dn_full, apply=True)
			finally:
				fix._PRICE_FIELDS = real_fields
			_assert(_snapshot(dn_full)["grand_total"] > before,
			        "without zeroing the list price the row stayed free -- the check proves nothing")

		def mutation_no_guard():
			"""Drop the reproduce-first guard: the tampered note gets rewritten."""
			real = fix._recalculate
			calls = {"n": 0}

			def recalc_skipping_guard(doc):
				calls["n"] += 1
				if calls["n"] == 1:
					for f in fix._TOTALS:
						doc.set(f, frappe.db.get_value("Delivery Note", doc.name, f))
					return
				real(doc)

			fix._recalculate = recalc_skipping_guard
			try:
				res = fix.reprice(dn_tamper, apply=False)
			finally:
				fix._recalculate = real
			_assert(res["status"] == "would correct", "the guard is what holds the tampered note back")

		check("the migration patch corrects notes and restates every order's value", patch_restates_every_order)
		check("MUTATION: zeroing only the rate leaves the row priced", mutation_rate_only)
		check("MUTATION: without the reproduce-first guard the tampered note is rewritten", mutation_no_guard)
		return _report()
	finally:
		fix._PRICE_FIELDS = real_fields
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
