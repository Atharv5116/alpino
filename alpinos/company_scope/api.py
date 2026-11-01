"""Whitelisted methods: the switcher, the boot data, workflow buttons, and the Company
Access Manager page."""

import json

import frappe
from frappe import _
from frappe.permissions import get_rights

from alpinos.company_scope import ALL, access, active, enabled, exempt_user, registry, sync

MANAGER_ROLE = "System Manager"
_COLORS = ("#2563eb", "#16a34a", "#d97706", "#9333ea", "#dc2626", "#0891b2", "#4f46e5", "#be185d")


# --- boot and switcher ---------------------------------------------------------------------


def context(user=None):
	"""What the desk needs to draw the switcher; None when the feature does not apply."""
	user = user or frappe.session.user
	if not enabled() or exempt_user(user) or not access.is_managed(user):
		return None
	companies = access.all_companies()
	members = access.member_companies(user)
	rows = []
	for company in members:
		abbr = access.company_abbr(company) or company[:3].upper()
		rows.append({"name": company, "abbr": abbr, "color": _COLORS[companies.index(company) % len(_COLORS)]})
	selection = active.get_active(user)
	return {
		"active": selection,
		"all_mode": selection == ALL,
		"default": access.default_company(user),
		"companies": rows,
		# Doctypes with a company field that are not company-wise (the form does not block them).
		"global_doctypes": sorted(registry.GLOBAL_DOCTYPES),
	}


def extend_bootinfo(bootinfo):
	try:
		bootinfo.alpinos_company = context()
	except Exception:
		bootinfo.alpinos_company = None
		frappe.log_error(title="Company-wise access: boot")


@frappe.whitelist()
def get_context():
	return context()


@frappe.whitelist(methods=["POST"])
def switch_company(company: str):
	"""Work in `company` (or "__all__" for All my companies). Every tab of the user reloads."""
	user = frappe.session.user
	if not enabled() or not access.is_managed(user):
		frappe.throw(_("Company-wise access is not set up for you."))
	active.set_active(user, company)
	frappe.publish_realtime("alpinos_company_switched", {"company": company}, user=user, after_commit=True)
	return context(user)


@frappe.whitelist()
def doctype_access(doctype: str):
	"""Per member company, what the current user may do on a doctype (lists hide New with it)."""
	user = frappe.session.user
	if not enabled() or not access.is_managed(user):
		return None
	out = {}
	for company, (full, owner) in access.company_rights(doctype, user).items():
		if company in access.member_companies(user):
			out[company] = sorted(full)
	return out


@frappe.whitelist()
def get_transitions(doc, workflow=None, raise_exception=False):
	"""frappe.model.workflow.get_transitions, keeping only transitions whose role the user
	holds in the document's company."""
	from frappe.model.document import Document
	from frappe.model.workflow import get_transitions as frappe_get_transitions

	if not isinstance(doc, Document):
		doc = frappe.get_doc(frappe.parse_json(doc))
		doc.load_from_db()
	transitions = frappe_get_transitions(doc, workflow, raise_exception)
	user = frappe.session.user
	if not enabled() or exempt_user(user) or not access.is_managed(user):
		return transitions
	mode, field = registry.mode(doc.doctype)
	company = doc.get(field) if mode == registry.STRICT else None
	if not company:
		return transitions
	roles = access.effective_roles(user, company)
	return [t for t in transitions if t.get("allowed") in roles]


# --- Company Access Manager page -----------------------------------------------------------


def _only_manager():
	frappe.only_for(MANAGER_ROLE)


@frappe.whitelist()
def manager_overview():
	"""Companies, company-wise roles, global roles and users, for the manager page."""
	_only_manager()
	companies = [
		{"name": c, "abbr": access.company_abbr(c), "series_code": frappe.db.get_value("Company", c, "custom_series_code")}
		for c in access.all_companies()
	]
	roles = frappe.get_all(
		"Role", filters={"disabled": 0, "name": ["not in", ["Administrator", "Guest", "All", "Desk User"]]},
		fields=["name", "custom_company_scoped as scoped", "desk_access"], order_by="name asc",
	)
	counts = {}
	for r in frappe.db.sql(
		"select user, count(*) from `tabCompany Membership` where enabled = 1 group by user", as_list=True
	):
		counts[r[0]] = r[1]
	users = frappe.get_all(
		"User",
		filters={"enabled": 1, "user_type": "System User", "name": ["not in", ["Administrator", "Guest"]]},
		fields=["name", "full_name"], order_by="full_name asc",
	)
	for u in users:
		u["companies"] = counts.get(u.name, 0)
	return {
		"enabled": enabled(),
		"companies": companies,
		"roles": roles,
		"users": users,
		"seeded_on": frappe.db.get_single_value("Alpino General Settings", "company_scope_seeded_on"),
	}


