"""W5 Quotation & Payment ("Opportunity to Sales Order v1.0.0", Section 5). TEST sites only.

Run:  ../env/bin/python ~/alpinos-wt/mrp_work/run.py <site> alpinos.offline_sales.quotation_payment_test.run

Everything is rolled back: commits are disabled for the run, background jobs are only recorded.
The buyers, users and items come from the Opportunity suite's fixtures (opportunity_test).
"""

import json

import frappe
from frappe.utils import add_days, flt, getdate, today

from alpinos.offline_sales import opportunity_test as OT
from alpinos.offline_sales import quotation as Q
from alpinos.offline_sales import quotation_payments as P

R = []
F = OT.F
JOBS = []

as_ = OT.as_
refused = OT.refused


def check(label, fn):
	try:
		fn()
		R.append(("PASS", label, ""))
	except AssertionError as e:
		R.append(("FAIL", label, str(e)))
	except Exception as e:
		R.append(("ERR ", label, f"{type(e).__name__}: {e}"))
	finally:
		frappe.set_user("Administrator")


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


def run():
	R.clear()
	JOBS.clear()
	frappe.set_user("Administrator")
	real_commit, real_enqueue = frappe.db.commit, frappe.enqueue
	frappe.db.commit = lambda *a, **k: None
	frappe.enqueue = lambda method, *a, **kw: JOBS.append((method, kw))
	try:
		_run()
	finally:
		frappe.db.commit = real_commit
		frappe.enqueue = real_enqueue
		frappe.db.rollback()
		frappe.clear_cache()
		frappe.set_user("Administrator")
	width = max(len(r[1]) for r in R) if R else 10
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in R if r[0] == 'PASS')}/{len(R)} passed")
	return R


# ----------------------------------------------------------------------------- helpers

_N = [0]


def proof():
	_N[0] += 1
	return f"/private/files/{OT.TAG}-proof-{_N[0]}.png"


def converted(buyer=None, rows=None, user=None):
	from alpinos.offline_sales.opportunity import convert_to_quotation

	opp = OT.submitted(user=F.so1.user, buyer=buyer or F.ready.name, rows=rows or [(F.single, 10)])
	q = as_(user or F.so1.user, lambda: convert_to_quotation(opp))["quotation"]
	return opp, q


def qdoc(name):
	return frappe.get_doc("Quotation", name)


def edit(name, user, change):
	"""Save a change to a Quotation as `user`; the error text, or "" when it went through."""

	def _go():
		d = qdoc(name)
		change(d)
		d.save()

	return refused(lambda: as_(user, _go))


def finalize(name, user=None, reason=None):
	return as_(user or F.sm1.user, lambda: Q.finalize(name, reason))


def pay(name, amount, user=None, row=None, date=None, with_proof=True, **kw):
	return as_(user or F.so1.user, lambda: P.record_payment(
		name, amount, date or today(), proof() if with_proof else None, kw.get("utr"), kw.get("remarks"), row,
	))


def trail(name, action=None):
	filters = {"reference_doctype": "Quotation", "reference_name": name}
	if action:
		filters["action"] = action
	return frappe.get_all(
		"Field Change Log", filters=filters,
		fields=["action", "field_label", "previous_value", "new_value", "reason", "user_role", "changed_by"],
		order_by="creation asc",
	)


def credit_quotation(days=30):
	_opp, q = converted(F.credit_buyer.name)
	_assert(qdoc(q).custom_payment_term == "Credit", "Credit buyer's Quotation is not Credit")
	finalize(q)
	return q


def advance_quotation():
	_opp, q = converted()
	finalize(q)
	return q


def partial_quotation(advance_share=0.3):
	"""Partial: Advance row of advance_share of the Grand Total, Credit row the rest."""
	_opp, q = converted(F.partial_buyer.name)
	gt = flt(qdoc(q).grand_total, 2)
	adv = flt(gt * advance_share, 2)
	rows = [
		{"payment_term": "Advance", "expected_payment_date": today(), "expected_amount": adv},
		{"payment_term": "Credit", "expected_payment_date": add_days(today(), 30), "expected_amount": flt(gt - adv, 2)},
	]
	err = edit(q, F.so1.user, lambda d: d.set("custom_payment_schedule", rows))
	_assert(not err, err)
	finalize(q)
	return q


def rows_of(name):
	return [
		(r.idx, r.payment_term, flt(r.expected_amount), flt(r.received_amount), flt(r.pending_amount), r.row_status)
		for r in qdoc(name).custom_payment_schedule
	]


# ----------------------------------------------------------------------------- tests


def _run():
	OT._fixtures()
	# every System Manager on the site also holds a sales manager role (Quotation read access)
	F.sysm = OT._person("sysm", "System Manager", "Sales Manager")
	F.credit_buyer = OT.new_buyer("Administrator", payment_term="Credit", payment_term_days="30 days")
	OT._catalog(F.credit_buyer)
	F.partial_buyer = OT.new_buyer("Administrator", payment_term="Partial", payment_term_days="15")
	OT._catalog(F.partial_buyer)
	_creation()
	_pricing()
	_statuses()
	_finalize()
	_lock()
	_advance()
	_credit()
	_partial()
	_force_complete()
	_exceptions()
	_eligibility_table()
	_proof_and_correction()
	_term_change()
	_cancel()
	_print_and_email()
	_reminders_and_independence()
	_migration()


