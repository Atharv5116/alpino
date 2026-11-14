"""W6 Credit payment reminders (doc Section 5). TEST sites only; everything is rolled back.

Run:  ../env/bin/python ~/alpinos-wt/mrp_work/run.py <site> alpinos.offline_sales.payment_reminders_test.run
"""

import frappe
from frappe.utils import add_days, getdate, today

from alpinos.offline_sales import payment_reminders as P

R = []
TAG = "PRT" + frappe.generate_hash(length=4).upper()
F = frappe._dict()


def check(label, fn):
	try:
		fn()
		R.append(("PASS", label, ""))
	except AssertionError as e:
		R.append(("FAIL", label, str(e)))
	except Exception as e:
		R.append(("ERR ", label, f"{type(e).__name__}: {e}"))


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
	R.clear()
	frappe.set_user("Administrator")
	real_commit = frappe.db.commit
	frappe.db.commit = lambda *a, **k: None
	try:
		_run()
	finally:
		frappe.db.commit = real_commit
		frappe.db.rollback()
		frappe.clear_cache()
		frappe.set_user("Administrator")
	width = max(len(r[1]) for r in R) if R else 10
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)} {detail}")
	print(f"{sum(1 for r in R if r[0] == 'PASS')}/{len(R)} passed")


def _run():
	def _cadence():
		d = getdate("2026-11-10")
		expect = {0: P.DUE_TODAY, 1: None, 2: None, 3: P.OVERDUE, 4: None, 5: None, 6: P.OVERDUE, 9: P.OVERDUE, -1: None}
		for days, kind in expect.items():
			got, _d = P.kind_for(d, add_days(d, days))
			_assert(got == kind, f"day {days}: {got}")

	check("W6: Due Today on the date; Overdue every 3 calendar days (3, 6, 9); nothing before the date", _cadence)

	if not P._fields_ready():
		R.append(("ERR ", "W6: reminders on real Quotations (needs the W5 payment fields)", "W5 fields missing"))
		return
	_quotations()


def _user(suffix, *roles):
	user = f"{TAG.lower()}.{suffix}@example.com"
	_insert("User", name=user, email=user, first_name=f"{TAG} {suffix}", user_type="System User", enabled=1)
	for i, role in enumerate(roles):
		_insert("Has Role", name=f"{TAG}-HR-{suffix}-{i}", parent=user, parenttype="User", parentfield="roles", role=role)
	return user


