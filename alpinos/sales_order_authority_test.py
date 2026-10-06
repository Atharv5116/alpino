"""Sections 6-11: who may create, edit and submit a Sales Order.

Run:  bench --site alpinos.test execute alpinos.sales_order_authority_test.run

From "Buyer Master & Sales Order - Required Changes" (03-10-2026). Its permission matrix
gives the Sales Officer everything on a Draft and withholds exactly one thing:

    Submit Sales Order    Sales Officer  X    Primary POC  OK    Secondary POC  OK

This reverses the approved BRD, which refused Sales Officers creation outright; the 03-10
document supersedes it. Fixtures roll back.
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
		frappe.clear_cache()
		frappe.set_user("Administrator")

	width = max(len(r[1]) for r in RES)
	for status, label, detail in RES:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in RES if r[0] == 'PASS')}/{len(RES)} passed")
	return RES


def _run():
	from alpinos import buyer_assignment as BA
	from alpinos import sales_order_authority as A

	tag = "SOA" + frappe.generate_hash(length=4).upper()
	company = frappe.defaults.get_global_default("company")

	def _person(suffix, role):
		user = f"{tag.lower()}.{suffix}@example.com"
		_insert("User", name=user, email=user, first_name=suffix.title(),
			user_type="System User", enabled=1)
		_insert("Has Role", name=f"{tag}-HR-{suffix}", parent=user, parenttype="User",
			parentfield="roles", role=role)
		emp = _insert("Employee", name=f"{tag}-{suffix.upper()}",
			employee_name=f"{tag} {suffix.title()}", status="Active", company=company,
			date_of_joining="2026-01-01", user_id=user)
		return emp, user

	officer, officer_user = _person("officer", BA.SALES_OFFICER_ROLE)
	primary, primary_user = _person("primary", BA.SALES_MANAGER_ROLE)
	secondary, secondary_user = _person("secondary", BA.SALES_ADMIN_ROLE)
	# A second officer, assigned to nothing, to prove authority is per Buyer.
	stranger, stranger_user = _person("stranger", BA.SALES_OFFICER_ROLE)

	buyer = _insert("Buyer Master", name=f"{tag}-OBM", customer_business_name=f"{tag} Party",
		channel="Offline", secondary_poc=secondary)
	_insert("Buyer Sales Officer", name=f"{tag}-BSO", parent=buyer, parenttype="Buyer Master",
		parentfield="sales_officers", employee=officer, idx=1)
	_insert("Buyer Primary POC", name=f"{tag}-BPP", parent=buyer, parenttype="Buyer Master",
		parentfield="primary_pocs", employee=primary, idx=1)

	so = _insert("Sales Order", name=f"SOA-{tag}", docstatus=0, company=company,
		customer="__Test Customer", customer_name="__Test Customer",
		transaction_date=today(), custom_offline_buyer_master=buyer,
		custom_workflow_status="Draft")

	def _the_role_may_create_and_edit_but_not_submit():
		perms = frappe.db.get_value(
			"Custom DocPerm",
			{"parent": "Sales Order", "role": BA.SALES_OFFICER_ROLE, "permlevel": 0},
			["`read`", "`write`", "`create`", "`submit`"], as_dict=True,
		)
		_assert(perms, "the Sales Officer role has no Sales Order permission row")
		_assert(perms["read"] and perms["write"] and perms["create"],
			f"a Sales Officer cannot build an order: {perms}")
		_assert(not perms["submit"],
			"the Sales Officer role carries submit; section 7 withholds exactly that")

	check("§7 the Sales Officer role may create and edit, and only submit is withheld",
		_the_role_may_create_and_edit_but_not_submit)

	def _the_officer_is_refused_submission_with_a_reason():
		allowed, reason = A.may_submit(so, officer_user)
		_assert(not allowed, "a Sales Officer was allowed to submit")
		_assert("Primary POC" in reason or "Secondary POC" in reason,
			f"the refusal does not say who does submit it: {reason!r}")

	check("§11 a Sales Officer is refused submission, and told who signs it off",
		_the_officer_is_refused_submission_with_a_reason)

	def _the_primary_poc_may_submit():
		allowed, _r = A.may_submit(so, primary_user)
		_assert(allowed, "the Buyer's Primary POC was refused")

	check("§11 the Buyer's Primary POC may submit", _the_primary_poc_may_submit)

	def _the_secondary_poc_may_submit():
		allowed, _r = A.may_submit(so, secondary_user)
		_assert(allowed, "the Buyer's Secondary POC was refused")

	check("§11 the Buyer's Secondary POC may submit", _the_secondary_poc_may_submit)

	def _authority_follows_the_buyer_not_the_role():
		"""An officer of another Buyer has no say here."""
		allowed, _r = A.may_submit(so, stranger_user)
		_assert(not allowed, "an officer assigned to another Buyer could submit")
		_assert(not A.is_poc_for_buyer(buyer, officer_user),
			"the Sales Officer was read as a POC")
		_assert(A.is_poc_for_buyer(buyer, primary_user), "the Primary POC was not recognised")

	check("§11 submission authority follows the Buyer, not the role alone",
		_authority_follows_the_buyer_not_the_role)

	def _the_server_path_refuses_not_just_the_button():
		from alpinos.workflow_engine import submit_sales_order

		frappe.set_user(officer_user)
		try:
			submit_sales_order(so)
		except frappe.PermissionError:
			return
		except Exception as e:
			raise AssertionError(f"refused, but with the wrong error: {type(e).__name__}: {e}")
		finally:
			frappe.set_user("Administrator")
		raise AssertionError("the server let a Sales Officer submit")

	check("§11 the server refuses, not merely the hidden button",
		_the_server_path_refuses_not_just_the_button)

	def _the_permission_hook_denies_only_submit():
		doc = frappe.get_doc("Sales Order", so)
		_assert(A.sales_order_has_permission(doc, officer_user, "submit") is False,
			"the hook did not deny submit to a Sales Officer")
		_assert(A.sales_order_has_permission(doc, officer_user, "read") is None,
			"the hook interfered with read; it must only ever deny submit or cancel")
		_assert(A.sales_order_has_permission(doc, officer_user, "write") is None,
			"the hook interfered with write, which section 7 grants")

	check("§7 the hook denies submission without touching read or write",
		_the_permission_hook_denies_only_submit)

	def _a_manager_keeps_blanket_authority():
		other = _insert("Buyer Master", name=f"{tag}-OBM2",
			customer_business_name=f"{tag} Other", channel="Offline")
		so2 = _insert("Sales Order", name=f"SOA-{tag}-2", docstatus=0, company=company,
			customer="__Test Customer", transaction_date=today(),
			custom_offline_buyer_master=other, custom_workflow_status="Draft")
		allowed, _r = A.may_submit(so2, primary_user)
		_assert(allowed,
			"a Sales Manager lost authority on a Buyer they are not POC of; that would "
			"strand orders whose POC has left")

	check("§11 Sales Manager and Sales Admin keep authority beyond their own Buyers",
		_a_manager_keeps_blanket_authority)
