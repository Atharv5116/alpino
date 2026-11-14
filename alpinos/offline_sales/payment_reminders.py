"""Credit payment reminders (doc Section 5, "Credit Reminder & Overdue"; W6).

Every calendar day at 08:00 (weekends and holidays too) the system looks at every outstanding
Credit obligation of a Finalized / Sales Order Created Quotation:
  - a Credit Quotation: its Expected Payment Date and Total Pending;
  - a Partial Quotation: each Credit row of its Payment Schedule (Expected Payment Date and the
    row's Pending Amount). Advance obligations never get reminders.
Due Today: Expected Payment Date is today and something is pending.
Overdue: the date has passed and something is pending; sent every 3 calendar days (day 3, 6, 9 ...).
Recipients: the Quotation's Responsible Sales Officer, the Sales Manager who finalized it and the
buyer's Secondary POC (Sales Admin), not everyone assigned to the buyer. In-app + email, with the
amount outstanding NOW. Stops when nothing is pending, the Quotation is Cancelled or Force
Complete has been applied. A revised Expected Payment Date counts from the next run.
Each reminder is written to the Quotation's Activity trail, which also keeps it to once a day.
"""

import frappe
from frappe import _
from frappe.utils import cint, date_diff, flt, fmt_money, formatdate, getdate, today

from alpinos.offline_sales import audit

ACTION = "Reminder Sent"
DUE_TODAY, OVERDUE = "Payment Due Today", "Payment Overdue"
OPEN_STATUSES = ("Finalized", "Sales Order Created")


def _fields_ready():
	return all(
		frappe.db.has_column("Quotation", f)
		for f in ("custom_quotation_status", "custom_payment_term", "custom_force_complete_applied", "custom_total_pending")
	)


def obligations():
	"""[(quotation, schedule row or None, expected date, pending)] for every outstanding Credit obligation."""
	if not _fields_ready():
		return []
	# company-scope: n/a (system job over every company's Quotations; recipients are named users)
	quotations = frappe.get_all(
		"Quotation",
		filters={
			"docstatus": 1,
			"custom_quotation_status": ("in", OPEN_STATUSES),
			"custom_force_complete_applied": 0,
			"custom_payment_term": ("in", ["Credit", "Partial"]),
		},
		fields=["name", "customer_name", "party_name", "custom_payment_term", "custom_expected_payment_date", "custom_total_pending"],
	)
	out = []
	for q in quotations:
		if q.custom_payment_term == "Credit":
			if q.custom_expected_payment_date and flt(q.custom_total_pending) > 0:
				out.append((q, None, getdate(q.custom_expected_payment_date), flt(q.custom_total_pending)))
			continue
		for row in frappe.get_all(
			"Quotation Payment Schedule",
			filters={"parent": q.name, "parenttype": "Quotation", "payment_term": "Credit"},
			fields=["idx", "row_key", "expected_payment_date", "pending_amount"],
			order_by="idx",
		):
			if row.expected_payment_date and flt(row.pending_amount) > 0:
				out.append((q, row, getdate(row.expected_payment_date), flt(row.pending_amount)))
	return out


def kind_for(expected, on_date):
	"""Due Today, Overdue (with days) on day 3, 6, 9 ..., else None."""
	days = date_diff(on_date, expected)
	if days == 0:
		return DUE_TODAY, 0
	if days > 0 and days % 3 == 0:
		return OVERDUE, days
	return None, days


def _user_of(value):
	"""A User from a User or Employee link value."""
	if not value:
		return None
	if frappe.db.exists("User", value):
		return value
	return frappe.db.get_value("Employee", value, "user_id")


def recipients(quotation):
	"""Responsible Sales Officer, the finalizing Sales Manager, and the buyer's Secondary POC."""
	values = frappe.db.get_value(
		"Quotation", quotation,
		["custom_responsible_sales_officer", "custom_finalized_by", "custom_buyer_master", "party_name", "quotation_to"],
		as_dict=True,
	) or {}
	buyer = values.get("custom_buyer_master") or (values.get("party_name") if values.get("quotation_to") == "Buyer Master" else None)
	users = [
		_user_of(values.get("custom_responsible_sales_officer")),
		_user_of(values.get("custom_finalized_by")),
		_user_of(frappe.db.get_value("Buyer Master", buyer, "secondary_poc") if buyer else None),
	]
	enabled = set(frappe.get_all("User", filters={"name": ("in", [u for u in users if u]), "enabled": 1}, pluck="name"))
	seen, out = set(), []
	for u in users:
		if u and u in enabled and u not in seen:
			seen.add(u)
			out.append(u)
	return out


def message(kind, q, row, pending, expected, days):
	where = f"Credit, Row {row.idx}" if row else "Credit"
	amount = fmt_money(pending, currency="INR")
	head = DUE_TODAY if kind == DUE_TODAY else _("Payment Overdue by {0} days").format(days)
	return _("{0}: Quotation {1} for {2}, {3} outstanding ({4}, due {5}).").format(
		head, q.name, q.customer_name or q.party_name, amount, where, formatdate(expected, "dd-MM-yyyy")
	)


def _key(kind, row, on_date):
	return f"{kind} | {'Row ' + str(row.idx) if row else 'Credit'} | {on_date}"


def _already_sent(quotation, key):
	return frappe.db.exists(
		"Field Change Log",
		{"reference_doctype": "Quotation", "reference_name": quotation, "action": ACTION, "field_label": key},
	)


def plan(on_date=None):
	"""The reminders due on `on_date` (default today): [{quotation, kind, row, pending, expected, days, users, text}]."""
	on_date = getdate(on_date or today())
	out = []
	for q, row, expected, pending in obligations():
		kind, days = kind_for(expected, on_date)
		if not kind:
			continue
		out.append(frappe._dict(
			quotation=q.name, kind=kind, row=row.idx if row else None, pending=pending, expected=str(expected), days=days,
			users=recipients(q.name), text=message(kind, q, row, pending, expected, days), key=_key(kind, row, on_date),
		))
	return out


def run(on_date=None):
	"""Daily 08:00 job: send what plan() finds, once per obligation per day."""
	from alpinos.production.notify import notify

	sent = []
	for r in plan(on_date):
		if _already_sent(r.quotation, r.key):
			continue
		if r.users:
			notify([], r.text, doctype="Quotation", name=r.quotation, email=True, users=r.users)
		audit.log("Quotation", r.quotation, ACTION, r.key, None, ", ".join(r.users) or "no recipient",
			reason=r.text)
		sent.append(r)
	return sent


@frappe.whitelist()
def dry_run(on_date=None):
	"""What the 08:00 job would send on a date, without sending anything (System Manager)."""
	frappe.only_for(("System Manager",))
	return plan(on_date)
