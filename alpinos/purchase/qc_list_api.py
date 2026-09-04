"""Server side of the Purchase QC list screen (BRD "Purchase Inward Part -1" 3.1 - 3.5).

Task 303. One paginated endpoint feeds the desk page at `purchase_qc_list`, which is
the "QC Dashboard" the BRD keeps referring to (BR-QC-01):

    3.1 columns   -> LIST_FIELDS + the Purchase Order / UOM enrichment below
    3.3 filters   -> get_purchase_qc_list() keyword arguments
    3.4/3.5 buttons -> _row_actions(), derived from the workflow engine
    BR-QC-03/04   -> the SLA countdown and breach flag returned on every row

The row buttons are NOT a status-to-buttons map: for an open inspection they are read
off `alpinos.purchase.workflow.available_actions()` for the LINKED Purchase Inward, so
the list can never offer a Start QC that `purchase_qc.start_qc` would then refuse (it
runs `assert_transition` against that same inward). The one thing the engine offers and
this list deliberately drops is `complete_qc` — BRD 3.4 is explicit that Complete QC
lives inside the QC screen, so an in-progress row gets "Continue QC", which only reopens
the inspection.

`frappe.get_all` bypasses `has_permission` hooks and User Permissions, so the rows the
user actually sees come from `frappe.get_list` behind an explicit `frappe.has_permission`
gate. The `get_all` calls here are narrowing/enrichment helpers whose input is either fed
back into that permission-filtered query or is keyed off rows it has already returned.
"""

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, get_fullname, getdate, now_datetime, time_diff_in_seconds

from alpinos.purchase import constants as C
from alpinos.purchase import workflow

DOCTYPE = "Purchase QC"
INWARD_DOCTYPE = "Purchase Inward"
INWARD_ITEM_DOCTYPE = "Purchase Inward Item"
PAGE_NAME = "purchase_qc_list"

PAGE_LENGTHS = (20, 50, 100)
DEFAULT_PAGE_LENGTH = 20

# Roles allowed to open the desk page. The DocPerm matrix in alpinos.purchase.roles
# still governs what they can do once inside.
PAGE_ROLES = C.ALL_PURCHASE_ROLES + ("System Manager",)

# Columns of BRD 3.1, plus QC Status / QC Result, the SLA clock and the link fields the
# row buttons route to.
LIST_FIELDS = (
	"name",
	"purchase_inward",
	"supplier",
	"supplier_name",
	"supplier_order_no",
	"invoice_number",
	"inward_type",
	"received_qty",
	"inspector",
	"inspection_date",
	"company",
	"qc_status",
	"qc_result",
	"sla_start",
	"sla_due",
	"sla_breached",
	"total_approved_qty",
	"total_rejected_qty",
	"purchase_receipt",
	"debit_note",
	"owner",
	"docstatus",
	"modified",
)

# Fields pulled off the linked Purchase Inward: the first block is displayed (BRD 3.1
# "Order No."), the rest is what the workflow guards read. It MUST cover every field
# read by a guard in alpinos.purchase.workflow — the guards are handed a lightweight
# stub rather than a full Document, so a 100-row page costs two queries and not a
# hundred get_doc() calls.
_INWARD_FIELDS = (
	"name",
	"purchase_order",
	"inward_status",
	"docstatus",
	"actual_arrival_datetime",
	"vehicle_details_verified",
	"actual_vehicle_no",
	"actual_driver_contact_no",
	"purchase_qc",
	"purchase_receipt",
	"purchase_invoice",
)

# Sort columns arrive from the client as raw strings and are interpolated into
# order_by, so only these are accepted. "Order No." is enriched, not stored on the QC,
# and is deliberately absent.
_SORTABLE = frozenset(
	{
		"name",
		"purchase_inward",
		"supplier_name",
		"supplier_order_no",
		"invoice_number",
		"inward_type",
		"received_qty",
		"inspector",
		"inspection_date",
		"qc_status",
		"qc_result",
		"sla_due",
		"modified",
		"creation",
	}
)

# QC statuses at which the SLA clock is still running (BR-QC-03).
_SLA_OPEN_STATUSES = (C.QC_PENDING, C.QC_IN_PROGRESS, C.QC_SLA_BREACHED, C.QC_READY_FOR_DECISION)

