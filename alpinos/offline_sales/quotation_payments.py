"""Quotation payments ("Opportunity to Sales Order v1.0.0", Section 5, 8-19; W5).

One dynamic Payment Section on the Quotation:

    Payment Term   Advance   the whole Grand Total is expected before the Sales Order
                   Credit    due on Expected Payment Date = Finalized date + Credit Days
                   Partial   a Payment Schedule of Advance / Credit rows whose Expected Amounts
                             add up to the Grand Total (at least two rows)

Each submitted payment is a row of Quotation Payment Receipt (amount, date, proof, reference,
the schedule row it pays, who / when); schedule rows show the sums (A-4). Totals, Payment Status,
SO Eligibility and the Payment Process are recomputed after every change (recompute).

Payments and changes to the payment arrangement happen after Finalize, through the whitelisted
actions below (a Sales Officer holds no submit right on Quotation, A-2): Record Payment, Change
Payment Term, Change Expected Payment Date, Revise Payment Schedule, Convert to Partial, Force
Complete (SO / SM / SA), and Correct Payment (System Manager only). Force Complete closes the
payment process for good and leaves the Quotation read only; a Cancelled Quotation takes no
payment. A submitted payment is never changed except by a System Manager's correction, with a
reason; every action is in the Activity / Audit Trail.
"""

import json

import frappe
from frappe import _
from frappe.utils import add_days, cint, cstr, date_diff, flt, formatdate, getdate, now_datetime, today

from alpinos.alpinos_development.doctype.field_change_log.field_change_log import acting_role
from alpinos.offline_sales import audit
from alpinos.offline_sales import quotation as Q

DOCTYPE = Q.DOCTYPE
SCHEDULE = "custom_payment_schedule"
RECEIPTS = Q.RECEIPTS
ROW_TERMS = ("Advance", "Credit")
PENDING, PARTIALLY, FULLY = "Pending", "Partially Received", "Fully Received"
ALLOWED, BLOCKED = "Allowed", "Blocked"

# messages the document gives word for word (24, 10.1, 15.4)
M_AMOUNT_ZERO = "Received Amount must be greater than ₹0."
M_OVERPAY = "Received Amount cannot exceed the current pending amount of ₹{0}."
M_PROOF = "Payment Proof is mandatory when recording a received payment."
M_SCHEDULE_TOTAL = "Total Scheduled Amount does not match Quotation Grand Total. Please adjust the Payment Schedule."
M_TERM_REQUIRED = Q.M_TERM_REQUIRED
M_FC_REASON = "Mandatory Force Complete reason is required."
M_FC_PAYMENT = (
	"Payment process for this Quotation has been permanently closed through Force Complete. No further payment can be "
	"recorded."
)
M_CANCELLED_PAYMENT = "Payments cannot be recorded for a cancelled Quotation."
# messages written for this build
M_DATE_REQUIRED = "Received Date is mandatory when recording a received payment."
M_DATE_FUTURE = "Received Date cannot be a future date."
M_ROW_FIELDS = "Row {0}: Payment Term and Expected Payment Date are mandatory."
M_ROW_AMOUNT = "Row {0}: Expected Amount must be greater than ₹0."
M_ROW_FLOOR = "Row {0}: Expected Amount cannot be less than the ₹{1} already received."
M_ROW_LOCKED = "Row {0} has recorded payments and cannot be removed."
M_ROW_TERM_LOCKED = "Row {0} has recorded payments, so its Payment Term cannot change."
M_MIN_ROWS = "A Partial Payment Schedule needs at least two rows."
M_SELECT_ROW = "Select the Payment Schedule row this payment is for."
M_NOTHING_PENDING = "Nothing is pending on this Quotation."
M_CREDIT_DATE = "Enter the Credit Days or the Expected Payment Date."
M_NOT_FINALIZED = "This action is for a Finalized Quotation. Before Finalize, the Payment section is changed on the form."
M_SYSTEM_MANAGER = "A submitted payment cannot be changed. Only a System Manager can correct it, with a reason."


def fmt(value):
	return frappe.utils.fmt_money(flt(value, 2), 2)


