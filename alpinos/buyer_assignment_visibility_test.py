"""Buyer assignment decides what a Sales Officer sees.

Run:  bench --site alpinos.test execute alpinos.buyer_assignment_visibility_test.run

Buyer Master & Sales Order - Required Changes (03-10-2026) sections 5, 14 and 15. The case
the document singles out is the last one here: Manager A raises the Sales Order, Rahul the
Sales Officer must still see it, because the scope is the Buyer and not who typed it.

frappe.get_list applies the permission hooks; frappe.get_all deliberately does not, so every
check below goes through get_list. Fixtures are rolled back at the end.
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
		frappe.clear_cache()
		frappe.set_user("Administrator")

	width = max(len(r[1]) for r in RES)
	for status, label, detail in RES:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in RES if r[0] == 'PASS')}/{len(RES)} passed")
	return RES


def _run():
	from alpinos import buyer_assignment as BA
	from alpinos import buyer_assignment_visibility as V

	tag = "BAV" + frappe.generate_hash(length=5).upper()
	company = frappe.defaults.get_global_default("company")

	def _person(suffix, *roles):
		user = f"{tag.lower()}.{suffix}@example.com"
		_insert("User", name=user, email=user, first_name=suffix.title(),
			user_type="System User", enabled=1)
		for i, role in enumerate(roles):
			_insert("Has Role", name=f"{tag}-HR-{suffix}-{i}", parent=user, parenttype="User",
				parentfield="roles", role=role)
		emp = _insert("Employee", name=f"{tag}-{suffix.upper()}",
			employee_name=f"{tag} {suffix.title()}", status="Active", company=company,
			date_of_joining="2026-01-01", user_id=user)
		return emp, user

	# Rahul is assigned to Buyer ABC; Amit is assigned to Buyer XYZ. Manager A runs both.
	rahul, rahul_user = _person("rahul", BA.SALES_OFFICER_ROLE)
	amit, amit_user = _person("amit", BA.SALES_OFFICER_ROLE)
	manager, manager_user = _person("manager", BA.SALES_MANAGER_ROLE)

	abc = _insert("Buyer Master", name=f"{tag}-OBM-ABC",
		customer_business_name=f"{tag} ABC Retail", channel="Offline")
	xyz = _insert("Buyer Master", name=f"{tag}-OBM-XYZ",
		customer_business_name=f"{tag} XYZ Traders", channel="Offline")
	_insert("Buyer Sales Officer", name=f"{tag}-BSO-1", parent=abc, parenttype="Buyer Master",
		parentfield="sales_officers", employee=rahul, idx=1)
	_insert("Buyer Sales Officer", name=f"{tag}-BSO-2", parent=xyz, parenttype="Buyer Master",
		parentfield="sales_officers", employee=amit, idx=1)
	_insert("Buyer Primary POC", name=f"{tag}-BPP-1", parent=abc, parenttype="Buyer Master",
		parentfield="primary_pocs", employee=manager, idx=1)

	# Manager A raises the order on Buyer ABC -- Rahul did not create it.
	so_abc = _insert("Sales Order", name=f"{tag}-SOR-ABC", customer="__Test Customer",
		company=company, transaction_date="2026-10-03", docstatus=0,
		custom_offline_buyer_master=abc, owner=manager_user)
	so_xyz = _insert("Sales Order", name=f"{tag}-SOR-XYZ", customer="__Test Customer",
		company=company, transaction_date="2026-10-03", docstatus=0,
		custom_offline_buyer_master=xyz, owner=manager_user)

	def _as(user, doctype, **kw):
		frappe.set_user(user)
		try:
			return {r.name for r in frappe.get_list(
				doctype, filters=[["name", "like", f"{tag}%"]], fields=["name"],
				limit_page_length=0, ignore_ifnull=True, **kw)}
		finally:
			frappe.set_user("Administrator")

	def _a_sales_officer_is_scoped_but_a_manager_is_not():
		_assert(V.is_assignment_scoped(rahul_user), "the Sales Officer is not scoped")
		_assert(not V.is_assignment_scoped(manager_user),
			"a Sales Manager was narrowed; only Sales Officers are")

	check("only a Sales Officer is narrowed to their assigned Buyers",
		_a_sales_officer_is_scoped_but_a_manager_is_not)

	def _rahul_sees_only_his_buyer():
		seen = _as(rahul_user, "Buyer Master")
		_assert(abc in seen, f"Rahul cannot see the Buyer he is assigned to: {seen}")
		_assert(xyz not in seen, f"Rahul can see an unrelated Buyer: {seen}")

	check("a Sales Officer sees the Buyers they are assigned to and no others",
		_rahul_sees_only_his_buyer)

	def _amit_sees_the_other_buyer():
		seen = _as(amit_user, "Buyer Master")
		_assert(xyz in seen and abc not in seen,
			f"Amit's Buyer scope is wrong: {seen}")

	check("a second Sales Officer sees their own Buyer, not the first one's",
		_amit_sees_the_other_buyer)

	def _the_manager_is_not_narrowed():
		seen = _as(manager_user, "Buyer Master")
		_assert({abc, xyz} <= seen, f"the Sales Manager lost Buyers: {seen}")

	check("a Sales Manager keeps the scope they had", _the_manager_is_not_narrowed)

	def _rahul_sees_the_order_a_manager_created():
		"""The document's own example: Manager A creates it, Rahul must still reach it."""
		seen = _as(rahul_user, "Sales Order")
		_assert(so_abc in seen,
			f"Rahul cannot see his Buyer's order because somebody else created it: {seen}")
		_assert(so_xyz not in seen, f"Rahul can see an unrelated Buyer's order: {seen}")

	check("a Sales Officer sees their Buyer's order even when another user created it",
		_rahul_sees_the_order_a_manager_created)

	def _unassigning_removes_the_buyer_and_its_orders():
		frappe.db.delete("Buyer Sales Officer", {"name": f"{tag}-BSO-1"})
		try:
			buyers = _as(rahul_user, "Buyer Master")
			orders = _as(rahul_user, "Sales Order")
			_assert(abc not in buyers, f"the Buyer survived the unassignment: {buyers}")
			_assert(so_abc not in orders,
				f"the order survived the unassignment: {orders}")
		finally:
			_insert("Buyer Sales Officer", name=f"{tag}-BSO-1", parent=abc,
				parenttype="Buyer Master", parentfield="sales_officers", employee=rahul, idx=1)

	check("unassigning a Sales Officer removes the Buyer and its orders from their view",
		_unassigning_removes_the_buyer_and_its_orders)

	def _a_poc_assignment_also_grants_the_buyer():
		"""Section 5 makes all three fields access control, not only Sales Officer(s)."""
		names = V._assigned_buyer_names(manager)
		_assert(abc in names, f"the Primary POC assignment granted nothing: {names}")

	check("a Primary POC assignment grants the Buyer too",
		_a_poc_assignment_also_grants_the_buyer)

	def _an_officer_without_an_employee_record_sees_nothing():
		user = f"{tag.lower()}.ghost@example.com"
		_insert("User", name=user, email=user, first_name="Ghost",
			user_type="System User", enabled=1)
		_insert("Has Role", name=f"{tag}-HR-ghost", parent=user, parenttype="User",
			parentfield="roles", role=BA.SALES_OFFICER_ROLE)
		cond = V.buyer_master_query_conditions(user)
		_assert(cond == "1 = 0", f"condition {cond!r}: this must deny, never fall open")
		_assert(not _as(user, "Buyer Master"), "a Sales Officer with no Employee saw Buyers")

	check("a Sales Officer with no Employee record is denied, not handed everything",
		_an_officer_without_an_employee_record_sees_nothing)

	def _explain_reports_the_scope():
		out = V.explain(rahul_user)
		_assert(out["assignment_scoped"] is True, out)
		_assert(abc in (out["assigned_buyers"] or []), out)

	check("explain() reports a user's scope and the Buyers behind it", _explain_reports_the_scope)
