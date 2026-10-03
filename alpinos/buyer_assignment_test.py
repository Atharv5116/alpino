"""Buyer Master internal sales assignment -- Sales Officer(s), Primary POC(s), Secondary POC.

Run:  bench --site alpinos.test execute alpinos.buyer_assignment_test.run

Buyer Master & Sales Order - Required Changes (03-10-2026) sections 1-5. These fields are
access control, so each check is about who may be assigned and who ends up assigned, not
about how the form looks. Fixtures are rolled back at the end.
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

	tag = "BAS" + frappe.generate_hash(length=5).upper()
	company = frappe.defaults.get_global_default("company")

	def _person(suffix, role):
		"""An active employee with a linked, enabled user holding one role."""
		user = f"{tag.lower()}.{suffix}@example.com"
		_insert("User", name=user, email=user, first_name=suffix.title(),
			user_type="System User", enabled=1)
		if role:
			_insert("Has Role", name=f"{tag}-HR-{suffix}", parent=user, parenttype="User",
				parentfield="roles", role=role)
		emp = _insert("Employee", name=f"{tag}-{suffix.upper()}",
			employee_name=f"{tag} {suffix.title()}", status="Active", company=company,
			date_of_joining="2026-01-01", user_id=user)
		return emp, user

	officer, officer_user = _person("officer", BA.SALES_OFFICER_ROLE)
	officer2, _ = _person("officer2", BA.SALES_OFFICER_ROLE)
	manager, manager_user = _person("manager", BA.SALES_MANAGER_ROLE)
	admin, admin_user = _person("admin", BA.SALES_ADMIN_ROLE)
	outsider, _ = _person("outsider", "Blogger")
	# Someone on the payroll with no login at all.
	no_user = _insert("Employee", name=f"{tag}-NOUSER", employee_name=f"{tag} No User",
		status="Active", company=company, date_of_joining="2026-01-01")

	def _buyer(**kw):
		doc = frappe.new_doc("Buyer Master")
		doc.customer_business_name = kw.pop("business_name", f"{tag} Party")
		doc.channel = "Offline"
		for k, v in kw.items():
			doc.set(k, v)
		return doc

	def _the_sales_officer_role_exists():
		BA.setup_assignment_roles()
		_assert(frappe.db.exists("Role", BA.SALES_OFFICER_ROLE),
			"the Sales Officer role was not created")

	check("the Sales Officer role is created", _the_sales_officer_role_exists)

	def _each_picker_offers_only_its_own_population():
		officers = {r[0] for r in BA.employees_with_roles((BA.SALES_OFFICER_ROLE,), tag)}
		_assert(officer in officers and officer2 in officers,
			f"Sales Officers missing from their own picker: {officers}")
		_assert(manager not in officers and admin not in officers and outsider not in officers,
			f"the Sales Officer picker offered somebody else: {officers}")

		primaries = {r[0] for r in BA.employees_with_roles(BA.PRIMARY_POC_ROLES, tag)}
		_assert({manager, admin} <= primaries,
			f"Primary POC must offer Sales Manager and Sales Admin: {primaries}")
		_assert(officer not in primaries, "a Sales Officer was offered as a Primary POC")

		secondaries = {r[0] for r in BA.employees_with_roles(BA.SECONDARY_POC_ROLES, tag)}
		_assert(admin in secondaries, f"the Sales Admin is missing: {secondaries}")
		_assert(manager not in secondaries,
			"a Sales Manager was offered as Secondary POC; the field is Sales Admin only")
		_assert(no_user not in secondaries, "an employee with no User was offered")

	check("each picker offers only the roles its field is defined for",
		_each_picker_offers_only_its_own_population)

	def _several_officers_and_primaries_may_be_assigned():
		doc = _buyer(business_name=f"{tag} Multi")
		doc.append("sales_officers", {"employee": officer})
		doc.append("sales_officers", {"employee": officer2})
		doc.append("primary_pocs", {"employee": manager})
		doc.append("primary_pocs", {"employee": admin})
		doc.secondary_poc = admin
		BA.validate_assignments(doc)
		_assert(len(doc.sales_officers) == 2, f"{len(doc.sales_officers)} officers kept")
		_assert(len(doc.primary_pocs) == 2, f"{len(doc.primary_pocs)} primary POCs kept")

	check("several Sales Officers and Primary POCs may be assigned to one Buyer",
		_several_officers_and_primaries_may_be_assigned)

	def _a_repeated_employee_is_dropped():
		doc = _buyer()
		doc.append("sales_officers", {"employee": officer})
		doc.append("sales_officers", {"employee": officer})
		BA.validate_assignments(doc)
		_assert(len(doc.sales_officers) == 1,
			f"the same officer was kept {len(doc.sales_officers)} times")

	check("the same employee cannot be assigned twice to one field",
		_a_repeated_employee_is_dropped)

	def _an_employee_without_the_role_is_refused():
		doc = _buyer()
		doc.append("sales_officers", {"employee": outsider})
		try:
			BA.validate_assignments(doc)
		except frappe.ValidationError:
			return
		raise AssertionError("an employee without the Sales Officer role was accepted")

	check("an employee without the field's role is refused",
		_an_employee_without_the_role_is_refused)

	def _a_manager_cannot_be_the_secondary_poc():
		doc = _buyer()
		doc.secondary_poc = manager
		try:
			BA.validate_assignments(doc)
		except frappe.ValidationError:
			return
		raise AssertionError("a Sales Manager was accepted as Secondary POC")

	check("Secondary POC refuses anyone outside Sales Admin",
		_a_manager_cannot_be_the_secondary_poc)

	def _an_employee_with_no_login_is_refused():
		doc = _buyer()
		doc.append("primary_pocs", {"employee": no_user})
		try:
			BA.validate_assignments(doc)
		except frappe.ValidationError:
			return
		raise AssertionError("an employee with no linked User was accepted")

	check("an employee with no linked User cannot be assigned",
		_an_employee_with_no_login_is_refused)

	def _the_creating_sales_officer_is_added_automatically():
		frappe.set_user(officer_user)
		try:
			doc = _buyer(business_name=f"{tag} Created By SO")
			BA.validate_assignments(doc)
		finally:
			frappe.set_user("Administrator")
		assigned = [r.employee for r in doc.sales_officers]
		_assert(assigned == [officer],
			f"the creating Sales Officer was not assigned: {assigned}")

	check("a Sales Officer who creates a Buyer is assigned to it",
		_the_creating_sales_officer_is_added_automatically)

	def _a_manager_creating_a_buyer_is_not_added_as_an_officer():
		frappe.set_user(manager_user)
		try:
			doc = _buyer(business_name=f"{tag} Created By SM")
			BA.validate_assignments(doc)
		finally:
			frappe.set_user("Administrator")
		_assert(not doc.sales_officers,
			f"a Sales Manager was auto-assigned as a Sales Officer: {doc.sales_officers}")

	check("a manager creating a Buyer is not auto-assigned as a Sales Officer",
		_a_manager_creating_a_buyer_is_not_added_as_an_officer)

	def _the_creator_is_added_only_once():
		frappe.set_user(officer_user)
		try:
			doc = _buyer()
			doc.append("sales_officers", {"employee": officer})
			BA.validate_assignments(doc)
		finally:
			frappe.set_user("Administrator")
		_assert(len(doc.sales_officers) == 1,
			f"the creator was added again: {[r.employee for r in doc.sales_officers]}")

	check("a Sales Officer already listed is not added a second time",
		_the_creator_is_added_only_once)

	def _the_legacy_migration_moves_the_value_and_reports_first():
		buyer = _insert("Buyer Master", name=f"{tag}-OBM-LEGACY",
			customer_business_name=f"{tag} Legacy", channel="Offline", primary_poc=manager)
		dry = BA.migrate_legacy_pocs(apply=0)
		_assert(dry["mode"] == "DRY-RUN", dry["mode"])
		_assert(any(s["buyer"] == buyer for s in dry["sample"]),
			f"the legacy buyer is not in the dry run: {dry['sample'][:3]}")
		_assert(not frappe.db.exists("Buyer Primary POC", {"parent": buyer}),
			"the dry run wrote a row")

		BA.migrate_legacy_pocs(apply=1)
		moved = frappe.db.get_value("Buyer Primary POC", {"parent": buyer}, "employee")
		_assert(moved == manager, f"the value did not move: {moved}")

	check("the legacy Primary POC value moves into the new table, dry run first",
		_the_legacy_migration_moves_the_value_and_reports_first)

	def _the_migration_does_not_move_a_value_twice():
		before = frappe.db.count("Buyer Primary POC", {"parent": f"{tag}-OBM-LEGACY"})
		BA.migrate_legacy_pocs(apply=1)
		after = frappe.db.count("Buyer Primary POC", {"parent": f"{tag}-OBM-LEGACY"})
		_assert(before == after == 1, f"rows went {before} -> {after}; re-running duplicated it")

	check("re-running the migration does not duplicate a row",
		_the_migration_does_not_move_a_value_twice)
