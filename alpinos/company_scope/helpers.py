"""What alpinos pages and APIs use to follow the company.

Pages read with frappe.get_all / frappe.db.sql, which no permission hook reaches, so each
list or data endpoint adds the company itself:

    filters.update(company_filters("Purchase Order"))           # get_all / get_list dict
    where += company_sql("Sales Order", alias="so")              # raw SQL
    assert_company(doc, "write")                                 # before changing a document
    if has_company_role(["Purchase Manager"], doc.company): ...  # instead of frappe.get_roles()
    users_with_roles(["HR Manager"], company)                    # pickers and notifications
    current_company()                                            # a new document's company

All of them do nothing (return {} / "" / True) while company-wise access is off, for
Administrator, and for users without memberships, so an endpoint behaves as before then.
"""

import frappe
from frappe import _

from alpinos.company_scope import ALL, access, enabled, exempt_user, registry
from alpinos.company_scope.access import has_company_role, users_with_roles  # noqa: F401 (re-export)


def scope_companies(doctype=None, ptype="read", narrow=True):
	"""Companies the current user sees now (None = no restriction)."""
	return access.scope(doctype, ptype, narrow=narrow)


def company_filters(doctype=None, ptype="read", fieldname="company", narrow=True):
	"""A filters dict for frappe.get_all / get_list, {} when nothing restricts.

	For a TAGGED master pass its doctype; the filter then reads its company scope.
	"""
	companies = access.scope(doctype, ptype, narrow=narrow)
	if companies is None:
		return {}
	if doctype and registry.mode(doctype)[0] == registry.TAGGED:
		raise ValueError("Use tagged_condition() for a tagged master")
	if not companies:
		return {fieldname: ["in", ["__none__"]]}
	return {fieldname: ["in", companies]}


def company_filter_list(doctype=None, ptype="read", fieldname="company", narrow=True):
	"""The same as company_filters, as a [[field, "in", [...]]] list (for list-style filters)."""
	f = company_filters(doctype, ptype, fieldname, narrow)
	return [[k, v[0], v[1]] for k, v in f.items()]


def company_sql(doctype=None, alias=None, fieldname="company", ptype="read", narrow=True, blank=False):
	"""' and <alias>.company in (...)' for raw SQL, '' when nothing restricts.

	blank=True also keeps rows with no company.
	"""
	companies = access.scope(doctype, ptype, narrow=narrow)
	if companies is None:
		return ""
	column = f"`{alias}`.`{fieldname}`" if alias else f"`{fieldname}`"
	if not companies:
		return " and 1=0"
	values = ", ".join(frappe.db.escape(c) for c in companies)
	if blank:
		return f" and (ifnull({column}, '') = '' or {column} in ({values}))"
	return f" and {column} in ({values})"


def tagged_condition(doctype, alias=None, narrow=True):
	"""' and (<scope> blank or tagged for a visible company)' for a TAGGED master, in SQL."""
	companies = access.scope(None, narrow=narrow)
	if companies is None:
		return ""
	column = f"`{alias}`.`{registry.SCOPE_FIELD}`" if alias else f"`{registry.SCOPE_FIELD}`"
	parts = [f"ifnull({column}, '') = ''"]
	parts += ["{0} like {1}".format(column, frappe.db.escape(f"%|{c}|%")) for c in companies]
	return " and (" + " or ".join(parts) + ")"


def tagged_names(doctype, names, company=None):
	"""The subset of master names usable in `company` (default: the visible companies)."""
	if not names:
		return []
	from alpinos.company_scope import guard

	companies = [company] if company else access.scope(None)
	if companies is None:
		return list(names)
	scopes = guard._tag_scope(doctype, list(names))
	return [n for n, s in scopes.items() if not s or any(f"|{c}|" in s for c in companies)]


def assert_company(doc_or_company, doctype=None, ptype="write", user=None):
	"""Throw unless the user may `ptype` a `doctype` in that company."""
	user = user or frappe.session.user
	if not enabled() or exempt_user(user) or not access.is_managed(user):
		return True
	if isinstance(doc_or_company, str):
		company = doc_or_company
	else:
		doctype = doctype or doc_or_company.doctype
		field = registry.mode(doctype)[1] if doctype else "company"
		company = doc_or_company.get(field or "company")
	if not company:
		return True
	allowed = access.allowed_companies(doctype, ptype, user) if doctype else access.member_companies(user)
	if company not in allowed:
		frappe.throw(
			_("You do not have {0} access to {1} in {2}.").format(_(ptype), _(doctype or _("documents")), frappe.bold(company)),
			frappe.PermissionError,
			title=_("Not permitted in this company"),
		)
	return True


def current_company(user=None):
	"""The company a new document gets: the active one, else the user's default membership,
	else the user's `company` default, else Global Defaults."""
	user = user or frappe.session.user
	if enabled() and not exempt_user(user) and access.is_managed(user):
		selection = access.active_selection(user)
		if selection and selection != ALL:
			return selection
		default = access.default_company(user)
		if default:
			return default
	return (
		frappe.defaults.get_user_default("Company", user)
		or frappe.defaults.get_defaults_for(user).get("company")
		or frappe.db.get_single_value("Global Defaults", "default_company")
	)


def listing():
	"""Context manager: queries inside count as a person's list (narrowed to the active company)."""
	import contextlib

	@contextlib.contextmanager
	def _ctx():
		previous = frappe.local.flags.get("alpinos_cs_listing")
		frappe.local.flags.alpinos_cs_listing = True
		try:
			yield
		finally:
			frappe.local.flags.alpinos_cs_listing = previous

	return _ctx()
