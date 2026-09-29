"""Changes(HP) #50: an HR user permission must not decide which buyers a salesperson sees.

Run:  bench --site alpinos.test execute alpinos.buyer_user_permission_test.run

On prod a Sales Admin could list 964 of 1081 buyers and not "U.S Supplements". Their only
User Permissions were Company and Employee AHFPL69, both apply_to_all_doctypes -- and
Buyer Master carries poc_employee, an Employee link. So a permission that exists for HR
self-service was quietly deciding which customers a salesperson could see: the ones whose
POC is them, and no others.

The fields now ignore user permissions. The check toggles that property at runtime, so a
single run shows the party hidden with it off and visible with it on.
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


def _set_ignore(value):
	"""Flip ignore_user_permissions on poc_employee for this run."""
	name = frappe.db.get_value(
		"DocField", {"parent": "Buyer Master", "fieldname": "poc_employee"}, "name"
	)
	frappe.db.set_value("DocField", name, "ignore_user_permissions", value, update_modified=False)
	frappe.clear_cache(doctype="Buyer Master")


def run():
	RES.clear()
	frappe.set_user("Administrator")
	real_commit = frappe.db.commit
	frappe.db.commit = lambda *a, **k: None
	original = frappe.db.get_value(
		"DocField", {"parent": "Buyer Master", "fieldname": "poc_employee"}, "ignore_user_permissions"
	)
	try:
		_run()
	finally:
		_set_ignore(original)
		frappe.db.commit = real_commit
		frappe.db.rollback()
		frappe.clear_cache(doctype="Buyer Master")
		frappe.set_user("Administrator")

	width = max(len(r[1]) for r in RES)
	for status, label, detail in RES:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in RES if r[0] == 'PASS')}/{len(RES)} passed")
	return RES


def _run():
	tag = "BUP" + frappe.generate_hash(length=5).upper()
	company = frappe.defaults.get_global_default("company")

	mine = _insert("Employee", name=f"{tag}-EMP-MINE", employee_name=f"{tag} Mine",
		status="Active", company=company, date_of_joining="2026-01-01")
	theirs = _insert("Employee", name=f"{tag}-EMP-THEIRS", employee_name=f"{tag} Theirs",
		status="Active", company=company, date_of_joining="2026-01-01")

	user = f"{tag.lower()}.sales@example.com"
	_insert("User", name=user, email=user, first_name="Sales", user_type="System User", enabled=1)
	_insert("Has Role", name=f"{tag}-ROLE", parent=user, parenttype="User",
		parentfield="roles", role="Sales Admin")
	# The HR self-service permission, exactly as prod has it.
	_insert("User Permission", name=f"{tag}-UP", user=user, allow="Employee",
		for_value=mine, apply_to_all_doctypes=1)

	# A buyer whose POC is somebody else -- "U.S Supplements" stood in this position.
	other = _insert("Buyer Master", name=f"{tag}-OBM-OTHER",
		customer_business_name=f"{tag} U.S Supplements", channel="Offline", poc_employee=theirs)
	own = _insert("Buyer Master", name=f"{tag}-OBM-OWN",
		customer_business_name=f"{tag} Own Party", channel="Offline", poc_employee=mine)

	def _visible_to_user():
		frappe.set_user(user)
		try:
			return {r.name for r in frappe.get_list(
				"Buyer Master",
				filters=[["customer_business_name", "like", f"%{tag}%"]],
				fields=["name"], limit_page_length=0)}
		finally:
			frappe.set_user("Administrator")

	def _with_the_permission_enforced_the_party_is_hidden():
		_set_ignore(0)
		seen = _visible_to_user()
		_assert(own in seen, f"the salesperson cannot see their own party either: {seen}")
		_assert(other not in seen,
			f"the fixture does not reproduce prod: {other} was visible with the permission enforced")

	check("#50 with user permissions enforced, a buyer whose POC is somebody else is hidden",
		_with_the_permission_enforced_the_party_is_hidden)

	def _ignoring_the_permission_shows_every_buyer():
		_set_ignore(1)
		seen = _visible_to_user()
		_assert(other in seen, f"{other} is still hidden with the field ignoring permissions: {seen}")
		_assert(own in seen, f"{own} went missing: {seen}")

	check("#50 with poc_employee ignoring user permissions, both buyers are listed",
		_ignoring_the_permission_shows_every_buyer)

	def _the_shipped_doctype_ignores_them():
		import json
		import os

		path = os.path.join(
			frappe.get_app_path("alpinos"),
			"alpinos_development", "doctype", "buyer_master", "buyer_master.json",
		)
		fields = {f["fieldname"]: f for f in json.load(open(path))["fields"]}
		for fieldname in ("poc_employee", "party_owner"):
			_assert(fields[fieldname].get("ignore_user_permissions") == 1,
				f"{fieldname} does not ignore user permissions in the shipped doctype")

	check("#50 the shipped doctype ships with both links ignoring user permissions",
		_the_shipped_doctype_ignores_them)