def _creation():
	def _convert():
		opp, q = converted()
		d = qdoc(q)
		_assert(d.custom_quotation_status == "Draft" and d.docstatus == 0, d.custom_quotation_status)
		_assert(d.custom_payment_term == "Advance", f"term {d.custom_payment_term} (buyer Advance)")
		_assert(d.custom_responsible_sales_officer == F.so1.user, d.custom_responsible_sales_officer)
		_assert(str(d.transaction_date) == today(), d.transaction_date)
		t = trail(q, "Quotation Created")
		_assert(t and opp in t[0].new_value and t[0].user_role == "Sales Officer", str(t))
		_assert(d.custom_total_pending == d.grand_total and d.custom_payment_status == "Pending"
			and d.custom_so_eligibility == "Blocked", f"{d.custom_payment_status} {d.custom_so_eligibility}")
		F.opp1, F.q1 = opp, q

	check("S5 create: Convert gives a Draft; Payment Term from the Buyer; Responsible SO; Pending / Blocked; audited", _convert)

	def _credit_default():
		_opp, q = converted(F.credit_buyer.name)
		d = qdoc(q)
		_assert(d.custom_payment_term == "Credit" and d.custom_credit_days == 30, f"{d.custom_payment_term} {d.custom_credit_days}")
		_assert(not d.custom_expected_payment_date, "Expected Payment Date set before Finalize")

	check("S5 9.1 Credit Days from Buyer Master 'Payment Term Days' (free text '30 days' -> 30); date only at Finalize", _credit_default)

	def _one_active():
		d = frappe.copy_doc(qdoc(F.q1))
		err = refused(lambda: as_(F.sm1.user, lambda: d.insert()))
		_assert(f"An active Quotation [{F.q1}] already exists for this Opportunity." in err, err)

	check("S5 one active Quotation per Opportunity: a second one is refused with the doc's message", _one_active)

	def _customer_locked():
		err = edit(F.q1, F.sm1.user, lambda d: d.set("party_name", F.other.name))
		_assert("its Customer cannot be changed" in err, err)

	check("A-28 the Customer of a Quotation converted from an Opportunity cannot change", _customer_locked)

	def _stamps():
		err = edit(F.q1, F.sm1.user, lambda d: d.set("custom_quotation_status", "Finalized"))
		_assert("only through" in err, f"status changed by a save: {err}")
		err = edit(F.q1, F.sm1.user, lambda d: d.set("custom_finalized_by", F.sm1.user))
		_assert("only through" in err, f"stamp changed by a save: {err}")
		d = frappe.copy_doc(qdoc(F.q1))
		d.opportunity = None
		d.custom_quotation_status = "Finalized"
		d.custom_force_complete_applied = 1
		as_(F.sm1.user, lambda: d.insert())
		_assert(d.custom_quotation_status == "Draft" and not d.custom_force_complete_applied, "status / stamps kept on insert")
		_assert("Standalone" in trail(d.name, "Quotation Created")[0].new_value, "standalone source")
		_assert(d.custom_responsible_sales_officer == F.so1.user, f"RSO {d.custom_responsible_sales_officer} (buyer's only SO)")

	check("S5 status and stamps change only through actions; a Standalone copy starts Draft; RSO = buyer's only SO", _stamps)


def _pricing():
	from alpinos.sales_order_api import _calculate_sales_order_line_values

	def _engine():
		d = qdoc(F.q1)
		row = d.items[0]
		sp = flt(F.single_mrp * 0.8, 2)
		_assert(flt(row.custom_selling_price) == sp and flt(row.custom_flat_discount) == 20, f"{row.custom_selling_price}")
		gst = flt(frappe.db.get_value("Item", row.item_code, "custom_gst_percent"))
		calc = _calculate_sales_order_line_values({
			"qty": row.qty, "custom_customer_mrp": row.custom_mrp, "custom_selling_price": sp,
			"custom_flat_discount": 20, "custom_offer": 0, "custom_additional_discount": 0, "custom_gst_percent": gst,
		})
		_assert(flt(row.rate) == calc["rate"] and flt(row.amount) == calc["amount"], f"{row.rate}/{row.amount} vs {calc}")
		_assert(flt(d.total, 2) == flt(sum(flt(r.amount) for r in d.items), 2) and d.total == d.net_total, "total")
		_assert(Q._same(d.grand_total, flt(d.net_total) + flt(d.total_taxes_and_charges) - flt(d.discount_amount)), "grand total")
		_assert(d.disable_rounded_total == 1, "rounded total")

	check("S5 5.1-5.2 lines priced by the Sales Order engine (Selling Price GST included); totals and taxes as the SO", _engine)

	def _cash_discount():
		err = edit(F.q1, F.sm1.user, lambda d: d.set("custom_cash_discount", 2))
		_assert(not err, err)
		d = qdoc(F.q1)
		before = flt(d.net_total) + flt(d.total_taxes_and_charges)
		_assert(abs(flt(d.custom_cash_discount_amount) - before * 0.02) < 0.1, f"{d.custom_cash_discount_amount} vs {before * 0.02}")
		_assert(Q._same(d.grand_total, before - flt(d.custom_cash_discount_amount)), "cash discount not off the Grand Total")
		_assert(d.custom_total_pending == d.grand_total, "pending does not follow the Grand Total")
		edit(F.q1, F.sm1.user, lambda d: d.set("custom_cash_discount", 0))

	check("S5 5.2 Cash Discount % comes off the Grand Total as on the Sales Order; payable follows", _cash_discount)

	def _officer_limits():
		for field, value in (("custom_selling_price", 1), ("custom_flat_discount", 50), ("custom_offer", 5), ("custom_additional_discount", 3)):
			err = edit(F.q1, F.so1.user, lambda d: d.items[0].set(field, value))
			_assert("A Sales Officer cannot change Selling Price or discounts" in err, f"{field}: {err}")
		err = edit(F.q1, F.so1.user, lambda d: d.set("custom_cash_discount", 5))
		_assert("cannot change Selling Price or discounts" in err, f"cash discount: {err}")
		err = edit(F.q1, F.so1.user, lambda d: d.items[0].set("qty", 12))
		_assert(not err, f"SO cannot change Quantity: {err}")

		def _add(d):
			d.append("items", {"item_code": F.plain, "qty": 2, "custom_selling_price": 1, "custom_flat_discount": 99})

		err = edit(F.q1, F.so1.user, _add)
		_assert(not err, err)
		row = [r for r in qdoc(F.q1).items if r.item_code == F.plain][0]
		_assert(flt(row.custom_selling_price) == flt(F.plain_rate, 2) and flt(row.custom_flat_discount) == 0,
			f"SO's own price kept: {row.custom_selling_price}")

	check("S5 2.2 a Sales Officer edits SKU / Quantity, never Selling Price, discounts or Cash Discount", _officer_limits)

	def _manager_prices():
		err = edit(F.q1, F.sm1.user, lambda d: (d.items[0].set("custom_selling_price", 1500), d.items[0].set("custom_additional_discount", 10)))
		_assert(not err, err)
		row = qdoc(F.q1).items[0]
		_assert(flt(row.custom_selling_price) == 1500 and flt(row.custom_additional_discount) == 10, "manager's price not kept")
		t = trail(F.q1, "Commercial Edit")
		_assert(any(x.field_label == "Selling Price" and x.new_value in ("1500.0", "1500") for x in t), str(t[-3:]))

	check("S5 2.2 Sales Manager sets Selling Price / Additional Discount %; every commercial edit in the trail with SKU", _manager_prices)

	def _boxes():
		d = qdoc(F.q1)
		row = d.items[0]
		_assert(flt(row.qty) == 12, f"quantity changed: {row.qty}")
		if F.box:
			from math import ceil

			_assert(flt(row.custom_boxes) == ceil(12 / F.box), f"box {row.custom_boxes} for 12 / {F.box} (Round Up)")

	check("S5 2.2 Box follows the Customer Type's rounding; Quantity is never changed", _boxes)


