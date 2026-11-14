"""W8 Lists & Dashboards (doc Section 8). TEST sites only; everything is rolled back.

Run:  ../env/bin/python ~/alpinos-wt/mrp_work/run.py <site> alpinos.offline_sales.dashboard_test.run
"""

import frappe
from frappe.utils import add_days, getdate, today

from alpinos.offline_sales import accounts_view as A
from alpinos.offline_sales import dashboard as D

R = []
TAG = "DBT" + frappe.generate_hash(length=4).upper()
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


def _user(suffix, *roles):
	user = f"{TAG.lower()}.{suffix}@example.com"
	_insert("User", name=user, email=user, first_name=f"{TAG} {suffix}", user_type="System User", enabled=1)
	for i, role in enumerate(roles):
		_insert("Has Role", name=f"{TAG}-HR-{suffix}-{i}", parent=user, parenttype="User", parentfield="roles", role=role)
	return user


def as_(user, fn):
	frappe.set_user(user)
	frappe.local.role_permissions = {}
	try:
		return fn()
	finally:
		frappe.set_user("Administrator")
		frappe.local.role_permissions = {}


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


def _keys(user):
	return {c["key"]: c for c in as_(user, lambda: D.get_dashboard())["cards"]}


def _run():
	company = frappe.defaults.get_global_default("company")
	F.sm = _user("sm", "Sales Manager", "Employee")
	F.so = _user("so", "Sales Officer", "Employee")
	F.acc = _user("acc", "Accounts User")
	from alpinos.company_scope import sync

	for u, roles in ((F.sm, ["Sales Manager"]), (F.so, ["Sales Officer"])):
		sync.ensure_membership(u, company, roles, is_default=True)
		sync.sync_user(u)
	have_q = frappe.db.has_column("Quotation", "custom_quotation_status")

	def _roles():
		sm, so = _keys(F.sm), _keys(F.so)
		_assert({"K1", "K2", "K3", "K4", "K11"} <= set(sm), sorted(sm))
		_assert(not {"K1", "K2", "K10"} & set(so) and {"K3", "K4", "K11"} <= set(so), sorted(so))
		if have_q:
			_assert({"K5", "K6", "K7", "K8", "K9", "K10"} <= set(sm) and {"K5", "K6", "K7", "K8", "K9"} <= set(so), (sorted(sm), sorted(so)))
		err = ""
		try:
			as_(F.acc, lambda: D.get_dashboard())
		except frappe.PermissionError as e:
			err = str(e) or "PermissionError"
		_assert(err, "Accounts User got the sales dashboard")

	check("S8: each role sees the cards the doc gives it (Buyer cards SM/SA only; Force Complete SM/SA)", _roles)

	def _counts_match_lists():
		sm = _keys(F.sm)
		pending = as_(F.sm, lambda: len(frappe.get_list("Buyer Master", filters={"buyer_status": "Pending Approval", "channel": ("!=", "E-com")},
			pluck="name", limit_page_length=0)))
		_assert(sm["K1"]["count"] == pending, (sm["K1"]["count"], pending))
		drafts = as_(F.sm, lambda: len(frappe.get_list("Opportunity", filters={"custom_opportunity_status": "Pending (Draft)"}, pluck="name",
			limit_page_length=0)))
		_assert(sm["K3"]["count"] == drafts, (sm["K3"]["count"], drafts))
		_assert(sm["K1"]["link"] == {"doctype": "Buyer Master", "filters": {"buyer_status": "Pending Approval"}}, sm["K1"]["link"])

	check("S8: card counts equal what the user's own filtered list shows; a card opens that list", _counts_match_lists)

	def _late_approvals():
		bm = frappe.db.get_value("Buyer Master", {"buyer_status": "Approved", "channel": ("!=", "E-com")}, "name")
		before = _keys(F.sm)["K2"]["count"]
		frappe.db.set_value("Buyer Master", bm, "buyer_status", "Pending Approval")
		frappe.db.sql("update `tabBuyer Master` set creation = %s where name = %s", (add_days(today(), -3), bm))
		_assert(_keys(F.sm)["K2"]["count"] == before + 1, "a buyer pending for 3 days is not in Buyer Approvals > 48h")

	check("S8: Buyer Approvals > 48h counts buyers pending longer than the escalation hours", _late_approvals)

	def _payment_columns():
		so = frappe.db.get_value("Sales Order", {"docstatus": 1}, "name")
		cols = A.payment_columns([so])
		_assert(so in cols and not cols[so]["has_quotation"] and cols[so]["payment_proof_count"] == 0, cols)

	check("S8: an order without a Quotation shows no Payment Status and No Files", _payment_columns)

	if not have_q:
		R.append(("ERR ", "S8: Quotation cards, queues and proofs (need the W5 fields)", "W5 fields missing"))
		return
	_with_quotations()


