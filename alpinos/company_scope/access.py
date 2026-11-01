"""Who can do what in which company.

effective_roles(user, company) = the user's global roles + the company-wise roles of their
membership in that company. allowed_companies() reads the doctype's permission rules (the
same DocPerm / Custom DocPerm rows Role Permissions Manager edits) against those roles, the
way frappe.permissions.get_role_permissions does for the pooled roles.

Caches: memberships per user and the list of company-wise roles live in Redis (cleared when
a Company Membership, Role or Company changes); everything derived from them is memoised for
the request only, so a Role Permissions Manager edit applies on the next request.
"""

import frappe
from frappe.permissions import AUTOMATIC_ROLES, get_rights
from frappe.utils import cint

from alpinos.company_scope import ALL, exempt_user

MEMBERSHIP = "Company Membership"
_CACHE_MEMBERS = "alpinos_cs_memberships"
_CACHE_SCOPED_ROLES = "alpinos_cs_scoped_roles"
_CACHE_COMPANIES = "alpinos_cs_companies"


# --- reference data ------------------------------------------------------------------------


def all_companies():
	"""Every company, in name order."""

	def load():
		return frappe.get_all("Company", pluck="name", order_by="name asc")

	return frappe.cache.get_value(_CACHE_COMPANIES, load)


def company_abbr(company):
	return frappe.get_cached_value("Company", company, "abbr") if company else None


def scoped_roles():
	"""Roles ticked 'Company-wise role'."""

	def load():
		if not frappe.db.has_column("Role", "custom_company_scoped"):
			return []
		return frappe.get_all("Role", {"custom_company_scoped": 1}, pluck="name")

	return set(frappe.cache.get_value(_CACHE_SCOPED_ROLES, load))


def clear_cache(user=None):
	"""Forget memberships (one user's, or everyone's) and the role / company lists."""
	if user:
		frappe.cache.hdel(_CACHE_MEMBERS, user)
	else:
		frappe.cache.delete_value(_CACHE_MEMBERS)
	frappe.cache.delete_value(_CACHE_SCOPED_ROLES)
	frappe.cache.delete_value(_CACHE_COMPANIES)
	from alpinos.company_scope import reset_request_cache

	reset_request_cache()


# --- memberships ---------------------------------------------------------------------------


def _load_memberships(user):
	rows = frappe.get_all(
		MEMBERSHIP,
		filters={"user": user, "enabled": 1},
		fields=["name", "company", "is_default", "role_profile"],
		order_by="is_default desc, company asc",
	)
	if not rows:
		return []
	names = [r.name for r in rows]
	roles = {}
	for r in frappe.get_all(
		"Company Membership Role",
		filters={"parent": ["in", names], "parenttype": MEMBERSHIP},
		fields=["parent", "role"],
	):
		roles.setdefault(r.parent, set()).add(r.role)
	profiles = {r.role_profile for r in rows if r.role_profile}
	profile_roles = {}
	if profiles:
		for r in frappe.get_all(
			"Has Role",
			filters={"parenttype": "Role Profile", "parent": ["in", list(profiles)]},
			fields=["parent", "role"],
		):
			profile_roles.setdefault(r.parent, set()).add(r.role)
	out = []
	for r in rows:
		granted = set(roles.get(r.name, set())) | profile_roles.get(r.role_profile, set())
		out.append({"company": r.company, "is_default": cint(r.is_default), "roles": sorted(granted)})
	return out


def memberships(user=None):
	"""[{company, is_default, roles}] of the user's enabled memberships, default first."""
	user = user or frappe.session.user
	local = getattr(frappe.local, "alpinos_cs_members", None)
	if local is None:
		local = frappe.local.alpinos_cs_members = {}
	if user not in local:
		local[user] = frappe.cache.hget(_CACHE_MEMBERS, user, lambda: _load_memberships(user))
	return local[user]


def is_managed(user=None):
	"""True when the user has at least one membership: only then does anything here apply."""
	return bool(memberships(user))


def member_companies(user=None):
	"""Companies the user is a member of, default first."""
	return [m["company"] for m in memberships(user)]


def default_company(user=None):
	ms = memberships(user)
	for m in ms:
		if m["is_default"]:
			return m["company"]
	return ms[0]["company"] if ms else None


def global_roles(user=None):
	user = user or frappe.session.user
	return set(frappe.get_roles(user)) - scoped_roles()


def company_roles(user, company):
	"""The company-wise roles of the user's membership in `company` (empty if not a member)."""
	scoped = scoped_roles()
	for m in memberships(user):
		if m["company"] == company:
			return set(m["roles"]) & scoped
	return set()


def effective_roles(user, company):
	"""Roles that count for the user in `company`."""
	user = user or frappe.session.user
	if user == "Administrator":
		return set(frappe.get_roles(user))
	return global_roles(user) | company_roles(user, company)


def roles_for(user=None, company=None):
	"""The roles to check before acting on a document of `company`: the user's roles in that
	company, or simply frappe.get_roles() when there is no company / the feature is off /
	the user is not managed."""
	user = user or frappe.session.user
	from alpinos.company_scope import enabled

	if company and enabled() and user != "Administrator" and is_managed(user):
		return effective_roles(user, company)
	return set(frappe.get_roles(user))


