"""Computed columns for frappe.get_all / get_list that read the same on v15 and v16.

v16's query engine rejects an SQL function written as a string in `fields`
("count(name) as total") and accepts only plain field names or a field alias in
`order_by`. v15's db_query knows nothing of the dict form v16 wants instead. These
helpers return whichever form the running Frappe understands, so a call site reads the
same on both and the app can be deployed to v15 before the upgrade.

Sorting on an expression: `sort_by_expression()`. v16 needs the expression selected under
an alias and ordered by the alias; v15's get_list refuses some functions in a select
column (NULLIF) but takes any expression in ORDER BY, which is what it always did.
"""

import frappe

IS_V16 = int(frappe.__version__.split(".")[0]) >= 16


def agg(func, field, alias):
	"""An aggregate column, e.g. agg("count", "name", "total") for `count(name) as total`."""
	if IS_V16:
		return {func.upper(): field, "as": alias}
	return f"{func.lower()}({field}) as {alias}"


def sort_by_expression(v15_sql, v16_spec, alias, direction):
	"""(extra fields, order_by) that sort a list on an SQL expression.

	Add the extra fields to the call's `fields`; on v15 there are none and the expression
	goes straight into ORDER BY as before.
	"""
	if IS_V16:
		return [{**v16_spec, "as": alias}], f"{alias} {direction}"
	return [], f"{v15_sql} {direction}"
