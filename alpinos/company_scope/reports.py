"""Query and script reports follow the companies a user may see.

Frappe runs reports without permission_query_conditions, so this wraps
frappe.desk.query_report.get_report_result, the one place every report run goes through
(the report view, Export, and prepared reports run in a background job as their owner):

- a `company` filter outside the user's companies is refused;
- a report with a Company column loses rows of companies the user may not see;
- a Query Report written in the database (Daily Sales Offline, On Leave Today, Stock
  Movement...) reads every company table in its FROM / JOIN through a copy already cut to
  the user's companies, so its own SQL needs no company condition.

Applied from the before_request / before_job hooks, like stock_ledger_batch; idempotent.
"""

import re

import frappe
from frappe import _

from alpinos.company_scope import access, enabled, exempt_user


def patch(*args, **kwargs):
	try:
		import frappe.desk.query_report as query_report
	except Exception:
		return
	if getattr(query_report.get_report_result, "_alpinos_cs", False):
		return
	original = query_report.get_report_result

	def get_report_result(report, filters):
		user = frappe.session.user
		active = enabled() and not exempt_user(user) and access.is_managed(user)
		if active:
			_check_filters(report, filters, user)
			if report.get("report_type") == "Query Report" and report.get("query"):
				report.query = scope_query(report.query, user)
		result = original(report, filters)
		if active and result:
			result = _drop_rows(report, result, user)
		return result

	get_report_result._alpinos_cs = True
	query_report.get_report_result = get_report_result


def _visible(report, user):
	"""Member companies where the user may run this report: where they hold one of the
	report's roles (its Report roles; for a report without roles, read on its ref doctype).
	Many reports are opened by roles that cannot read the ledger they summarise (QC, DN,
	Store users on Stock Balance), so the report's own roles decide, not the ref doctype."""
	members = access.member_companies(user)
	roles = set(frappe.get_all("Has Role", {"parenttype": "Report", "parent": report.name}, pluck="role")) if report.get("name") else set()
	if roles:
		return {c for c in members if roles & access.effective_roles(user, c)}
	ref = report.get("ref_doctype")
	from alpinos.company_scope import registry

	if ref and registry.mode(ref)[0] == registry.STRICT:
		return set(access.allowed_companies(ref, "read", user)) & set(members)
	return set(members)


_TABLE = re.compile(
	r"(?P<kw>\bfrom|\bjoin)\s+`tab(?P<dt>[^`]+)`(?:\s+(?:as\s+)?(?P<alias>(?!(?:where|on|left|right|inner|outer|cross|join|group|order|limit|having|union|straight_join|natural|using|for|lock|window)\b)[a-zA-Z_][a-zA-Z0-9_]*|`[^`]+`))?",
	re.IGNORECASE,
)


def scope_query(query, user):
	"""The query with each company table in FROM / JOIN read through a copy cut to the
	companies the user may read it in (aliases kept, so the rest of the SQL is untouched)."""
	from alpinos.company_scope import registry

	def replace(match):
		doctype = match.group("dt")
		mode, field = registry.mode(doctype)
		if mode != registry.STRICT:
			return match.group(0)
		companies = set(access.allowed_companies(doctype, "read", user)) & set(access.member_companies(user))
		values = ", ".join(frappe.db.escape(c) for c in sorted(companies)) or "''"
		alias = match.group("alias") or f"`tab{doctype}`"
		return (
			f"{match.group('kw')} (select * from `tab{doctype}` where ifnull(`{field}`, '') = '' "
			f"or `{field}` in ({values})) as {alias}"
		)

	return _TABLE.sub(replace, query)


def _check_filters(report, filters, user):
	if not isinstance(filters, dict):
		return
	value = filters.get("company")
	if not value:
		return
	asked = value if isinstance(value, list | tuple) else [value]
	visible = _visible(report, user)
	wrong = [c for c in asked if c and c not in visible]
	if wrong:
		frappe.throw(
			_("You cannot run {0} for {1}.").format(_(report.name), ", ".join(frappe.bold(c) for c in wrong)),
			frappe.PermissionError,
		)


def _company_columns(columns):
	from frappe.desk.query_report import get_column_as_dict

	out = []
	for index, col in enumerate(columns or []):
		try:
			c = get_column_as_dict(col)
		except Exception:
			continue
		if c.get("fieldtype") == "Link" and c.get("options") == "Company":
			out.append((index, c.get("fieldname")))
	return out


def _drop_rows(report, result, user):
	if not isinstance(result, list | tuple) or len(result) < 2:
		return result
	columns, rows = result[0], result[1]
	targets = _company_columns(columns)
	if not targets or not rows:
		return result
	visible = _visible(report, user)

	def keep(row):
		for index, fieldname in targets:
			if isinstance(row, dict):
				value = row.get(fieldname)
			elif isinstance(row, list | tuple) and index < len(row):
				value = row[index]
			else:
				value = None
			if value and value not in visible:
				return False
		return True

	kept = [r for r in rows if keep(r)]
	if len(kept) == len(rows):
		return result
	result = list(result)
	result[1] = kept
	return result
