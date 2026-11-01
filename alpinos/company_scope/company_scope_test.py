"""Company-wise access, end to end. Run on a TEST site (it turns the feature on):

	bench --site <test site> execute alpinos.company_scope.company_scope_test.run

The client's example is the fixture: a user who may read and write Purchase Orders in
company A, only read them in B, and has nothing in C. Test roles, users, Purchase Orders,
Machines and Machine Runs are created with fixed names and removed again at the end.
"""

import time

import frappe
from frappe.permissions import add_permission, update_permission_property
from frappe.utils import add_days, nowdate

R = []

WRITER, VIEWER, EDITOR = "CS Test Writer", "CS Test Viewer", "CS Test Editor"
U_MULTI, U_SINGLE = "cs.multi@example.com", "cs.single@example.com"
PO = "Purchase Order"
MR = "Machine Run"
WORKFLOW = "CS Test Machine Run"


def check(label, fn):
	try:
		fn()
		R.append(("PASS", label, ""))
	except AssertionError as e:
		R.append(("FAIL", label, str(e)))
	except Exception as e:
		R.append(("ERROR", label, f"{type(e).__name__}: {e}"))


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


def _raises(fn, exc=frappe.PermissionError, contains=None):
	try:
		fn()
	except exc as e:
		if contains and contains not in str(e):
			raise AssertionError(f"raised, but '{contains}' not in: {e}")
		return
	except frappe.ValidationError as e:
		if exc is frappe.ValidationError or isinstance(e, exc):
			return
		raise
	raise AssertionError("did not raise")


def _as(user, fn):
	previous = frappe.session.user
	frappe.set_user(user)
	_fresh()
	try:
		return fn()
	finally:
		frappe.set_user(previous)
		_fresh()


def _fresh():
	from alpinos.company_scope import access, reset_request_cache

	reset_request_cache()
	frappe.local.role_permissions = {}
	for attr in ("alpinos_cs_authorized",):
		if hasattr(frappe.local, attr):
			delattr(frappe.local, attr)
	frappe.local.flags.alpinos_cs_listing = None


def _companies():
	default = frappe.db.get_single_value("Global Defaults", "default_company")
	others = [c for c in frappe.get_all("Company", pluck="name", order_by="name") if c != default]
	return default, others[0], others[1]


# --- fixtures ------------------------------------------------------------------------------


def _role(name):
	if not frappe.db.exists("Role", name):
		frappe.get_doc({"doctype": "Role", "role_name": name, "desk_access": 1}).insert(ignore_permissions=True)
	frappe.db.set_value("Role", name, "custom_company_scoped", 1)


def _perm(doctype, role, rights):
	if not frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": role, "permlevel": 0}):
		add_permission(doctype, role, 0)
	for ptype in ("read", "write", "create", "submit", "cancel", "delete", "amend", "print", "email",
		"report", "export", "share", "select"):
		value = 1 if ptype in rights else 0
		update_permission_property(doctype, role, 0, ptype, value, validate=False)


def _user(email):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0}
		).insert(ignore_permissions=True)
	return email


def _membership(user, company, roles, default=False):
	from alpinos.company_scope import sync

	name = frappe.db.get_value("Company Membership", {"user": user, "company": company})
	if name:
		frappe.delete_doc("Company Membership", name, ignore_permissions=True, flags={"alpinos_skip_user_sync": True})
	sync.ensure_membership(user, company, roles, source="Manual", is_default=default)


def _po_copy(template, name, company):
	if frappe.db.exists(PO, name):
		frappe.db.delete(PO, {"name": name})
	doc = frappe.get_doc(PO, template).as_dict()
	for key in ("items", "taxes", "payment_schedule", "custom_approval_log"):
		doc.pop(key, None)
	doc.update({"name": name, "company": company, "docstatus": 0, "owner": "Administrator"})
	new = frappe.get_doc(doc)
	new.db_insert()
	return name


def _machine(name, companies):
	from alpinos.company_scope import tags

	if frappe.db.exists("Machine", name):
		frappe.db.delete("Alpinos Company Tag", {"parent": name, "parenttype": "Machine"})
		frappe.db.delete("Machine", {"name": name})
	machine_type = frappe.db.get_value("Machine Type", {}, "name")
	doc = frappe.get_doc(
		{"doctype": "Machine", "machine_name": name, "machine_type": machine_type, "status": "Active",
		 "custom_companies": [{"company": c} for c in companies]}
	)
	doc.flags.ignore_mandatory = True
	doc.flags.ignore_links = True
	doc.insert(ignore_permissions=True, set_name=name)
	frappe.db.set_value("Machine", doc.name, "custom_company_scope", tags.scope_string(companies), update_modified=False)
	return doc.name


