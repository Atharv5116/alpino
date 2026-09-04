"""Server side of the Purchase Inward list screen (BRD "Purchase Inward Part -1" 1.1 - 1.4).

Task 292. One paginated endpoint feeds the desk page at `purchase_inward_list`:

    1.1 columns   -> LIST_FIELDS + the roll-ups already stored on the parent
    1.2 filters   -> get_purchase_inward_list() keyword arguments
    1.3/1.4 buttons -> alpinos.purchase.workflow.available_actions()

The per-row action buttons are resolved by the workflow engine, never by a
status-to-buttons map kept here or in the page JS, so the list can never offer an
action the server would refuse (and vice versa). A transition whose guard fails is
still returned, disabled, carrying the guard's reason for the button tooltip.

`frappe.get_all` bypasses `has_permission` hooks and User Permissions, so every row
the user actually sees is fetched with `frappe.get_list` (which applies both) behind
an explicit `frappe.has_permission` gate. There are exactly two `get_all` calls: the
vehicle-number lookup, whose output is only a name set ANDed into that same
permission-filtered query, and the child-row fetch, which reads the item lines of
parents the user has already been granted.
"""

import frappe
from frappe import _
from frappe.utils import cint, get_fullname, getdate

from alpinos.purchase import constants as C
from alpinos.purchase import workflow

DOCTYPE = "Purchase Inward"
ITEM_DOCTYPE = "Purchase Inward Item"
PAGE_NAME = "purchase_inward_list"

PAGE_LENGTHS = (20, 50, 100)
DEFAULT_PAGE_LENGTH = 20

# Roles allowed to open the desk page. The DocPerm matrix in alpinos.purchase.roles
# still governs what they can do once inside.
PAGE_ROLES = C.ALL_PURCHASE_ROLES + ("System Manager",)

# Columns of BRD 1.1 plus the link fields the row buttons route to. The last block
# is not displayed: it is what the workflow guards read (see _GUARD_FIELDS).
LIST_FIELDS = (
	"name",
	"purchase_order",
	"inward_type",
	"supplier",
	"supplier_name",
	"supplier_order_no",
	"invoice_number",
	"invoice_date",
	"inward_datetime",
	"company",
	"inward_status",
	"qc_status",
	"grn_status",
	"total_order_qty",
	"total_received_qty",
	"total_pending_qty",
	"total_items",
	"po_vehicle_no",
	"actual_vehicle_no",
	"purchase_qc",
	"purchase_receipt",
	"purchase_invoice",
	# BRD 5.2.3's "View Debit Note" row button routes on this, so the list has to select it
	"debit_note",
	"owner",
	"docstatus",
	"modified",
	"actual_arrival_datetime",
	"vehicle_details_verified",
	"actual_driver_contact_no",
)

# Fields handed to the workflow guards. MUST cover every field read by a guard in
# alpinos.purchase.workflow (plus `items`, attached separately) — the guards are given
# a lightweight stub rather than a full Document so a 100-row page costs two queries
# instead of a hundred get_doc() calls.
_GUARD_FIELDS = (
	"name",
	"inward_status",
	"docstatus",
	"actual_arrival_datetime",
	"vehicle_details_verified",
	"actual_vehicle_no",
	"actual_driver_contact_no",
	"purchase_qc",
	"purchase_receipt",
	"purchase_invoice",
	"debit_note",
)

# Sort columns arrive from the client as raw strings and are interpolated into
# order_by, so only these are accepted.
# Columns the list DISPLAYS as one value but stores in two. The Vehicle No. column
# renders `actual_vehicle_no or po_vehicle_no` (see _attach_row_extras), so sorting on
# actual_vehicle_no alone left the key blank for every row still awaiting receipt and the
# header looked broken. Sorting on the same expression the cell shows fixes that.
_SORT_EXPRESSIONS = {
	"vehicle_no": "COALESCE(NULLIF(`actual_vehicle_no`, ''), `po_vehicle_no`)",
}

_SORTABLE = frozenset(
	{
		"name",
		"purchase_order",
		"inward_type",
		"supplier_name",
		"supplier_order_no",
		"invoice_number",
		"inward_datetime",
		"inward_status",
		"qc_status",
		"grn_status",
		"total_order_qty",
		"total_received_qty",
		"total_items",
		"actual_vehicle_no",
		"owner",
		"modified",
		"creation",
	}
)

# An action is additionally gated on the DocPerm that performing it needs, so a role
# the workflow lets see "Delete" but that has no delete permission is not offered it.
_ACTION_PTYPE = {
	"edit": "write",
	"delete": "delete",
	"continue_receiving": "write",
	"submit": "submit",
	"submit_for_qc": "write",
}


# ----------------------------------------------------------------- filter helpers


def _like(value):
	"""LIKE pattern for `value`, neutralising the wildcards the user typed.

	`%` is dropped outright -- typing one would dump the whole table. `_` is ESCAPED
	rather than deleted: it is a single-character wildcard, but it is also an ordinary
	character in real invoice numbers, and deleting it silently changed the question
	(searching "INV_2026_001" became LIKE '%INV2026001%', which matches nothing).
	The leading backslash doubling keeps a literal backslash from escaping the escape.
	"""
	safe = str(value or "").strip().replace("\\", "\\\\").replace("%", "")
	safe = safe.replace("_", "\\_")
	return f"%{safe}%" if safe.strip() else ""


