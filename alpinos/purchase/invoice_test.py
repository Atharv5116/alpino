"""BRD 6 "Purchase Invoice & Payment" — the validations and the derived state.

    bench --site alpinos.test execute alpinos.purchase.invoice_test.run

Written so that reverting a rule makes a test fail, not merely so they pass today. The
payment rules in particular are asserted at their boundary: VAL-UNF-06 is checked with a
payment one paisa over the bill, not with an obviously absurd number, because an
off-by-epsilon guard is exactly what a rounding tolerance can hide.

The chain fixture is reused from the regression suite rather than rebuilt, so an invoice
is always raised from a GRN that reached final submission the way a real one does.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, flt, today

from alpinos.purchase import constants as C
from alpinos.purchase import e2e_test as H
from alpinos.purchase import purchase_invoice as INV
from alpinos.purchase.purchase_invoice_fields import STATUS_FIELD, TYPE_FIELD
from alpinos.purchase.regression_test import _chain

_assert = H._assert

R = []


def check(label, fn):
	try:
		fn()
		R.append(("PASS", label, ""))
	except AssertionError as e:
		R.append(("FAIL", label, str(e)))
	except Exception as e:
		R.append(("ERROR", label, f"{type(e).__name__}: {frappe.utils.strip_html(str(e))[:200]}"))


def expect_throw(label, fn, fragment=None):
	try:
		fn()
		R.append(("FAIL", label, "expected an exception, none raised"))
	except Exception as e:
		msg = frappe.utils.strip_html(str(e))
		if fragment and fragment.lower() not in msg.lower():
			R.append(("FAIL", label, f"threw, but message lacked '{fragment}': {msg[:200]}"))
		else:
			R.append(("PASS", label, ""))


def _final_grn(supplier, qty=20):
	"""A GRN taken all the way to Admin final submission (BR-GRN-06)."""
	item = H.ensure_item(f"PITEST-INV-{H.SEQ}-{frappe.generate_hash(length=4)}")
	chain = _chain(supplier, item, qty, qty)
	grn = frappe.get_doc("Purchase Receipt", chain["pr"])
	grn.flags.ignore_permissions = True
	grn.submit()
	frappe.db.commit()
	return chain, grn


def _ready_to_submit(invoice, freight=0.0, vendor=None):
	"""Fill what VAL-UNF-01/02/03 demand, so a test can get past them deliberately."""
	invoice.bill_no = f"SUPP-INV-{frappe.generate_hash(length=6)}"
	invoice.bill_date = today()
	invoice.custom_invoice_attachment = "/files/supplier-invoice.pdf"
	if freight:
		invoice.custom_include_logistics = 1
		invoice.custom_logistics_vendor = vendor
		invoice.custom_transport_invoice_no = "LR-0001"
		invoice.custom_freight_amount = freight
	invoice.flags.ignore_permissions = True
	return invoice


def run():
	R.clear()
	H.SEQ = H._seq()
	H.COMPANY = H._company()
	frappe.set_user("Administrator")

	supplier = H.ensure_supplier()

	# ------------------------------------------------ BR-UNF-01: GRN must be final
	def t_draft_grn_refused():
		item = H.ensure_item(f"PITEST-INVD-{H.SEQ}")
		chain = _chain(supplier, item, 10, 10)
		INV.create_from_grn(chain["pr"])  # still docstatus 0

	expect_throw(
		"BR-UNF-01 an invoice cannot be raised from a GRN that is not finally submitted",
		t_draft_grn_refused,
		"finally submitted",
	)

	# ------------------------------------------------------- the normal path
	chain, grn = _final_grn(supplier)
	invoice = INV.create_from_grn(grn.name)

	check(
		"BRD 6.0 normal path links the invoice to its GRN and Purchase Inward",
		lambda: _assert(
			invoice.custom_grn == grn.name
			and invoice.custom_purchase_inward == chain["inward"].name
			and invoice.get(TYPE_FIELD) == C.UNF_TYPE_NORMAL,
			f"grn={invoice.custom_grn} inward={invoice.custom_purchase_inward} "
			f"type={invoice.get(TYPE_FIELD)}",
		),
	)
	check(
		"BRD 6.2 a new invoice starts in Draft",
		lambda: _assert(invoice.get(STATUS_FIELD) == C.UNF_DRAFT, invoice.get(STATUS_FIELD)),
	)

	expect_throw(
		"BR-UNF-02 a second invoice against the same GRN is refused",
		lambda: INV.create_from_grn(grn.name),
		"already exists",
	)

	# ------------------------------------------------------ VAL-UNF-01 / 02 / 03
	def _fresh_draft(freight=0.0):
		_c, g = _final_grn(supplier)
		return INV.create_from_grn(g.name)

	inv1 = _fresh_draft()
	inv1.bill_no = ""
	inv1.custom_invoice_attachment = "/files/x.pdf"
	inv1.flags.ignore_permissions = True
	expect_throw(
		"VAL-UNF-01 submitting without a Supplier Invoice Number is blocked",
		inv1.submit,
		"Supplier Invoice Number",
	)

	inv2 = _fresh_draft()
	inv2.bill_no = "SUPP-NO-ATTACH"
	inv2.bill_date = today()
	inv2.custom_invoice_attachment = ""
	inv2.flags.ignore_permissions = True
	expect_throw(
		"VAL-UNF-02 submitting without the supplier invoice copy is blocked",
		inv2.submit,
		"supplier invoice copy",
	)

	inv3 = _ready_to_submit(_fresh_draft())
	inv3.custom_include_logistics = 1
	inv3.custom_logistics_vendor = None
	inv3.custom_freight_amount = 0
	expect_throw(
		"VAL-UNF-03 Include Logistics without vendor or freight is blocked",
		inv3.submit,
		"Logistics details",
	)

	# --------------------------------------------- submit -> Pending Payment
	inv = _ready_to_submit(_fresh_draft())
	inv.submit()
	inv.reload()
	billed = flt(inv.rounded_total or inv.grand_total)
	check(
		"BRD 6.2.1 submitting hands the invoice to Accounts as Pending Payment",
		lambda: _assert(
			inv.get(STATUS_FIELD) == C.UNF_PENDING_PAYMENT
			and flt(inv.custom_supplier_pending_amount) == billed
			and flt(inv.custom_logistics_pending_amount) == 0.0,
			f"{inv.get(STATUS_FIELD)} supplier_pending={inv.custom_supplier_pending_amount} "
			f"logistics_pending={inv.custom_logistics_pending_amount}",
		),
	)

	# ------------------------------------------------------------ BR-UNF-03
	def t_locked_after_submit():
		"""Deliberately the Payment Due Date, not Invoice Remarks.

		Remarks is not allow_on_submit, so Frappe refuses it on its own and the test
		would pass with BR-UNF-03 deleted. Payment Due Date IS allow_on_submit -- it has
		to be, so the field can exist on a submitted invoice at all -- which makes it the
		only Purchase-owned field this guard is actually what stops.
		"""
		fresh = frappe.get_doc("Purchase Invoice", inv.name)
		fresh.custom_payment_due_date = add_days(today(), 45)
		fresh.flags.ignore_permissions = True
		fresh.save()

	expect_throw(
		"BR-UNF-03 the Purchase Team sections are locked once the invoice is submitted",
		t_locked_after_submit,
		"cannot be changed after the invoice has been submitted",
	)

	# ------------------------------------------------ VAL-UNF-04 / 05 / 06 / 07
	#
	# On their own invoice, not the one the progression below walks. Each of these is
	# expected to be REFUSED, so if a rule is ever removed the payment lands instead --
	# and a stray payment would move the balance the later assertions depend on, turning
	# one real failure into a cascade of unrelated ones. Isolating them means a broken
	# rule fails exactly one test.
	probe = _ready_to_submit(_fresh_draft())
	probe.submit()
	probe.reload()
	probe_billed = flt(probe.rounded_total or probe.grand_total)

	expect_throw(
		"VAL-UNF-04 a zero payment is blocked",
		lambda: INV.add_payment(probe.name, C.UNF_PAYMENT_SUPPLIER, 0, today(), "Cash"),
		"greater than zero",
	)
	expect_throw(
		"VAL-UNF-05 a bank payment without a reference is blocked",
		lambda: INV.add_payment(probe.name, C.UNF_PAYMENT_SUPPLIER, 100, today(), "NEFT"),
		"Reference/UTR is mandatory",
	)
	expect_throw(
		"VAL-UNF-06 a supplier payment over the bill is blocked, at the boundary",
		lambda: INV.add_payment(
			probe.name, C.UNF_PAYMENT_SUPPLIER, probe_billed + 0.01, today(), "Cash"
		),
		"cannot exceed the pending supplier bill",
	)
	expect_throw(
		"VAL-UNF-07 a logistics payment with no freight bill is blocked",
		lambda: INV.add_payment(probe.name, C.UNF_PAYMENT_LOGISTICS, 10, today(), "Cash"),
		"no logistics bill",
	)

	# ------------------------------------------- partial -> Partially Paid
	half = round(billed / 2.0, 2)
	INV.add_payment(inv.name, C.UNF_PAYMENT_SUPPLIER, half, today(), "Cash")
	inv.reload()
	check(
		"BRD 6.2 a part payment moves the invoice to Partially Paid",
		lambda: _assert(
			inv.get(STATUS_FIELD) == C.UNF_PARTIALLY_PAID
			and abs(flt(inv.custom_supplier_pending_amount) - (billed - half)) < 0.01,
			f"{inv.get(STATUS_FIELD)} pending={inv.custom_supplier_pending_amount}",
		),
	)
	check(
		"a Cash payment needs no reference number",
		lambda: _assert(flt(inv.custom_total_paid_amount) == half, str(inv.custom_total_paid_amount)),
	)

	INV.add_payment(
		inv.name, C.UNF_PAYMENT_SUPPLIER, billed - half, today(), "NEFT", reference_number="UTR-1"
	)
	inv.reload()
	check(
		"BR-UNF-06 the balance settles the invoice to Completed",
		lambda: _assert(
			inv.get(STATUS_FIELD) == C.UNF_COMPLETED
			and flt(inv.custom_supplier_pending_amount) == 0.0,
			f"{inv.get(STATUS_FIELD)} pending={inv.custom_supplier_pending_amount}",
		),
	)

	# ------- BR-UNF-06 the other half: logistics outstanding blocks Completed
	freight = 500.0
	inv_l = _ready_to_submit(_fresh_draft(), freight=freight, vendor=supplier)
	inv_l.submit()
	inv_l.reload()
	billed_l = flt(inv_l.rounded_total or inv_l.grand_total)
	INV.add_payment(inv_l.name, C.UNF_PAYMENT_SUPPLIER, billed_l, today(), "Cash")
	inv_l.reload()
	check(
		"BR-UNF-06 supplier paid in full but freight outstanding is NOT Completed",
		lambda: _assert(
			inv_l.get(STATUS_FIELD) == C.UNF_PARTIALLY_PAID
			and flt(inv_l.custom_supplier_pending_amount) == 0.0
			and flt(inv_l.custom_logistics_pending_amount) == freight,
			f"{inv_l.get(STATUS_FIELD)} supplier={inv_l.custom_supplier_pending_amount} "
			f"logistics={inv_l.custom_logistics_pending_amount}",
		),
	)
	expect_throw(
		"VAL-UNF-07 a freight payment over the transport bill is blocked, at the boundary",
		lambda: INV.add_payment(
			inv_l.name, C.UNF_PAYMENT_LOGISTICS, freight + 0.01, today(), "Cash"
		),
		"cannot exceed the pending freight bill",
	)
	INV.add_payment(inv_l.name, C.UNF_PAYMENT_LOGISTICS, freight, today(), "Cash")
	inv_l.reload()
	check(
		"BR-UNF-06 Completed only once BOTH pending amounts reach zero",
		lambda: _assert(
			inv_l.get(STATUS_FIELD) == C.UNF_COMPLETED,
			f"{inv_l.get(STATUS_FIELD)} logistics={inv_l.custom_logistics_pending_amount}",
		),
	)

	# ------------------------------------------------- BRD 6.0 the direct path
	direct_item = H.ensure_item(f"PITEST-INVX-{H.SEQ}")
	direct_po = H.make_po(supplier, [(direct_item, 5, 100)], direct_invoice=1)
	direct = INV.create_direct_from_po(direct_po.name)
	check(
		"BRD 6.0 a Direct Purchase Invoice carries no GRN and no Purchase Inward",
		lambda: _assert(
			direct.get(TYPE_FIELD) == C.UNF_TYPE_DIRECT
			and not direct.custom_grn
			and not direct.custom_purchase_inward,
			f"type={direct.get(TYPE_FIELD)} grn={direct.custom_grn} "
			f"inward={direct.custom_purchase_inward}",
		),
	)

	normal_po = H.make_po(supplier, [(direct_item, 5, 100)])
	expect_throw(
		"BRD 6.0 the direct path is refused on a Purchase Order not marked Direct",
		lambda: INV.create_direct_from_po(normal_po.name),
		"not marked Direct Purchase Invoice",
	)

	frappe.db.commit()

	width = max(len(r[1]) for r in R)
	print("\nPurchase Invoice & Payment (BRD 6)")
	print("=" * (width + 24))
	for state, label, detail in R:
		print(f"[{state}] {label.ljust(width)}  {detail}")
	passed = sum(1 for r in R if r[0] == "PASS")
	print("-" * (width + 24))
	print(f"{passed}/{len(R)} passed")
	return R
