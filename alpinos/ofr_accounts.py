"""Changes(HP) #106: the Order Fulfilment Report's Accounts View.

Who: Accounts User / Accounts Manager. For someone holding only those (of the roles the
report knows), it is the report: their default and only view. Someone who also holds a
sales, e-com, warehouse or System Manager role can switch between it and the usual report.

What: submitted Sales Orders that have a Pick List (submitted, or cancelled -- kept so its
invoice can be delinked) and submitted Only Invoice orders, in a Dispatch Date range
(today by default) and a channel (E-com, Offline, or both). RL No Invoice orders are not
invoiced, so they are not here.

    Pending Invoice   no invoice linked with its PDF fetched yet (regular and Only Invoice)
    Total Invoice     invoice linked and PDF fetched (regular and Only Invoice)
    Only Invoice      every submitted Only Invoice order, whatever its invoice state; these
                      are already inside Pending or Total, never added on top

A cancelled Pick List shows in red until a new Pick List exists for the order. Invoices can
be delinked (the order's invoice number and PDF cleared, and the part numbers on its Pick
Lists / Delivery Notes) and resynced, one order or a selection.
"""

import frappe
from frappe import _
from frappe.utils import cint, getdate, today

from alpinos.channel_access import CHANNEL_ECOM, OFFLINE_CHANNELS, resolve_access
from alpinos.company_scope.helpers import company_sql

ACCOUNTS_ROLES = {"Accounts User", "Accounts Manager"}
#: Holding any of these as well, the user keeps the usual report and may switch views.
OTHER_VIEW_ROLES = {
	"System Manager", "Sales Manager", "Sales Admin", "Sales User", "Sales Officer",
	"E-Commerce Manager", "E-Commerce Admin", "E-Commerce Coordinator",
	"Warehouse Manager", "Warehouse Admin",
}
CARDS = ("pending", "total", "only_invoice")

_LINKED = "(IFNULL(so.custom_invoice_no, '') <> '' AND IFNULL(so.custom_invoice_pdf, '') <> '')"
_PL = (
	"LEFT JOIN `tabPick List` pl ON pl.name = ("
	" SELECT p.name FROM `tabPick List` p WHERE p.custom_sales_order_id = so.name AND p.docstatus IN (1, 2)"
	" ORDER BY (p.docstatus = 1) DESC, p.creation DESC LIMIT 1)"
)


def mode(user=None):
	"""None (no Accounts View), "only" (it is their report) or "switch" (they may choose)."""
	roles = set(frappe.get_roles(user or frappe.session.user))
	if not roles & ACCOUNTS_ROLES:
		return None
	return "switch" if roles & OTHER_VIEW_ROLES else "only"


def _assert_mode():
	if not mode():
		frappe.throw(_("The Accounts View is for Accounts User and Accounts Manager."), frappe.PermissionError)


def _only_invoice_sql():
	return "IFNULL(so.custom_only_invoice, 0) = 1" if frappe.db.has_column("Sales Order", "custom_only_invoice") else "0 = 1"


def _where(dispatch_from, dispatch_to, channel):
	only = _only_invoice_sql()
	conditions = [
		"so.docstatus = 1",
		f"({only} OR pl.name IS NOT NULL)",
		"COALESCE(pl.custom_dispatch_date, so.custom_dispatch_date) BETWEEN %(dfrom)s AND %(dto)s",
	]
	if frappe.db.has_column("Sales Order", "custom_rl_no_invoice"):
		conditions.append("IFNULL(so.custom_rl_no_invoice, 0) = 0")
	params = {"dfrom": getdate(dispatch_from or today()), "dto": getdate(dispatch_to or dispatch_from or today())}
	allowed = resolve_access()["channels"]
	wanted = None
	if channel == CHANNEL_ECOM:
		wanted = [CHANNEL_ECOM]
	elif channel:
		wanted = list(OFFLINE_CHANNELS) + [""]
	values = wanted
	if allowed is not None:
		allowed_values = list(allowed) + ([""] if "Offline" in allowed else [])
		values = [v for v in (wanted or allowed_values) if v in allowed_values]
	if values is not None:
		conditions.append("IFNULL(so.custom_channel, '') IN %(channels)s")
		params["channels"] = tuple(values) or ("__none__",)
	conditions.append("1 = 1" + company_sql("Sales Order", "so"))
	return " AND ".join(conditions), params