@frappe.whitelist()
def get_user_access(user: str):
	_only_manager()
	rows = {
		m.company: m
		for m in frappe.get_all(
			"Company Membership", {"user": user},
			["name", "company", "enabled", "is_default", "role_profile", "source"],
		)
	}
	role_rows = {}
	if rows:
		for r in frappe.get_all(
			"Company Membership Role", {"parent": ["in", [m.name for m in rows.values()]]}, ["parent", "role"]
		):
			role_rows.setdefault(r.parent, []).append(r.role)
	scoped = access.scoped_roles()
	user_roles = set(frappe.get_all("Has Role", {"parenttype": "User", "parent": user}, pluck="role"))
	out = []
	for company in access.all_companies():
		m = rows.get(company)
		out.append(
			{
				"company": company,
				"member": bool(m and m.enabled),
				"exists": bool(m),
				"is_default": bool(m and m.is_default),
				"role_profile": m.role_profile if m else None,
				"source": m.source if m else None,
				"roles": sorted(role_rows.get(m.name, [])) if m else [],
			}
		)
	return {
		"user": user,
		"full_name": frappe.db.get_value("User", user, "full_name"),
		"rows": out,
		"global_roles": sorted(user_roles - scoped - {"All", "Guest", "Desk User"}),
		"employee_company": frappe.db.get_value("Employee", {"user_id": user, "status": ["!=", "Left"]}, "company"),
		"active": active._stored(user),
	}


@frappe.whitelist(methods=["POST"])
def save_user_access(user: str, rows: str | list):
	"""Write every company's membership of a user in one go."""
	_only_manager()
	rows = frappe.parse_json(rows) if isinstance(rows, str) else rows
	scoped = access.scoped_roles()
	defaults = [r for r in rows if r.get("member") and r.get("is_default")]
	if len(defaults) > 1:
		frappe.throw(_("Pick one default company."))
	for row in rows:
		company = row["company"]
		name = frappe.db.get_value("Company Membership", {"user": user, "company": company})
		member = bool(row.get("member"))
		roles = [r for r in row.get("roles") or [] if r in scoped]
		if not name and not member:
			continue
		doc = frappe.get_doc("Company Membership", name) if name else frappe.new_doc("Company Membership")
		if not name:
			doc.update({"user": user, "company": company, "source": "Manual"})
		doc.enabled = 1 if member else 0
		doc.is_default = 1 if (member and row.get("is_default")) else 0
		doc.role_profile = row.get("role_profile") or None
		doc.set("roles", [{"role": r} for r in sorted(set(roles))])
		doc.flags.alpinos_skip_user_sync = True
		doc.save()
	sync.sync_user(user)
	return get_user_access(user)


@frappe.whitelist()
def get_company_users(company: str):
	_only_manager()
	members = frappe.get_all(
		"Company Membership", {"company": company},
		["name", "user", "enabled", "is_default", "role_profile", "source"], order_by="user asc",
	)
	roles = {}
	for r in frappe.get_all(
		"Company Membership Role", {"parent": ["in", [m.name for m in members] or ["-"]]}, ["parent", "role"]
	):
		roles.setdefault(r.parent, []).append(r.role)
	names = {u.name: u.full_name for u in frappe.get_all("User", {"name": ["in", [m.user for m in members] or ["-"]]}, ["name", "full_name"])}
	for m in members:
		m["roles"] = sorted(roles.get(m.name, []))
		m["full_name"] = names.get(m.user)
	return members


@frappe.whitelist()
def effective_access(user: str, doctype: str):
	"""Per company, what `user` can do on `doctype` (the preview grid)."""
	_only_manager()
	shown = ("read", "write", "create", "submit", "cancel", "delete", "print", "report", "export")
	rights = [r for r in shown if r in get_rights(doctype)]
	out = []
	members = set(access.member_companies(user))
	mode = registry.mode(doctype)[0]
	for company, (full, owner) in access.company_rights(doctype, user).items():
		cells = {}
		for r in rights:
			cells[r] = "yes" if r in full else ("own" if r in owner else "")
		# A user who is not a member of a company reaches its documents only through a share
		# (Company User Permissions keep the rest out), so show that row as no access.
		if mode != registry.GLOBAL and company not in members:
			cells = {r: "" for r in rights}
		out.append({"company": company, "member": company in members, "rights": cells,
			"roles": sorted(access.effective_roles(user, company) - {"All", "Guest"})})
	return {"doctype": doctype, "mode": mode, "rights": rights, "rows": out}


@frappe.whitelist(methods=["POST"])
def set_role_scoped(role: str, scoped: int):
	"""Tick or untick 'Company-wise role' (from Role Permissions Manager)."""
	_only_manager()
	doc = frappe.get_doc("Role", role)
	doc.custom_company_scoped = 1 if int(scoped) else 0
	doc.save()
	return {"role": role, "scoped": doc.custom_company_scoped}


@frappe.whitelist(methods=["POST"])
def set_enabled(on: int):
	"""Turn Company-wise access on (users are set up once, from what they have today) or off."""
	_only_manager()
	settings = frappe.get_single("Alpino General Settings")
	settings.company_scope_enabled = 1 if int(on) else 0
	settings.save()
	return {"enabled": settings.company_scope_enabled, "seeded_on": settings.company_scope_seeded_on}