def _with_quotations():
	buyer = frappe.db.get_value("Buyer Master", {"buyer_status": "Approved"}, ["name", "customer"], as_dict=True)
	company = frappe.defaults.get_global_default("company")
	day = getdate(today())

	def q(name, **kw):
		values = dict(name=f"{TAG}-{name}", quotation_to="Buyer Master", party_name=buyer.name, customer_name="Buyer X", company=company,
			transaction_date=today(), docstatus=1, custom_buyer_master=buyer.name, custom_quotation_status="Finalized",
			custom_payment_term="Credit", custom_total_pending=1000, custom_force_complete_applied=0, custom_payment_status="Pending",
			grand_total=1000)
		values.update(kw)
		return _insert("Quotation", **values)

	F.due = q("DUE", custom_expected_payment_date=day)
	F.over = q("OVER", custom_expected_payment_date=add_days(day, -1))
	F.fc = q("FC", custom_expected_payment_date=day, custom_force_complete_applied=1)

	def _queues():
		from alpinos.alpinos_development.report.offline_payment_follow_up import offline_payment_follow_up as rep

		_c, due = rep.execute({"queue": "Due Today"})
		_c, over = rep.execute({"queue": "Overdue"})
		_assert(F.due in {r["quotation"] for r in due} and F.fc not in {r["quotation"] for r in due}, due)
		_assert(F.over in {r["quotation"] for r in over} and any(r["days"] == 1 for r in over if r["quotation"] == F.over), over)
		sm = _keys(F.sm)
		_assert(sm["K8"]["count"] >= 1 and sm["K9"]["count"] >= 1 and sm["K10"]["count"] >= 1, {k: sm[k]["count"] for k in ("K8", "K9", "K10")})

	check("S8: Due Today / Overdue queues use the current pending amount; Force Completed stays out", _queues)

	def _proofs():
		so = frappe.db.get_value("Sales Order", {"docstatus": 1}, "name")
		frappe.db.set_value("Sales Order", so, "custom_quotation", F.due)
		f = frappe.get_doc({"doctype": "File", "file_name": f"{TAG}.png", "is_private": 1, "content": b"\x89PNG\r\n\x1a\n" + b"0" * 32,
			"attached_to_doctype": "Quotation", "attached_to_name": F.due})
		f.insert(ignore_permissions=True)
		for i in (1, 2):
			_insert("Quotation Payment Receipt", name=f"{TAG}-R{i}", parent=F.due, parenttype="Quotation", parentfield="custom_payment_receipts",
				idx=i, received_amount=100, received_date=today(), payment_proof=f.file_url, payment_term="Credit")
		cols = A.payment_columns([so])
		_assert(cols[so]["payment_status"] == "Pending" and cols[so]["payment_proof_count"] == 2, cols)
		files = as_(F.acc, lambda: A.so_payment_proofs(so))["files"]
		_assert(len(files) == 2 and files[0]["kind"] == "image", files)

	check("S8: Accounts sees the linked Quotation's Payment Status and its proofs (View Files (2))", _proofs)