def _quotations():
	F.so = _user("so", "Sales Officer")
	F.sm = _user("sm", "Sales Manager")
	F.sa = _user("sa", "Sales Admin")
	F.other = _user("other", "Sales Officer")
	sa_emp = _insert("Employee", name=f"{TAG}-SA", employee_name=f"{TAG} sa", first_name="sa", status="Active",
		company=frappe.defaults.get_global_default("company"), date_of_joining="2026-01-01", user_id=F.sa)
	buyer = frappe.db.get_value("Buyer Master", {"buyer_status": "Approved"}, ["name", "customer"], as_dict=True)
	frappe.db.set_value("Buyer Master", buyer.name, "secondary_poc", sa_emp)
	day = getdate(today())

	def quotation(name, term, epd=None, pending=1000, status="Finalized", fc=0):
		return _insert("Quotation", name=f"{TAG}-{name}", quotation_to="Buyer Master", party_name=buyer.name, customer_name="Buyer X",
			company=frappe.defaults.get_global_default("company"), transaction_date=today(), docstatus=1,
			custom_buyer_master=buyer.name, custom_quotation_status=status, custom_payment_term=term,
			custom_expected_payment_date=epd, custom_total_pending=pending, custom_force_complete_applied=fc,
			custom_responsible_sales_officer=F.so, custom_finalized_by=F.sm)

	F.due = quotation("DUE", "Credit", day, 5000)
	F.over3 = quotation("OVER3", "Credit", add_days(day, -3), 2000)
	F.over4 = quotation("OVER4", "Credit", add_days(day, -4), 2000)
	F.paid = quotation("PAID", "Credit", day, 0)
	F.cancel = quotation("CANCEL", "Credit", day, 900, status="Cancelled")
	F.fc = quotation("FC", "Credit", day, 900, fc=1)
	F.adv = quotation("ADV", "Advance", day, 900)
	F.part = quotation("PART", "Partial", None, 3000)
	_insert("Quotation Payment Schedule", name=f"{TAG}-S1", parent=F.part, parenttype="Quotation", parentfield="custom_payment_schedule",
		idx=1, row_key="r1", payment_term="Advance", expected_payment_date=day, expected_amount=1000, pending_amount=1000)
	_insert("Quotation Payment Schedule", name=f"{TAG}-S2", parent=F.part, parenttype="Quotation", parentfield="custom_payment_schedule",
		idx=2, row_key="r2", payment_term="Credit", expected_payment_date=day, expected_amount=2000, pending_amount=1500)
	plan = {(r.quotation, r.row): r for r in P.plan()}

	def _scope():
		_assert((F.due, None) in plan and plan[(F.due, None)].kind == P.DUE_TODAY, "Credit due today")
		_assert((F.over3, None) in plan and plan[(F.over3, None)].kind == P.OVERDUE and plan[(F.over3, None)].days == 3, "overdue day 3")
		_assert((F.over4, None) not in plan, "overdue day 4 must wait for day 6")
		for q in (F.paid, F.cancel, F.fc, F.adv):
			_assert(not any(k[0] == q for k in plan), f"{q} got a reminder")
		_assert((F.part, 2) in plan and (F.part, 1) not in plan, "Partial: only the Credit row")

	check("W6: Credit due / overdue only; none when paid, Cancelled, Force Completed or Advance; Partial Credit rows", _scope)

	def _amount_and_text():
		r = plan[(F.part, 2)]
		_assert(r.pending == 1500 and "1,500" in r.text and "Row 2" in r.text and r.text.startswith("Payment Due Today"), r.text)
		_assert(plan[(F.over3, None)].text.startswith("Payment Overdue by 3 days"), plan[(F.over3, None)].text)

	check("W6: the reminder shows the amount outstanding now, the row and the due date", _amount_and_text)

	def _recipients():
		users = plan[(F.due, None)].users
		_assert(set(users) == {F.so, F.sm, F.sa}, users)

	check("W6: recipients = Responsible Sales Officer, finalizing Sales Manager, Secondary POC (no one else)", _recipients)

	def _send_once():
		real = frappe.get_attr("alpinos.production.notify.notify")
		calls = []
		import alpinos.production.notify as N

		N.notify = lambda *a, **k: calls.append(k) or k.get("users")
		try:
			first = P.run()
			second = P.run()
		finally:
			N.notify = real
		_assert(len(first) == len(plan) and not second, f"{len(first)} then {len(second)}")
		_assert(all(c.get("email") for c in calls), "email not requested")
		trail = frappe.get_all("Field Change Log", filters={"reference_doctype": "Quotation", "reference_name": F.due, "action": P.ACTION}, pluck="reason")
		_assert(trail and trail[0].startswith("Payment Due Today"), trail)

	check("W6: in-app + email once per obligation per day, recorded in the Quotation's trail", _send_once)

	def _revised_date():
		frappe.db.set_value("Quotation", F.over4, "custom_expected_payment_date", add_days(day, -6))
		_assert(any(r.quotation == F.over4 and r.days == 6 for r in P.plan()), "revised date not used at once")

	check("W6: a revised Expected Payment Date counts from the next run", _revised_date)

	def _dry_run():
		before = frappe.db.count("Notification Log")
		got = P.dry_run()
		_assert(got and frappe.db.count("Notification Log") == before, "dry run sent something")

	check("W6: dry run lists what would be sent and sends nothing", _dry_run)
