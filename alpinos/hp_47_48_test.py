"""Changes(HP) #47 Delivery Note list filters, #48 Post Dispatch filters and PO column.

Run:  bench --site alpinos.test execute alpinos.hp_47_48_test.run

Fixtures are written straight to the tables and everything is ROLLED BACK at the end. The
suite drives the page's own server entry points, so a filter that only narrows the screen
would not pass.
"""

import random

import frappe
from frappe.utils import add_days, today

from alpinos import post_delivery_api as PDQ
from alpinos.alpinos_development.page.delivery_note_entry import delivery_note_entry as DNE

RESULTS = []


def check(label, fn):
	try:
		fn()
		RESULTS.append(("PASS", label, ""))
	except AssertionError as e:
		RESULTS.append(("FAIL", label, str(e)))
	except Exception as e:
		RESULTS.append(("ERROR", label, f"{type(e).__name__}: {e}"))


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


def _insert(doctype, **values):
	doc = frappe.get_doc(dict(doctype=doctype, **values))
	doc.db_insert()
	return doc


class Fixture:
	"""Three orders and their notes, each differing in exactly one filterable field."""

	def __init__(self):
		self.tag = f"HP47{random.randint(1000, 9999)}"
		t = self.tag
		self.day = today()
		self.company = frappe.defaults.get_global_default("company")

		self.cust_a = f"{t}-CUST-A"
		self.cust_b = f"{t}-CUST-B"

		# order, customer, invoice number, channel
		self.so_a = self._so("A", self.cust_a, f"{t}-INV-A", "Offline")
		self.so_b = self._so("B", self.cust_b, f"{t}-INV-B", "Offline")
		self.so_e = self._so("E", self.cust_a, f"{t}-INV-E", "E-com")

		# note, order, LR, dispatch datetime, docstatus
		self.dn_a = self._dn("A", self.so_a, self.cust_a, f"LR-{t}-111", f"{self.day} 09:30:00", 1)
		self.dn_b = self._dn("B", self.so_b, self.cust_b, f"LR-{t}-222", f"{add_days(self.day, -3)} 23:30:00", 0)
		self.dn_e = self._dn("E", self.so_e, self.cust_a, f"LR-{t}-333", f"{self.day} 10:00:00", 2)
		self.all = [self.dn_a, self.dn_b, self.dn_e]

		# Changes(HP) #48. The queue takes notes with docstatus < 2, so the cancelled E-com
		# note cannot stand in for the channel check: C is its submitted counterpart.
		self.dn_c = self._dn("C", self.so_e, self.cust_a, f"LR-{t}-444", f"{self.day} 11:00:00", 1)
		self.queued = [self.dn_a, self.dn_b, self.dn_c]
		_insert(
			"Post Dispatch", name=f"{t}-PD-A", delivery_note=self.dn_a, sales_order=self.so_a,
			customer=self.cust_a, post_delivery_status="In Progress",
		)

	def _so(self, n, customer, invoice_no, channel):
		name = f"{self.tag}-SO-{n}"
		_insert(
			"Sales Order",
			name=name,
			docstatus=1,
			customer=customer,
			customer_name=customer,
			transaction_date=self.day,
			custom_invoice_no=invoice_no,
			custom_channel=channel,
			company=self.company,
			# Changes(HP) #48: the Post Dispatch queue only carries appointment orders.
			custom_appointment_required=1,
			# A carries BOTH PO fields, so the column and filter show which one wins.
			custom_po_number=f"{self.tag}-POECOM-{n}" if n == "A" else "",
			po_no=f"{self.tag}-POSTD-{n}",
		)
		return name

	def _dn(self, n, so, customer, lr, dispatch, docstatus):
		name = f"{self.tag}-DN-{n}"
		_insert(
			"Delivery Note",
			name=name,
			docstatus=docstatus,
			is_return=0,
			customer=customer,
			customer_name=customer,
			custom_dn_so_customer_name=customer,
			custom_sales_order_id=so,
			custom_lr_gr_no=lr,
			custom_dispatch_date=dispatch,
			# The note's OWN copy of the invoice number is deliberately wrong: the list
			# shows the order's live value, so the filter must read that too.
			custom_invoice_no="STALE-COPY",
			posting_date=self.day,
			company=self.company,
			status="To Bill",
		)
		return name