def _statuses():
	def _negotiation():
		r = as_(F.so1.user, lambda: Q.start_negotiation(F.q1))
		_assert(r["status"] == "Negotiation" and qdoc(F.q1).custom_quotation_status == "Negotiation", str(r))
		err = refused(lambda: as_(F.so1.user, lambda: Q.start_negotiation(F.q1)))
		_assert("Only a Draft Quotation" in err, err)
		_assert(trail(F.q1, "Negotiation Started"), "not audited")

	check("A-1 Start Negotiation: Draft -> Negotiation (Sales Officer); not twice", _negotiation)

	def _standard_buttons():
		d = qdoc(F.q1)
		_assert("Use Finalize Quotation" in refused(lambda: d.submit()), "plain submit allowed")
		d = qdoc(F.q1)
		_assert("Use Cancel Quotation" in refused(lambda: d.discard()), "plain discard allowed")

	check("A-2 ERPNext's own Submit / Discard are refused: Finalize / Cancel Quotation only", _standard_buttons)


def _finalize():
	def _roles():
		err = refused(lambda: as_(F.so1.user, lambda: Q.finalize(F.q1)))
		_assert("Only a Sales Manager or Sales Admin can finalize" in err, err)

	check("S5 7 a Sales Officer cannot finalize", _roles)

	def _term_required():
		err = edit(F.q1, F.sm1.user, lambda d: d.set("custom_payment_term", ""))
		_assert(not err, err)
		err = refused(lambda: finalize(F.q1))
		_assert("Payment Term is mandatory. Select Advance, Credit, or Partial." in err, err)
		edit(F.q1, F.sm1.user, lambda d: d.set("custom_payment_term", "Advance"))

	check("S5 24.5 Finalize without Payment Term: the doc's message", _term_required)

	def _advance_finalized():
		r = finalize(F.q1)
		d = qdoc(F.q1)
		_assert(d.docstatus == 1 and d.custom_quotation_status == "Finalized", f"{d.docstatus} {d.custom_quotation_status}")
		_assert(d.custom_finalized_by == F.sm1.user and d.custom_finalized_on, "stamps")
		_assert(r["opportunity_result"] == "Won" and frappe.db.get_value("Opportunity", F.opp1, "custom_opportunity_status") == "Won", str(r))
		_assert(d.custom_so_eligibility == "Blocked" and d.custom_payment_status == "Pending", "Advance unpaid must block")
		t = trail(F.q1, "Quotation Finalized")
		_assert(any(x.new_value == "Finalized" and x.user_role == "Sales Manager" for x in t), str(t))
		_assert(any(x.field_label == "Final Commercial Values" and "Grand Total" in x.new_value for x in t), str(t))
		_assert(any(m == "alpinos.offline_sales.quotation.email_buyer_finalized" and kw.get("quotation") == F.q1
			and kw.get("enqueue_after_commit") for m, kw in JOBS), "buyer email not queued after commit")

	check("S5 7 Finalize (SM): submitted, Finalized By / On, Opportunity Won, audited, buyer email queued after commit", _advance_finalized)

	def _credit_date():
		q = credit_quotation()
		d = qdoc(q)
		_assert(getdate(d.custom_expected_payment_date) == getdate(add_days(getdate(d.custom_finalized_on), 30)), str(d.custom_expected_payment_date))
		_assert(d.custom_so_eligibility == "Allowed" and d.custom_payment_status == "Pending", d.custom_so_eligibility)

	check("S5 9.3 Credit: Expected Payment Date = Finalized date + Credit Days; SO Allowed without payment", _credit_date)

	def _partial_reason():
		opp, q = converted(rows=[(F.single, 10), (F.plain, 4)])
		edit(q, F.sm1.user, lambda d: d.set("items", [r for r in d.items if r.item_code == F.single]))
		err = refused(lambda: finalize(q))
		_assert("Enter the Partial Reason" in err, err)
		finalize(q, reason="Buyer dropped the second SKU")
		row = frappe.db.get_value("Opportunity", opp, ["custom_opportunity_status", "custom_status_reason"], as_dict=True)
		_assert(row.custom_opportunity_status == "Partial" and row.custom_status_reason == "Buyer dropped the second SKU", str(row))

	check("S3 6.2 / W4 hand-off: Finalize with less than the Opportunity asks needs the Partial Reason; Opportunity Partial", _partial_reason)

	def _schedule_at_finalize():
		_opp, q = converted(F.partial_buyer.name)
		gt = flt(qdoc(q).grand_total, 2)
		edit(q, F.so1.user, lambda d: d.set("custom_payment_schedule", [
			{"payment_term": "Advance", "expected_payment_date": today(), "expected_amount": flt(gt * 0.3, 2)},
			{"payment_term": "Credit", "expected_payment_date": add_days(today(), 30), "expected_amount": flt(gt * 0.6, 2)},
		]))
		err = refused(lambda: finalize(q))
		_assert(P.M_SCHEDULE_TOTAL in err, err)
		edit(q, F.so1.user, lambda d: d.set("custom_payment_schedule", [
			{"payment_term": "Advance", "expected_payment_date": today(), "expected_amount": gt},
		]))
		err = refused(lambda: finalize(q))
		_assert(P.M_MIN_ROWS in err, err)

	check("S5 13 / 24.4 Finalize: schedule total must equal the Grand Total (doc message); at least two rows (A-9)", _schedule_at_finalize)


def _lock():
	def _commercial():
		d = qdoc(F.q1)
		d.shipping_address_name = None
		err = refused(lambda: as_(F.sm1.user, lambda: d.save()))
		_assert(Q.M_LOCKED in err, err)
		d = qdoc(F.q1)
		d.items[0].qty = 99
		d.flags.ignore_validate_update_after_submit = True  # what ERPNext's Update Items does
		err = refused(lambda: as_(F.sm1.user, lambda: d.save()))
		_assert(Q.M_LOCKED in err, err)

	check("S5 7 after Finalize the commercial values are locked (form Update refused)", _commercial)

	def _payment_fields():
		for field, value in (("custom_payment_term", "Credit"), ("custom_total_received", 5), ("custom_so_eligibility", "Allowed")):
			d = qdoc(F.q1)
			d.set(field, value)
			err = refused(lambda: as_(F.sm1.user, lambda: d.save()))
			_assert(err and ("payment actions" in err or "only through" in err), f"{field}: {err}")

	check("S5 8 after Finalize the payment fields change only through the payment actions", _payment_fields)

	def _rso():
		d = qdoc(F.q1)
		d.custom_responsible_sales_officer = F.so2.user
		_assert(not refused(lambda: as_(F.sm1.user, lambda: d.save())), "SM could not change the Responsible Sales Officer")
		_assert(trail(F.q1, "Responsible Sales Officer Changed"), "not audited")
		d = qdoc(F.q1)
		d.custom_responsible_sales_officer = F.so1.user
		d.save()

	check("S5 2.1 / A-16 Sales Manager changes the Responsible Sales Officer after Finalize; audited", _rso)