# An action is additionally gated on the DocPerm performing it needs, so a role the
# workflow lets see "Start QC" but that cannot write a Purchase QC is not offered it.
_ACTION_PTYPE = {
	"start_qc": "write",
	"continue_qc": "write",
}

_SLA_ANY = ""
_SLA_BREACHED = "breached"
_SLA_WITHIN = "within"

# Row-level SLA states the page renders; "done" means the inspection closed, so the
# clock stopped whether or not it was met.
SLA_STATE_NONE = ""
SLA_STATE_OK = "ok"
SLA_STATE_BREACHED = "breached"
SLA_STATE_MET = "met"
SLA_STATE_MISSED = "missed"


# ----------------------------------------------------------------- filter helpers


def _like(value):
	"""LIKE pattern for `value`, with any wildcards the user typed stripped out.

	Without the strip a user typing `%` dumps the whole table.
	"""
	safe = str(value or "").strip().replace("%", "").replace("_", "")
	return f"%{safe}%" if safe else ""


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
	"""Document-level ptypes the current user holds on Purchase QC, resolved once."""
	return {
		ptype: bool(frappe.has_permission(DOCTYPE, ptype))
		for ptype in ("write", "create", "submit", "cancel", "print")
	}


def _breached_names(limit=5000):
	"""Names of every QC that has breached its SLA, or is overdue right now.

	Two conditions, because they disagree between scheduler runs: `sla_breached` is the
	recorded verdict (set on validate and by the escalation job in
	alpinos.purchase.notifications), while an open inspection whose `sla_due` has just
	passed is already breached even though nothing has stamped it yet.
	"""
	now = now_datetime()
	names = set(
		frappe.get_all(DOCTYPE, filters={"sla_breached": 1}, pluck="name", limit=limit)
	)
	names.update(
		frappe.get_all(
			DOCTYPE,
			filters={
				"sla_due": ["<", now],
				"qc_status": ["in", list(_SLA_OPEN_STATUSES)],
				"docstatus": ["<", 2],
			},
			pluck="name",
			limit=limit,
		)
	)
	return list(names)


# ------------------------------------------------------------------ list endpoint


