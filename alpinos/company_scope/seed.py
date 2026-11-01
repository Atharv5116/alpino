"""Turning Company-wise access on: every user keeps exactly the access they have today.

For each enabled desk user without a membership:
- the companies = their Company User Permissions; none = every company (today they are not
  restricted at all, e.g. System Managers);
- in each of those companies they get every company-wise role they hold today;
- their own Employee's company is added as a membership too (no roles), which lets their
  global roles - self-service, approvals - reach it. Three Hospitality employees are today
  restricted to Alpino Health Foods; this is what puts them back in their own company.
- the default company is their Employee's company when they are a member of it, else the
  global default company when they are, else the first.

report() lists what apply() would do; apply() is idempotent (users with a membership are
skipped), so turning the feature off and on again changes nothing.
"""

import frappe
from frappe.utils import now_datetime

from alpinos.company_scope import access, sync


def _users():
	return frappe.get_all(
		"User",
		filters={"enabled": 1, "user_type": "System User", "name": ["not in", ["Administrator", "Guest"]]},
		pluck="name",
		order_by="name asc",
	)


def plan_for(user, scoped=None, companies=None, global_default=None):
	scoped = access.scoped_roles() if scoped is None else scoped
	companies = access.all_companies() if companies is None else companies
	if global_default is None:
		global_default = frappe.db.get_single_value("Global Defaults", "default_company")
	ups = frappe.get_all("User Permission", {"user": user, "allow": "Company"}, pluck="for_value")
	targets = [c for c in companies if c in set(ups)] if ups else list(companies)
	roles = sorted(set(frappe.get_all("Has Role", {"parenttype": "User", "parent": user}, pluck="role")) & scoped)
	employee_company = frappe.db.get_value("Employee", {"user_id": user, "status": ["!=", "Left"]}, "company")
	extra = employee_company if employee_company and employee_company not in targets else None
	if employee_company and employee_company in targets:
		default = employee_company
	elif global_default in targets:
		default = global_default
	else:
		default = targets[0] if targets else employee_company
	return {
		"user": user,
		"companies": targets,
		"roles": roles,
		"employee_company": employee_company,
		"extra_employee_membership": extra,
		"default": default,
		"restricted_today": bool(ups),
	}


def report():
	"""What apply() would do, user by user (only users without a membership)."""
	scoped = access.scoped_roles()
	companies = access.all_companies()
	gd = frappe.db.get_single_value("Global Defaults", "default_company")
	out = []
	for user in _users():
		if frappe.db.exists("Company Membership", {"user": user}):
			continue
		out.append(plan_for(user, scoped, companies, gd))
	return out


def apply():
	"""Create the memberships, then bring every user's roles and permissions in line."""
	plans = report()
	for p in plans:
		for company in p["companies"]:
			sync.ensure_membership(
				p["user"], company, p["roles"], source="Seed", is_default=(company == p["default"])
			)
		if p["extra_employee_membership"]:
			sync.ensure_membership(
				p["user"], p["extra_employee_membership"], (), source="Employee",
				is_default=(p["extra_employee_membership"] == p["default"]),
			)
	frappe.db.set_single_value("Alpino General Settings", "company_scope_seeded_on", now_datetime())
	sync.reconcile_all()
	return plans


def on_settings_update(doc, method=None):
	"""Alpino General Settings saved: turning the feature on sets every user up once."""
	before = doc.get_doc_before_save()
	was = bool(before and before.get("company_scope_enabled"))
	now = bool(doc.get("company_scope_enabled"))
	from alpinos.company_scope import reset_request_cache

	reset_request_cache()
	access.clear_cache()
	if now and not was:
		frappe.local.alpinos_cs_enabled = True
		apply()
	frappe.clear_cache()
