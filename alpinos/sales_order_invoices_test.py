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
		_from_the_upload()
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


def _from_the_upload():
	"""The popup reads what the Invoice Mapping upload actually writes: part 1's invoice on the
	order and its Pick List, SOR-.../2 on the second part's Pick List (Changes(HP) #125), the
	second PDF attached to the order. Nothing fills the Sales Order Invoice table."""
	from alpinos import invoice_sync as S
	from alpinos import sales_order_invoices as I

	tag = "IUP" + frappe.generate_hash(length=4).upper()
	wh = frappe.db.get_value("Warehouse", {"is_group": 0}, ["name", "company"], as_dict=True)
	company = wh.company if wh else frappe.defaults.get_global_default("company")

	def _order(suffix, partial=1, **extra):
		return _insert("Sales Order", name=f"SOU-{tag}-{suffix}", docstatus=1, company=company,
			customer="Cust", transaction_date=today(), custom_partial_order_allowed=partial,
			custom_total_invoice_value=50000, **extra)

	def _part(so, suffix, creation, **extra):
		return _insert("Pick List", name=f"PLU-{tag}-{suffix}", docstatus=1, company=company,
			custom_sales_order_id=so, custom_dispatch_date="2026-11-20", purpose="Delivery",
			creation=creation, **extra)

	so = _order("A")
	part1 = _part(so, "A1", "2026-11-20 10:47:00")
	part2 = _part(so, "A2", "2026-11-20 10:54:00")

	real_drive = S._drive_enabled
	S._drive_enabled = lambda s: False
	try:
		S._run_invoice_sync({so: "12306", f"{so}/2": "12307"})
	finally:
		S._drive_enabled = real_drive

	def _both_invoices_listed():
		_assert(frappe.db.get_value("Pick List", part2, "custom_invoice_no") == "12307", "the upload did not stamp part 2")
		out = I.get_sales_order_invoices(so)
		got = [(i["invoice_no"], i["part_label"], i["pick_list"]) for i in out["invoices"]]
		_assert(got == [("12306", "Part 1", part1), ("12307", "Part 2", part2)], got)
		_assert(out["count"] == 2 and out["multiple"] == 1, out)

	check("#51 the popup lists SOR-.../2's invoice from its Pick List beside part 1's", _both_invoices_listed)

	def _list_badge_counts_both():
		_assert(I.invoice_counts([so]) == {so: 2}, I.invoice_counts([so]))

	check("#51 the Post Dispatch count says 2, so the cell shows +1 more", _list_badge_counts_both)

	def _each_part_has_its_pdf():
		frappe.db.set_value("Sales Order", so, "custom_invoice_pdf", "/private/files/12306.pdf", update_modified=False)
		_insert("File", name=f"FU{tag}", file_name="12307.pdf", file_url=f"/private/files/12307{tag}.pdf",
			attached_to_doctype="Sales Order", attached_to_name=so, is_private=1)
		pdf = {i["invoice_no"]: i["invoice_pdf"] for i in I.get_sales_order_invoices(so)["invoices"]}
		_assert(pdf == {"12306": "/private/files/12306.pdf", "12307": f"/private/files/12307{tag}.pdf"}, pdf)

	check("#51 each invoice downloads its own PDF (part 2's is the one the sync attached)", _each_part_has_its_pdf)

	def _whole_order_value_not_put_on_one_part():
		amounts = [i["invoice_amount"] for i in I.get_sales_order_invoices(so)["invoices"]]
		_assert(amounts == [0, 0], amounts)
		single = _order("S", partial=0, custom_invoice_no="12400")
		_part(single, "S1", "2026-11-20 11:00:00", custom_invoice_no="12400")
		one = I.get_sales_order_invoices(single)
		_assert(one["count"] == 1 and one["invoices"][0]["invoice_amount"] == 50000, one)

	check("#51 the order's Total Invoice Value shows only when it has one invoice", _whole_order_value_not_put_on_one_part)

	def _same_number_once():
		legacy = _order("L", custom_invoice_no="9080")
		_part(legacy, "L1", "2026-09-22 09:09:00")
		pl2 = _part(legacy, "L2", "2026-09-26 10:26:00", custom_invoice_no="9080")
		out = I.get_sales_order_invoices(legacy)
		_assert([(i["invoice_no"], i["pick_list"]) for i in out["invoices"]] == [("9080", pl2)], out["invoices"])
		_assert(I.invoice_counts([legacy]) == {legacy: 1}, I.invoice_counts([legacy]))

	check("#51 a number on both the order and a Pick List is listed once", _same_number_once)

	def _from_a_delivery_note():
		dn_so = _order("D", custom_invoice_no="12500")
		_part(dn_so, "D1", "2026-11-21 09:00:00", custom_invoice_no="12500")
		p2 = _part(dn_so, "D2", "2026-11-21 10:00:00")
		dn = _insert("Delivery Note", name=f"DNU-{tag}", docstatus=1, company=company, customer="Cust",
			custom_sales_order_id=dn_so, custom_invoice_no="12501")
		_insert("Delivery Note Item", name=f"DNIU-{tag}", parent=dn, parenttype="Delivery Note",
			parentfield="items", item_code="X", against_pick_list=p2)
		got = [(i["invoice_no"], i["part_label"]) for i in I.get_sales_order_invoices(dn_so)["invoices"]]
		_assert(got == [("12500", "Part 1"), ("12501", "Part 2")], got)

	check("#51 a part's invoice on its Delivery Note is listed, as the Accounts Format Report reads it", _from_a_delivery_note)