def _advance():
	def _full():
		q = advance_quotation()
		gt = flt(qdoc(q).grand_total, 2)
		r = pay(q, gt, utr="UTR-FULL")
		_assert(r["payment_status"] == "Fully Received" and r["total_pending"] == 0 and r["so_eligibility"] == "Allowed", str(r))
		d = qdoc(q)
		rec = d.custom_payment_receipts[0]
		_assert(rec.submitted_by == F.so1.user and rec.submitted_by_role == "Sales Officer" and rec.payment_term == "Advance", str(rec.as_dict()))
		_assert(trail(q, "Payment Submitted") and trail(q, "SO Eligibility Updated"), "payment / eligibility not audited")

	check("S5 12.1 Advance: full payment with proof -> Fully Received, Pending 0, SO Allowed; audited", _full)

	def _short_convert():
		q = advance_quotation()
		gt = flt(qdoc(q).grand_total, 2)
		pay(q, flt(gt * 0.6, 2))
		d = qdoc(q)
		_assert(d.custom_payment_status == "Partially Received" and d.custom_so_eligibility == "Blocked", d.custom_so_eligibility)
		acts = as_(F.so1.user, lambda: Q.form_actions(q))["actions"]
		_assert("convert_to_partial" in acts and "force_complete" in acts, str(acts))
		err = refused(lambda: as_(F.so1.user, lambda: P.convert_to_partial(q, None, add_days(today(), 30))))
		_assert("Enter the reason" in err, err)
		as_(F.so1.user, lambda: P.convert_to_partial(q, "Buyer pays the rest later", add_days(today(), 30)))
		rows = rows_of(q)
		_assert(rows[0][1:] == ("Advance", flt(gt * 0.6, 2), flt(gt * 0.6, 2), 0.0, "Fully Received"), str(rows))
		_assert(rows[1][1] == "Credit" and Q._same(rows[1][2], gt - flt(gt * 0.6, 2)) and rows[1][5] == "Pending", str(rows))
		d = qdoc(q)
		_assert(d.custom_payment_term == "Partial" and d.custom_so_eligibility == "Allowed", d.custom_so_eligibility)
		_assert(d.custom_payment_receipts[0].schedule_row_no == 1 and d.custom_payment_receipts[0].payment_proof, "receipt not on row 1")
		t = trail(q, "Converted to Partial")
		_assert(any(x.reason == "Buyer pays the rest later" and "Total Received" in (x.new_value or "") for x in t), str(t))

	check("S5 12.2-12.3 Advance short -> Convert to Partial: row 1 = received, row 2 Credit = pending; proof kept; SO Allowed", _short_convert)


def _credit():
	def _date_change():
		q = credit_quotation()
		err = refused(lambda: as_(F.so1.user, lambda: P.change_expected_payment_date(q, None, None, add_days(today(), 45))))
		_assert("Enter the reason" in err, err)
		as_(F.so1.user, lambda: P.change_expected_payment_date(q, "Buyer asked for 45 days", 45))
		d = qdoc(q)
		_assert(d.custom_credit_days == 45 and getdate(d.custom_expected_payment_date) == getdate(add_days(getdate(d.custom_finalized_on), 45)), str(d.custom_expected_payment_date))
		t = trail(q, "Credit Date Changed")
		_assert(t and t[0].reason == "Buyer asked for 45 days", str(t))
		F.credit_q = q

	check("S5 9.4 Credit: change Credit Days / Expected Payment Date with a reason; audited old -> new", _date_change)

	def _full_and_short():
		q = F.credit_q
		gt = flt(qdoc(q).grand_total, 2)
		pay(q, flt(gt * 0.6, 2))
		_assert(qdoc(q).custom_so_eligibility == "Allowed", "Credit must never block")
		as_(F.sm1.user, lambda: P.convert_to_partial(q, "Rest in two weeks", add_days(today(), 14)))
		rows = rows_of(q)
		_assert(rows[0][1] == "Credit" and rows[0][4] == 0 and rows[1][1] == "Credit", f"Credit -> Partial rows {rows}")
		_assert(getdate(qdoc(q).custom_payment_schedule[0].expected_payment_date) == getdate(qdoc(q).custom_expected_payment_date), "row 1 date")
		q2 = credit_quotation()
		r = pay(q2, qdoc(q2).grand_total)
		_assert(r["payment_status"] == "Fully Received", str(r))

	check("S5 9.5-9.6 Credit: short payment -> Convert to Partial (row 1 Credit at the old date); full payment -> Fully Received", _full_and_short)


