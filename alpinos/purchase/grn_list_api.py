"""Server side of the GRN list screen.

The GRN is ERPNext's Purchase Receipt, so the list has to do one thing the inward
and QC lists do not: separate THIS module's receipts from every other goods receipt
on the site, and from the Purchase Returns that copy the inward link off the receipt
they return. `_module_filters` is that boundary and every query goes through it.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

from alpinos.purchase import constants as C

DOCTYPE = "Purchase Receipt"
PAGE_NAME = "purchase_grn_list"
PAGE_ROLES = tuple(C.ALL_PURCHASE_ROLES) + ("System Manager",)

DEFAULT_PAGE_LENGTH = 20
PAGE_LENGTHS = (20, 100, 500, 2500)

SORTABLE = {
	"name": "name",
	"posting_date": "posting_date",
	"supplier": "supplier_name",
	"grn_status": "custom_grn_status",
	"modified": "modified",
}


def _module_filters():
	"""Only receipts this module raised, and never a Purchase Return.

	make_purchase_return copies custom_purchase_inward off the receipt it returns, so
	filtering on that link alone would list every return alongside its own GRN.
	"""
	return [
		[DOCTYPE, "custom_purchase_inward", "is", "set"],
		[DOCTYPE, "is_return", "=", 0],
		[DOCTYPE, "docstatus", "<", 2],
	]


@frappe.whitelist()
def get_grn_list(
	start=0,
	page_length=DEFAULT_PAGE_LENGTH,
	grn_id=None,
	purchase_inward=None,
	purchase_qc=None,
	supplier=None,
	grn_status=None,
	from_date=None,
	to_date=None,
	has_rejection=None,
	sort_field=None,
	sort_dir=None,
):
	"""One page of GRN rows for the list screen.

	Every argument arrives from frappe.call as a string, so numbers are cint()ed and
	the page size is clamped here — a client can otherwise ask for 100000 rows.
	"""
	if not frappe.has_permission(DOCTYPE, "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	start = max(cint(start), 0)
	page_length = min(max(cint(page_length) or DEFAULT_PAGE_LENGTH, 1), max(PAGE_LENGTHS))

	filters = _module_filters()
	if grn_id:
		filters.append([DOCTYPE, "name", "like", f"%{_escape(grn_id)}%"])
	if purchase_inward:
		filters.append([DOCTYPE, "custom_purchase_inward", "=", purchase_inward])
	if purchase_qc:
		filters.append([DOCTYPE, "custom_purchase_qc", "=", purchase_qc])
	if supplier:
		filters.append([DOCTYPE, "supplier", "=", supplier])
	if grn_status:
		filters.append([DOCTYPE, "custom_grn_status", "=", grn_status])
	if from_date:
		filters.append([DOCTYPE, "posting_date", ">=", from_date])
	if to_date:
		filters.append([DOCTYPE, "posting_date", "<=", to_date])

	order_by = "{0} {1}".format(
		SORTABLE.get(sort_field or "modified", "modified"),
		"asc" if (sort_dir or "desc").lower() == "asc" else "desc",
	)

	rows = frappe.get_list(
		DOCTYPE,
		filters=filters,
		fields=[
			"name", "posting_date", "supplier", "supplier_name", "docstatus",
			"custom_grn_status", "custom_purchase_inward", "custom_purchase_qc",
			"custom_debit_note", "custom_final_submitted_by", "custom_final_submission_datetime",
		],
		order_by=order_by,
		limit_start=start,
		limit_page_length=page_length,
	)

	_attach_quantities(rows)

	# A rejection filter cannot be expressed against the parent, so it is applied
	# after the child quantities are attached rather than by a second query.
	if cint(has_rejection):
		rows = [r for r in rows if flt(r.get("rejected_qty")) > 0]

	return {
		"rows": rows,
		"total": len(
			frappe.get_list(DOCTYPE, filters=filters, fields=["name"], limit_page_length=0)
		),
		"start": start,
		"page_length": page_length,
	}


def _attach_quantities(rows):
	"""Accepted and rejected totals per receipt, in one query rather than per row."""
	if not rows:
		return
	names = [r["name"] for r in rows]
	agg = frappe.db.sql(
		"""
		SELECT parent,
		       IFNULL(SUM(qty), 0)          AS accepted_qty,
		       IFNULL(SUM(rejected_qty), 0) AS rejected_qty
		FROM `tabPurchase Receipt Item`
		WHERE parent IN %(names)s
		GROUP BY parent
		""",
		{"names": names},
		as_dict=True,
	)
	by_name = {a.parent: a for a in agg}
	for row in rows:
		a = by_name.get(row["name"])
		row["accepted_qty"] = flt(a.accepted_qty) if a else 0
		row["rejected_qty"] = flt(a.rejected_qty) if a else 0


def _escape(term):
	"""A typed underscore is a character, not a wildcard."""
	return (term or "").replace("\\", "\\\\").replace("%", "").replace("_", "\\_")


@frappe.whitelist()
def get_filter_options():
	"""The vocabularies the filter row offers, so the client hard-codes nothing."""
	if not frappe.has_permission(DOCTYPE, "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	statuses = frappe.get_meta(DOCTYPE).get_field("custom_grn_status")
	return {
		"grn_statuses": [s for s in ((statuses.options or "").split("\n") if statuses else []) if s],
		"page_lengths": list(PAGE_LENGTHS),
	}


def setup_grn_list_page_access():
	"""Let the module roles open the GRN list page. Idempotent, runs every migrate.

	Roles are inserted as Has Role rows rather than through page.save(), which in
	developer_mode rewrites the tracked page JSON on disk.
	"""
	for page in (PAGE_NAME, "purchase_grn_view"):
		if not frappe.db.exists("Page", page):
			continue
		for role in PAGE_ROLES:
			if not frappe.db.exists("Role", role):
				continue
			if frappe.db.exists(
				"Has Role", {"parenttype": "Page", "parent": page, "role": role}
			):
				continue
			frappe.get_doc(
				{
					"doctype": "Has Role",
					"parenttype": "Page",
					"parentfield": "roles",
					"parent": page,
					"role": role,
				}
			).insert(ignore_permissions=True)
	frappe.clear_cache()
