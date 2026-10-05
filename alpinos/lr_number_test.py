"""Changes(HP) #52: the LR No. takes a typed number and a scanned one alike.

Run:  bench --site alpinos.test execute alpinos.lr_number_test.run

A scanner types the number and then sends a terminator, and some models wrap the payload in
control characters. What matters is that the value stored is the number, whichever of the
three routes it arrived by -- the entry page, the bulk update, or the LR Excel. Fixtures
roll back.
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
	from alpinos.lr_number import clean_existing_lr_numbers, normalise_delivery_note_lr, normalise_lr

	def _a_typed_number_is_left_alone():
		_assert(normalise_lr("LR-99812") == "LR-99812", normalise_lr("LR-99812"))
		_assert(normalise_lr("MH12 AB 3344") == "MH12 AB 3344",
			f"an inner space was removed: {normalise_lr('MH12 AB 3344')!r}")

	check("#52 a typed number is stored exactly as typed", _a_typed_number_is_left_alone)

	def _a_scanner_terminator_is_stripped():
		for raw in ("LR-99812\r\n", "LR-99812\n", "LR-99812\t", "\x02LR-99812\x03"):
			_assert(normalise_lr(raw) == "LR-99812",
				f"{raw!r} came out as {normalise_lr(raw)!r}")

	check("#52 the terminator and control characters a scanner adds are stripped",
		_a_scanner_terminator_is_stripped)

	def _invisible_characters_from_a_spreadsheet_go_too():
		_assert(normalise_lr("﻿LR-99812​") == "LR-99812",
			f"zero-width characters survived: {normalise_lr(chr(0xfeff) + 'LR-99812')!r}")

	check("#52 zero-width characters from a copy-paste are stripped too",
		_invisible_characters_from_a_spreadsheet_go_too)

	def _an_empty_scan_becomes_nothing_not_a_blank_string():
		_assert(normalise_lr("   ") is None, f"{normalise_lr('   ')!r}")
		_assert(normalise_lr("\r\n") is None, f"{normalise_lr(chr(13) + chr(10))!r}")
		_assert(normalise_lr(None) is None)

	check("#52 an empty scan stores nothing rather than a blank string",
		_an_empty_scan_becomes_nothing_not_a_blank_string)

	def _the_hook_cleans_whatever_route_the_value_came_by():
		doc = frappe._dict(custom_lr_gr_no="LR-55501\r\n")
		normalise_delivery_note_lr(doc)
		_assert(doc.custom_lr_gr_no == "LR-55501",
			f"the validate hook did not clean it: {doc.custom_lr_gr_no!r}")

	check("#52 the Delivery Note hook cleans it on every save path",
		_the_hook_cleans_whatever_route_the_value_came_by)

	def _the_repair_tool_reports_before_it_writes():
		company = frappe.db.get_value("Warehouse", {"is_group": 0}, "company")
		dn = _insert("Delivery Note", name=f"DNLRX-{frappe.generate_hash(length=4).upper()}",
			docstatus=1, company=company, customer="Cust", posting_date=today(),
			custom_lr_gr_no="LR-DIRTY-1\r\n", is_return=0)
		dry = clean_existing_lr_numbers(apply=0)
		_assert(dry["mode"] == "DRY-RUN", dry["mode"])
		_assert(any(d["delivery_note"] == dn for d in dry["sample"]),
			f"the dirty note is not in the report: {dry['sample'][:3]}")
		_assert(frappe.db.get_value("Delivery Note", dn, "custom_lr_gr_no") == "LR-DIRTY-1\r\n",
			"the dry run wrote to the record")

		clean_existing_lr_numbers(apply=1)
		_assert(frappe.db.get_value("Delivery Note", dn, "custom_lr_gr_no") == "LR-DIRTY-1",
			"the repair did not clean the stored value")

	check("#52 the repair tool reports first, then cleans what is already stored",
		_the_repair_tool_reports_before_it_writes)