def _partial():
	def _rows():
		q = partial_quotation(0.3)
		gt = flt(qdoc(q).grand_total, 2)
		adv = flt(gt * 0.3, 2)
		d = qdoc(q)
		_assert(d.custom_so_eligibility == "Blocked", "Advance row unpaid must block")
		err = refused(lambda: pay(q, 10))
		_assert(P.M_SELECT_ROW in err, err)
		row1, row2 = d.custom_payment_schedule[0].row_key, d.custom_payment_schedule[1].row_key
		err = refused(lambda: pay(q, adv + 1, row=row1))
		_assert(err == P.M_OVERPAY.format(P.fmt(adv)), err)
		pay(q, adv, row=row1)
		d = qdoc(q)
		_assert(d.custom_so_eligibility == "Allowed" and d.custom_payment_status == "Partially Received", f"{d.custom_so_eligibility}")
		pay(q, flt((gt - adv) / 2, 2), row=row2)
		rows = rows_of(q)
		_assert(rows[1][5] == "Partially Received" and qdoc(q).custom_so_eligibility == "Allowed", str(rows))
		F.partial_q = q

	check("S5 13-14 Partial: payment against a row; row overpayment (doc message); Advance row paid -> Allowed; Credit partly paid stays Allowed", _rows)

	def _revise():
		q = partial_quotation(0.3)
		gt = flt(qdoc(q).grand_total, 2)
		adv = flt(gt * 0.3, 2)
		got = flt(adv * 2 / 3, 2)
		d = qdoc(q)
		k1, k2 = d.custom_payment_schedule[0].row_key, d.custom_payment_schedule[1].row_key
		pay(q, got, row=k1)
		_assert(qdoc(q).custom_so_eligibility == "Blocked", "Advance short must block")

		def revise(rows, reason="Revised with buyer"):
			return refused(lambda: as_(F.so1.user, lambda: P.revise_schedule(q, json.dumps(rows), reason)))

		d1 = add_days(today(), 1)
		err = revise([{"row_key": k1, "payment_term": "Advance", "expected_payment_date": today(), "expected_amount": got - 1},
			{"row_key": k2, "payment_term": "Credit", "expected_payment_date": d1, "expected_amount": gt - got + 1}])
		_assert("cannot be less than" in err, f"below received: {err}")
		err = revise([{"row_key": k2, "payment_term": "Credit", "expected_payment_date": d1, "expected_amount": gt}])
		_assert("has recorded payments and cannot be removed" in err, f"paid row removed: {err}")
		err = revise([{"row_key": k1, "payment_term": "Credit", "expected_payment_date": today(), "expected_amount": got},
			{"row_key": k2, "payment_term": "Credit", "expected_payment_date": d1, "expected_amount": gt - got}])
		_assert("Payment Term cannot change" in err, f"paid row term changed: {err}")
		err = revise([{"row_key": k1, "payment_term": "Advance", "expected_payment_date": today(), "expected_amount": got},
			{"row_key": k2, "payment_term": "Credit", "expected_payment_date": d1, "expected_amount": gt - got - 5}])
		_assert(P.M_SCHEDULE_TOTAL in err, f"total: {err}")
		err = revise([{"row_key": k1, "payment_term": "Advance", "expected_payment_date": today(), "expected_amount": got},
			{"row_key": k2, "payment_term": "Credit", "expected_payment_date": d1, "expected_amount": gt - got}], reason="")
		_assert("Enter the reason" in err, err)
		err = revise([{"row_key": k1, "payment_term": "Advance", "expected_payment_date": today(), "expected_amount": got},
			{"row_key": k2, "payment_term": "Credit", "expected_payment_date": d1, "expected_amount": gt - got}])
		_assert(not err, err)
		rows = rows_of(q)
		_assert(rows[0][4] == 0 and Q._same(rows[1][2], gt - got) and qdoc(q).custom_so_eligibility == "Allowed", str(rows))
		_assert(qdoc(q).custom_payment_receipts[0].payment_proof, "proof lost")
		_assert(trail(q, "Payment Schedule Revised") and trail(q, "Expected Payment Date Changed"), "revision not audited")

	check("S5 14 Revise Schedule (option B): reallocated rows; floor = received, paid row kept with its term; reason; audited", _revise)


def _force_complete():
	def _execute():
		q = advance_quotation()
		gt = flt(qdoc(q).grand_total, 2)
		paid = flt(gt * 0.6, 2)
		pay(q, paid)
		err = refused(lambda: as_(F.so1.user, lambda: P.force_complete(q, " ")))
		_assert(err == P.M_FC_REASON, err)
		as_(F.so1.user, lambda: P.force_complete(q, "Buyer settled at 60%"))
		d = qdoc(q)
		_assert(d.custom_force_complete_applied == 1 and d.custom_force_completed_by == F.so1.user and d.custom_force_completed_role == "Sales Officer", "stamps")
		_assert(Q._same(d.custom_total_received, paid) and Q._same(d.custom_total_pending, gt - paid), "totals changed by Force Complete")
		_assert(d.custom_payment_status == "Partially Received" and d.custom_so_eligibility == "Allowed", d.custom_payment_status)
		_assert(Q._same(d.custom_force_complete_unpaid, gt - paid) and d.custom_payment_process == "Closed", "unpaid / process")
		t = trail(q, "Force Complete")
		_assert(any(x.reason == "Buyer settled at 60%" and "Remaining Unpaid" in (x.new_value or "") for x in t), str(t))
		F.fc_q = q

	check("S5 15 Force Complete: reason (doc message); received stays, unpaid visible, Partially Received, SO Allowed, Closed", _execute)

	def _read_only():
		q = F.fc_q
		_assert(refused(lambda: pay(q, 1)) == P.M_FC_PAYMENT, "payment after Force Complete")
		for fn in (
			lambda: P.change_payment_term(q, "Credit", "x", 10),
			lambda: P.convert_to_partial(q, "x", add_days(today(), 3)),
			lambda: P.force_complete(q, "again"),
		):
			_assert(refused(lambda: as_(F.sm1.user, fn)) == Q.M_FC_READ_ONLY, "change after Force Complete")
		d = qdoc(q)
		d.custom_responsible_sales_officer = F.so2.user
		_assert(Q.M_FC_READ_ONLY in refused(lambda: as_(F.sm1.user, lambda: d.save())), "form update after Force Complete")
		acts = as_(F.so1.user, lambda: Q.form_actions(q))["actions"]
		_assert(not {"record_payment", "change_payment_term", "force_complete"} & set(acts), str(acts))
		q2 = advance_quotation()
		pay(q2, qdoc(q2).grand_total)
		_assert(refused(lambda: as_(F.so1.user, lambda: P.force_complete(q2, "x"))) == P.M_NOTHING_PENDING, "Force Complete with nothing pending")

	check("S5 15.5 / 24.7-24.8 after Force Complete: no payment (doc message), no term / date / schedule change, read only", _read_only)