def _names(out):
	return {r["name"] for r in out["data"]}


def _mine(out, fx):
	"""Only this run's notes: the site has real ones too."""
	return {n for n in _names(out) if n.startswith(fx.tag)}


def run():
	RESULTS.clear()
	frappe.set_user("Administrator")
	real_commit = frappe.db.commit
	frappe.db.commit = lambda *a, **k: None
	try:
		_run()
	finally:
		frappe.db.commit = real_commit
		frappe.db.rollback()
		frappe.set_user("Administrator")

	width = max(len(r[1]) for r in RESULTS)
	for status, label, detail in RESULTS:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in RESULTS if r[0] == 'PASS')}/{len(RESULTS)} passed")
	return RESULTS


def _run():
	fx = Fixture()
	call = lambda **kw: DNE.get_delivery_note_list(page_length=500, **kw)

	def _sales_order_filter():
		got = _mine(call(sales_order=fx.so_a), fx)
		_assert(got == {fx.dn_a}, f"Sales Order filter got {sorted(got)}")

	check("#47 Sales Order filter", _sales_order_filter)

	def _invoice_filter_reads_the_order():
		got = _mine(call(invoice_no=f"{fx.tag}-INV-B"), fx)
		_assert(got == {fx.dn_b}, f"Invoice No filter got {sorted(got)}")
		# The note's own copy says STALE-COPY; searching that must NOT find it.
		stale = _mine(call(invoice_no="STALE-COPY"), fx)
		_assert(not stale, f"the filter read the note's stale copy: {sorted(stale)}")

	check("#47 Invoice No. filter reads the order's live number, not the note's copy",
		_invoice_filter_reads_the_order)

	def _lr_filter():
		got = _mine(call(lr_no="222"), fx)
		_assert(got == {fx.dn_b}, f"LR No filter got {sorted(got)}")

	check("#47 LR No. filter matches part of the number", _lr_filter)

	def _dispatch_range():
		today_only = _mine(call(dispatch_from=fx.day, dispatch_to=fx.day), fx)
		_assert(today_only == {fx.dn_a, fx.dn_c, fx.dn_e}, f"today got {sorted(today_only)}")
		# dn_b is dispatched at 23:30, which a plain <= date would drop.
		late = _mine(call(dispatch_from=add_days(fx.day, -3), dispatch_to=add_days(fx.day, -3)), fx)
		_assert(late == {fx.dn_b}, f"a 23:30 dispatch fell outside its own day: {sorted(late)}")
		span = _mine(call(dispatch_from=add_days(fx.day, -3), dispatch_to=fx.day), fx)
		_assert(span == set(fx.all) | {fx.dn_c}, f"the range missed notes: {sorted(span)}")

	check("#47 Dispatch Date From / To cover whole days, ends included", _dispatch_range)

	def _customer_filter():
		got = _mine(call(customer=fx.cust_b), fx)
		_assert(got == {fx.dn_b}, f"Customer filter got {sorted(got)}")

	check("#47 Customer filter", _customer_filter)

	def _workflow_status():
		_assert(_mine(call(status="Draft"), fx) == {fx.dn_b}, "Draft")
		_assert(_mine(call(status="Dispatched"), fx) == {fx.dn_a, fx.dn_c}, "Dispatched")
		_assert(_mine(call(status="Cancelled"), fx) == {fx.dn_e}, "Cancelled")

	check("#47 Workflow Status matches the column: Draft / Dispatched / Cancelled", _workflow_status)

	def _filters_combine():
		got = _mine(call(sales_order=fx.so_a, status="Dispatched"), fx)
		_assert(got == {fx.dn_a}, f"combined got {sorted(got)}")
		none = _mine(call(sales_order=fx.so_a, status="Draft"), fx)
		_assert(not none, f"a contradictory pair still returned {sorted(none)}")

	check("#47 filters narrow together, not one at a time", _filters_combine)

	# ------------------------------------------------------- Changes(HP) #48
	queue = lambda **kw: PDQ.get_post_delivery_queue(page_length=500, **kw)
	rows = lambda out: {r["delivery_note"] for r in out["data"] if r["delivery_note"].startswith(fx.tag)}
	row_of = lambda out, dn: next(r for r in out["data"] if r["delivery_note"] == dn)

	def _the_queue_holds_the_expected_notes():
		got = rows(queue())
		_assert(got == {fx.dn_a, fx.dn_b, fx.dn_c},
			f"the queue holds {sorted(got)}; the cancelled note must not be in it")

	check("#48 the queue still carries appointment orders and skips a cancelled note",
		_the_queue_holds_the_expected_notes)

	def _status_filter_no_longer_raises():
		# It used to append the placeholder without binding the value: KeyError: status.
		got = rows(queue(status="In Progress"))
		_assert(got == {fx.dn_a}, f"Status filter got {sorted(got)}")
		_assert(rows(queue(status="Not Started")) == {fx.dn_b, fx.dn_c},
			"Not Started should cover the notes with no Post Dispatch row")

	check("#48 the Status filter works at all, and matches the right rows",
		_status_filter_no_longer_raises)

	def _sales_order_filter():
		_assert(rows(queue(sales_order=fx.so_b)) == {fx.dn_b}, "Sales Order filter")

	check("#48 Sales Order filter", _sales_order_filter)

	def _customer_po_filter_and_column():
		# A carries both fields; the e-com one wins in the column and in the filter.
		_assert(rows(queue(customer_po=f"{fx.tag}-POECOM-A")) == {fx.dn_a}, "e-com PO filter")
		_assert(row_of(queue(), fx.dn_a)["customer_po_no"] == f"{fx.tag}-POECOM-A",
			f"column shows {row_of(queue(), fx.dn_a)['customer_po_no']}")
		# B carries only the standard field, which the column falls back to.
		_assert(rows(queue(customer_po=f"{fx.tag}-POSTD-B")) == {fx.dn_b}, "standard PO filter")
		_assert(row_of(queue(), fx.dn_b)["customer_po_no"] == f"{fx.tag}-POSTD-B",
			f"column shows {row_of(queue(), fx.dn_b)['customer_po_no']}")

	check("#48 Customer's Purchase No. filters and shows, e-com field before the standard one",
		_customer_po_filter_and_column)

	def _invoice_filter():
		_assert(rows(queue(invoice_no=f"{fx.tag}-INV-B")) == {fx.dn_b}, "Invoice No filter")

	check("#48 Invoice No. filter", _invoice_filter)

	def _channel_filter():
		_assert(rows(queue(channel="E-com")) == {fx.dn_c}, "Channel filter")
		_assert(rows(queue(channel="Offline")) == {fx.dn_a, fx.dn_b}, "Channel filter, offline")

	check("#48 Channel filter", _channel_filter)

	def _dispatch_range():
		_assert(rows(queue(dispatch_from=fx.day, dispatch_to=fx.day)) == {fx.dn_a, fx.dn_c},
			"today's dispatches")
		late = rows(queue(dispatch_from=add_days(fx.day, -3), dispatch_to=add_days(fx.day, -3)))
		_assert(late == {fx.dn_b}, f"a 23:30 dispatch fell outside its own day: {sorted(late)}")

	check("#48 Dispatch Date From / To cover whole days, ends included", _dispatch_range)

	def _filters_combine():
		_assert(rows(queue(channel="Offline", status="In Progress")) == {fx.dn_a}, "combined")
		_assert(not rows(queue(channel="E-com", status="In Progress")),
			"a contradictory pair still returned rows")

	check("#48 filters narrow together", _filters_combine)
