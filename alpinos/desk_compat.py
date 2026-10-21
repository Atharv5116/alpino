"""Frappe 16 desk fixes applied at import, like print_compat.

Heatmap dashboard charts (the "work from home" chart) always fail on Frappe 16.52:
get_heatmap_chart_config calls datetime.date(year, 1, 1) on the datetime CLASS the module
imports ("descriptor 'date' ... doesn't apply to a 'int' object"), and then passes
unix_timestamp(<field>) as a string field, which Frappe 16's query builder refuses. This
replacement reads the year's rows and counts them per day in Python. Frappe 15 is untouched.
"""

import frappe


def apply_heatmap_fix():
	try:
		from frappe.desk.doctype.dashboard_chart import dashboard_chart as dc
	except Exception:
		return
	original = getattr(dc, "get_heatmap_chart_config", None)
	if not original or getattr(original, "_alpinos_fixed", False) or int(frappe.__version__.split(".")[0]) < 16:
		return

	def get_heatmap_chart_config(chart, filters, heatmap_year):
		import datetime as dt

		from frappe.utils import cint, flt, get_datetime, getdate, nowdate

		doctype, datefield = chart.document_type, chart.based_on
		value_field = chart.value_based_on
		year = cint(heatmap_year) if heatmap_year else getdate(nowdate()).year
		filters.append([doctype, datefield, ">", str(dt.date(year, 1, 1))])
		filters.append([doctype, datefield, "<", str(dt.date(year + 1, 1, 1))])
		fields = [datefield] + ([value_field] if value_field and value_field != datefield else [])
		per_day = {}
		for row in frappe.get_all(doctype, fields=fields, filters=filters, as_list=1, ignore_ifnull=True):
			if not row[0]:
				continue
			day = getdate(row[0])
			stamp = int(get_datetime(f"{day} 00:00:00").timestamp())
			agg = per_day.setdefault(stamp, [0, 0.0])
			agg[0] += 1
			agg[1] += flt(row[1]) if len(row) > 1 else 0
		kind = (chart.chart_type or "Count").lower()
		data = {
			stamp: (n if kind == "count" else total if kind == "sum" else (total / n if n else 0))
			for stamp, (n, total) in per_day.items()
		}
		return {"labels": [], "dataPoints": data}

	get_heatmap_chart_config._alpinos_fixed = True
	dc.get_heatmap_chart_config = get_heatmap_chart_config


def apply_raven_push_fix():
	"""Raven 3 sends no push notification at all from a site in developer mode (its guard against
	restored backups on a laptop notifying real phones). Production runs in developer mode by
	choice, so every push stopped after the upgrade; Raven 2 on Frappe 15 had no such rule.
	A site whose site_config sets raven_push_in_developer_mode gets pushes again; localhost stays
	silent, and every other site keeps Raven's rule unchanged."""
	try:
		import raven.notification as rn
	except Exception:
		return
	original = getattr(rn, "push_disabled", None)
	if not original or getattr(original, "_alpinos_fixed", False):
		return

	def push_disabled():
		if frappe.conf.get("raven_push_in_developer_mode"):
			url = frappe.utils.get_url(allow_header_override=False)
			return url.startswith("http://localhost") or url.startswith("http://127.0.0.1")
		return original()

	push_disabled._alpinos_fixed = True
	rn.push_disabled = push_disabled
