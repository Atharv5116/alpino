"""Server side of the Purchase Invoice & Payment list screen (BRD 6.1).

One paginated endpoint feeds the desk page at `purchase_invoice_list`:

    6.1   columns  -> LIST_FIELDS + the PO No. enrichment below
    6.1.1 filters  -> get_invoice_list() keyword arguments
    6.1.2 buttons  -> _row_actions(), gated on docstatus, status, role and DocPerm

The invoice is ERPNext's Purchase Invoice, so like the GRN list this one draws a
boundary first: only invoices this module raised (linked to a GRN, or Direct), never a
debit note. `_module_filters` is that boundary and every query goes through it.

BRD 6.1.1 lists "Payment Status" and "Status" as two filters. Until the per-payment status
is designed they are one Status filter over the invoice's own status.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

from alpinos.purchase import constants as C
from alpinos.purchase.purchase_invoice import document_state, invoice_status

DOCTYPE = "Purchase Invoice"
ITEM_DOCTYPE = "Purchase Invoice Item"
LIST_PAGE = "purchase_invoice_list"
ENTRY_PAGE = "purchase_invoice_entry"

PAGE_LENGTHS = (20, 50, 100)
DEFAULT_PAGE_LENGTH = 20

PAGE_ROLES = tuple(C.ALL_PURCHASE_ROLES) + ("System Manager",)

LIST_FIELDS = (
	"name",
	"supplier",
	"supplier_name",
	"bill_no",
	"bill_date",
	"posting_date",
	"custom_payment_due_date",
	"custom_invoice_type",
	"custom_unified_status",
	"custom_purchase_inward",
	"custom_grn",
	"currency",
	"grand_total",
	"rounded_total",
	"custom_supplier_pending_amount",
	"custom_logistics_pending_amount",
	"custom_total_paid_amount",
	"docstatus",
	"modified",
)

# Sort columns arrive as raw strings and are interpolated into order_by, so only these
# are accepted. PO No. is enriched from the item lines and is deliberately absent.
_SORTABLE = frozenset(
	{
		"name",
		"custom_purchase_inward",
		"custom_grn",
		"supplier_name",
		"bill_no",
		"bill_date",
		"custom_payment_due_date",
		"custom_unified_status",
		"grand_total",
		"modified",
		"creation",
	}
)


# ----------------------------------------------------------------- filter helpers


def _like(value):
	"""LIKE pattern for `value`, with any wildcards the user typed stripped out."""
	safe = str(value or "").strip().replace("%", "").replace("_", "")
	return f"%{safe}%" if safe else ""


def _date(value):
	if not value:
		return None
	try:
		return getdate(value)
	except Exception:
		return None


def _date_range(filters, field, start, end):
	fd, td = _date(start), _date(end)
	if fd and td and fd > td:
		fd, td = td, fd
	if fd and td:
		filters.append([field, "between", [fd, td]])
	elif fd:
		filters.append([field, ">=", fd])
	elif td:
		filters.append([field, "<=", td])


def _module_filters():
	"""(filters, or_filters) that keep the list to this module's own invoices.

	Invoice Type defaults to Normal on every Purchase Invoice on the site, so "Normal" is
	recognised by its GRN link, and a Direct invoice by its type (only create_direct_from_po
	sets it). A debit note is a return and never belongs here.
	"""
	return (
		[["is_return", "=", 0]],
		[["custom_grn", "is", "set"], ["custom_invoice_type", "=", C.UNF_TYPE_DIRECT]],
	)


def _status_filter(filters, status):
	"""The payment status: Pending Payment / Partially Paid / Paid.

	A draft counts as Pending Payment even when an older build stored "Draft" on it, which
	is how invoice_status reads it too.
	"""
	status = str(status or "").strip()
	if status not in C.UNF_STATUSES:
		return
	if status == C.UNF_PENDING_PAYMENT:
		filters.append(["custom_unified_status", "in", [status, "Draft", "Cancelled", ""]])
	elif status == C.UNF_PAID:
		filters.append(["custom_unified_status", "in", [status, "Completed"]])
	else:
		filters.append(["custom_unified_status", "=", status])


def _doc_state_filter(filters, doc_state):
	"""Draft / Submitted / Cancelled — the document state, filtered on docstatus."""
	docstatus = {C.UNF_DOC_DRAFT: 0, C.UNF_DOC_SUBMITTED: 1, C.UNF_DOC_CANCELLED: 2}.get(
		str(doc_state or "").strip()
	)
	if docstatus is not None:
		filters.append(["docstatus", "=", docstatus])


# ------------------------------------------------------------------ list endpoint


@frappe.whitelist()
def get_invoice_list(
	start=0,
	page_length=DEFAULT_PAGE_LENGTH,
	invoice_id=None,
	grn=None,
	supplier=None,
	bill_no=None,
	from_date=None,
	to_date=None,
	due_from=None,
	due_to=None,
	invoice_type=None,
	status=None,
	doc_state=None,
	sort_field=None,
	sort_dir=None,
	with_actions=1,
):
	"""One page of invoice rows for the list screen, plus their action buttons."""
	if not frappe.has_permission(DOCTYPE, "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	start = max(cint(start), 0)
	page_length = min(max(cint(page_length) or DEFAULT_PAGE_LENGTH, 1), max(PAGE_LENGTHS))

	filters, or_filters = _module_filters()

	# BRD 6.1.1 "Invoice ID" / "GRN ID" / "Supplier Invoice No."
	for field, raw in (("name", invoice_id), ("custom_grn", grn), ("bill_no", bill_no)):
		pattern = _like(raw)
		if pattern:
			filters.append([field, "like", pattern])

	if supplier:
		filters.append(["supplier", "=", str(supplier).strip()])

	# BRD 6.1.1 "Invoice Date" / "Payment Due Date" — a single date or a range
	_date_range(filters, "bill_date", from_date, to_date)
	_date_range(filters, "custom_payment_due_date", due_from, due_to)

	# BRD 6.1.1 "PO Type" — Normal Invoice vs Direct Invoice
	invoice_type = str(invoice_type or "").strip()
	if invoice_type == C.UNF_TYPE_DIRECT:
		filters.append(["custom_invoice_type", "=", C.UNF_TYPE_DIRECT])
	elif invoice_type == C.UNF_TYPE_NORMAL:
		filters.append(["custom_grn", "is", "set"])

	_status_filter(filters, status)
	_doc_state_filter(filters, doc_state)

	sf = str(sort_field or "").strip()
	sd = "asc" if str(sort_dir or "").strip().lower() == "asc" else "desc"
	order_by = f"`{sf}` {sd}" if sf in _SORTABLE else "modified desc"

	count_rows = frappe.get_list(
		DOCTYPE,
		fields=["count(name) as total"],
		filters=filters,
		or_filters=or_filters,
		limit_page_length=0,
	)
	total = cint(count_rows[0].get("total")) if count_rows else 0

	rows = frappe.get_list(
		DOCTYPE,
		fields=list(LIST_FIELDS),
		filters=filters,
		or_filters=or_filters,
		limit_start=start,
		limit_page_length=page_length + 1,
		order_by=order_by,
	)
	has_more = len(rows) > page_length
	rows = rows[:page_length]

	_attach_row_extras(rows, with_actions=cint(with_actions))

	return {
		"data": rows,
		"has_more": int(has_more),
		"start": start,
		"page_length": page_length,
		"total": total,
	}


def _attach_row_extras(rows, with_actions=1):
	"""PO No., the displayed status, the payable amount and the row buttons.

	One query for every PO on the page, never one per row.
	"""
	if not rows:
		return

	orders = {}
	for line in frappe.get_all(
		ITEM_DOCTYPE,
		filters={"parenttype": DOCTYPE, "parent": ["in", [r.name for r in rows]]},
		fields=["parent", "purchase_order"],
		order_by="parent asc, idx asc",
	):
		if line.purchase_order and line.purchase_order not in orders.setdefault(line.parent, []):
			orders[line.parent].append(line.purchase_order)

	context = _action_context() if with_actions else None

	for row in rows:
		row["purchase_orders"] = orders.get(row.name, [])
		row["status"] = invoice_status(row)
		row["doc_state"] = document_state(row)
		row["invoice_type"] = row.get("custom_invoice_type") or C.UNF_TYPE_NORMAL
		row["invoice_amount"] = flt(row.get("rounded_total") or row.get("grand_total"))
		row["pending_amount"] = flt(row.get("custom_supplier_pending_amount")) + flt(
			row.get("custom_logistics_pending_amount")
		)
		row["actions"] = _row_actions(row, context) if with_actions else []


def _action_context():
	roles = set(frappe.get_roles())
	return {
		"write": bool(frappe.has_permission(DOCTYPE, "write")),
		"submit": bool(frappe.has_permission(DOCTYPE, "submit")),
		"may_create": bool(roles & set(C.UNF_CREATE_ROLES)),
		"may_pay": bool(roles & set(C.UNF_PAYMENT_ROLES)),
	}


def _act(action, label, kind="view"):
	return {"action": action, "label": label, "kind": kind, "enabled": True, "reason": None}


def _row_actions(row, ctx):
	"""BRD 6.1.2: View always; Edit / Submit on a Draft; Add Payment while money is owed."""
	docstatus = cint(row.get("docstatus"))
	actions = [_act("view", _("View"))]
	if docstatus == 0 and ctx["may_create"]:
		if ctx["write"]:
			actions.append(_act("edit", _("Edit")))
		if ctx["submit"]:
			actions.append(_act("submit", _("Submit"), kind="transition"))
	if (
		docstatus == 1
		and row.get("status") in (C.UNF_PENDING_PAYMENT, C.UNF_PARTIALLY_PAID)
		and ctx["may_pay"]
		and ctx["write"]
	):
		actions.append(_act("add_payment", _("Add Payment"), kind="transition"))
	return actions


# --------------------------------------------------------------- page vocabulary


@frappe.whitelist()
def get_filter_options():
	"""Select options for the list page, sourced from alpinos.purchase.constants."""
	if not frappe.has_permission(DOCTYPE, "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return {
		"statuses": "\n" + "\n".join(C.UNF_STATUSES),
		"invoice_types": [
			{"value": "", "label": ""},
			{"value": C.UNF_TYPE_NORMAL, "label": _("Normal Invoice")},
			{"value": C.UNF_TYPE_DIRECT, "label": _("Direct Invoice")},
		],
		"page_lengths": list(PAGE_LENGTHS),
		"can_create": bool(frappe.has_permission(DOCTYPE, "create"))
		and bool(set(frappe.get_roles()) & set(C.UNF_CREATE_ROLES)),
	}


# ------------------------------------------------- + Create Invoice (BRD 6.1.2)


def _assert_can_create():
	if not frappe.has_permission(DOCTYPE, "create") or not (
		set(frappe.get_roles()) & set(C.UNF_CREATE_ROLES)
	):
		frappe.throw(_("Not permitted"), frappe.PermissionError)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def eligible_grn_query(doctype, txt, searchfield, start, page_len, filters):
	"""Link search for Create Invoice: finally submitted GRNs with no live invoice yet.

	BR-UNF-01 (the GRN must be finally submitted) and BR-UNF-02 (one invoice per GRN), so
	the picker offers only what create_from_grn will accept.
	"""
	_assert_can_create()
	like = f"%{txt or ''}%"
	return frappe.db.sql(
		"""
		SELECT pr.name, pr.supplier_name, pr.custom_purchase_inward, pr.posting_date
		FROM `tabPurchase Receipt` pr
		WHERE pr.docstatus = 1
		  AND IFNULL(pr.is_return, 0) = 0
		  AND IFNULL(pr.custom_purchase_inward, '') != ''
		  AND (pr.name LIKE %(txt)s OR pr.supplier_name LIKE %(txt)s
		       OR pr.custom_purchase_inward LIKE %(txt)s)
		  AND NOT EXISTS (
		      SELECT 1 FROM `tabPurchase Invoice` pi
		      WHERE pi.custom_grn = pr.name AND pi.docstatus < 2
		  )
		ORDER BY pr.posting_date DESC, pr.name DESC
		LIMIT %(start)s, %(page_len)s
		""",
		{"txt": like, "start": cint(start), "page_len": cint(page_len)},
	)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def eligible_direct_po_query(doctype, txt, searchfield, start, page_len, filters):
	"""Link search for Create Invoice: approved Direct Purchase Invoice orders not yet invoiced.

	Mirrors what the PO list offers Create Invoice on (po_list_api._row_actions) and what
	create_direct_from_po accepts: submitted, flagged Direct, Approved or Sent to Supplier,
	not closed, and no live Direct invoice (BR-PO-25).
	"""
	_assert_can_create()
	like = f"%{txt or ''}%"
	return frappe.db.sql(
		"""
		SELECT po.name, po.supplier_name, po.transaction_date
		FROM `tabPurchase Order` po
		WHERE po.docstatus = 1
		  AND IFNULL(po.custom_direct_purchase_invoice, 0) = 1
		  AND po.status NOT IN ('Closed', 'On Hold', 'Cancelled')
		  AND po.custom_approval_status IN %(live)s
		  AND (po.name LIKE %(txt)s OR po.supplier_name LIKE %(txt)s)
		  AND NOT EXISTS (
		      SELECT 1 FROM `tabPurchase Invoice Item` pii
		      JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
		      WHERE pii.purchase_order = po.name AND pi.docstatus < 2
		        AND pi.custom_invoice_type = %(direct)s
		  )
		ORDER BY po.transaction_date DESC, po.name DESC
		LIMIT %(start)s, %(page_len)s
		""",
		{
			"txt": like,
			"live": tuple(C.PO_LIVE_STATUSES),
			"direct": C.UNF_TYPE_DIRECT,
			"start": cint(start),
			"page_len": cint(page_len),
		},
	)


@frappe.whitelist()
def create_invoice(source_type, source):
	"""+ Create Invoice from the list: one entry point for both BRD 6.0 paths."""
	from alpinos.purchase import purchase_invoice as INV

	_assert_can_create()
	if source_type == "grn":
		invoice = INV.create_from_grn(source)
	elif source_type == "po":
		invoice = INV.create_direct_from_po(source)
	else:
		frappe.throw(_("Choose a GRN or a Direct Purchase Invoice order."))
	return {"name": invoice.name}


# ----------------------------------------------- page access (hooks.after_migrate)


def setup_invoice_page_access():
	"""Let the module roles open both invoice pages. Idempotent; safe on every migrate.

	Roles are inserted as Has Role rows rather than through page.save(), which in
	developer_mode rewrites the tracked page JSON on disk.
	"""
	for page in (LIST_PAGE, ENTRY_PAGE):
		if not frappe.db.exists("Page", page):
			continue
		for role in PAGE_ROLES:
			if not frappe.db.exists("Role", role):
				continue
			if frappe.db.exists("Has Role", {"parenttype": "Page", "parent": page, "role": role}):
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