def is_system_manager(user=None):
	user = user or frappe.session.user
	return user == "Administrator" or "System Manager" in frappe.get_roles(user)


def _date(value):
	return formatdate(value, "dd-MM-yyyy") if value else ""


# ----------------------------------------------------------------------------- the summary


def status_for(received, pending):
	"""11 / S5-R82, per Quotation and per schedule row (2-decimal compare). A Grand Total of 0 has
	nothing to collect: Fully Received (A-36)."""
	if flt(pending, 2) <= 0:
		return FULLY
	if flt(received, 2) <= 0:
		return PENDING
	return PARTIALLY


def eligibility(doc):
	"""16: SO Eligibility. Blocked before Finalize and when Cancelled; Force Complete = Allowed;
	only an unpaid Advance obligation blocks (Credit never does)."""
	if Q.status_of(doc) not in Q.OPEN or doc.docstatus != 1:
		return BLOCKED
	if cint(doc.get("custom_force_complete_applied")):
		return ALLOWED
	term = doc.get("custom_payment_term")
	if term == "Credit":
		return ALLOWED
	if term == "Advance":
		return ALLOWED if flt(doc.get("custom_total_pending"), 2) <= 0 else BLOCKED
	if term == "Partial":
		return ALLOWED if advance_pending(doc) <= 0 else BLOCKED
	return BLOCKED


def advance_pending(doc):
	if doc.get("custom_payment_term") == "Advance":
		return max(flt(doc.get("custom_total_pending"), 2), 0)
	return flt(sum(max(flt(r.get("pending_amount")), 0) for r in doc.get(SCHEDULE) or [] if r.get("payment_term") == "Advance"), 2)


def eligibility_note(doc):
	"""The form's line under a Blocked SO Eligibility (S5-R179)."""
	if doc.get("custom_so_eligibility") != BLOCKED or Q.status_of(doc) not in Q.OPEN:
		return None
	return _("SO Eligibility is Blocked: Advance pending ₹{0}.").format(fmt(advance_pending(doc)))


def recompute(doc):
	"""Schedule rows from the receipts, then Total Received / Pending, Payment Status, SO
	Eligibility and the Payment Process (11, 16)."""
	receipts = doc.get(RECEIPTS) or []
	got, latest = {}, {}
	for r in receipts:
		key = r.get("schedule_row_key")
		if not key:
			continue
		got[key] = flt(got.get(key)) + flt(r.get("received_amount"))
		last = latest.get(key)
		if not last or (getdate(r.received_date), cint(r.idx)) >= (getdate(last.received_date), cint(last.idx)):
			latest[key] = r
	row_no = {}
	for i, row in enumerate(doc.get(SCHEDULE) or [], 1):
		if not row.get("row_key"):
			row.row_key = frappe.generate_hash(length=12)
		row.idx = i
		row_no[row.row_key] = i
		received = flt(got.get(row.row_key), 2)
		last = latest.get(row.row_key)
		row.received_amount = received
		row.received_date = last.received_date if last else None
		row.payment_proof = last.payment_proof if last else None
		row.reference_utr = last.reference_utr if last else None
		row.pending_amount = flt(flt(row.get("expected_amount"), 2) - received, 2)
		row.row_status = status_for(received, row.pending_amount)
	for r in receipts:
		if r.get("schedule_row_key") in row_no:
			r.schedule_row_no = row_no[r.schedule_row_key]
	received = flt(sum(flt(r.get("received_amount")) for r in receipts), 2)
	pending = flt(flt(doc.get("grand_total"), 2) - received, 2)
	# the Payment Section shows the Quotation Grand Total beside Received / Pending (11)
	if doc.meta.has_field("custom_payment_grand_total"):
		doc.custom_payment_grand_total = flt(doc.get("grand_total"), 2)
	doc.custom_total_received = received
	doc.custom_total_pending = pending
	doc.custom_payment_status = status_for(received, pending)
	doc.custom_so_eligibility = eligibility(doc)
	doc.custom_payment_process = "Closed" if cint(doc.get("custom_force_complete_applied")) else "Open"


def snapshot(doc):
	return {"custom_payment_status": doc.get("custom_payment_status"), "custom_so_eligibility": doc.get("custom_so_eligibility")}


