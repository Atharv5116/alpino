"""Keeps a user's roles and Company User Permissions in step with their memberships.

- Has Role = the user's global roles + every company-wise role of every enabled membership.
  Written straight to Has Role (not through User.save), so syncing never re-enters the User
  controller and never fires its side effects (welcome mails, role-profile resets).
- Company User Permissions = the member companies; none when the user is a member of every
  company. is_default is never set (it would beat the active company on new documents).
  Employee User Permissions are never touched.
- A user is "managed" once they have a membership. Users without one are left exactly as
  they are: nothing here strips their roles.

Roles ticked or unticked on the User form still work: a company-wise role added there goes
to the user's home company (their Employee's company, else their default membership), and a
company-wise role removed there is removed from every company.
"""

import frappe
from frappe.permissions import AUTOMATIC_ROLES

from alpinos.company_scope import access, enabled

MEMBERSHIP = access.MEMBERSHIP


# --- one user ------------------------------------------------------------------------------


def _membership_role_union(user):
	scoped = access.scoped_roles()
	roles = set()
	for m in access._load_memberships(user):
		roles |= set(m["roles"]) & scoped
	return roles


def sync_user(user):
	"""Bring Has Role and Company User Permissions in line with the memberships."""
	if not enabled() or user in ("Administrator", "Guest"):
		return
	access.clear_cache(user)
	if not frappe.db.exists(MEMBERSHIP, {"user": user}):
		return
	_sync_roles(user)
	sync_user_permissions(user)
	access.clear_cache(user)
	frappe.clear_cache(user=user)
	from alpinos.company_scope import active

	active.apply_mirror(user)


def _sync_roles(user):
	scoped = access.scoped_roles()
	current = set(
		frappe.get_all("Has Role", {"parenttype": "User", "parent": user}, pluck="role")
	)
	desired = (current - scoped) | _membership_role_union(user)
	for role in sorted(current - desired):
		if role in AUTOMATIC_ROLES:
			continue
		frappe.db.delete("Has Role", {"parenttype": "User", "parent": user, "role": role})
	missing = sorted(desired - current)
	if missing:
		idx = frappe.db.sql(
			"select coalesce(max(idx), 0) from `tabHas Role` where parenttype='User' and parent=%s", user
		)[0][0]
		for role in missing:
			idx += 1
			frappe.get_doc(
				{"doctype": "Has Role", "parenttype": "User", "parentfield": "roles", "parent": user,
				 "role": role, "idx": idx}
			).db_insert()
	if missing or (current - desired):
		frappe.cache.hdel("roles", user)
	# Frappe decides System User from roles with desk access when a User is saved; roles
	# written here bypass that, so a user whose desk roles came only from memberships would
	# stay a Website User and could not open the desk.
	if desired and frappe.db.get_value("User", user, "user_type") != "System User":
		if frappe.get_all("Role", {"name": ["in", list(desired)], "desk_access": 1}, limit=1):
			frappe.db.set_value("User", user, "user_type", "System User", update_modified=False)


def sync_user_permissions(user):
	"""Company User Permissions = member companies (none when the user is in every company)."""
	members = set(access.member_companies(user))
	if not members:
		return
	companies = set(access.all_companies())
	desired = set() if members >= companies else members
	existing = frappe.get_all(
		"User Permission",
		filters={"user": user, "allow": "Company"},
		fields=["name", "for_value", "apply_to_all_doctypes", "applicable_for", "is_default"],
	)
	kept = set()
	for row in existing:
		ok = (
			row.for_value in desired
			and row.for_value not in kept
			and row.apply_to_all_doctypes
			and not row.applicable_for
			and not row.is_default
		)
		if ok:
			kept.add(row.for_value)
			continue
		doc = frappe.get_doc("User Permission", row.name)
		doc.flags.alpinos_company_sync = True
		doc.delete(ignore_permissions=True)
	for company in sorted(desired - kept):
		doc = frappe.get_doc(
			{"doctype": "User Permission", "user": user, "allow": "Company", "for_value": company,
			 "apply_to_all_doctypes": 1, "is_default": 0}
		)
		doc.flags.alpinos_company_sync = True
		doc.insert(ignore_permissions=True)


# --- memberships ---------------------------------------------------------------------------


def home_company(user):
	"""The company a role ticked on the User form belongs to."""
	company = frappe.db.get_value("Employee", {"user_id": user, "status": ["!=", "Left"]}, "company")
	if company:
		return company
	return access.default_company(user) or frappe.db.get_single_value("Global Defaults", "default_company")