def _cleanup():
	frappe.set_user("Administrator")
	for name in frappe.get_all(MR, {"machine": ["like", "CS-M-%"]}, pluck="name"):
		frappe.db.delete(MR, {"name": name})
	for name in ("CS-TEST-PO-B", "CS-TEST-PO-C"):
		frappe.db.delete(PO, {"name": name})
	for name in ("CS-M-A", "CS-M-B", "CS-M-BLANK", "CS-M-AC"):
		frappe.db.delete("Alpinos Company Tag", {"parent": name, "parenttype": "Machine"})
		frappe.db.delete("Machine", {"name": name})
	if frappe.db.exists("Workflow", WORKFLOW):
		frappe.delete_doc("Workflow", WORKFLOW, ignore_permissions=True, force=True)
	for user in (U_MULTI, U_SINGLE):
		for name in frappe.get_all("Company Membership", {"user": user}, pluck="name"):
			frappe.delete_doc("Company Membership", name, ignore_permissions=True, flags={"alpinos_skip_user_sync": True})
		frappe.db.delete("User Permission", {"user": user})
		emp = frappe.db.get_value("Employee", {"user_id": user})
		if emp:
			frappe.db.delete("Employee", {"name": emp})
		if frappe.db.exists("User", user):
			frappe.delete_doc("User", user, ignore_permissions=True, force=True)
	for role in (WRITER, VIEWER, EDITOR):
		frappe.db.delete("Custom DocPerm", {"role": role})
		frappe.db.delete("Has Role", {"role": role})
		if frappe.db.exists("Role", role):
			frappe.delete_doc("Role", role, ignore_permissions=True, force=True)
	frappe.clear_cache(doctype=PO)
	frappe.clear_cache(doctype=MR)
	frappe.clear_cache(doctype="Machine")
	frappe.db.commit()


# --- the run -------------------------------------------------------------------------------


def run():
	R.clear()
	frappe.set_user("Administrator")
	from alpinos.company_scope import access, active, enabled, reset_request_cache, seed, sync

	A, B, C = _companies()

	# 0. Go-live: turning the feature on changes nobody's roles.
	if not enabled():
		before_roles = {
			u: set(frappe.get_all("Has Role", {"parenttype": "User", "parent": u}, pluck="role"))
			for u in frappe.get_all("User", {"enabled": 1, "user_type": "System User"}, pluck="name")
		}
		before_ups = {
			u: set(frappe.get_all("User Permission", {"user": u, "allow": "Company"}, pluck="for_value"))
			for u in before_roles
		}
		settings = frappe.get_single("Alpino General Settings")
		settings.company_scope_enabled = 1
		settings.save(ignore_permissions=True)
		reset_request_cache()
		access.clear_cache()
		after_roles = {
			u: set(frappe.get_all("Has Role", {"parenttype": "User", "parent": u}, pluck="role")) for u in before_roles
		}
		changed = [u for u in before_roles if before_roles[u] != after_roles[u]]
		check("go-live: no user's roles change", lambda: _assert(not changed, changed[:5]))
		every = set(frappe.get_all("Company", pluck="name"))

		def reach(ups):
			return set(ups) or every

		lost = [
			u for u in before_roles
			if not reach(before_ups[u]) <= reach(frappe.get_all("User Permission", {"user": u, "allow": "Company"}, pluck="for_value"))
		]
		check("go-live: nobody loses a company they had", lambda: _assert(not lost, lost[:5]))
		unmanaged = [
			u for u in before_roles
			if u not in ("Administrator", "Guest") and not frappe.db.exists("Company Membership", {"user": u})
		]
		check("go-live: every desk user is set up", lambda: _assert(not unmanaged, unmanaged[:5]))
	frappe.db.commit()
	_cleanup()
	try:
		_run(A, B, C)
	finally:
		_cleanup()
	return _report()