def log_derived(doc, before):
	"""System entries for the computed values an action moved (S7: "Payment Status Updated",
	"SO Eligibility Updated")."""
	for field, action, label in (
		("custom_payment_status", "Payment Status Updated", "Payment Status"),
		("custom_so_eligibility", "SO Eligibility Updated", "SO Eligibility"),
	):
		if (before or {}).get(field) != doc.get(field):
			Q.system_log(doc.name, action, _(label), (before or {}).get(field), doc.get(field))


# ----------------------------------------------------------------------------- the schedule


def schedule_summary(doc, rows=None):
	rows = doc.get(SCHEDULE) if rows is None else rows
	return "; ".join(
		f"Row {i} {r.get('payment_term') or ''} {_date(r.get('expected_payment_date'))} ₹{fmt(r.get('expected_amount'))}"
		for i, r in enumerate(rows or [], 1)
	)


def config_summary(doc):
	"""The payment arrangement in one line, for the trail."""
	term = doc.get("custom_payment_term") or ""
	if term == "Credit":
		return _("Credit, {0} days, due {1}").format(cint(doc.get("custom_credit_days")), _date(doc.get("custom_expected_payment_date")))
	if term == "Partial":
		return _("Partial: {0}").format(schedule_summary(doc))
	if term == "Advance":
		return _("Advance: ₹{0} expected").format(fmt(doc.get("grand_total")))
	return ""


def schedule_errors(doc, rows=None):
	"""13-14: at least two rows, each with a term, a date and an amount above 0, adding up to the
	Grand Total."""
	rows = doc.get(SCHEDULE) if rows is None else rows
	errors = []
	if len(rows or []) < 2:
		errors.append(_(M_MIN_ROWS))
	for i, r in enumerate(rows or [], 1):
		if r.get("payment_term") not in ROW_TERMS or not r.get("expected_payment_date"):
			errors.append(_(M_ROW_FIELDS).format(i))
		if flt(r.get("expected_amount"), 2) <= 0:
			errors.append(_(M_ROW_AMOUNT).format(i))
	total = flt(sum(flt(r.get("expected_amount"), 2) for r in rows or []), 2)
	if rows and not Q._same(total, doc.get("grand_total")):
		errors.append(_(M_SCHEDULE_TOTAL))
	return errors


def prepare_schedule(doc, blocking=False):
	"""Draft / Negotiation save: rows keyed and complete; a total that does not match the Grand
	Total is a warning while the Grand Total can still move, and blocks at Finalize (A-8)."""
	rows = doc.get(SCHEDULE) or []
	if doc.get("custom_payment_term") != "Partial":
		if blocking and rows:
			doc.set(SCHEDULE, [])
		return
	for r in rows:
		if not r.get("row_key"):
			r.row_key = frappe.generate_hash(length=12)
	errors = [e for e in schedule_errors(doc) if e not in (_(M_SCHEDULE_TOTAL), _(M_MIN_ROWS))]
	if errors:
		frappe.throw("<br>".join(errors), title=_("Payment Schedule"))
	if blocking:
		errors = schedule_errors(doc)
		if errors:
			frappe.throw("<br>".join(errors), title=_("Payment Schedule"))
	elif rows and not Q._same(sum(flt(r.get("expected_amount"), 2) for r in rows), doc.get("grand_total")):
		frappe.msgprint(_(M_SCHEDULE_TOTAL), indicator="orange", title=_("Payment Schedule"))


def _parse_rows(schedule):
	rows = json.loads(schedule) if isinstance(schedule, str) else (schedule or [])
	return [frappe._dict(r) for r in rows]


