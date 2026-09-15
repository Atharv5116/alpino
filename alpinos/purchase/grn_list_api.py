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
ITEM_DOCTYPE = "Purchase Receipt Item"
PAGE_NAME = "purchase_grn_list"
PAGE_ROLES = tuple(C.ALL_PURCHASE_ROLES) + ("System Manager",)

DEFAULT_PAGE_LENGTH = 20
PAGE_LENGTHS = (20, 100, 500, 2500)
# What the list screen offers; PAGE_LENGTHS stays the ceiling a caller may ask for.
SCREEN_PAGE_LENGTHS = (20, 50, 100)

# Sort keys the screen sends (its column fields) plus the older aliases.
SORTABLE = {
	"name": "name",
	"posting_date": "posting_date",
	"custom_purchase_inward": "custom_purchase_inward",
	"supplier_name": "supplier_name",
	"supplier": "supplier_name",
	"custom_grn_status": "custom_grn_status",
	"grn_status": "custom_grn_status",
	"modified": "modified",
}


def _module_filters():
	"""Only receipts this module raised, and never a Purchase Return.

	make_purchase_return copies custom_purchase_inward off the receipt it returns, so
	filtering on that link alone would list every return alongside its own GRN.
	"""
	# Cancelled GRNs stay listed (GRN Status reads Cancelled): the list is where a cancelled
	# GRN is found again to be amended.
	return [
		[DOCTYPE, "custom_purchase_inward", "is", "set"],
		[DOCTYPE, "is_return", "=", 0],
	]


@frappe.whitelist()
def get_grn_list(
	start=0,
	page_length=DEFAULT_PAGE_LENGTH,
	grn_id=None,
	purchase_inward=None,
	purchase_qc=None,
	purchase_order=None,
	supplier=None,
	target_location=None,
	grn_status=None,
	from_date=None,
	to_date=None,
	has_rejection=None,
	sort_field=None,
	sort_dir=None,
	with_actions=0,
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
	# PO and target location live on the receipt lines. They are resolved to receipt
	# names first: a child-table filter on get_list joins the lines and returns a
	# receipt once per matching line, which breaks both the page and the total.
	if purchase_order:
		filters.append([DOCTYPE, "name", "in", _receipts_for_purchase_order(purchase_order)])
	if target_location:
		filters.append([DOCTYPE, "name", "in", _receipts_for_location(target_location)])

	order_by = "{0} {1}".format(
		SORTABLE.get(sort_field or "modified", "modified"),
		"asc" if (sort_dir or "desc").lower() == "asc" else "desc",
	)

	rows = frappe.get_list(
		DOCTYPE,
		filters=filters,
		fields=[
			"name", "posting_date", "supplier", "supplier_name", "docstatus", "set_warehouse",
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

	if cint(with_actions):
		_attach_actions(rows)

	total = len(frappe.get_list(DOCTYPE, filters=filters, fields=["name"], limit_page_length=0))
	return {
		"rows": rows,
		# `data` / `has_more` are the shape the inward, QC and invoice list screens read.
		"data": rows,
		"total": total,
		"has_more": 1 if start + page_length < total else 0,
		"start": start,
		"page_length": page_length,
	}


def _attach_actions(rows):
	"""The row buttons: View on every GRN, Edit on a Draft for whoever may change it.

	Both open the GRN screen, which re-checks every edit server-side
	(grn_edit.get_grn_context), so a button here never grants anything by itself.
	"""
	from alpinos.purchase.grn_edit import EDIT_ROLES

	may_edit = bool(set(frappe.get_roles()) & set(EDIT_ROLES))
	for row in rows:
		row["actions"] = [{"action": "view", "label": _("View"), "kind": "view"}]
		if cint(row.get("docstatus")) == 0 and may_edit:
			row["actions"].append({"action": "edit", "label": _("Edit"), "kind": "transition"})


def _receipts_for_purchase_order(purchase_order):
	return _receipts_with_line({"purchase_order": purchase_order}) or [""]


def _receipts_for_location(warehouse):
	"""Receipts with a line going to the warehouse, or whose target location it is.

	The header's set_warehouse is the inward's Target Location; a line can still land
	somewhere else (a QC decision or a quarantine store), so both are matched.
	"""
	names = set(_receipts_with_line({"warehouse": warehouse}))
	names.update(
		frappe.get_all(
			DOCTYPE, filters={"set_warehouse": warehouse, "is_return": 0}, pluck="name"
		)
	)
	return list(names) or [""]


def _receipts_with_line(line_filters):
	return frappe.get_all(
		ITEM_DOCTYPE,
		filters=dict(line_filters, parenttype=DOCTYPE),
		pluck="parent",
		distinct=True,
	)


def _attach_quantities(rows):
	"""Per receipt: quantities, PO numbers and target locations, from one line query.

	Received is accepted + rejected, the same total the GRN Detail screen shows:
	BuyingController forces received_qty to exactly that sum.
	"""
	if not rows:
		return
	lines = frappe.get_all(
		ITEM_DOCTYPE,
		filters={"parent": ["in", [r["name"] for r in rows]], "parenttype": DOCTYPE},
		fields=["parent", "qty", "rejected_qty", "purchase_order", "warehouse"],
		order_by="parent, idx",
	)
	by_name = {}
	for line in lines:
		agg = by_name.setdefault(
			line.parent, {"accepted": 0.0, "rejected": 0.0, "pos": [], "locations": []}
		)
		agg["accepted"] += flt(line.qty)
		agg["rejected"] += flt(line.rejected_qty)
		if line.purchase_order and line.purchase_order not in agg["pos"]:
			agg["pos"].append(line.purchase_order)
		if line.warehouse and line.warehouse not in agg["locations"]:
			agg["locations"].append(line.warehouse)

	for row in rows:
		agg = by_name.get(row["name"]) or {}
		row["accepted_qty"] = agg.get("accepted", 0.0)
		row["rejected_qty"] = agg.get("rejected", 0.0)
		row["received_qty"] = row["accepted_qty"] + row["rejected_qty"]
		row["purchase_orders"] = agg.get("pos") or []
		row["target_locations"] = agg.get("locations") or (
			[row["set_warehouse"]] if row.get("set_warehouse") else []
		)


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
		"page_lengths": list(SCREEN_PAGE_LENGTHS),
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