def _run(A, B, C):
	from alpinos.company_scope import access, active, guard, helpers, numbering, permissions, sync, tags

	frappe.local.alpinos_cs_enabled = True
	for role in (WRITER, VIEWER, EDITOR):
		_role(role)
	_perm(PO, WRITER, {"read", "write", "create", "submit", "cancel", "delete", "print", "report", "select"})
	_perm(PO, VIEWER, {"read", "print", "report", "select"})
	_perm(MR, WRITER, {"read", "write", "create", "delete", "select"})
	_perm(MR, EDITOR, {"read", "write", "create", "select"})
	_perm(MR, VIEWER, {"read", "select"})
	for role in (WRITER, VIEWER, EDITOR):
		_perm("Machine", role, {"read", "select"})
	frappe.clear_cache()
	access.clear_cache()

	_user(U_MULTI)
	_user(U_SINGLE)
	_membership(U_MULTI, A, [WRITER], default=True)
	_membership(U_MULTI, B, [VIEWER, EDITOR])
	_membership(U_SINGLE, A, [WRITER], default=True)
	sync.sync_user(U_MULTI)
	sync.sync_user(U_SINGLE)
	active.set_active(U_MULTI, A)
	active.set_active(U_SINGLE, A)
	frappe.db.commit()
	_fresh()

	template = frappe.db.get_value(PO, {"company": A}, "name", order_by="creation desc")
	po_a = template
	po_b = _po_copy(template, "CS-TEST-PO-B", B)
	po_c = _po_copy(template, "CS-TEST-PO-C", C)
	frappe.db.commit()

	# 1. Resolver: the client's example.
	check("PO write only in A", lambda: _assert(access.allowed_companies(PO, "write", U_MULTI) == [A],
		access.allowed_companies(PO, "write", U_MULTI)))
	check("PO read in A and B, not C", lambda: _assert(
		set(access.allowed_companies(PO, "read", U_MULTI)) == {A, B}, access.allowed_companies(PO, "read", U_MULTI)))
	check("PO create only in A", lambda: _assert(access.allowed_companies(PO, "create", U_MULTI) == [A]))
	check("effective roles differ by company", lambda: _assert(
		WRITER in access.effective_roles(U_MULTI, A) and WRITER not in access.effective_roles(U_MULTI, B)
		and VIEWER in access.effective_roles(U_MULTI, B) and not ({WRITER, VIEWER} & access.effective_roles(U_MULTI, C))))

	# 2. Sync: roles and Company User Permissions.
	roles = set(frappe.get_all("Has Role", {"parenttype": "User", "parent": U_MULTI}, pluck="role"))
	check("Has Role = union of the memberships", lambda: _assert({WRITER, VIEWER, EDITOR} <= roles, roles))
	ups = frappe.get_all("User Permission", {"user": U_MULTI, "allow": "Company"}, ["for_value", "is_default", "apply_to_all_doctypes"])
	check("Company User Permissions = member companies", lambda: _assert(
		{u.for_value for u in ups} == {A, B} and not any(u.is_default for u in ups) and all(u.apply_to_all_doctypes for u in ups), ups))
	check("a desk role from a membership makes a System User", lambda: _assert(
		frappe.db.get_value("User", U_MULTI, "user_type") == "System User"))

	# 3. Documents: every right in every company.
	def perm(user, ptype, name):
		def go():
			_fresh()
			return frappe.has_permission(PO, ptype, doc=frappe.get_doc(PO, name), user=user)
		return _as(user, go)

	matrix = [
		("read", po_a, True), ("write", po_a, True), ("submit", po_a, True), ("delete", po_a, True),
		("read", po_b, True), ("print", po_b, True), ("write", po_b, False), ("submit", po_b, False),
		("cancel", po_b, False), ("delete", po_b, False),
		("read", po_c, False), ("write", po_c, False), ("print", po_c, False),
	]
	for ptype, name, expected in matrix:
		check(f"has_permission {ptype} on PO in {frappe.get_value(PO, name, 'company')}: {expected}",
			lambda ptype=ptype, name=name, expected=expected: _assert(perm(U_MULTI, ptype, name) == expected))
	check("single-company user cannot read B", lambda: _assert(perm(U_SINGLE, "read", po_b) is False))

	# 4. Tampering: posting a B document as A.
	def move_b_to_a():
		doc = frappe.get_doc(PO, po_b)
		doc.company = A
		return frappe.has_permission(PO, "write", doc=doc, user=U_MULTI)

	check("a B document posted as A is still refused", lambda: _assert(_as(U_MULTI, move_b_to_a) is False))

	def guard_move():
		doc = frappe.get_doc(PO, po_b)
		doc._doc_before_save = frappe.get_doc(PO, po_b)
		doc.company = A
		guard.validate(doc)

	check("the guard refuses moving a document between companies",
		lambda: _as(U_MULTI, lambda: _raises(guard_move, contains="cannot move")))

	# 5. Lists: allowed, narrowed to the active company on listing calls.
	names = [po_a, po_b, po_c]

	def listed(listing):
		def go():
			_fresh()
			if listing:
				with helpers.listing():
					return set(frappe.get_list(PO, filters={"name": ["in", names]}, pluck="name"))
			return set(frappe.get_list(PO, filters={"name": ["in", names]}, pluck="name"))
		return _as(U_MULTI, go)

	check("list view shows only the active company", lambda: _assert(listed(True) == {po_a}, listed(True)))
	active.set_active(U_MULTI, "__all__")
	frappe.db.commit()
	check("All my companies shows A and B", lambda: _assert(listed(True) == {po_a, po_b}, listed(True)))
	active.set_active(U_MULTI, B)
	frappe.db.commit()
	check("switched to B, the list shows B", lambda: _assert(listed(True) == {po_b}, listed(True)))
	check("internal reads see every allowed company", lambda: _assert(listed(False) == {po_a, po_b}, listed(False)))
	check("C never appears", lambda: _assert(po_c not in listed(False)))
	check("frappe.get_all is not filtered (pages use helpers)", lambda: _assert(
		_as(U_MULTI, lambda: len(frappe.get_all(PO, {"name": ["in", names]}))) == 3))
	check("company_filters follows the active company", lambda: _assert(
		_as(U_MULTI, lambda: helpers.company_filters(PO)) == {"company": ["in", [B]]}))
	check("company_sql for raw SQL", lambda: _assert(
		_as(U_MULTI, lambda: helpers.company_sql(PO, "po")) == f" and `po`.`company` in ({frappe.db.escape(B)})"))
	check("Administrator is never filtered", lambda: _assert(helpers.company_filters(PO) == {} and
		len(frappe.get_list(PO, filters={"name": ["in", names]})) == 3))

	# 6. Defaults follow the switch; logout does not clear them.
	check("company default follows the switch", lambda: _assert(
		frappe.defaults.get_user_default("Company", U_MULTI) == B, frappe.defaults.get_user_default("Company", U_MULTI)))
	active.set_active(U_MULTI, "__all__")
	check("All mode: company default = default membership", lambda: _assert(
		frappe.defaults.get_defaults_for(U_MULTI).get("company") == A))

	def after_logout():
		from frappe.core.doctype.session_default_settings.session_default_settings import clear_session_defaults

		clear_session_defaults()
		frappe.cache.hdel("defaults", U_MULTI)
		return frappe.defaults.get_defaults_for(U_MULTI).get("company")

	check("logout keeps the company", lambda: _assert(_as(U_MULTI, after_logout) == A))
	check("switching to a non-member company is refused", lambda: _raises(lambda: active.set_active(U_MULTI, C)))
	active.set_active(U_MULTI, A)
	frappe.db.commit()

	# 7. Write guard on ignore_permissions inserts (alpinos pages).
	m_a = _machine("CS-M-A", [A])
	m_b = _machine("CS-M-B", [B])
	m_blank = _machine("CS-M-BLANK", [])
	m_ac = _machine("CS-M-AC", [A, C])
	frappe.db.commit()

	def make_run(company, machine, ignore=True):
		def go():
			_fresh()
			doc = frappe.get_doc({"doctype": MR, "company": company, "machine": machine, "planned_date": nowdate(),
				"status": "Planned"})
			doc.flags.ignore_links = True
			doc.insert(ignore_permissions=ignore)
			return doc.name
		return go

	check("page insert in a member company passes", lambda: _assert(_as(U_MULTI, make_run(A, m_a))))
	check("page insert in a non-member company is refused",
		lambda: _as(U_MULTI, lambda: _raises(make_run(C, m_blank), contains="do not have")))
	check("form insert needs create in that company (B: Editor yes)", lambda: _assert(_as(U_MULTI, make_run(B, m_b, ignore=False))))
	check("form insert refused where the user only reads (single user in B)",
		lambda: _as(U_SINGLE, lambda: _raises(make_run(B, m_blank, ignore=False))))

	# 8. Tagged masters.
	check("a machine tagged for B cannot be used in A",
		lambda: _as(U_MULTI, lambda: _raises(make_run(A, m_b), exc=frappe.ValidationError, contains="not tagged")))
	check("an untagged machine works everywhere", lambda: _assert(_as(U_MULTI, make_run(A, m_blank))))

	def machines_listed(user):
		def go():
			_fresh()
			with helpers.listing():
				return set(frappe.get_list("Machine", filters={"name": ["like", "CS-M-%"]}, pluck="name"))
		return _as(user, go)

	check("A-only user sees A, A+C and blank machines", lambda: _assert(
		machines_listed(U_SINGLE) == {m_a, m_blank, m_ac}, machines_listed(U_SINGLE)))
	check("A-only user cannot open a B machine", lambda: _assert(
		_as(U_SINGLE, lambda: frappe.has_permission("Machine", "read", doc=frappe.get_doc("Machine", m_b), user=U_SINGLE)) is False))
	check("tag mirror is kept on save", lambda: _assert(
		tags.scope_string([C, A]) == f"|{A}|{C}|"))

	# 9. Workflow: the transition's role must be held in the document's company.
	_workflow()

	def transition_in(company, machine):
		def go():
			_fresh()
			doc = frappe.get_doc({"doctype": MR, "company": company, "machine": machine, "planned_date": nowdate(),
				"status": "Planned"})
			doc.flags.ignore_links = True
			doc.insert()
			doc = frappe.get_doc(MR, doc.name)
			doc.workflow_state = "CS Approved"
			doc.save()
			return doc.workflow_state
		return go

	check("workflow: approve in A (holds the role there)", lambda: _assert(_as(U_MULTI, transition_in(A, m_a)) == "CS Approved"))
	check("workflow: approve in B refused (role only held in A)",
		lambda: _as(U_MULTI, lambda: _raises(transition_in(B, m_b), contains="needs the role")))

	def buttons(company, machine):
		def go():
			_fresh()
			doc = frappe.get_doc({"doctype": MR, "company": company, "machine": machine, "planned_date": nowdate(),
				"status": "Planned"})
			doc.flags.ignore_links = True
			doc.insert()
			from alpinos.company_scope.api import get_transitions

			return [t["action"] for t in get_transitions(frappe.get_doc(MR, doc.name))]
		return go

	check("workflow buttons in B hide the A-only transition", lambda: _assert(
		_as(U_MULTI, buttons(B, m_b)) == [], _as(U_MULTI, buttons(B, m_b))))
	check("workflow buttons in A show it", lambda: _assert(_as(U_MULTI, buttons(A, m_a)) == ["CS Approve"]))

	# 10. Reports.
	from alpinos.company_scope import reports

	reports.patch()

	def run_report(company):
		import frappe.desk.query_report as qr

		report = frappe._dict(name="CS Test Report", ref_doctype=PO, report_type="Script Report")
		report.execute_script_report = lambda filters: (
			[{"fieldname": "company", "fieldtype": "Link", "options": "Company", "label": "Company"},
			 {"fieldname": "n", "fieldtype": "Int", "label": "N"}],
			[{"company": A, "n": 1}, {"company": B, "n": 2}, {"company": C, "n": 3}],
		)
		return qr.get_report_result(report, {"company": company} if company else {})

	check("report refuses a company the user cannot see",
		lambda: _as(U_SINGLE, lambda: _raises(lambda: run_report(B), contains="cannot run")))
	check("report drops rows of other companies", lambda: _assert(
		[r["company"] for r in _as(U_SINGLE, lambda: run_report(None))[1]] == [A]))
	check("Administrator's report keeps every row", lambda: _assert(len(run_report(None)[1]) == 3))

	# 11. Pickers and notifications.
	check("users_with_roles: Writer in A includes the user", lambda: _assert(U_MULTI in access.users_with_roles([WRITER], A)))
	check("users_with_roles: Writer in B leaves them out", lambda: _assert(U_MULTI not in access.users_with_roles([WRITER], B)))
	check("has_company_role", lambda: _assert(
		_as(U_MULTI, lambda: access.has_company_role([WRITER], A) and not access.has_company_role([WRITER], B))))

	# 12. Numbering.
	code_b = frappe.db.get_value("Company", B, "custom_series_code")
	check("non-default companies have a series code", lambda: _assert(code_b, B))
	check("default company keeps its numbers", lambda: _assert(not frappe.db.get_value("Company", A, "custom_series_code")))

	def named(company):
		doc = frappe._dict(naming_series="SOR-2627-.#####", company=company, amended_from=None)
		numbering.before_naming(doc)
		return doc.naming_series

	check("SO series gets the code for B", lambda: _assert(named(B) == f"SOR-{code_b}-2627-.#####", named(B)))
	check("SO series unchanged for A", lambda: _assert(named(A) == "SOR-2627-.#####"))

	# 13. Roles ticked on the User form land in the home company.
	def tick_on_user_form():
		user = frappe.get_doc("User", U_SINGLE)
		user.append("roles", {"role": VIEWER})
		user.save(ignore_permissions=True)
		access.clear_cache(U_SINGLE)
		return access.company_roles(U_SINGLE, A)

	check("role ticked on the User form joins the home company", lambda: _assert(VIEWER in tick_on_user_form()))

	def untick_on_user_form():
		user = frappe.get_doc("User", U_SINGLE)
		user.set("roles", [r for r in user.roles if r.role != VIEWER])
		user.save(ignore_permissions=True)
		access.clear_cache(U_SINGLE)
		return access.company_roles(U_SINGLE, A)

	check("role unticked on the User form leaves every company", lambda: _assert(VIEWER not in untick_on_user_form()))

	# 14. Employee: the user becomes a member of their Employee's company.
	def employee_in_c():
		emp = frappe.get_doc(
			{"doctype": "Employee", "first_name": "CS Single", "gender": frappe.db.get_value("Gender", {}, "name"),
			 "date_of_birth": "1990-01-01", "date_of_joining": add_days(nowdate(), -30), "company": C,
			 "user_id": U_SINGLE, "status": "Active", "create_user_permission": 0}
		)
		emp.flags.ignore_mandatory = True
		emp.flags.ignore_links = True
		emp.insert(ignore_permissions=True, set_name=f"CS-EMP-{int(time.time())}")
		access.clear_cache(U_SINGLE)
		return set(access.member_companies(U_SINGLE)), set(
			frappe.get_all("User Permission", {"user": U_SINGLE, "allow": "Company"}, pluck="for_value"))

	members, ups = employee_in_c()
	check("an Employee in C makes the user a member of C", lambda: _assert(C in members, members))
	check("...and their Company User Permissions follow", lambda: _assert(ups == {A, C}, ups))
	check("...with no roles there", lambda: _assert(not access.company_roles(U_SINGLE, C)))

	# 15. Off switch: nothing applies while the feature is off.
	def off():
		frappe.local.alpinos_cs_enabled = False
		try:
			return permissions.query_conditions(U_MULTI, PO), permissions.has_permission(frappe.get_doc(PO, po_c), "read", U_MULTI)
		finally:
			frappe.local.alpinos_cs_enabled = None

	check("feature off: hooks have no say", lambda: _assert(_as(U_MULTI, off) == ("", True), _as(U_MULTI, off)))

	# 16. Speed.
	def timing():
		_fresh()
		doc = frappe.get_doc(PO, po_a)
		start = time.perf_counter()
		for _ in range(2000):
			frappe.local.role_permissions = {}
			permissions.has_permission(doc, "write", U_MULTI)
		return (time.perf_counter() - start) / 2000 * 1e6

	micro = _as(U_MULTI, timing)
	check(f"has_permission hook costs {micro:.0f} µs (< 300)", lambda: _assert(micro < 300, micro))