def ensure_membership(user, company, roles=(), source="Manual", is_default=None):
	"""Get or create the user's membership in a company, adding `roles` to it."""
	name = frappe.db.get_value(MEMBERSHIP, {"user": user, "company": company})
	if name:
		doc = frappe.get_doc(MEMBERSHIP, name)
	else:
		doc = frappe.new_doc(MEMBERSHIP)
		doc.update({"user": user, "company": company, "enabled": 1, "source": source})
		if is_default is None:
			is_default = not frappe.db.exists(MEMBERSHIP, {"user": user, "is_default": 1})
	if is_default is not None:
		doc.is_default = 1 if is_default else 0
	have = {r.role for r in doc.roles}
	for role in roles:
		if role not in have:
			doc.append("roles", {"role": role})
			have.add(role)
	doc.flags.alpinos_skip_user_sync = True
	doc.save(ignore_permissions=True)
	return doc


def on_user_update(user_doc):
	"""User.on_update: carry roles ticked or unticked on the User form into the memberships."""
	if not enabled() or user_doc.flags.alpinos_company_sync or user_doc.name in ("Administrator", "Guest"):
		return
	if user_doc.user_type != "System User":
		return
	scoped = access.scoped_roles()
	before = user_doc.get_doc_before_save()
	prev = {r.role for r in before.roles} if before else set()
	cur = {r.role for r in user_doc.roles}
	added, removed = (cur - prev) & scoped, (prev - cur) & scoped
	managed = frappe.db.exists(MEMBERSHIP, {"user": user_doc.name})
	if not managed:
		if not (cur & scoped):
			return
		added = cur & scoped
	if added:
		ensure_membership(user_doc.name, home_company(user_doc.name), sorted(added), source="User Form")
	if removed:
		for name in frappe.get_all(MEMBERSHIP, {"user": user_doc.name}, pluck="name"):
			doc = frappe.get_doc(MEMBERSHIP, name)
			keep = [r for r in doc.roles if r.role not in removed]
			if len(keep) != len(doc.roles):
				doc.set("roles", keep)
				doc.flags.alpinos_skip_user_sync = True
				doc.save(ignore_permissions=True)
	sync_user(user_doc.name)


def on_employee_update(doc, method=None):
	"""Employee.on_update: a user is always a member of their own Employee's company.

	The automatic membership has no roles; it lets global roles (Employee self-service, a
	manager's approvals) reach that company. When the Employee moves company, an automatic
	membership left empty in the old company is removed.
	"""
	if not enabled() or not doc.user_id or doc.status == "Left":
		return
	if not frappe.db.exists("User", doc.user_id):
		return
	ensure_membership(doc.user_id, doc.company, source="Employee", is_default=None)
	before = doc.get_doc_before_save()
	old = before.company if before else None
	if old and old != doc.company:
		name = frappe.db.get_value(MEMBERSHIP, {"user": doc.user_id, "company": old, "source": "Employee"})
		if name and not frappe.get_all("Company Membership Role", {"parent": name}, limit=1):
			frappe.delete_doc(MEMBERSHIP, name, ignore_permissions=True, flags={"alpinos_skip_user_sync": True})
	sync_user(doc.user_id)


def on_role_update(doc, method=None):
	"""Role saved: a role newly ticked 'Company-wise role' keeps every holder's access by
	putting it into each of their memberships; unticked, it simply becomes global again."""
	access.clear_cache()
	if not enabled():
		return
	before = doc.get_doc_before_save()
	was = bool(before and before.get("custom_company_scoped"))
	now = bool(doc.get("custom_company_scoped"))
	if was and not now:
		# Global again: it now lives on the User and applies everywhere, so it leaves the
		# memberships (whose roles must be company-wise).
		frappe.db.delete("Company Membership Role", {"role": doc.name})
	if now and not was:
		holders = frappe.get_all("Has Role", {"parenttype": "User", "role": doc.name}, pluck="parent")
		for user in holders:
			for name in frappe.get_all(MEMBERSHIP, {"user": user}, pluck="name"):
				m = frappe.get_doc(MEMBERSHIP, name)
				if doc.name not in {r.role for r in m.roles}:
					m.append("roles", {"role": doc.name})
					m.flags.alpinos_skip_user_sync = True
					m.save(ignore_permissions=True)
	access.clear_cache()


def on_role_profile_update(doc, method=None):
	if not enabled():
		return
	for user in frappe.get_all(MEMBERSHIP, {"role_profile": doc.name}, pluck="user", distinct=True):
		sync_user(user)


def on_company_change(doc, method=None):
	access.clear_cache()


# --- everyone ------------------------------------------------------------------------------


def reconcile_all():
	"""Nightly, and when the feature is turned on: every managed user back in line.

	ERPNext adds a Company User Permission whenever an Employee gets a user, and never takes
	it away when the Employee moves company; this undoes that drift.
	"""
	if not enabled():
		return
	for user in frappe.get_all(MEMBERSHIP, pluck="user", distinct=True):
		try:
			sync_user(user)
		except Exception:
			frappe.log_error(title=f"Company-wise access: could not sync {user}")