def has_company_role(roles, company, user=None):
	"""True if the user holds any of `roles` in `company` (global roles count everywhere).

	Use it where code used to test `role in frappe.get_roles()` before acting on a document
	of a known company.
	"""
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	if isinstance(roles, str):
		roles = [roles]
	from alpinos.company_scope import enabled

	if not enabled() or not is_managed(user) or not company:
		return bool(set(roles) & set(frappe.get_roles(user)))
	return bool(set(roles) & effective_roles(user, company))


# --- rights --------------------------------------------------------------------------------


def _rights_for_roles(meta, roles):
	"""(full rights, owner-only rights) the roles give on a doctype at permlevel 0.

	Mirrors frappe.permissions.get_role_permissions, including its "if owner" rule: a right
	that only "Only If Creator" rows give is an owner-only right (read / select still list).
	"""
	applicable = [p for p in (meta.permissions or []) if p.role in roles and cint(p.permlevel) == 0]
	has_if_owner = any(cint(p.get("if_owner")) for p in applicable)
	full, owner = set(), set()
	for ptype in get_rights(meta.name):
		if not any(cint(p.get(ptype)) for p in applicable):
			continue
		without_owner = any(cint(p.get(ptype)) and not cint(p.get("if_owner")) for p in applicable)
		if has_if_owner and not without_owner and ptype != "create":
			owner.add(ptype)
		else:
			full.add(ptype)
	return full, owner


def company_rights(doctype, user=None):
	"""{company: (full rights, owner-only rights)} for every company. Memoised per request."""
	user = user or frappe.session.user
	cache = getattr(frappe.local, "alpinos_cs_rights", None)
	if cache is None:
		cache = frappe.local.alpinos_cs_rights = {}
	key = (user, doctype)
	if key in cache:
		return cache[key]
	meta = frappe.get_meta(doctype)
	glob = global_roles(user)
	out = {}
	by_roles = {}
	for company in all_companies():
		roles = frozenset(glob | company_roles(user, company))
		if roles not in by_roles:
			by_roles[roles] = _rights_for_roles(meta, roles)
		out[company] = by_roles[roles]
	cache[key] = out
	return out


def _wants(ptype, full, owner, is_owner):
	ptypes = ("select", "read") if ptype == "select" else (ptype,)
	return any(p in full or (is_owner and p in owner) for p in ptypes)


def allowed_companies(doctype, ptype="read", user=None, is_owner=False):
	"""Companies where the user's roles give `ptype` on `doctype`.

	Not narrowed to the active company: this is what the user may do at all.
	"""
	user = user or frappe.session.user
	if exempt_user(user):
		return list(all_companies())
	return [c for c, (full, owner) in company_rights(doctype, user).items() if _wants(ptype, full, owner, is_owner)]


def read_split(doctype, user=None):
	"""(companies with read, companies where only own documents can be read)."""
	user = user or frappe.session.user
	full_read, owner_read = [], []
	for company, (full, owner) in company_rights(doctype, user).items():
		if "read" in full or "select" in full:
			full_read.append(company)
		elif "read" in owner or "select" in owner:
			owner_read.append(company)
	return full_read, owner_read


# --- active company ------------------------------------------------------------------------


def active_selection(user=None):
	"""The company the user works in, ALL for "All my companies", or None (not managed)."""
	user = user or frappe.session.user
	if exempt_user(user) or not is_managed(user):
		return None
	from alpinos.company_scope import active

	return active.get_active(user)


def active_companies(user=None):
	"""Companies lists and reports show: [active], the member companies in All mode, or None
	when nothing narrows (not managed / Administrator)."""
	selection = active_selection(user)
	if selection is None:
		return None
	if selection == ALL:
		return member_companies(user)
	return [selection]


def scope(doctype=None, ptype="read", user=None, narrow=True):
	"""Companies the user may see right now for `doctype`: allowed and (if narrow) active.

	Without a doctype: the member companies (narrowed to the active one).
	Returns None when nothing restricts (company-wise access off, Administrator, not managed).
	"""
	from alpinos.company_scope import enabled

	user = user or frappe.session.user
	if not enabled() or exempt_user(user) or not is_managed(user):
		return None
	if doctype:
		allowed = allowed_companies(doctype, ptype, user)
	else:
		allowed = member_companies(user)
	if narrow:
		act = active_companies(user)
		if act is not None:
			allowed = [c for c in allowed if c in act]
	return allowed


def users_with_roles(roles, company=None, enabled_only=True):
	"""Users holding any of `roles` in `company` (global holders always; company-wise holders
	only through a membership in that company). Without a company: every holder."""
	if isinstance(roles, str):
		roles = [roles]
	roles = [r for r in roles if r not in AUTOMATIC_ROLES]
	if not roles:
		return []
	filters = {"parenttype": "User", "role": ["in", roles]}
	holders = set(frappe.get_all("Has Role", filters=filters, pluck="parent", distinct=True))
	if enabled_only and holders:
		holders = set(frappe.get_all("User", {"name": ["in", list(holders)], "enabled": 1}, pluck="name"))
	from alpinos.company_scope import enabled

	if not company or not enabled():
		return sorted(holders)
	out = []
	for user in sorted(holders):
		if user == "Administrator" or not is_managed(user):
			out.append(user)
			continue
		if set(roles) & effective_roles(user, company):
			out.append(user)
	return out