def set_schedule(doc, rows_in, place_unrowed=False):
	"""Replace the Payment Schedule with `rows_in` ({row_key?, payment_term, expected_payment_date,
	expected_amount, remarks}), keeping each existing row (by row_key) and its payments: a row with
	payments is never removed, keeps its term and never drops below what it received (A-12).
	place_unrowed: payments that belong to no row yet (an Advance / Credit Quotation's) go to row 1.
	Returns the Expected Payment Date changes of kept rows [(row no, old, new)]."""
	existing = {r.row_key: r for r in doc.get(SCHEDULE) or [] if r.get("row_key")}
	received = {}
	for r in doc.get(RECEIPTS) or []:
		if r.get("schedule_row_key") in existing:
			received[r.schedule_row_key] = flt(received.get(r.schedule_row_key)) + flt(r.received_amount)
	unrowed = [r for r in doc.get(RECEIPTS) or [] if r.get("schedule_row_key") not in existing]

	errors, plan, seen = [], [], set()
	for i, item in enumerate(rows_in, 1):
		key = cstr(item.get("row_key")).strip()
		old = existing.get(key) if key and key not in seen else None
		term = item.get("payment_term")
		amount = flt(item.get("expected_amount"), 2)
		if old:
			seen.add(key)
			got = flt(received.get(key), 2)
			if got > 0 and term != old.payment_term:
				errors.append(_(M_ROW_TERM_LOCKED).format(i))
			if amount + 0.004 < got:
				errors.append(_(M_ROW_FLOOR).format(i, fmt(got)))
		else:
			key = frappe.generate_hash(length=12)
		plan.append(frappe._dict(
			row_key=key, old=old, payment_term=term, expected_payment_date=item.get("expected_payment_date"),
			expected_amount=amount, remarks=item.get("remarks"),
		))
	for key, old in existing.items():
		if key not in seen and flt(received.get(key)) > 0:
			errors.append(_(M_ROW_LOCKED).format(old.idx))
	if place_unrowed and unrowed and plan:
		floor = flt(received.get(plan[0].row_key)) + sum(flt(r.received_amount) for r in unrowed)
		if plan[0].expected_amount + 0.004 < flt(floor, 2):
			errors.append(_(M_ROW_FLOOR).format(1, fmt(floor)))
	errors += schedule_errors(doc, plan)
	if errors:
		frappe.throw("<br>".join(dict.fromkeys(errors)), title=_("Payment Schedule"))

	date_changes, rows = [], []
	for i, p in enumerate(plan, 1):
		if p.old:
			if p.old.expected_payment_date and getdate(p.old.expected_payment_date) != getdate(p.expected_payment_date):
				date_changes.append((i, p.old.expected_payment_date, p.expected_payment_date))
			p.old.update({
				"payment_term": p.payment_term, "expected_payment_date": p.expected_payment_date,
				"expected_amount": p.expected_amount, "remarks": p.remarks,
			})
			rows.append(p.old)
		else:
			rows.append({
				"row_key": p.row_key, "payment_term": p.payment_term, "expected_payment_date": p.expected_payment_date,
				"expected_amount": p.expected_amount, "remarks": p.remarks,
			})
	doc.set(SCHEDULE, [])
	for r in rows:
		doc.append(SCHEDULE, r)
	for i, r in enumerate(doc.get(SCHEDULE), 1):
		r.idx = i
	if place_unrowed:
		for r in unrowed:
			r.schedule_row_key = plan[0].row_key
	return date_changes


def _set_credit_date(doc, credit_days=None, expected_payment_date=None):
	"""Credit: Expected Payment Date = Finalized date + Credit Days (calendar days), or the date
	given (then Credit Days are the days from the Finalized date)."""
	base = getdate(doc.get("custom_finalized_on") or doc.get("transaction_date") or today())
	if expected_payment_date:
		date = getdate(expected_payment_date)
		days = date_diff(date, base)
	elif cint(credit_days) > 0:
		days = cint(credit_days)
		date = add_days(base, days)
	else:
		frappe.throw(_(M_CREDIT_DATE), title=_("Credit"))
	doc.custom_credit_days = days
	doc.custom_expected_payment_date = date


# ----------------------------------------------------------------------------- actions


def _load(name):
	doc = Q.get(name)
	Q.assert_actor()
	recompute(doc)
	return doc


