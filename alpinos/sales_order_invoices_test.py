"""Changes(HP) #51: several invoices against one partially dispatched Sales Order.

Run:  bench --site alpinos.test execute alpinos.sales_order_invoices_test.run

The part numbering has to agree with #63's -- Part 1 must mean the same dispatch in the
popup as it does in the Accounts Format Report -- so that is checked here directly rather
than assumed. Fixtures roll back.
"""

import frappe
from frappe.utils import today

RES = []


def check(label, fn):
	try:
		fn()
		RES.append(("PASS", label, ""))
	except AssertionError as e:
		RES.append(("FAIL", label, str(e)))
	except Exception as e:
		RES.append(("ERROR", label, f"{type(e).__name__}: {e}"))


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


def _insert(doctype, **values):
	doc = frappe.get_doc(dict(doctype=doctype, **values))
	doc.flags.ignore_mandatory = True
	doc.flags.ignore_validate = True
	doc.db_insert()
	return doc.name


def run():
	RES.clear()
	frappe.set_user("Administrator")
	real_commit = frappe.db.commit
	frappe.db.commit = lambda *a, **k: None
	try:
		_run()
	finally:
		frappe.db.commit = real_commit
		frappe.db.rollback()
		frappe.set_user("Administrator")

	width = max(len(r[1]) for r in RES)
	for status, label, detail in RES:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in RES if r[0] == 'PASS')}/{len(RES)} passed")
	return RES


def _run():
	from alpinos import sales_order_invoices as I

	tag = "INV" + frappe.generate_hash(length=4).upper()
	wh = frappe.db.get_value("Warehouse", {"is_group": 0}, ["name", "company"], as_dict=True)
	company = wh.company if wh else frappe.defaults.get_global_default("company")

	so = _insert("Sales Order", name=f"SOI-{tag}", docstatus=1, company=company,
		customer="Cust", transaction_date=today(), custom_partial_order_allowed=1,
		custom_workflow_status="Partial Dispatched")
	part1 = _insert("Pick List", name=f"PLI-{tag}-A", docstatus=1, company=company,
		custom_sales_order_id=so, custom_dispatch_date="2026-10-01", purpose="Delivery")
	part2 = _insert("Pick List", name=f"PLI-{tag}-B", docstatus=1, company=company,
		custom_sales_order_id=so, custom_dispatch_date="2026-10-05", purpose="Delivery")

	def _parts_are_numbered_oldest_first():
		parts = I._parts_for(so)
		_assert(parts.get(part1) == 1 and parts.get(part2) == 2,
			f"the parts are numbered wrongly: {parts}")

	check("#51 dispatch parts are numbered oldest first", _parts_are_numbered_oldest_first)

	def _the_numbering_agrees_with_the_report():
		"""Part 1 must mean the same dispatch here as in #63's report."""
		from alpinos.alpinos_development.report.accounts_format_report import (
			accounts_format_report as R,
		)
		report_order = [p["name"] for p in R._submitted_parts(so)]
		popup_order = [pl for pl, _n in sorted(I._parts_for(so).items(), key=lambda kv: kv[1])]
		_assert(report_order == popup_order,
			f"the report and the popup disagree about part order: {report_order} vs {popup_order}")

	check("#51 part numbering agrees with the Accounts Format Report",
		_the_numbering_agrees_with_the_report)

	def _an_order_with_one_invoice_and_no_rows_still_reads():
		frappe.db.set_value("Sales Order", so, "custom_invoice_no", "AHF/26-27/6756",
			update_modified=False)
		out = I.get_sales_order_invoices(so)
		_assert(out["count"] == 1, f"the single invoice did not come through: {out}")
		_assert(out["invoices"][0]["invoice_no"] == "AHF/26-27/6756", out["invoices"])
		_assert(not out["multiple"], "one invoice was reported as multiple")

	check("#51 an order carrying only the old single invoice still reads",
		_an_order_with_one_invoice_and_no_rows_still_reads)

	def _two_invoices_can_be_linked_to_their_own_parts():
		I.set_part_invoice(so, "AHF/26-27/6756", pick_list=part1,
			invoice_date="2026-10-01", invoice_amount=12000)
		out = I.set_part_invoice(so, "AHF/26-27/6812", pick_list=part2,
			invoice_date="2026-10-05", invoice_amount=8000)
		_assert(out["count"] == 2, f"two invoices expected: {out['count']}")
		_assert(out["multiple"] == 1, "two invoices were not flagged as multiple")
		by_no = {i["invoice_no"]: i for i in out["invoices"]}
		_assert(by_no["AHF/26-27/6756"]["part_no"] == 1,
			f"the first invoice is not Part 1: {by_no['AHF/26-27/6756']}")
		_assert(by_no["AHF/26-27/6812"]["part_no"] == 2,
			f"the second invoice is not Part 2: {by_no['AHF/26-27/6812']}")

	check("#51 two invoices link to their own dispatch parts",
		_two_invoices_can_be_linked_to_their_own_parts)

	def _each_row_carries_what_the_popup_shows():
		out = I.get_sales_order_invoices(so)
		row = next(i for i in out["invoices"] if i["invoice_no"] == "AHF/26-27/6812")
		for field in ("invoice_no", "invoice_date", "invoice_amount", "part_label", "invoice_pdf"):
			_assert(field in row, f"the row is missing {field}: {row}")
		_assert(row["invoice_date"].startswith("2026-10-05"), row["invoice_date"])
		_assert(row["invoice_amount"] == 8000, row["invoice_amount"])
		_assert(row["part_label"] == "Part 2", row["part_label"])

	check("#51 each row carries the number, date, amount and part the popup shows",
		_each_row_carries_what_the_popup_shows)

	def _recording_the_same_number_again_updates_it():
		before = I.get_sales_order_invoices(so)["count"]
		out = I.set_part_invoice(so, "AHF/26-27/6812", pick_list=part2, invoice_amount=9500)
		_assert(out["count"] == before,
			f"re-recording the same invoice added a row: {before} -> {out['count']}")
		row = next(i for i in out["invoices"] if i["invoice_no"] == "AHF/26-27/6812")
		_assert(row["invoice_amount"] == 9500, f"the correction was not applied: {row}")

	check("#51 re-recording an invoice corrects it instead of duplicating",
		_recording_the_same_number_again_updates_it)

	def _a_part_from_another_order_is_refused():
		other_so = _insert("Sales Order", name=f"SOI-{tag}-X", docstatus=1, company=company,
			customer="Cust", transaction_date=today())
		stray = _insert("Pick List", name=f"PLI-{tag}-X", docstatus=1, company=company,
			custom_sales_order_id=other_so, purpose="Delivery")
		try:
			I.set_part_invoice(so, "AHF/26-27/9999", pick_list=stray)
		except frappe.ValidationError:
			return
		raise AssertionError("an invoice was linked to a Pick List of another order")

	check("#51 a Pick List belonging to another order is refused",
		_a_part_from_another_order_is_refused)

	def _the_list_pages_can_flag_the_multi_invoice_orders():
		counts = I.invoice_counts([so])
		_assert(counts.get(so) == 2, f"the count for the list badge is wrong: {counts}")

	check("#51 a list page can tell which orders carry more than one invoice",
		_the_list_pages_can_flag_the_multi_invoice_orders)