def _workflow():
	if frappe.db.exists("Workflow", WORKFLOW):
		frappe.delete_doc("Workflow", WORKFLOW, ignore_permissions=True, force=True)
	for state in ("CS Draft", "CS Approved"):
		if not frappe.db.exists("Workflow State", state):
			frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": state}).insert(ignore_permissions=True)
	if not frappe.db.exists("Workflow Action Master", "CS Approve"):
		frappe.get_doc({"doctype": "Workflow Action Master", "workflow_action_name": "CS Approve"}).insert(ignore_permissions=True)
	frappe.get_doc(
		{
			"doctype": "Workflow",
			"workflow_name": WORKFLOW,
			"document_type": MR,
			"is_active": 1,
			"workflow_state_field": "workflow_state",
			"send_email_alert": 0,
			"states": [
				{"state": "CS Draft", "doc_status": "0", "allow_edit": EDITOR},
				{"state": "CS Draft", "doc_status": "0", "allow_edit": WRITER},
				{"state": "CS Approved", "doc_status": "0", "allow_edit": WRITER},
			],
			"transitions": [
				{"state": "CS Draft", "action": "CS Approve", "next_state": "CS Approved", "allowed": WRITER,
				 "allow_self_approval": 1},
			],
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()
	frappe.clear_cache(doctype=MR)


def _report():
	width = max((len(r[1]) for r in R), default=10)
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in R if r[0] == 'PASS')}/{len(R)} passed")
	frappe.db.commit()
	return R