def _assert_open(doc, entry=False):
	"""Payment structure and entries: Finalized / Sales Order Created, not Force Completed, not
	Cancelled (19, 21.2, 15.5)."""
	status = Q.status_of(doc)
	if status == Q.CANCELLED or doc.docstatus == 2:
		frappe.throw(_(M_CANCELLED_PAYMENT if entry else Q.M_CANCELLED_READ_ONLY), title=_("Not Permitted"))
	if cint(doc.get("custom_force_complete_applied")):
		frappe.throw(_(M_FC_PAYMENT if entry else Q.M_FC_READ_ONLY), title=_("Not Permitted"))
	if status not in Q.OPEN or doc.docstatus != 1:
		frappe.throw(_(Q.M_NO_DRAFT_PAYMENT if entry else M_NOT_FINALIZED), title=_("Not Permitted"))


def _reason(reason, message=None):
	reason = cstr(reason).strip()
	if not reason:
		frappe.throw(_(message or Q.M_REASON), title=_("Reason Required"))
	return reason


def _schedule_row(doc, ref):
	ref = cstr(ref).strip()
	if not ref:
		return None
	for r in doc.get(SCHEDULE) or []:
		if r.row_key == ref or cstr(r.idx) == ref or r.name == ref:
			return r
	return None


def _received_date(value):
	if not value:
		frappe.throw(_(M_DATE_REQUIRED), title=_("Record Payment"))
	date = getdate(value)
	if date > getdate(today()):
		frappe.throw(_(M_DATE_FUTURE), title=_("Record Payment"))
	return date


def _attach_proof(name, url):
	"""The proof file belongs to the Quotation, so whoever reads the Quotation can open it."""
	file = frappe.db.get_value("File", {"file_url": url}, ["name", "attached_to_name"], as_dict=True)
	if file and not file.attached_to_name:
		frappe.db.set_value("File", file.name, {"attached_to_doctype": DOCTYPE, "attached_to_name": name}, update_modified=False)


def _result(doc):
	return {
		"total_received": doc.custom_total_received, "total_pending": doc.custom_total_pending,
		"payment_status": doc.custom_payment_status, "so_eligibility": doc.custom_so_eligibility,
		"payment_term": doc.custom_payment_term, "force_complete_applied": cint(doc.custom_force_complete_applied),
	}


@frappe.whitelist(methods=["POST"])
def record_payment(name, received_amount=None, received_date=None, payment_proof=None, reference_utr=None, remarks=None, schedule_row=None):
	"""Record Payment (10): amount above 0 and not above what is pending (the Quotation's, or the
	Partial row's), date not in the future, proof mandatory."""
	# company-scope: n/a (one Quotation, after its own read permission check)
	doc = _load(name)
	_assert_open(doc, entry=True)
	amount = flt(received_amount, 2)
	if amount <= 0:
		frappe.throw(_(M_AMOUNT_ZERO), title=_("Record Payment"))
	row = None
	if doc.get("custom_payment_term") == "Partial":
		row = _schedule_row(doc, schedule_row)
		if not row:
			frappe.throw(_(M_SELECT_ROW), title=_("Record Payment"))
		pending = flt(row.pending_amount, 2)
	else:
		pending = flt(doc.custom_total_pending, 2)
	if amount > pending + 0.004:
		frappe.throw(_(M_OVERPAY).format(fmt(max(pending, 0))), title=_("Record Payment"))
	if not cstr(payment_proof).strip():
		frappe.throw(_(M_PROOF), title=_("Record Payment"))
	date = _received_date(received_date)

	before = snapshot(doc)
	doc.append(RECEIPTS, {
		"received_amount": amount,
		"received_date": date,
		"payment_proof": cstr(payment_proof).strip(),
		"reference_utr": cstr(reference_utr).strip() or None,
		"remarks": cstr(remarks).strip() or None,
		"schedule_row_key": row.row_key if row else None,
		"schedule_row_no": cint(row.idx) if row else None,
		"payment_term": row.payment_term if row else doc.custom_payment_term,
		"submitted_by": frappe.session.user,
		"submitted_by_role": acting_role(),
		"submitted_on": now_datetime(),
	})
	recompute(doc)
	Q.save(doc, "record_payment")
	_attach_proof(doc.name, cstr(payment_proof).strip())
	detail = _("₹{0} received {1}; Proof {2}{3}{4}").format(
		fmt(amount), _date(date), cstr(payment_proof).strip(),
		_("; Reference {0}").format(reference_utr) if cstr(reference_utr).strip() else "",
		_("; Row {0} ({1})").format(row.idx, row.payment_term) if row else "",
	)
	audit.log(DOCTYPE, doc.name, "Payment Submitted", _("Received Amount"), "", detail, reason=cstr(remarks).strip() or None)
	log_derived(doc, before)
	return _result(doc)


