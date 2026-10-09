"""Carry the Invoice Download Page's old sidebar "Saved Filters" into Saved Views.

Before the queue was rebuilt, a user could save a set of filters by name in the page
sidebar; they lived in that user's settings under `invoice_download_queue`. The rebuilt
page saves views instead (columns, order, filters, sort) and has no sidebar, so without
this those saved filter sets would silently disappear.

Each one becomes a view with the default columns and the default sort. Single-date
filters from the old page become a one-day From/To range. A view of the same name the
user already has is left alone.
"""

import json

import frappe

SETTINGS_KEY = "invoice_download_queue"
PAGE_ROUTE = "invoice-download-queue"


def _filters(old):
	f = dict(old or {})
	for single, pair in (("order_date", "order_date"), ("dispatch_date", "dispatch_date")):
		if f.get(single):
			f[f"{pair}_from"] = f[single]
			f[f"{pair}_to"] = f[single]
		f.pop(single, None)
	return {k: v for k, v in f.items() if v not in (None, "")}


def execute():
	if not frappe.db.table_exists("Alpino Saved View") or not frappe.db.table_exists("__UserSettings"):
		return
	from alpinos.invoice_queue_api import DEFAULT_COLUMNS

	rows = frappe.db.sql(
		"SELECT `user`, `data` FROM `__UserSettings` WHERE `doctype` = %s", SETTINGS_KEY, as_dict=True
	)
	for row in rows:
		try:
			data = json.loads(row.data or "{}")
		except ValueError:
			continue
		for entry in data.get("saved_filters") or []:
			title = (entry.get("title") or "").strip()
			if not title or not frappe.db.exists("User", row.user):
				continue
			if frappe.db.exists(
				"Alpino Saved View", {"user": row.user, "page_route": PAGE_ROUTE, "view_name": title}
			):
				continue
			doc = frappe.new_doc("Alpino Saved View")
			doc.update({
				"view_name": title,
				"page_route": PAGE_ROUTE,
				"user": row.user,
				"columns_json": json.dumps(list(DEFAULT_COLUMNS)),
				"filters_json": json.dumps(_filters(entry.get("filters"))),
				"sort_field": "order_date",
				"sort_dir": "desc",
				"is_default": 0,
			})
			doc.flags.ignore_permissions = True
			# Written as Administrator for another user, which validate() allows only
			# to a System Manager; a patch runs as Administrator.
			doc.insert(ignore_permissions=True)