@frappe.whitelist()
def get_purchase_qc_list(
	start=0,
	page_length=DEFAULT_PAGE_LENGTH,
	qc_id=None,
	purchase_inward=None,
	supplier=None,
	supplier_order_no=None,
	invoice_number=None,
	inward_type=None,
	from_date=None,
	to_date=None,
	inspector=None,
	qc_result=None,
	qc_status=None,
	sla_state=None,
	sort_field=None,
	sort_dir=None,
	with_actions=1,
):
	"""One page of Purchase QC rows for the list screen, plus its action buttons.

	Every argument arrives from `frappe.call` as a string, so numbers are cint()ed and
	the page size is clamped server-side — a client can otherwise ask for 100000 rows.

	Filters are built as a list of [field, operator, value] triples rather than a dict
	because two different filters (QC ID and the SLA state) both constrain `name`, and
	a dict can only hold one condition per key.
	"""
	if not frappe.has_permission(DOCTYPE, "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	start = max(cint(start), 0)
	page_length = min(max(cint(page_length) or DEFAULT_PAGE_LENGTH, 1), max(PAGE_LENGTHS))

	filters = []

	# BRD 3.3 "QC ID" / "Purchase Inward ID" / "Supplier Order No." / "Invoice Number"
	for field, raw in (
		("name", qc_id),
		("purchase_inward", purchase_inward),
		("supplier_order_no", supplier_order_no),
		("invoice_number", invoice_number),
	):
		pattern = _like(raw)
		if pattern:
			filters.append([field, "like", pattern])

	# BRD 3.3 "Vendor Name" / "Inspector" — exact links, not text searches
	if supplier:
		filters.append(["supplier", "=", str(supplier).strip()])
	if inspector:
		filters.append(["inspector", "=", str(inspector).strip()])

	# BRD 3.3 "Inward Type" / "QC Result" / "Current Status" — vocabulary only, so a
	# stale saved filter or a hand-built URL cannot inject an unknown value.
	value = _one_of(inward_type, C.INWARD_TYPES)
	if value:
		filters.append(["inward_type", "=", value])
	value = _one_of(qc_result, C.QC_RESULTS)
	if value:
		filters.append(["qc_result", "=", value])
	value = _one_of(qc_status, C.QC_STATUSES)
	if value:
		filters.append(["qc_status", "=", value])

	# BRD 3.3 "Inspection Date" — a single date or a range. inspection_date is a
	# Datetime, so the bounds are widened to cover the whole day.
	fd = _date(from_date)
	td = _date(to_date)
	if fd and td and fd > td:
		fd, td = td, fd
	if fd and td:
		filters.append(["inspection_date", "between", [f"{fd} 00:00:00", f"{td} 23:59:59"]])
	elif fd:
		filters.append(["inspection_date", ">=", f"{fd} 00:00:00"])
	elif td:
		filters.append(["inspection_date", "<=", f"{td} 23:59:59"])

	# BR-QC-03 / BR-QC-04 — the dashboard's own filter: show only what has blown the
	# 2-hour SLA, or only what is still inside it.
	sla_state = str(sla_state or "").strip()
	if sla_state in (_SLA_BREACHED, _SLA_WITHIN):
		names = _breached_names()
		if sla_state == _SLA_BREACHED:
			# an empty IN () list is dropped by the query builder and returns everything
			filters.append(["name", "in", names or ["__no_sla_match__"]])
		else:
			filters.append(["name", "not in", names or ["__no_sla_match__"]])

	sf = str(sort_field or "").strip()
	sd = "asc" if str(sort_dir or "").strip().lower() == "asc" else "desc"
	order_by = f"`{sf}` {sd}" if sf in _SORTABLE else "modified desc"

	# A lone count() with no group by drops the default order by, so this is one plain
	# aggregate over the same permission-filtered set.
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

	_attach_row_extras(rows, with_actions=cint(with_actions))

	return {
		"data": rows,
		"has_more": int(has_more),
		"start": start,
		"page_length": page_length,
		"total": total,
	}


def _attach_row_extras(rows, with_actions=1):
	"""Order No., display UOM, inspector name, the SLA clock and the row buttons.

	Two bulk queries for the whole page, never one per row.
	"""
	if not rows:
		return

	inward_names = sorted({r.purchase_inward for r in rows if r.get("purchase_inward")})
	inwards = {}
	uom_by_inward = {}
	if inward_names:
		for inward in frappe.get_all(
			INWARD_DOCTYPE, filters={"name": ["in", inward_names]}, fields=list(_INWARD_FIELDS)
		):
			inwards[inward.name] = inward
		for line in frappe.get_all(
			INWARD_ITEM_DOCTYPE,
			filters={"parenttype": INWARD_DOCTYPE, "parent": ["in", inward_names]},
			fields=["parent", "uom"],
		):
			if line.uom:
				uom_by_inward.setdefault(line.parent, set()).add(line.uom)

	perms = _docperms() if with_actions else {}
	fullnames = {}
	now = now_datetime()

	for row in rows:
		inward = inwards.get(row.get("purchase_inward"))

		# BRD 3.1 "Order No." — the Purchase Order the inward was raised against, with
		# the vendor's own order number as the fallback for a PO-less inward.
		row["purchase_order"] = (inward or {}).get("purchase_order") or ""
		row["inward_status"] = (inward or {}).get("inward_status") or ""

		# BRD 3.1 prints quantities as "2,500 KG"; a mixed-UOM inward has no single unit
		# to print, so the page falls back to a bare number.
		uoms = uom_by_inward.get(row.get("purchase_inward")) or set()
		row["uom"] = next(iter(uoms)) if len(uoms) == 1 else ""

		for field in ("inspector", "owner"):
			user = row.get(field)
			if user and user not in fullnames:
				fullnames[user] = get_fullname(user)
		row["inspector_full_name"] = fullnames.get(row.get("inspector")) or ""
		row["owner_full_name"] = fullnames.get(row.get("owner")) or ""

		_attach_sla(row, now)
		row["actions"] = _row_actions(row, inward, perms) if with_actions else []


def _attach_sla(row, now):
	"""BR-QC-03 / BR-QC-04 — how long is left on the 2-hour clock, and was it blown.

	`sla_seconds_left` is signed: negative means overdue by that many seconds. The page
	formats it and ticks it down locally, so the number never has to be re-fetched.
	"""
	due = row.get("sla_due")
	closed = cint(row.get("docstatus")) != 0 or row.get("qc_status") in (
		C.QC_COMPLETED,
		C.QC_CANCELLED,
	)

	if not due:
		row["sla_seconds_left"] = None
		row["sla_state"] = SLA_STATE_MET if closed else SLA_STATE_NONE
		row["sla_is_breached"] = 0
		return

	seconds = int(time_diff_in_seconds(get_datetime(due), now))
	row["sla_seconds_left"] = seconds

	if closed:
		# the clock has stopped; only the recorded verdict still matters
		breached = cint(row.get("sla_breached"))
		row["sla_state"] = SLA_STATE_MISSED if breached else SLA_STATE_MET
		row["sla_is_breached"] = 1 if breached else 0
		return

	# an open inspection past its due time is breached even before the escalation job
	# has stamped sla_breached (alpinos.purchase.notifications runs every 30 minutes)
	breached = cint(row.get("sla_breached")) or seconds < 0
	row["sla_state"] = SLA_STATE_BREACHED if breached else SLA_STATE_OK
	row["sla_is_breached"] = 1 if breached else 0


def _view_action(action, label):
	return {
		"action": action,
		"label": label,
		"kind": "view",
		"enabled": True,
		"reason": None,
	}


def _row_actions(row, inward, perms):
	"""BRD 3.4 / 3.5 buttons for one row.

	Pending QC -> Start QC, QC In Progress -> Continue QC, QC Completed -> View QC
	Report + Print. "QC SLA Breached" is not a stage of its own — it overwrites Pending
	QC / QC In Progress on the QC document — so which of the first two a breached row
	gets is decided by the linked inward's status through the workflow engine, exactly
	as `purchase_qc.start_qc` will re-decide it server-side.
	"""
	docstatus = cint(row.get("docstatus"))
	status = row.get("qc_status") or ""

	if docstatus == 2 or status == C.QC_CANCELLED:
		return []

	if docstatus == 1 or status == C.QC_COMPLETED:
		actions = [_view_action("view_qc_report", _("View QC Report"))]
		if perms.get("print", True):
			actions.append(_view_action("print", _("Print")))
		return actions

	if not inward:
		return []

	stub = frappe._dict(dict(inward))
	stub["doctype"] = INWARD_DOCTYPE
	engine = {a["action"]: a for a in workflow.available_actions(stub)}

	actions = []
	if "start_qc" in engine:
		offered = engine["start_qc"]
		actions.append(
			{
				"action": "start_qc",
				"label": _("Start QC"),
				"kind": "transition",
				"enabled": bool(offered.get("enabled")),
				"reason": offered.get("reason"),
			}
		)
	elif "complete_qc" in engine:
		# BRD 3.4 note: Complete QC belongs to the QC screen, never to this list. The
		# list only reopens the inspection that is already running.
		actions.append(_view_action("continue_qc", _("Continue QC")))

	return [
		a
		for a in actions
		if not _ACTION_PTYPE.get(a["action"]) or perms.get(_ACTION_PTYPE[a["action"]])
	]


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
		"qc_statuses": "\n" + C.select_options([s for s in C.QC_STATUSES if s]),
		"qc_results": "\n" + C.select_options([r for r in C.QC_RESULTS if r]),
		"sla_states": [
			{"value": _SLA_ANY, "label": ""},
			{"value": _SLA_BREACHED, "label": _("SLA Breached")},
			{"value": _SLA_WITHIN, "label": _("Within SLA")},
		],
		"page_lengths": list(PAGE_LENGTHS),
		"sla_hours": C.QC_SLA_HOURS,
	}


# --------------------------------------------- page access (hooks.after_migrate)


def setup_qc_list_page_access():
	"""Let the module roles open the QC list page. Idempotent; safe on every migrate.

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