def _apply_term(doc, term, credit_days=None, expected_payment_date=None, schedule=None):
	if term in ("Advance", "Credit"):
		if doc.get(SCHEDULE):
			# A-41: the rows go; each payment keeps its row number as it was, the old schedule is
			# in the trail (the caller logs it)
			for r in doc.get(RECEIPTS) or []:
				r.schedule_row_key = None
			doc.set(SCHEDULE, [])
		if term == "Credit":
			_set_credit_date(doc, credit_days, expected_payment_date)
	else:
		set_schedule(doc, _parse_rows(schedule), place_unrowed=True)
	doc.custom_payment_term = term


@frappe.whitelist(methods=["POST"])
def change_payment_term(name, payment_term=None, reason=None, credit_days=None, expected_payment_date=None, schedule=None):
	"""Change Payment Term after Finalize (9.2), with a mandatory reason; payments and proofs stay."""
	# company-scope: n/a (one Quotation, after its own read permission check)
	doc = _load(name)
	_assert_open(doc)
	reason = _reason(reason)
	if payment_term not in Q.TERMS:
		frappe.throw(_(M_TERM_REQUIRED), title=_("Payment Term"))
	old_term = doc.get("custom_payment_term")
	if payment_term == old_term:
		frappe.throw(_("The Payment Term is already {0}.").format(_(payment_term)), title=_("Payment Term"))
	before, old_config = snapshot(doc), config_summary(doc)
	_apply_term(doc, payment_term, credit_days, expected_payment_date, schedule)
	recompute(doc)
	Q.save(doc, "change_payment_term")
	_log_term_change(doc, "Payment Term Changed", old_term, old_config, reason)
	log_derived(doc, before)
	return _result(doc)


def _log_term_change(doc, action, old_term, old_config, reason):
	audit.log(DOCTYPE, doc.name, action, _("Payment Term"), old_term, doc.custom_payment_term, reason=reason)
	audit.log(
		DOCTYPE, doc.name, action, _("Payment Configuration"), old_config,
		_("{0}; Total Received ₹{1}, Total Pending ₹{2} at the change").format(
			config_summary(doc), fmt(doc.custom_total_received), fmt(doc.custom_total_pending)
		),
		reason=reason,
	)


@frappe.whitelist(methods=["POST"])
def convert_to_partial(name, reason=None, expected_payment_date=None, payment_term="Credit"):
	"""Convert to Partial (12.3, 14.3): the amount received so far becomes row 1 (the original
	term, fully received), the rest row 2 (Credit unless chosen otherwise), still tracked."""
	# company-scope: n/a (one Quotation, after its own read permission check)
	doc = _load(name)
	_assert_open(doc)
	term = doc.get("custom_payment_term")
	if term not in ("Advance", "Credit"):
		frappe.throw(_("Convert to Partial is for an Advance or Credit Quotation."), title=_("Convert to Partial"))
	if doc.get("custom_payment_status") != PARTIALLY:
		frappe.throw(_("Convert to Partial is for a Quotation whose payment is Partially Received."), title=_("Convert to Partial"))
	reason = _reason(reason)
	if not expected_payment_date:
		frappe.throw(_("Enter the Expected Payment Date of the remaining amount."), title=_("Convert to Partial"))
	receipts = doc.get(RECEIPTS) or []
	if term == "Credit" and doc.get("custom_expected_payment_date"):
		first_date = doc.custom_expected_payment_date
	else:
		first_date = max(getdate(r.received_date) for r in receipts)
	rows = [
		{"payment_term": term, "expected_payment_date": first_date, "expected_amount": doc.custom_total_received},
		{"payment_term": payment_term or "Credit", "expected_payment_date": expected_payment_date, "expected_amount": doc.custom_total_pending},
	]
	before, old_config = snapshot(doc), config_summary(doc)
	_apply_term(doc, "Partial", schedule=rows)
	recompute(doc)
	Q.save(doc, "convert_to_partial")
	_log_term_change(doc, "Converted to Partial", term, old_config, reason)
	log_derived(doc, before)
	return _result(doc)