def _restrict_names(filters, names):
	"""AND a name-restriction into `filters`, intersecting with any already applied.

	Two filters resolve to a `name IN (...)` set (Vehicle Number and QC Result). Each
	assigning filters["name"] directly would let the second silently discard the first,
	so the sets are intersected here. An empty IN () list is dropped by the query builder
	and would return everything, hence the sentinel.
	"""
	names = set(names or [])
	existing = filters.get("name")
	if existing and isinstance(existing, (list, tuple)) and existing[0] == "in":
		names &= set(existing[1])
	filters["name"] = ["in", sorted(names) or ["__no_match__"]]


def _one_of(value, allowed):
	"""Return `value` only when it is part of the module vocabulary, else None."""
	value = str(value or "").strip()
	return value if value in allowed else None


def _date(value):
	if not value:
		return None
	try:
		return getdate(value)
	except Exception:
		return None


def _docperms():
	"""Document-level ptypes the current user holds, resolved once per request."""
	return {
		ptype: bool(frappe.has_permission(DOCTYPE, ptype))
		for ptype in ("write", "create", "delete", "submit", "cancel")
	}


# ------------------------------------------------------------------ list endpoint


@frappe.whitelist()
def get_purchase_inward_list(
	start=0,
	page_length=DEFAULT_PAGE_LENGTH,
	search=None,
	inward_type=None,
	supplier=None,
	from_date=None,
	to_date=None,
	supplier_order_no=None,
	vehicle_no=None,
	qc_status=None,
	qc_result=None,
	inward_status=None,
	created_by=None,
	purchase_order=None,
	sort_field=None,
	sort_dir=None,
	with_actions=1,
):
	"""One page of Purchase Inward rows for the list screen, plus its action buttons.

	Every argument arrives from `frappe.call` as a string, so numbers are cint()ed and
	the page size is clamped server-side — a client can otherwise ask for 100000 rows.
	"""
	if not frappe.has_permission(DOCTYPE, "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	start = max(cint(start), 0)
	page_length = min(max(cint(page_length) or DEFAULT_PAGE_LENGTH, 1), max(PAGE_LENGTHS))

	filters = {}

	# BRD 1.2 "Inward Type" / "QC Status" / "Current Status" — vocabulary only, so a
	# stale saved filter or a hand-built URL cannot inject an unknown value.
	value = _one_of(inward_type, C.INWARD_TYPES)
	if value:
		filters["inward_type"] = value
	value = _one_of(qc_status, C.QC_STATUSES)
	if value:
		filters["qc_status"] = value

	# BRD 1.2 asks for QC Status = Pending / In Progress / Approved / Rejected / Partial
	# Approved. The first two are workflow statuses (qc_status above); the last three are
	# QC *outcomes*, which live on the Purchase QC as qc_result and have no column on the
	# inward at all -- so filtering "show me everything QC rejected" was impossible. It is
	# resolved to a name IN (...) set, the same way the Vehicle Number filter is.
	value = _one_of(qc_result, C.QC_RESULTS)
	if value:
		_restrict_names(
			filters,
			frappe.get_all(
				"Purchase QC",
				filters={"qc_result": value, "docstatus": ("<", 2)},
				pluck="purchase_inward",
				limit=5000,
			),
		)
	value = _one_of(inward_status, C.PI_STATUSES)
	if value:
		filters["inward_status"] = value

	# BRD 1.2 "Vendor Name" (exact vendor) / "PO Number" / "Created By"
	if supplier:
		filters["supplier"] = str(supplier).strip()
	if purchase_order:
		filters["purchase_order"] = str(purchase_order).strip()
	if created_by:
		filters["owner"] = str(created_by).strip()

	# BRD 1.2 "Order No." — the vendor's own order number, not ours
	order_no_like = _like(supplier_order_no)
	if order_no_like:
		filters["supplier_order_no"] = ["like", order_no_like]

	# BRD 1.2 "Inward Date" — a single date or a range. inward_datetime is a Datetime,
	# so the bounds are widened to cover the whole day.
	fd = _date(from_date)
	td = _date(to_date)
	if fd and td and fd > td:
		fd, td = td, fd
	if fd and td:
		filters["inward_datetime"] = ["between", [f"{fd} 00:00:00", f"{td} 23:59:59"]]
	elif fd:
		filters["inward_datetime"] = [">=", f"{fd} 00:00:00"]
	elif td:
		filters["inward_datetime"] = ["<=", f"{td} 23:59:59"]

	# BRD 1.2 "Vehicle Number" — matches the actual vehicle or, before the Store has
	# recorded one, the vehicle planned on the Purchase Order. Two columns need an OR,
	# and or_filters is already spent on the search box, so it is resolved to a name IN
	# (...) set; the visible rows still come from the permission-filtered query below.
	vehicle_like = _like(vehicle_no)
	if vehicle_like:
		vehicle_names = frappe.get_all(
			DOCTYPE,
			or_filters=[
				["actual_vehicle_no", "like", vehicle_like],
				["po_vehicle_no", "like", vehicle_like],
			],
			pluck="name",
			limit=5000,
		)
		_restrict_names(filters, vehicle_names)

	or_filters = None
	search_like = _like(search)
	if search_like:
		or_filters = [
			["name", "like", search_like],
			["supplier_name", "like", search_like],
			["invoice_number", "like", search_like],
		]

	sf = str(sort_field or "").strip()
	sd = "asc" if str(sort_dir or "").strip().lower() == "asc" else "desc"
	if sf in _SORT_EXPRESSIONS:
		order_by = f"{_SORT_EXPRESSIONS[sf]} {sd}"
	elif sf in _SORTABLE:
		order_by = f"`{sf}` {sd}"
	else:
		order_by = "modified desc"

	# A lone count() with no group by drops the default order by, so this is one plain
	# aggregate over the same permission-filtered set.
	count_rows = frappe.get_list(
		DOCTYPE,
		fields=["count(name) as total"],
		filters=filters or None,
		or_filters=or_filters,
		limit_page_length=0,
	)
	total = cint(count_rows[0].get("total")) if count_rows else 0

	rows = frappe.get_list(
		DOCTYPE,
		fields=list(LIST_FIELDS),
		filters=filters or None,
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
	"""Created-by name, display UOM, vehicle number and the row's action buttons.

	One bulk query for the whole page, never one per row.
	"""
	if not rows:
		return

	names = [r.name for r in rows]
	lines_by_parent = {}
	for line in frappe.get_all(
		ITEM_DOCTYPE,
		filters={"parenttype": DOCTYPE, "parent": ["in", names]},
		fields=["parent", "idx", "item_code", "uom", "received_qty", "target_warehouse"],
		order_by="parent asc, idx asc",
	):
		lines_by_parent.setdefault(line.parent, []).append(line)

	perms = _docperms() if with_actions else {}
	fullnames = {}

	for row in rows:
		lines = lines_by_parent.get(row.name) or []

		# BRD 1.1 prints quantities as "3,000 KG"; a mixed-UOM inward has no single
		# unit to print, so the page falls back to a bare number.
		uoms = {line.uom for line in lines if line.uom}
		row["uom"] = uoms.pop() if len(uoms) == 1 else ""

		if row.owner not in fullnames:
			fullnames[row.owner] = get_fullname(row.owner)
		row["owner_full_name"] = fullnames[row.owner]

		# the Store's actual vehicle wins; before receiving, show what the PO planned
		row["vehicle_no"] = (row.get("actual_vehicle_no") or "").strip() or (
			row.get("po_vehicle_no") or ""
		)

		row["actions"] = _row_actions(row, lines, perms) if with_actions else []


def _row_actions(row, lines, perms):
	"""BRD 1.3 / 1.4 buttons for one row, straight from the workflow engine.

	One guard — `_guard_grn_submitted` — reads the linked GRN's docstatus itself, so a
	page of rows sitting in GRN Generated costs one primary-key lookup each. That guard
	is the workflow engine's, not this module's; bulk-loading it here would mean holding
	a second copy of the rule, which is exactly what reading the buttons off
	`available_actions()` exists to prevent.
	"""
	stub = frappe._dict({field: row.get(field) for field in _GUARD_FIELDS})
	stub["doctype"] = DOCTYPE
	stub["items"] = lines

	actions = []
	for action in workflow.available_actions(stub):
		ptype = _ACTION_PTYPE.get(action.get("action"))
		if ptype and not perms.get(ptype):
			continue
		actions.append(action)
	return actions


# --------------------------------------------------------------- page vocabulary


@frappe.whitelist()
def get_filter_options():
	"""Select options for the list page, sourced from alpinos.purchase.constants.

	Fetched once per session by the page so the status vocabulary lives in exactly one
	place; the page keeps a hard-coded fallback for the case where this call fails.
	"""
	if not frappe.has_permission(DOCTYPE, "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	return {
		"inward_types": [{"value": "", "label": ""}]
		+ [{"value": t, "label": C.label_for_inward_type(t)} for t in C.INWARD_TYPES],
		"inward_statuses": "\n" + C.select_options(C.PI_STATUSES),
		"qc_statuses": "\n" + C.select_options([s for s in C.QC_STATUSES if s]),
		"qc_results": "\n" + C.select_options([r for r in C.QC_RESULTS if r]),
		"page_lengths": list(PAGE_LENGTHS),
		"can_create": 1 if frappe.has_permission(DOCTYPE, "create") else 0,
	}


# --------------------------------------------- page access (hooks.after_migrate)


def setup_inward_list_page_access():
	"""Let the module roles open the list page. Idempotent; safe on every migrate.

	Roles are inserted as Has Role rows rather than through page.save(), which in
	developer_mode rewrites the tracked page JSON. Must run AFTER the standard page
	sync and after alpinos.purchase.roles.setup_purchase_roles() has created the
	roles — a role that does not exist yet is skipped, not created here.
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
