"""The two "*" permission hooks: per-company rights on documents, and lists cut to the
companies the user may see.

has_permission (deny-only, every doctype):
    the document's company (STRICT) or tags (TAGGED) must be one where the user's roles in
    that company give the right asked for. For write-type rights the company stored in the
    database is checked too, so a document of company B cannot be "moved" into company A by
    posting it with A. Uses the hook's `user` argument, never the session user.

permission_query_conditions (every doctype):
    rows of companies the user may read; owner-only companies only for their own rows; blank
    company rows stay visible (a company-less row belongs to nobody). On listing endpoints -
    list view, report view, counts, link search, number cards - the rows are cut further to
    the active company ("All my companies" = every member company).

Both return at once for GLOBAL doctypes, Administrator, unmanaged users and while the
feature is off.
"""

import frappe

from alpinos.company_scope import access, enabled, exempt_user, registry
from alpinos.permission_compat import NO_OBJECTION

#: Rights checked against the stored company as well as the posted one.
_WRITE_TYPES = frozenset({"write", "submit", "cancel", "delete", "amend"})

#: Whitelisted methods that list documents for a person to browse.
LISTING_METHODS = frozenset(
	{
		"frappe.desk.reportview.get",
		"frappe.desk.reportview.get_list",
		"frappe.desk.reportview.get_count",
		"frappe.desk.reportview.export_query",
		"frappe.desk.reportview.get_sidebar_stats",
		"frappe.desk.reportview.get_stats",
		"frappe.desk.reportview.get_group_by_count",
		"frappe.desk.listview.get_group_by_count",
		"frappe.client.get_list",
		"frappe.client.get_count",
		"frappe.desk.search.search_link",
		"frappe.desk.search.search_widget",
		"frappe.desk.doctype.number_card.number_card.get_result",
		"frappe.desk.doctype.dashboard_chart.dashboard_chart.get",
		"frappe.desk.doctype.kanban_board.kanban_board.get_kanban_boards",
		"frappe.desk.calendar.get_events",
	}
)


def _skip(user):
	return not enabled() or exempt_user(user) or not access.is_managed(user)


def listing_request():
	"""True while serving a person's list, count, search or card - not a save."""
	if frappe.local.flags.get("alpinos_cs_listing"):
		return True
	if getattr(frappe.local, "job", None):
		return False
	request = getattr(frappe.local, "request", None)
	if not request:
		return False
	cmd = (frappe.local.form_dict or {}).get("cmd")
	if cmd in LISTING_METHODS:
		return True
	path = getattr(request, "path", "") or ""
	if request.method == "GET" and (path.startswith("/api/resource/") or path.startswith("/api/v2/document/")):
		# /api/resource/<doctype> lists; /api/resource/<doctype>/<name> reads one document.
		return path.rstrip("/").count("/") == 3
	return False


# --- has_permission ------------------------------------------------------------------------


def _doc_companies(doc, mode, field):
	if mode == registry.STRICT:
		value = doc.get(field)
		return [value] if value else []
	if mode == registry.SELF:
		return [doc.name] if doc.name else []
	if mode == registry.TAGGED:
		return tags_of(doc)
	return []


def tags_of(doc):
	"""Tagged companies of a master, from its loaded rows or its stored scope."""
	rows = doc.get(registry.TAG_FIELD)
	if rows:
		return [r.company if hasattr(r, "company") else r.get("company") for r in rows if r]
	scope = doc.get(registry.SCOPE_FIELD) or ""
	return [c for c in scope.split("|") if c]


def _is_owner(doc, user):
	return (doc.get("owner") or "").lower() == (user or "").lower()


def has_permission(doc, ptype=None, user=None, debug=False):
	user = user or frappe.session.user
	if _skip(user):
		return NO_OBJECTION
	mode, field = registry.mode(doc.doctype)
	if mode == registry.GLOBAL:
		return NO_OBJECTION
	ptype = ptype or "read"
	companies = _doc_companies(doc, mode, field)
	is_owner = _is_owner(doc, user)
	allowed = set(access.allowed_companies(doc.doctype, ptype, user, is_owner=is_owner))
	if mode == registry.TAGGED:
		if not companies:
			# Blank = every company: readable by anyone the roles allow; editable only by
			# someone with that right in a company (any one).
			return True if allowed else False
		if ptype in ("read", "select", "print", "email", "report", "export", "share"):
			return bool(allowed & set(companies))
		# Changing a shared master changes it for every tagged company.
		return set(companies) <= allowed
	if not companies:
		return NO_OBJECTION
	if companies[0] not in allowed:
		return False
	if mode == registry.STRICT and ptype in _WRITE_TYPES and not doc.get("__islocal") and doc.name:
		stored = _stored_company(doc.doctype, doc.name, field)
		if stored and stored != companies[0] and stored not in allowed:
			return False
	return NO_OBJECTION


def _stored_company(doctype, name, field):
	try:
		return frappe.db.get_value(doctype, name, field, cache=False)
	except Exception:
		return None


# --- permission_query_conditions -----------------------------------------------------------


def _in_list(column, companies):
	if not companies:
		return "1=0"
	return "{0} in ({1})".format(column, ", ".join(frappe.db.escape(c) for c in companies))


def query_conditions(user=None, doctype=None, **kwargs):
	user = user or frappe.session.user
	if not doctype or _skip(user):
		return ""
	mode, field = registry.mode(doctype)
	if mode == registry.GLOBAL:
		return ""
	full, owner_only = access.read_split(doctype, user)
	narrowing = listing_request()
	if narrowing:
		active = access.active_companies(user)
		if active is not None:
			full = [c for c in full if c in active]
			owner_only = [c for c in owner_only if c in active]
	everything = set(access.all_companies())
	table = f"`tab{doctype}`"

	if mode == registry.TAGGED:
		if set(full) >= everything:
			return ""
		column = f"{table}.`{registry.SCOPE_FIELD}`"
		parts = [f"ifnull({column}, '') = ''"]
		parts += ["{0} like {1}".format(column, frappe.db.escape(f"%|{c}|%")) for c in full]
		return "(" + " or ".join(parts) + ")"

	column = f"{table}.`{field}`" if mode == registry.STRICT else f"{table}.`name`"
	if set(full) >= everything and not owner_only:
		return ""
	parts = []
	if mode == registry.STRICT:
		parts.append(f"ifnull({column}, '') = ''")
	parts.append(_in_list(column, full))
	if owner_only:
		parts.append(
			"({0} and {1}.`owner` = {2})".format(_in_list(column, owner_only), table, frappe.db.escape(user))
		)
	return "(" + " or ".join(parts) + ")"