@frappe.whitelist(methods=["POST"])
def change_expected_payment_date(name, reason=None, credit_days=None, expected_payment_date=None):
	"""Credit: change the Credit Days or the Expected Payment Date (9.4), with a reason; the next
	reminder run uses the new date."""
	# company-scope: n/a (one Quotation, after its own read permission check)
	doc = _load(name)
	_assert_open(doc)
	if doc.get("custom_payment_term") != "Credit":
		frappe.throw(
			_("Change Expected Payment Date is for a Credit Quotation. A Partial one's dates change in its Payment Schedule."),
			title=_("Expected Payment Date"),
		)
	reason = _reason(reason)
	old = doc.get("custom_expected_payment_date")
	_set_credit_date(doc, credit_days, expected_payment_date)
	if old and getdate(old) == getdate(doc.custom_expected_payment_date):
		frappe.throw(_("That is the current Expected Payment Date."), title=_("Expected Payment Date"))
	recompute(doc)
	Q.save(doc, "change_expected_payment_date")
	audit.log(DOCTYPE, doc.name, "Credit Date Changed", _("Expected Payment Date"), _date(old), _date(doc.custom_expected_payment_date), reason=reason)
	return _result(doc)


@frappe.whitelist(methods=["POST"])
def revise_schedule(name, schedule=None, reason=None):
	"""Revise Payment Schedule (14): rows still add up to the Grand Total, a row never drops below
	what it received, a row with payments is never removed; mandatory reason (A-11)."""
	# company-scope: n/a (one Quotation, after its own read permission check)
	doc = _load(name)
	_assert_open(doc)
	if doc.get("custom_payment_term") != "Partial":
		frappe.throw(_("Revise Payment Schedule is for a Partial Quotation."), title=_("Payment Schedule"))
	reason = _reason(reason)
	before, old_summary = snapshot(doc), schedule_summary(doc)
	date_changes = set_schedule(doc, _parse_rows(schedule))
	recompute(doc)
	Q.save(doc, "revise_schedule")
	audit.log(DOCTYPE, doc.name, "Payment Schedule Revised", _("Payment Schedule"), old_summary, schedule_summary(doc), reason=reason)
	for row_no, old, new in date_changes:
		audit.log(DOCTYPE, doc.name, "Expected Payment Date Changed", _("Row {0} Expected Payment Date").format(row_no), _date(old), _date(new), reason=reason)
	log_derived(doc, before)
	return _result(doc)


@frappe.whitelist(methods=["POST"])
def force_complete(name, reason=None):
	"""Force Complete (15): SO / SM / SA close the payment process for good while something is
	pending. Received stays what was received, the unpaid amount stays visible, the Payment
	Status follows the actual receipts, SO Eligibility is Allowed, the Quotation is read only."""
	# company-scope: n/a (one Quotation, after its own read permission check)
	doc = _load(name)
	_assert_open(doc)
	if flt(doc.custom_total_pending, 2) <= 0:
		frappe.throw(_(M_NOTHING_PENDING), title=_("Force Complete"))
	reason = _reason(reason, M_FC_REASON)
	before = snapshot(doc)
	unpaid = flt(doc.custom_total_pending, 2)
	doc.custom_force_complete_applied = 1
	doc.custom_force_complete_reason = reason
	doc.custom_force_completed_by = frappe.session.user
	doc.custom_force_completed_role = acting_role()
	doc.custom_force_completed_on = now_datetime()
	doc.custom_force_complete_unpaid = unpaid
	recompute(doc)
	Q.save(doc, "force_complete")
	audit.log(DOCTYPE, doc.name, "Force Complete", _("Force Complete"), "No", "Yes", reason=reason)
	audit.log(
		DOCTYPE, doc.name, "Force Complete", _("Payment at Force Complete"), "",
		_("Payment Term {0}; Grand Total ₹{1}; Total Received ₹{2}; Remaining Unpaid ₹{3}").format(
			doc.custom_payment_term or "", fmt(doc.grand_total), fmt(doc.custom_total_received), fmt(unpaid)
		),
		reason=reason,
	)
	log_derived(doc, before)
	return _result(doc)