@frappe.whitelist()
def get_accounts_view(dispatch_from=None, dispatch_to=None, channel=None, card=None, search=None, start=0, page_length=100):
	# company-scope: n/a (company_sql is applied inside _where)
	_assert_mode()
	where, params = _where(dispatch_from, dispatch_to, channel)
	only = _only_invoice_sql()
	counts = frappe.db.sql(
		f"""
		SELECT
			SUM(NOT {_LINKED}) AS pending,
			SUM({_LINKED}) AS total,
			SUM({only}) AS only_invoice
		FROM `tabSales Order` so {_PL}
		WHERE {where}
		""",
		params,
		as_dict=True,
	)[0]
	card_sql = {"pending": f"NOT {_LINKED}", "total": _LINKED, "only_invoice": only}.get(card or "")
	extra = f" AND {card_sql}" if card_sql else ""
	if (search or "").strip():
		extra += " AND (so.name LIKE %(q)s OR so.customer_name LIKE %(q)s OR IFNULL(so.custom_invoice_no, '') LIKE %(q)s)"
		params["q"] = f"%{search.strip()}%"
	rows = frappe.db.sql(
		f"""
		SELECT so.name AS sales_order, so.customer_name, IFNULL(so.custom_channel, '') AS channel,
			COALESCE(pl.custom_dispatch_date, so.custom_dispatch_date) AS dispatch_date,
			pl.name AS pick_list, pl.docstatus AS pl_docstatus,
			IFNULL(so.custom_invoice_no, '') AS invoice_no, IFNULL(so.custom_invoice_pdf, '') AS invoice_pdf,
			{only} AS only_invoice, {_LINKED} AS linked
		FROM `tabSales Order` so {_PL}
		WHERE {where}{extra}
		ORDER BY dispatch_date DESC, so.name DESC
		LIMIT %(limit)s OFFSET %(offset)s
		""",
		dict(params, limit=min(max(cint(page_length) or 100, 1), 500), offset=max(cint(start), 0)),
		as_dict=True,
	)
	for r in rows:
		r["pl_cancelled"] = 1 if cint(r.pl_docstatus) == 2 else 0
		r["only_invoice"] = cint(r.only_invoice)
		r["linked"] = cint(r.linked)
	return {"counts": {k: cint(counts.get(k)) for k in CARDS}, "rows": rows, "mode": mode()}


@frappe.whitelist(methods=["POST"])
def delink_invoices(sales_orders):
	"""Clear the invoice of each order: number, PDF (its File too), downloaded flag, and the
	part numbers on its Pick Lists and Delivery Notes. Logged as Delink in Invoice Sync Log."""
	# company-scope: n/a (each order is checked with assert_company below)
	_assert_mode()
	from alpinos.alpinos_development.doctype.invoice_sync_log.invoice_sync_log import log_invoice_sync
	from alpinos.company_scope.helpers import assert_company

	names = frappe.parse_json(sales_orders) if isinstance(sales_orders, str) else (sales_orders or [])
	done, failed = [], []
	for i, so in enumerate([n for n in names if n]):
		sp = f"ofr_delink_{i}"
		frappe.db.savepoint(sp)
		try:
			row = frappe.db.get_value(
				"Sales Order", so, ["company", "custom_invoice_no", "custom_invoice_pdf"], as_dict=True
			)
			if not row:
				frappe.throw(_("No such Sales Order."))
			assert_company(row.company)
			pdf = (row.custom_invoice_pdf or "").strip()
			if pdf:
				for fname in frappe.get_all(
					"File", filters={"file_url": pdf, "attached_to_doctype": "Sales Order", "attached_to_name": so}, pluck="name"
				):
					frappe.delete_doc("File", fname, ignore_permissions=True, force=True)
			values = {"custom_invoice_no": "", "custom_invoice_pdf": ""}
			if frappe.db.has_column("Sales Order", "custom_invoice_downloaded"):
				values["custom_invoice_downloaded"] = 0
			frappe.db.set_value("Sales Order", so, values, update_modified=False)
			for doctype in ("Pick List", "Delivery Note"):
				if frappe.db.has_column(doctype, "custom_invoice_no"):
					frappe.db.sql(
						f"UPDATE `tab{doctype}` SET custom_invoice_no = '' WHERE custom_sales_order_id = %s",
						so,
					)
			log_invoice_sync(so, row.custom_invoice_no, "Success", _("Invoice delinked by {0}").format(frappe.session.user), sync_type="Delink")
			frappe.db.commit()
			done.append(so)
		except Exception as e:
			frappe.db.rollback(save_point=sp)
			frappe.clear_messages()
			failed.append({"name": so, "error": frappe.utils.strip_html(str(e)) or type(e).__name__})
	return {"done": done, "failed": failed}