def run_seed():
	"""Role Permissions Manager edits survive a migrate's role matrices.

	Edits two seeded rows the purchase matrix owns (as if in Role Permissions Manager), runs
	the matrix inside perm_seed start/finish like a migrate does, checks the edits held, and
	puts the rows back.
	"""
	from frappe.permissions import update_permission_property

	from alpinos.company_scope import perm_seed
	from alpinos.purchase import constants as C
	from alpinos.purchase.roles import setup_purchase_roles

	R.clear()
	frappe.set_user("Administrator")
	role = C.ROLE_PURCHASE_USER
	edit = {"parent": "Purchase Inward", "role": role, "permlevel": 0, "if_owner": 0}
	gone = {"parent": "Purchase QC", "role": role, "permlevel": 0, "if_owner": 0}
	check("rows are seeded", lambda: _assert(
		frappe.db.exists(perm_seed.SEED, f"Purchase Inward|{role}|0|0") and frappe.db.exists(perm_seed.SEED, f"Purchase QC|{role}|0|0")))
	write_before = frappe.db.get_value("Custom DocPerm", edit, "write")
	gone_row = frappe.db.get_value("Custom DocPerm", gone, "*", as_dict=True)
	try:
		# what someone does in Role Permissions Manager
		update_permission_property("Purchase Inward", role, 0, "write", 0 if write_before else 1, validate=False)
		frappe.db.delete("Custom DocPerm", gone)
		changed_to = frappe.db.get_value("Custom DocPerm", edit, "write")
		# what a migrate does
		perm_seed.start()
		setup_purchase_roles()
		mid = frappe.db.get_value("Custom DocPerm", edit, "write")
		perm_seed.finish()
		check("the matrix tried to put the old value back", lambda: _assert(mid == write_before, (mid, write_before)))
		check("Role Permissions Manager's change is kept", lambda: _assert(
			frappe.db.get_value("Custom DocPerm", edit, "write") == changed_to))
		check("a row removed in Role Permissions Manager stays removed", lambda: _assert(
			not frappe.db.exists("Custom DocPerm", gone)))
		# a new row the code adds for the first time is created and recorded
		new_key = f"Purchase Quarantine|{role}|0|0"
		new_filters = {"parent": "Purchase Quarantine", "role": role, "permlevel": 0, "if_owner": 0}
		saved = frappe.db.get_value("Custom DocPerm", new_filters, "*", as_dict=True)
		frappe.db.delete("Custom DocPerm", new_filters)
		frappe.db.delete(perm_seed.SEED, {"seed_key": new_key})
		perm_seed.start()
		setup_purchase_roles()
		perm_seed.finish()
		check("a permission code adds for the first time is created",
			lambda: _assert(frappe.db.exists("Custom DocPerm", new_filters) and frappe.db.exists(perm_seed.SEED, new_key)))
		if saved and not frappe.db.exists("Custom DocPerm", new_filters):
			frappe.get_doc(dict(saved, doctype="Custom DocPerm")).db_insert()
	finally:
		frappe.db.set_value("Custom DocPerm", edit, "write", write_before)
		if gone_row and not frappe.db.exists("Custom DocPerm", gone):
			frappe.get_doc(dict(gone_row, doctype="Custom DocPerm")).db_insert()
		frappe.clear_cache(doctype="Purchase Inward")
		frappe.clear_cache(doctype="Purchase QC")
	return _report()
