"""Query and script reports follow the companies a user may see.

Frappe runs reports without permission_query_conditions, so this wraps
frappe.desk.query_report.get_report_result, the one place every report run goes through
(the report view, Export, and prepared reports run in a background job as their owner):

- a `company` filter outside the user's companies is refused;
- a report with a Company column loses rows of companies the user may not see.

Applied from the before_request / before_job hooks, like stock_ledger_batch; idempotent.
"""

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
		result = original(report, filters)
		if active and result:
			result = _drop_rows(report, result, user)
		return result

	get_report_result._alpinos_cs = True
	query_report.get_report_result = get_report_result


def _visible(report, user):
	ref = report.get("ref_doctype")
	from alpinos.company_scope import registry

	if ref and registry.mode(ref)[0] == registry.STRICT:
		return set(access.allowed_companies(ref, "read", user)) & set(access.member_companies(user))
	return set(access.member_companies(user))


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