def _exceptions():
	q = advance_quotation()
	gt = flt(qdoc(q).grand_total, 2)

	check("S5 24.1 Received Amount <= 0 is blocked with the doc's message",
		lambda: _assert(refused(lambda: pay(q, 0)) == P.M_AMOUNT_ZERO and refused(lambda: pay(q, -5)) == P.M_AMOUNT_ZERO))
	check("S5 24.2 Received Amount above the pending amount is blocked with the doc's message (and amount)",
		lambda: _assert(refused(lambda: pay(q, gt + 1)) == P.M_OVERPAY.format(P.fmt(gt))))
	check("S5 24.3 a received amount without Payment Proof is blocked with the doc's message",
		lambda: _assert(refused(lambda: pay(q, 10, with_proof=False)) == P.M_PROOF))

	def _total():
		_opp, d = converted(F.partial_buyer.name)
		g = flt(qdoc(d).grand_total, 2)
		edit(d, F.so1.user, lambda x: x.set("custom_payment_schedule", [
			{"payment_term": "Advance", "expected_payment_date": today(), "expected_amount": flt(g / 2, 2)},
			{"payment_term": "Credit", "expected_payment_date": today(), "expected_amount": 1},
		]))
		_assert(P.M_SCHEDULE_TOTAL in refused(lambda: finalize(d)), "finalize")
		q3 = partial_quotation()
		key = qdoc(q3).custom_payment_schedule[0].row_key
		k2 = qdoc(q3).custom_payment_schedule[1].row_key
		err = refused(lambda: as_(F.sm1.user, lambda: P.revise_schedule(q3, json.dumps([
			{"row_key": key, "payment_term": "Advance", "expected_payment_date": today(), "expected_amount": 1},
			{"row_key": k2, "payment_term": "Credit", "expected_payment_date": today(), "expected_amount": 1},
		]), "x")))
		_assert(P.M_SCHEDULE_TOTAL in err, err)

	check("S5 24.4 schedule total different from the Grand Total blocks Finalize and the schedule save (doc message)", _total)

	def _term():
		_opp, d = converted()
		edit(d, F.sm1.user, lambda x: x.set("custom_payment_term", ""))
		_assert(P.M_TERM_REQUIRED in refused(lambda: finalize(d)), "finalize without term")
		_assert(P.M_TERM_REQUIRED in refused(lambda: as_(F.sm1.user, lambda: P.change_payment_term(q, "", "x"))), "change to blank")

	check("S5 24.5 Finalize without Payment Term is blocked with the doc's message", _term)

	def _fc_reason():
		_assert(refused(lambda: as_(F.so1.user, lambda: P.force_complete(q, None))) == P.M_FC_REASON, "no reason")

	check("S5 24.6 Force Complete without a reason is blocked with the doc's message", _fc_reason)
	check("S5 24.7 a payment after Force Complete is blocked with the doc's message",
		lambda: _assert(refused(lambda: pay(F.fc_q, 1)) == P.M_FC_PAYMENT))

	def _fc_modify():
		for user in (F.so1.user, F.sm1.user, F.sa1.user):
			_assert(refused(lambda: as_(user, lambda: P.change_payment_term(F.fc_q, "Credit", "x", 5))) == Q.M_FC_READ_ONLY, user)

	check("S5 24.8 SO / SM / SA cannot modify a Force Completed Quotation", _fc_modify)

	def _cancelled():
		q4 = advance_quotation()
		as_(F.sm1.user, lambda: Q.cancel_quotation(q4, "Buyer withdrew"))
		_assert(refused(lambda: pay(q4, 1)) == P.M_CANCELLED_PAYMENT, "payment on a cancelled Quotation")

	check("S5 24.9 a payment on a Cancelled Quotation is blocked with the doc's message", _cancelled)

	def _dates_and_draft():
		_assert(refused(lambda: pay(q, 10, date=add_days(today(), 1))) == P.M_DATE_FUTURE, "future date")
		_opp, d = converted()
		_assert(refused(lambda: pay(d, 10)) == Q.M_NO_DRAFT_PAYMENT, "payment before Finalize (A-3)")

	check("S5 10 Received Date not in the future; no payment before Finalize (A-3)", _dates_and_draft)


def _eligibility_table():
	def doc(status="Finalized", docstatus=1, term="Advance", gt=1000, receipts=(), rows=(), fc=0):
		d = frappe.new_doc("Quotation")
		d.update({"custom_quotation_status": status, "docstatus": docstatus, "custom_payment_term": term, "grand_total": gt,
			"custom_force_complete_applied": fc})
		for key, term_, amount in rows:
			d.append("custom_payment_schedule", {"row_key": key, "payment_term": term_, "expected_payment_date": today(), "expected_amount": amount})
		for amount, key in receipts:
			d.append("custom_payment_receipts", {"received_amount": amount, "received_date": today(), "payment_proof": "x", "schedule_row_key": key})
		P.recompute(d)
		return d.custom_payment_status, d.custom_so_eligibility

	def _table():
		cases = [
			(doc(status="Draft", docstatus=0), ("Pending", "Blocked"), "Draft"),
			(doc(status="Negotiation", docstatus=0, term="Credit"), ("Pending", "Blocked"), "Negotiation"),
			(doc(), ("Pending", "Blocked"), "Advance unpaid"),
			(doc(receipts=[(600, None)]), ("Partially Received", "Blocked"), "Advance short"),
			(doc(receipts=[(1000, None)]), ("Fully Received", "Allowed"), "Advance paid"),
			(doc(term="Credit"), ("Pending", "Allowed"), "Credit unpaid"),
			(doc(term="Partial", rows=[("a", "Advance", 300), ("c", "Credit", 700)]), ("Pending", "Blocked"), "Partial Advance row unpaid"),
			(doc(term="Partial", rows=[("a", "Advance", 300), ("c", "Credit", 700)], receipts=[(200, "a")]), ("Partially Received", "Blocked"), "Partial Advance row short"),
			(doc(term="Partial", rows=[("a", "Advance", 300), ("c", "Credit", 700)], receipts=[(300, "a")]), ("Partially Received", "Allowed"), "Partial Advance row paid"),
			(doc(term="Partial", rows=[("c", "Credit", 400), ("d", "Credit", 600)]), ("Pending", "Allowed"), "Partial Credit + Credit"),
			(doc(receipts=[(600, None)], fc=1), ("Partially Received", "Allowed"), "Force Completed"),
			(doc(status="Sales Order Created", term="Credit"), ("Pending", "Allowed"), "Sales Order Created"),
			(doc(status="Cancelled", docstatus=2, term="Credit"), ("Pending", "Blocked"), "Cancelled"),
			(doc(gt=0), ("Fully Received", "Allowed"), "Grand Total 0 (A-36)"),
		]
		for got, want, label in cases:
			_assert(got == want, f"{label}: {got} != {want}")

	check("S5 3.3 / 16 SO Eligibility and Payment Status table (Force Complete never makes it Fully Received)", _table)