@frappe.whitelist(methods=["POST"])
def correct_payment(name, receipt=None, reason=None, received_amount=None, received_date=None, payment_proof=None, reference_utr=None, remarks=None):
	"""System Manager correction of a submitted payment (19): mandatory reason, old and new values
	in the trail, still no overpayment. Allowed after Force Complete and Cancel (A-15)."""
	# company-scope: n/a (one Quotation, after its own read permission check)
	doc = Q.get(name)
	if not is_system_manager():
		frappe.throw(_(M_SYSTEM_MANAGER), frappe.PermissionError, title=_("Not Permitted"))
	recompute(doc)
	row = next((r for r in doc.get(RECEIPTS) or [] if r.name == receipt or cstr(r.idx) == cstr(receipt)), None)
	if not row:
		frappe.throw(_("Payment {0} is not on this Quotation.").format(receipt), title=_("Correct Payment"))
	reason = _reason(reason)
	changes = []
	if not Q._blank(received_amount) and not Q._same(received_amount, row.received_amount):
		amount = flt(received_amount, 2)
		if amount <= 0:
			frappe.throw(_(M_AMOUNT_ZERO), title=_("Correct Payment"))
		slot = _schedule_row(doc, row.schedule_row_key) if row.get("schedule_row_key") else None
		available = flt((slot.pending_amount if slot else doc.custom_total_pending), 2) + flt(row.received_amount, 2)
		if amount > available + 0.004:
			frappe.throw(_(M_OVERPAY).format(fmt(available)), title=_("Correct Payment"))
		changes.append(("received_amount", _("Received Amount"), fmt(row.received_amount), fmt(amount), amount))
	if not Q._blank(received_date) and getdate(received_date) != getdate(row.received_date):
		date = _received_date(received_date)
		changes.append(("received_date", _("Received Date"), _date(row.received_date), _date(date), date))
	if payment_proof is not None and cstr(payment_proof).strip() != cstr(row.payment_proof):
		if not cstr(payment_proof).strip():
			frappe.throw(_(M_PROOF), title=_("Correct Payment"))
		changes.append(("payment_proof", _("Payment Proof"), row.payment_proof, cstr(payment_proof).strip(), cstr(payment_proof).strip()))
	for field, label, value in (("reference_utr", _("UTR / Reference"), reference_utr), ("remarks", _("Remarks"), remarks)):
		if value is not None and cstr(value).strip() != cstr(row.get(field)):
			changes.append((field, label, row.get(field), cstr(value).strip(), cstr(value).strip() or None))
	if not changes:
		frappe.throw(_("Enter the corrected value."), title=_("Correct Payment"))

	before = snapshot(doc)
	for field, _label, _old, _new, value in changes:
		row.set(field, value)
	row.corrected = 1
	row.last_corrected_by = frappe.session.user
	row.last_corrected_on = now_datetime()
	recompute(doc)
	Q.save(doc, "correct_payment")
	if any(c[0] == "payment_proof" for c in changes):
		_attach_proof(doc.name, row.payment_proof)
	for _field, label, old, new, _value in changes:
		audit.log(
			DOCTYPE, doc.name, "System Manager Payment Correction", _("{0} (payment {1})").format(label, row.idx), old, new,
			reason=reason, role="System Manager",
		)
	log_derived(doc, before)
	return _result(doc)


def protect_proof_file(doc, method=None):
	"""File on_trash: a payment proof is part of a submitted payment (19)."""
	url = doc.get("file_url")
	if not url or is_system_manager() or not frappe.db.table_exists("Quotation Payment Receipt"):
		return
	if frappe.db.exists("Quotation Payment Receipt", {"payment_proof": url}):
		frappe.throw(_(M_SYSTEM_MANAGER), frappe.PermissionError, title=_("Not Permitted"))
