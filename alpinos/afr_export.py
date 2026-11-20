"""Changes(HP) #110: when a Pick List was submitted, and every time an Accounts Format Report
row went out in an Excel export.

  * Pick List gets custom_submitted_on, stamped on submit; older Pick Lists are filled from
    their Version history (patch afr_pick_list_submitted_on).
  * A report row is one part of a Sales Order: (sales order, its Pick List), or (sales order,
    "") for an order with no Pick List (Only Invoice). Every successful export writes one
    Accounts Format Export Log per row key, and the report shows all of them, oldest first:
    "03-11-2026 11:30, 03-11-2026 12:45, 04-11-2026 10:15".
  * An export is logged in the same transaction as the file is built: if the export fails the
    log goes with it, so only a record actually included in a successful export is counted.
    Both exports are covered: the Invoice Sync page's Download and the report's own Export.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import format_datetime, now_datetime

LOG = "Accounts Format Export Log"
REPORT = "Accounts Format Report"


def setup():
	create_custom_fields(
		{
			"Pick List": [
				{
					"fieldname": "custom_submitted_on",
					"fieldtype": "Datetime",
					"label": "Submitted On",
					"insert_after": "custom_dispatch_date",
					"read_only": 1,
					"no_copy": 1,
					"allow_on_submit": 1,
					"description": "When the Pick List was submitted (Accounts Format Report).",
				}
			]
		},
		ignore_validate=True,
	)


def pick_list_on_submit(doc, method=None):
	doc.db_set("custom_submitted_on", now_datetime(), update_modified=False)


def row_key(row):
	# the order itself: a Partial PO part's Sales Order Id reads SOR-.../2 (Changes(HP) #125)
	return (row.get("_sales_order") or row.get("sales_order_id") or "", row.get("_pick_list") or "")


def _fmt(value):
	return format_datetime(value, "dd-MM-yyyy HH:mm") if value else ""


def history(keys):
	"""{(sales order, pick list): "dd-MM-yyyy HH:mm, ..."} for the given row keys."""
	orders = sorted({so for so, _pl in keys if so})
	if not orders or not frappe.db.table_exists(LOG):
		return {}
	out = {}
	for row in frappe.get_all(
		LOG,
		filters={"sales_order": ("in", orders)},
		fields=["sales_order", "pick_list", "exported_on"],
		order_by="exported_on asc, creation asc",
	):
		key = (row.sales_order, row.pick_list or "")
		out.setdefault(key, []).append(_fmt(row.exported_on))
	return {k: ", ".join(v) for k, v in out.items()}


def fill_history(rows):
	"""Set each row's Accounts Format Exported At from the log."""
	hist = history({row_key(r) for r in rows})
	for r in rows:
		r["exported_at"] = hist.get(row_key(r), "")
	return rows


def record_export(rows, source):
	"""Log this export for every row key in `rows`, and show it on the rows being exported."""
	keys = sorted({row_key(r) for r in rows if r.get("_sales_order") or r.get("sales_order_id")})
	if not keys:
		return
	now = now_datetime()
	for so, pl in keys:
		frappe.get_doc(
			{
				"doctype": LOG,
				"sales_order": so,
				"pick_list": pl or None,
				"exported_on": now,
				"exported_by": frappe.session.user,
				"source": source,
			}
		).insert(ignore_permissions=True)
	stamp = _fmt(now)
	for r in rows:
		if r.get("sales_order_id"):
			r["exported_at"] = f"{r['exported_at']}, {stamp}" if r.get("exported_at") else stamp


@frappe.whitelist()
def export_query():
	"""The report's own Export, logged for the Accounts Format Report (Changes(HP) #110).

	frappe.desk.query_report.export_query builds the file from a fresh run of the report; this
	runs the report once more with the same filters to know which rows went out, logs them,
	and then lets Frappe build the file (in the same transaction).
	"""
	from frappe.desk.query_report import export_query as frappe_export_query

	form = frappe.form_dict
	if form.get("report_name") == REPORT:
		from alpinos.alpinos_development.report.accounts_format_report import accounts_format_report as AFR

		filters = frappe.parse_json(form.get("filters") or "{}") or {}
		_cols, rows = AFR.execute(filters)
		# the user may have exported only the rows on screen (visible_idx); log exactly those
		visible = frappe.parse_json(form.get("visible_idx") or "[]") or []
		if visible and not frappe.utils.sbool(form.get("ignore_visible_idx")):
			rows = [rows[i] for i in visible if isinstance(i, int) and 0 <= i < len(rows)]
		record_export(rows, "Report Export")
	return frappe_export_query()
