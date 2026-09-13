"""Server side of the Purchase Order List screen — BRD "Purchase Inward Part -1" 1.2 - 1.4.

One paginated endpoint feeds the desk page at `purchase_order_list`:

    1.2   columns       PO ID, PO Type, Vendor, PO Date, PO Order Quantity (with the SKU
                        breakdown for the hover), Total Items, PO Value, Expected Delivery
    1.2.1 filters       get_purchase_order_list() keyword arguments
    1.2.1 SKU Code      every row also carries that SKU's ordered / received / pending,
                        so the screen can switch to the BRD's SKU view
    1.3/1.4 buttons     built here per row, never by a status map in the page JS

WHERE EACH STATUS COMES FROM
---------------------------
The BRD's PO statuses (3.4) mix two different facts, and they are stored in two places:

    approval    Draft / Pending Approval / Approved / Rejected / Sent to Supplier
                -> custom_approval_status (purchase_order_approval)
    receiving   Pending Receipt / Partially Received / Fully Received
                -> custom_total_inward_qty + custom_pending_inward_qty, the roll-up
                   purchase_order_fields.refresh_inward_progress keeps current on every
                   inward submit, edit and cancel

"Current Status" is the one the BRD shows: receiving once goods have started arriving,
the approval status before that, and Closed / Cancelled from ERPNext's own status and
docstatus. It is derived identically in Python (_current_status) and in SQL
(_current_condition), because the filters must page and count on the server; a filter
applied in the browser would page through the wrong set.

A Direct Purchase Invoice order never receives goods (BR-PO-21), so it has no receiving
status and its current status stays on the approval track.

PERMISSIONS
-----------
Visible rows come from frappe.get_list, which applies User Permissions and permission
hooks, behind an explicit has_permission gate. The derived-status and SKU filters resolve
to a `name IN (...)` set first and are ANDed into that same permission-filtered query,
the pattern inward_list_api already uses.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

from alpinos.purchase import constants as C
from alpinos.purchase import purchase_order_approval as A
from alpinos.purchase.inward_list_api import _date, _like, _restrict_names
from alpinos.purchase.purchase_invoice import direct_invoices_for

DOCTYPE = "Purchase Order"
ITEM_DOCTYPE = "Purchase Order Item"
PAGE_NAME = "purchase_order_list"

PAGE_LENGTHS = (20, 50, 100)
DEFAULT_PAGE_LENGTH = 20

# ERPNext's own buying roles are included: on a stock site they ARE the purchase team, and
# PO_SUBMITTER_ROLES already grants them the approval actions this list offers.
PAGE_ROLES = C.ALL_PURCHASE_ROLES + ("System Manager", "Purchase User", "Purchase Manager")

RECV_PENDING = "Pending Receipt"
RECV_PARTIAL = "Partially Received"
RECV_FULL = "Fully Received"
RECEIVING_STATUSES = (RECV_PENDING, RECV_PARTIAL, RECV_FULL)

PO_CLOSED = "Closed"
PO_CANCELLED = "Cancelled"

#: BRD 3.4, in the BRD's order.
CURRENT_STATUSES = (
	C.PO_DRAFT,
	C.PO_PENDING_APPROVAL,
	C.PO_APPROVED,
	C.PO_REJECTED,
	C.PO_SENT_TO_SUPPLIER,
	RECV_PARTIAL,
	RECV_FULL,
	PO_CLOSED,
	PO_CANCELLED,
)

LIST_FIELDS = (
	"name",
	"custom_inward_type",
	"supplier",
	"supplier_name",
	"transaction_date",
	"schedule_date",
	"grand_total",
	"rounded_total",
	"currency",
	"total_qty",
	"company",
	"docstatus",
	"status",
	"custom_approval_status",
	"custom_direct_purchase_invoice",
	"custom_total_inward_qty",
	"custom_pending_inward_qty",
	"owner",
	"modified",
)

_SORTABLE = frozenset(
	{
		"name",
		"custom_inward_type",
		"supplier_name",
		"transaction_date",
		"total_qty",
		"grand_total",
		"schedule_date",
		"custom_approval_status",
		"modified",
	}
)

_NAME_SET_LIMIT = 5000


# ------------------------------------------------------------- status: Python


def _approval_status(row):
	"""A PO raised before the approval module existed has no status: read it as the
	approval module itself does (purchase_order_approval._current_status)."""
	status = (row.get("custom_approval_status") or "").strip()
	if status:
		return status
	return C.PO_APPROVED if cint(row.get("docstatus")) == 1 else C.PO_DRAFT


def _receiving_status(row):
	if (
		cint(row.get("docstatus")) != 1
		or (row.get("status") or "") == PO_CLOSED
		or cint(row.get("custom_direct_purchase_invoice"))
	):
		return ""
	if flt(row.get("custom_total_inward_qty")) <= 0:
		return RECV_PENDING
	return RECV_PARTIAL if flt(row.get("custom_pending_inward_qty")) > 0 else RECV_FULL


def _current_status(row):
	docstatus = cint(row.get("docstatus"))
	if docstatus == 2:
		return PO_CANCELLED
	if docstatus == 1 and (row.get("status") or "") == PO_CLOSED:
		return PO_CLOSED
	receiving = _receiving_status(row)
	if receiving in (RECV_PARTIAL, RECV_FULL):
		return receiving
	return _approval_status(row)


# ---------------------------------------------------------------- status: SQL
# Each condition below must select exactly the rows the matching Python function above
# labels with that value. po_list_test pins the two against each other.

_APPROVAL_EXPR = (
	"COALESCE(NULLIF(`custom_approval_status`, ''), IF(`docstatus` = 1, 'Approved', 'Draft'))"
)
_OPEN_RECEIVING = (
	"`docstatus` = 1 AND IFNULL(`status`, '') != 'Closed' "
	"AND IFNULL(`custom_direct_purchase_invoice`, 0) = 0"
)
_INWARDED = "IFNULL(`custom_total_inward_qty`, 0) > 0"
_PENDING_LEFT = "IFNULL(`custom_pending_inward_qty`, 0) > 0"


def _receiving_condition(value):
	if value == RECV_PENDING:
		return f"{_OPEN_RECEIVING} AND NOT ({_INWARDED})"
	if value == RECV_PARTIAL:
		return f"{_OPEN_RECEIVING} AND {_INWARDED} AND {_PENDING_LEFT}"
	if value == RECV_FULL:
		return f"{_OPEN_RECEIVING} AND {_INWARDED} AND NOT ({_PENDING_LEFT})"
	return None


def _current_condition(value):
	if value == PO_CANCELLED:
		return "`docstatus` = 2"
	if value == PO_CLOSED:
		return "`docstatus` = 1 AND `status` = 'Closed'"
	if value in (RECV_PARTIAL, RECV_FULL):
		return _receiving_condition(value)
	if value in (C.PO_DRAFT, C.PO_PENDING_APPROVAL, C.PO_REJECTED):
		return f"`docstatus` = 0 AND {_APPROVAL_EXPR} = %(value)s"
	if value in (C.PO_APPROVED, C.PO_SENT_TO_SUPPLIER):
		return (
			"`docstatus` = 1 AND IFNULL(`status`, '') != 'Closed' "
			f"AND (IFNULL(`custom_direct_purchase_invoice`, 0) = 1 OR NOT ({_INWARDED})) "
			f"AND {_APPROVAL_EXPR} = %(value)s"
		)
	return None


def _approval_condition(value):
	return f"{_APPROVAL_EXPR} = %(value)s" if value in C.PO_APPROVAL_STATUSES else None


def _names_where(condition, value=None):
	if not condition:
		return []
	rows = frappe.db.sql(
		f"SELECT `name` FROM `tabPurchase Order` WHERE {condition} LIMIT {_NAME_SET_LIMIT}",
		{"value": value},
	)
	return [r[0] for r in rows]


def _one_of(value, allowed):
	value = (value or "").strip()
	return value if value in allowed else ""


# ------------------------------------------------------------------ endpoint


@frappe.whitelist()
def get_purchase_order_list(
	start=0,
	page_length=DEFAULT_PAGE_LENGTH,
	po_type=None,
	supplier=None,
	po_id=None,
	sku_code=None,
	from_date=None,
	to_date=None,
	delivery_from=None,
	delivery_to=None,
	current_status=None,
	approval_status=None,
	receiving_status=None,
	sort_field=None,
	sort_dir=None,
):
	"""One page of Purchase Orders for the list screen, with the row buttons.

	Arguments arrive from frappe.call as strings, so numbers are cint()ed, the page size
	is clamped, and every vocabulary filter is checked against its allowed values -- a
	stale saved filter must narrow to nothing, never widen to everything.
	"""
	if not frappe.has_permission(DOCTYPE, "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	start = max(cint(start), 0)
	page_length = min(max(cint(page_length) or DEFAULT_PAGE_LENGTH, 1), max(PAGE_LENGTHS))

	filters = {}

	value = _one_of(po_type, C.INWARD_TYPES)
	if value:
		filters["custom_inward_type"] = value
	if supplier:
		filters["supplier"] = str(supplier).strip()

	like = _like(po_id)
	if like:
		filters["name"] = ["like", like]

	sku = (sku_code or "").strip()
	if sku:
		_restrict_names_keeping_like(
			filters,
			frappe.get_all(
				ITEM_DOCTYPE,
				filters={"item_code": sku, "parenttype": DOCTYPE},
				pluck="parent",
				distinct=True,
				limit=_NAME_SET_LIMIT,
			),
		)

	for field, lo, hi in (
		("transaction_date", from_date, to_date),
		("schedule_date", delivery_from, delivery_to),
	):
		fd, td = _date(lo), _date(hi)
		if fd and td and fd > td:
			fd, td = td, fd
		if fd and td:
			filters[field] = ["between", [fd, td]]
		elif fd:
			filters[field] = [">=", fd]
		elif td:
			filters[field] = ["<=", td]

	value = _one_of(current_status, CURRENT_STATUSES)
	if value:
		_restrict_names_keeping_like(filters, _names_where(_current_condition(value), value))
	elif current_status:
		_restrict_names_keeping_like(filters, [])

	value = _one_of(approval_status, C.PO_APPROVAL_STATUSES)
	if value:
		_restrict_names_keeping_like(filters, _names_where(_approval_condition(value), value))
	elif approval_status:
		_restrict_names_keeping_like(filters, [])

	value = _one_of(receiving_status, RECEIVING_STATUSES)
	if value:
		_restrict_names_keeping_like(filters, _names_where(_receiving_condition(value)))
	elif receiving_status:
		_restrict_names_keeping_like(filters, [])

	sf = str(sort_field or "").strip()
	sd = "asc" if str(sort_dir or "").strip().lower() == "asc" else "desc"
	order_by = f"`{sf}` {sd}" if sf in _SORTABLE else "modified desc"

	count_rows = frappe.get_list(
		DOCTYPE,
		fields=["count(name) as total"],
		filters=filters or None,
		limit_page_length=0,
	)
	total = cint(count_rows[0].get("total")) if count_rows else 0

	rows = frappe.get_list(
		DOCTYPE,
		fields=list(LIST_FIELDS),
		filters=filters or None,
		limit_start=start,
		limit_page_length=page_length + 1,
		order_by=order_by,
	)
	has_more = len(rows) > page_length
	rows = rows[:page_length]

	_attach_row_extras(rows, sku)

	return {
		"data": rows,
		"has_more": int(has_more),
		"start": start,
		"page_length": page_length,
		"total": total,
		"sku_code": sku,
	}


def _restrict_names_keeping_like(filters, names):
	"""_restrict_names, but without discarding a PO ID `like` filter on the same key.

	PO ID is a `name LIKE` filter and every derived filter is a `name IN` set; both live
	on filters["name"], so the LIKE is applied to the name set in Python first.
	"""
	existing = filters.get("name")
	if existing and isinstance(existing, (list, tuple)) and existing[0] == "like":
		needle = existing[1].strip("%").replace("\\_", "_").replace("\\\\", "\\").lower()
		names = [n for n in (names or []) if needle in n.lower()]
		filters.pop("name")
	_restrict_names(filters, names)


# ------------------------------------------------------------------ row data


def _attach_row_extras(rows, sku=""):
	"""Line breakdown, SKU view, linked documents and buttons. Bulk queries only."""
	if not rows:
		return
	names = [r.name for r in rows]

	lines = frappe.get_all(
		ITEM_DOCTYPE,
		filters={"parent": ["in", names], "parenttype": DOCTYPE},
		fields=["parent", "item_code", "item_name", "qty", "uom", "custom_inward_received_qty", "idx"],
		order_by="parent asc, idx asc",
	)
	by_parent = {}
	for line in lines:
		by_parent.setdefault(line.parent, []).append(line)

	inward_counts = {
		r.purchase_order: cint(r.n)
		for r in frappe.get_all(
			"Purchase Inward",
			filters={"purchase_order": ["in", names], "docstatus": ["<", 2]},
			fields=["purchase_order", "count(name) as n"],
			group_by="purchase_order",
		)
	}
	direct_invoices = direct_invoices_for(names)

	perms = {
		"write": frappe.has_permission(DOCTYPE, "write"),
		"delete": frappe.has_permission(DOCTYPE, "delete"),
		"inward": frappe.has_permission("Purchase Inward", "create"),
		"invoice": frappe.has_permission("Purchase Invoice", "create"),
	}

	for row in rows:
		items = by_parent.get(row.name, [])
		row.lines = [
			{"item_code": i.item_code, "item_name": i.item_name, "qty": flt(i.qty), "uom": i.uom}
			for i in items
		]
		row.total_items = len(items)
		by_uom = {}
		for i in items:
			by_uom[i.uom or ""] = by_uom.get(i.uom or "", 0.0) + flt(i.qty)
		row.qty_by_uom = [{"uom": u, "qty": q} for u, q in by_uom.items()]
		row.po_value = flt(row.rounded_total or row.grand_total)

		row.approval_status = _approval_status(row)
		row.receiving_status = _receiving_status(row)
		row.current_status = _current_status(row)
		row.inward_count = inward_counts.get(row.name, 0)
		row.direct_invoice = direct_invoices.get(row.name)

		if sku:
			mine = [i for i in items if i.item_code == sku]
			ordered = sum(flt(i.qty) for i in mine)
			received = sum(flt(i.custom_inward_received_qty) for i in mine)
			row.sku = {
				"item_code": sku,
				"item_name": mine[0].item_name if mine else "",
				"uom": mine[0].uom if mine else "",
				"ordered_qty": ordered,
				"received_qty": received,
				"pending_qty": max(ordered - received, 0.0),
			}

		row.actions = _row_actions(row, perms)


def _act(action, label, kind="view", enabled=True, reason=""):
	return {"action": action, "label": label, "kind": kind, "enabled": bool(enabled), "reason": reason}


def _row_actions(row, perms):
	"""BRD 1.3 buttons, gated by 1.4 availability, role and DocPerm.

	The approval transitions come from purchase_order_approval.available_actions -- the
	same table the PO form and perform_action use -- so this list can never offer an
	action the server would then refuse.
	"""
	acts = [_act("view", _("View"))]
	docstatus = cint(row.docstatus)
	approval = row.approval_status
	current = row.current_status
	direct = cint(row.custom_direct_purchase_invoice)

	if docstatus == 0 and approval in (C.PO_DRAFT, C.PO_REJECTED) and perms["write"]:
		acts.append(_act("edit", _("Edit")))
	if docstatus == 0 and approval == C.PO_DRAFT and perms["delete"]:
		acts.append(_act("delete", _("Delete")))

	for a in A.available_actions(row):
		acts.append(_act(a["action"], _(a["action"]), kind="transition"))

	live = docstatus == 1 and current not in (PO_CLOSED, PO_CANCELLED)
	if live and direct:
		# BRD 1.2 note + BR-PO-22: an approved Direct Purchase Invoice order goes straight
		# to its invoice, and never offers Create Inward (BR-PO-24).
		if row.direct_invoice:
			acts.append(_act("view_invoice", _("View Invoice")))
		elif approval in (C.PO_APPROVED, C.PO_SENT_TO_SUPPLIER) and perms["invoice"]:
			acts.append(_act("create_invoice", _("Create Invoice"), kind="create"))
	elif live and current != RECV_FULL and perms["inward"]:
		label = _("Continue Receiving") if current == RECV_PARTIAL else _("Create Inward")
		sent = approval == C.PO_SENT_TO_SUPPLIER or current == RECV_PARTIAL
		acts.append(
			_act(
				"create_inward",
				label,
				kind="create",
				enabled=sent,
				reason="" if sent else _("Send this Purchase Order to the supplier first (BRD 1.4)."),
			)
		)

	if row.inward_count:
		acts.append(_act("view_inwards", _("View Inwards ({0})").format(row.inward_count)))
	return acts


# ------------------------------------------------------------------- options


@frappe.whitelist()
def get_filter_options():
	"""Select vocabulary for the page, sourced from constants so it lives in one place."""
	if not frappe.has_permission(DOCTYPE, "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return {
		"po_types": [{"value": "", "label": ""}]
		+ [{"value": t, "label": C.label_for_inward_type(t)} for t in C.INWARD_TYPES],
		"current_statuses": "\n" + "\n".join(CURRENT_STATUSES),
		"approval_statuses": "\n" + "\n".join(C.PO_APPROVAL_STATUSES),
		"receiving_statuses": "\n" + "\n".join(RECEIVING_STATUSES),
		"page_lengths": list(PAGE_LENGTHS),
		"can_create": 1 if frappe.has_permission(DOCTYPE, "create") else 0,
	}


# --------------------------------------------- page access (hooks.after_migrate)


def setup_po_list_page_access():
	"""Let the purchase roles open the list page. Idempotent; runs on every migrate.

	Has Role rows are inserted directly rather than through page.save(), which in
	developer_mode rewrites the tracked page JSON.
	"""
	if not frappe.db.exists("Page", PAGE_NAME):
		return
	for role in PAGE_ROLES:
		if not frappe.db.exists("Role", role):
			continue
		if frappe.db.exists("Has Role", {"parenttype": "Page", "parent": PAGE_NAME, "role": role}):
			continue
		frappe.get_doc(
			{
				"doctype": "Has Role",
				"parenttype": "Page",
				"parentfield": "roles",
				"parent": PAGE_NAME,
				"role": role,
			}
		).insert(ignore_permissions=True)
	frappe.clear_cache()