def _proof_and_correction():
	def _protect():
		q = F.partial_q
		d = qdoc(q)
		d.custom_payment_receipts[0].received_amount = 1
		_assert(Q.M_SUBMITTED_PAYMENT in refused(lambda: as_(F.sa1.user, lambda: d.save())), "SA changed a submitted payment")
		d = qdoc(q)
		d.custom_payment_receipts = d.custom_payment_receipts[1:]
		_assert(Q.M_SUBMITTED_PAYMENT in refused(lambda: as_(F.sm1.user, lambda: d.save())), "SM removed a submitted payment")
		url = qdoc(q).custom_payment_receipts[0].payment_proof
		_assert(refused(lambda: as_(F.sm1.user, lambda: P.protect_proof_file(frappe._dict(file_url=url)))), "proof file deletable")
		_assert(not refused(lambda: as_(F.sysm.user, lambda: P.protect_proof_file(frappe._dict(file_url=url)))), "System Manager")
		_assert(refused(lambda: as_(F.sm1.user, lambda: P.correct_payment(q, qdoc(q).custom_payment_receipts[0].name, "x", 5))), "SM corrected")

	check("S5 19 a submitted payment and its proof are immutable for SO / SM / SA", _protect)

	def _correct():
		q = F.partial_q
		d = qdoc(q)
		rec = d.custom_payment_receipts[0]
		row = d.custom_payment_schedule[0]
		err = refused(lambda: as_(F.sysm.user, lambda: P.correct_payment(q, rec.name, None, 5)))
		_assert("Enter the reason" in err, err)
		over = flt(row.expected_amount) + 1
		err = refused(lambda: as_(F.sysm.user, lambda: P.correct_payment(q, rec.name, "typo", over)))
		_assert(err.startswith("Received Amount cannot exceed the current pending amount"), err)
		new = flt(rec.received_amount) - 10
		as_(F.sysm.user, lambda: P.correct_payment(q, rec.name, "Bank statement shows less", new, None, None, "UTR-FIX"))
		d = qdoc(q)
		rec = d.custom_payment_receipts[0]
		_assert(Q._same(rec.received_amount, new) and rec.corrected == 1 and rec.last_corrected_by == F.sysm.user and rec.reference_utr == "UTR-FIX", str(rec.as_dict()))
		_assert(Q._same(d.custom_payment_schedule[0].pending_amount, 10) and d.custom_so_eligibility == "Blocked", "recompute after correction")
		t = trail(q, "System Manager Payment Correction")
		_assert(len(t) == 2 and all(x.reason == "Bank statement shows less" and x.user_role == "System Manager" for x in t), str(t))
		_assert(t[0].previous_value and t[0].new_value and t[0].previous_value != t[0].new_value, "old / new value")

	check("S5 19 System Manager correction: reason, no overpayment, old -> new in the trail, totals recomputed", _correct)


def _term_change():
	def _changes():
		q = advance_quotation()
		gt = flt(qdoc(q).grand_total, 2)
		err = refused(lambda: as_(F.so1.user, lambda: P.change_payment_term(q, "Credit", "", 15)))
		_assert("Enter the reason" in err, err)
		as_(F.so1.user, lambda: P.change_payment_term(q, "Credit", "Buyer moved to credit", 15))
		d = qdoc(q)
		_assert(d.custom_payment_term == "Credit" and d.custom_credit_days == 15 and d.custom_so_eligibility == "Allowed", d.custom_payment_term)
		paid = flt(gt * 0.4, 2)
		pay(q, paid)
		rows = [
			{"payment_term": "Credit", "expected_payment_date": today(), "expected_amount": paid},
			{"payment_term": "Advance", "expected_payment_date": add_days(today(), 5), "expected_amount": flt(gt - paid, 2)},
		]
		as_(F.sm1.user, lambda: P.change_payment_term(q, "Partial", "Advance for the rest", schedule=json.dumps(rows)))
		d = qdoc(q)
		_assert(d.custom_payment_term == "Partial" and d.custom_payment_receipts[0].schedule_row_no == 1, "receipt not placed on row 1")
		_assert(d.custom_so_eligibility == "Blocked", "Advance row pending must block")
		as_(F.sm1.user, lambda: P.change_payment_term(q, "Advance", "Back to advance"))
		d = qdoc(q)
		_assert(not d.custom_payment_schedule and len(d.custom_payment_receipts) == 1 and d.custom_payment_receipts[0].payment_proof
			and d.custom_payment_receipts[0].schedule_row_no == 1, "payment lost or reset with the rows")
		_assert(Q._same(d.custom_total_received, paid), "received changed")
		t = trail(q, "Payment Term Changed")
		_assert(len([x for x in t if x.field_label == "Payment Term"]) == 3, str(t))
		_assert(any("Total Received" in (x.new_value or "") for x in t), "totals at the change not recorded")

	check("S5 9.2 Payment Term change after Finalize (Advance -> Credit -> Partial -> Advance): reason, payments kept, audited", _changes)


def _cancel():
	from alpinos.offline_sales.opportunity import convert_to_quotation

	def _draft():
		opp, q = converted()
		_assert("Only a Sales Manager or Sales Admin can cancel" in refused(lambda: as_(F.so1.user, lambda: Q.cancel_quotation(q, "x"))), "SO cancelled")
		_assert("Enter the reason" in refused(lambda: as_(F.sm1.user, lambda: Q.cancel_quotation(q, ""))), "no reason")
		as_(F.sa1.user, lambda: Q.cancel_quotation(q, "Buyer changed plans"))
		d = qdoc(q)
		_assert(d.docstatus == 2 and d.custom_quotation_status == "Cancelled", f"{d.docstatus} {d.custom_quotation_status}")
		_assert(d.custom_cancellation_reason == "Buyer changed plans" and d.custom_cancelled_by == F.sa1.user and d.custom_cancelled_by_role == "Sales Admin", "stamps")
		row = frappe.db.get_value("Opportunity", opp, ["custom_opportunity_status", "custom_linked_quotation"], as_dict=True)
		_assert(row.custom_opportunity_status == "Pending (Submitted)" and not row.custom_linked_quotation, str(row))
		q2 = as_(F.so1.user, lambda: convert_to_quotation(opp))["quotation"]
		_assert(q2 != q and qdoc(q2).custom_quotation_status == "Draft", "no new Quotation from the same Opportunity")
		_assert(trail(q, "Quotation Cancelled"), "not audited")

	check("S5 21 Cancel a Draft (SM / SA, reason): read only, stamped; Opportunity Pending (Submitted) again; new Quotation (A-46)", _draft)

	def _finalized():
		q = advance_quotation()
		pay(q, flt(qdoc(q).grand_total * 0.5, 2))
		so = OT._insert("Sales Order", name=f"{OT.TAG}-SO-{q}", customer=frappe.db.get_value("Buyer Master", F.ready.name, "customer"),
			company=F.company, transaction_date=today(), docstatus=0, custom_quotation=q, custom_workflow_status="Draft")
		err = refused(lambda: as_(F.sm1.user, lambda: Q.cancel_quotation(q, "x")))
		_assert(err == Q.M_CANCEL_SO.format(so), err)
		frappe.db.set_value("Sales Order", so, "docstatus", 2)
		as_(F.sm1.user, lambda: Q.cancel_quotation(q, "Order dropped"))
		d = qdoc(q)
		_assert(d.docstatus == 2 and d.custom_quotation_status == "Cancelled" and len(d.custom_payment_receipts) == 1, "payments not kept")
		_assert(d.custom_payment_status == "Partially Received" and d.custom_so_eligibility == "Blocked", d.custom_so_eligibility)
		F.cancelled_q = q

	check("S5 21 Cancel a Finalized Quotation: only once its Sales Order is cancelled (message); payments preserved", _finalized)

	def _correct_cancelled():
		q = F.cancelled_q
		rec = qdoc(q).custom_payment_receipts[0]
		as_(F.sysm.user, lambda: P.correct_payment(q, rec.name, "Wrong date", None, add_days(today(), -1)))
		_assert(getdate(qdoc(q).custom_payment_receipts[0].received_date) == getdate(add_days(today(), -1)), "not corrected")

	check("A-15 a System Manager may still correct a payment of a cancelled Quotation", _correct_cancelled)


