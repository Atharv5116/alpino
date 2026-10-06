"""Changes(HP) #61: LR No. on the Post Dispatch list.

Run:  bench --site alpinos.test execute alpinos.post_dispatch_lr_test.run

The number was already fetched for every row and simply never shown or searchable, which
is awkward because the LR number is the one thing a transporter query starts from.
Fixtures are rolled back.
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
	from alpinos import post_delivery_api as P

	tag = "LR" + frappe.generate_hash(length=4).upper()
	company = frappe.defaults.get_global_default("company")
	day = today()

	def _row(suffix, lr):
		so = _insert("Sales Order", name=f"SOLR-{tag}-{suffix}", docstatus=1, company=company,
			customer="__Test Customer", customer_name="__Test Customer",
			transaction_date=day, custom_appointment_required=1)
		dn = _insert("Delivery Note", name=f"DNLR-{tag}-{suffix}", docstatus=1, company=company,
			customer="__Test Customer", customer_name=f"{tag} Buyer", posting_date=day,
			custom_sales_order_id=so, custom_lr_gr_no=lr, is_return=0)
		return dn

	dn_a = _row("A", f"LRN-{tag}-11111")
	dn_b = _row("B", f"LRN-{tag}-22222")

	def _names(**kw):
		out = P.get_post_delivery_queue(page_length=100, **kw)
		return {r["delivery_note"] for r in out["data"]}

	def _the_row_carries_its_lr_number():
		out = P.get_post_delivery_queue(page_length=100, search=tag)
		rows = {r["delivery_note"]: r for r in out["data"]}
		_assert(dn_a in rows, f"the fixture row is missing: {list(rows)[:5]}")
		_assert(rows[dn_a]["lr_awb_no"] == f"LRN-{tag}-11111",
			f"the row does not carry its LR number: {rows[dn_a].get('lr_awb_no')}")

	check("#61 every row carries its LR number", _the_row_carries_its_lr_number)

	def _the_filter_narrows_to_one():
		seen = _names(lr_no=f"{tag}-11111")
		_assert(dn_a in seen, "the LR filter did not find its own row")
		_assert(dn_b not in seen, f"the LR filter returned another row too: {seen}")

	check("#61 the LR No. filter narrows to the matching note", _the_filter_narrows_to_one)

	def _the_filter_is_a_partial_match():
		seen = _names(lr_no=tag)
		_assert({dn_a, dn_b} <= seen,
			f"a partial LR search should match both fixtures: {seen}")

	check("#61 the LR No. filter matches on part of the number",
		_the_filter_is_a_partial_match)

	def _an_unknown_lr_returns_nothing():
		_assert(not _names(lr_no=f"NOSUCH-{tag}"),
			"an unknown LR number returned rows")

	check("#61 an unknown LR number returns nothing", _an_unknown_lr_returns_nothing)

	def _free_text_search_also_reaches_the_lr_number():
		seen = _names(search=f"{tag}-22222")
		_assert(dn_b in seen,
			"the free-text search does not reach the LR number")
		_assert(dn_a not in seen, f"the free-text search was too broad: {seen}")

	check("#61 the free-text search reaches the LR number too",
		_free_text_search_also_reaches_the_lr_number)
