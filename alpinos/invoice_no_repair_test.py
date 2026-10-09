"""The truncated-invoice repair restores the digit, and refuses where it cannot be sure.

Run:  bench --site alpinos.test execute alpinos.invoice_no_repair_test.run

The repair INFERS the missing digit, so the checks that matter are the ones about what it
declines to touch: a number that is not the truncation shape, and a repair that would land
on an invoice number another order already holds. Getting those wrong would hand a live
invoice's identity to the wrong order, silently, which is the same class of harm as the
bug being repaired.

Fixtures roll back, and the dry run is checked to write nothing.
"""

import frappe

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


def _so(name, invoice, company, pdf=""):
	doc = frappe.get_doc({
		"doctype": "Sales Order", "name": name, "docstatus": 1, "company": company,
		"customer": "Cust", "custom_invoice_no": invoice, "custom_invoice_pdf": pdf,
	})
	doc.flags.ignore_mandatory = True
	doc.flags.ignore_validate = True
	doc.db_insert()
	return name


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
	from alpinos import invoice_no_repair as R

	company = frappe.defaults.get_global_default("company") or frappe.db.get_value("Company", {}, "name")
	tag = "INVR" + frappe.generate_hash(length=4).upper()

	def _invoice_of(so):
		return frappe.db.get_value("Sales Order", so, "custom_invoice_no")

	# Three damaged orders, plus one that is fine and must be left alone.
	dmg = [_so(f"SO-{tag}-{i}", f"000{i}", company) for i in range(3)]
	healthy = _so(f"SO-{tag}-OK", "9863", company)

	def _the_dry_run_writes_nothing():
		R.run()
		for so, i in zip(dmg, range(3)):
			_assert(_invoice_of(so) == f"000{i}",
				f"the dry run changed {so} to {_invoice_of(so)!r}")

	check("the dry run reports but writes nothing", _the_dry_run_writes_nothing)

	def _apply_restores_the_dropped_digit():
		R.run(apply=1)
		for so, i in zip(dmg, range(3)):
			_assert(_invoice_of(so) == f"1000{i}",
				f"{so} reads {_invoice_of(so)!r}, expected '1000{i}'")

	check("apply restores the dropped digit", _apply_restores_the_dropped_digit)

	def _a_healthy_number_is_untouched():
		_assert(_invoice_of(healthy) == "9863",
			f"a four-digit invoice with no leading zero was rewritten to {_invoice_of(healthy)!r}")

	check("a number that is not the truncation shape is left alone",
		_a_healthy_number_is_untouched)

	def _it_refuses_a_repair_that_would_collide():
		"""The case worth being careful about.

		If some order already holds 10077, then repairing 0077 onto it would put one
		invoice number on two orders -- exactly the harm the original bug caused. The
		repair must decline and say so, not overwrite and not guess a different number.
		"""
		occupied = _so(f"SO-{tag}-TAKEN", "10077", company)
		victim = _so(f"SO-{tag}-CLASH", "0077", company)
		R.run(apply=1)
		_assert(_invoice_of(victim) == "0077",
			f"the clashing order was repaired anyway, to {_invoice_of(victim)!r}")
		_assert(_invoice_of(occupied) == "10077",
			f"the order that already held the number was altered: {_invoice_of(occupied)!r}")

	check("a repair that would collide with an existing invoice is refused",
		_it_refuses_a_repair_that_would_collide)

	def _it_is_safe_to_run_twice():
		"""Once repaired the numbers no longer match the signature, so a second run is a
		no-op rather than turning 10000 into 110000."""
		before = {so: _invoice_of(so) for so in dmg}
		R.run(apply=1)
		for so in dmg:
			_assert(_invoice_of(so) == before[so],
				f"a second run changed {so} from {before[so]!r} to {_invoice_of(so)!r}")

	check("running it a second time changes nothing", _it_is_safe_to_run_twice)