def _print_and_email():
	from alpinos.offline_sales.quotation_print import PF_NAME

	def _pdf():
		q = partial_quotation()
		frappe.db.set_value("Quotation", q, "custom_quotation_remarks", "Deliver in two lots")
		html = frappe.get_print("Quotation", q, PF_NAME)
		d = qdoc(q)
		for text in (q, "Payment Term: Partial", "Deliver in two lots", d.items[0].item_code, "Grand Total"):
			_assert(text in html, f"missing {text}")
		for text in ("Activity", "Payment Proof", "SO Eligibility", "Received Amount"):
			_assert(text not in html, f"internal {text} on the PDF")
		_assert(frappe.get_meta("Quotation").default_print_format == PF_NAME, "not the default print format")
		as_(F.sm1.user, lambda: Q.cancel_quotation(q, "x"))
		from alpinos.offline_sales.quotation_print import HTML

		_assert("This Quotation is Cancelled" in frappe.render_template(HTML, {"doc": qdoc(q)}), "cancelled PDF")

	check("S5 22 PDF: Payment Term, schedule, remarks, items, totals; no internal data; none for a Cancelled one", _pdf)

	def _email():
		real, real_send, sent = Q.quotation_pdf, frappe.sendmail, []
		Q.quotation_pdf = lambda name: b"%PDF-1.4 test"
		frappe.sendmail = lambda **kw: (sent.append(kw), real_send(**kw))[1]
		try:
			Q.email_buyer_finalized(F.q1)
			frappe.db.set_value("Buyer Master", F.ready.name, "email", "")
			before = frappe.db.count("Email Queue", {"reference_doctype": "Quotation", "reference_name": F.q1})
			Q.email_buyer_finalized(F.q1)
			after = frappe.db.count("Email Queue", {"reference_doctype": "Quotation", "reference_name": F.q1})
		finally:
			Q.quotation_pdf, frappe.sendmail = real, real_send
		mail = frappe.get_all("Email Queue", filters={"reference_doctype": "Quotation", "reference_name": F.q1}, pluck="name")
		_assert(len(mail) == 1 and len(sent) == 1 and before == after, f"{len(mail)} mails ({before} -> {after}), {len(sent)} sent")
		_assert(sent[0]["recipients"] == [frappe.db.get_value("Buyer Master", F.ready.name, "email") or sent[0]["recipients"][0]], "recipient")
		_assert([a["fname"] for a in sent[0]["attachments"]] == [f"{F.q1}.pdf"], str(sent[0]["attachments"]))
		_assert(sent[0]["message"] == f"Your Quotation {F.q1} has been finalized. Review the attached terms.", sent[0]["message"])

	check("S2 7.2 Quotation Finalized: buyer email with the PDF and the doc's text; none when the buyer has no email", _email)


def _reminders_and_independence():
	from alpinos.offline_sales import payment_reminders as W6

	def _reminders():
		q = credit_quotation()
		frappe.db.set_value("Quotation", q, "custom_expected_payment_date", today())
		plan = {(r.quotation, r.row): r for r in W6.plan()}
		_assert((q, None) in plan and plan[(q, None)].kind == W6.DUE_TODAY, "Credit due today not planned")
		_assert(F.so1.user in plan[(q, None)].users and F.sm1.user in plan[(q, None)].users, plan[(q, None)].users)
		as_(F.so1.user, lambda: P.force_complete(q, "settled"))
		_assert(not any(r.quotation == q for r in W6.plan()), "reminder after Force Complete")

	check("W6 hand-off: a Finalized Credit Quotation is reminded to the Responsible SO and the finalizing SM; stops at Force Complete", _reminders)

	def _independent():
		a, b = advance_quotation(), advance_quotation()
		pay(a, qdoc(a).grand_total)
		_assert(qdoc(b).custom_total_received == 0 and qdoc(b).custom_payment_status == "Pending", "one Quotation's payment moved another")

	check("S5 25.1 payments belong to their own Quotation only", _independent)


def _migration():
	from alpinos.patches.v2_0 import quotation_payment_v2 as M

	def _patch():
		q = advance_quotation()
		frappe.db.set_value("Quotation", q, {
			"custom_payment_mode": "Debit", "custom_payment_term": None, "custom_quotation_status": None,
			"custom_attachment_proof": "/private/files/old.png", "custom_advance_amount": 500,
			"custom_total_received": 0, "custom_total_pending": 0, "custom_payment_status": None, "custom_so_eligibility": None,
		})
		frappe.db.delete("Quotation Payment Receipt", {"parent": q})
		_opp, draft = converted()
		frappe.db.set_value("Quotation", draft, {"custom_payment_mode": "Partial", "custom_quotation_status": None, "custom_payment_term": None})
		M.migrate([q, draft])
		d = qdoc(q)
		_assert(d.custom_payment_term == "Credit" and d.custom_quotation_status == "Finalized", f"{d.custom_payment_term} {d.custom_quotation_status}")
		_assert(not d.custom_payment_receipts and d.custom_total_received == 0 and Q._same(d.custom_total_pending, d.grand_total), "receipt invented")
		_assert(d.custom_payment_status == "Pending" and d.custom_so_eligibility == "Allowed", f"{d.custom_payment_status} {d.custom_so_eligibility}")
		_assert(d.custom_attachment_proof == "/private/files/old.png", "old proof field cleared")
		d = qdoc(draft)
		_assert(d.custom_payment_term == "Partial" and d.custom_quotation_status == "Draft", f"{d.custom_payment_term} {d.custom_quotation_status}")

	check("A-32 migration: Debit -> Credit, docstatus -> status, totals, no receipts invented, old fields kept", _patch)
