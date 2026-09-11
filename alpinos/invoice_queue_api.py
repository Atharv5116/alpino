"""Server side of the Invoice Download Queue: access, columns, filters, sorting, export.

The DOWNLOAD logic is not here and is not touched by this module. Downloading still
goes through alpinos.sales_order_api, and membership of the queue still comes from
alpinos.pending_invoice_api. This file only decides WHICH ROWS a user may see, WHICH
COLUMNS they may ask for, and how those rows are filtered, ordered and exported.

CHANNEL ACCESS
--------------
Three role groups, enforced here rather than in the page, so a crafted API call, a
saved view, a sort or an export cannot reach rows the screen would have hidden:

  * E-Commerce Admin / Coordinator / Manager -> E-com only, locked.
  * Sales Manager / Admin / User            -> the offline channels, locked.
  * Warehouse Admin / Manager, Accounts User -> every channel, free to choose.

"Offline" means both `Offline` and `General Trade`: General Trade is an offline
channel, so locking Sales to the literal string would hide its own orders from the
team that owns them.

Unrestricted wins when a user holds roles from more than one group — holding a
warehouse or accounts role is what makes someone cross-channel, and the narrow
roles are there to scope a specialist, not to cage a generalist.

A user holding NONE of the nine named roles is left unrestricted, which is what the
page did before this change; their ordinary Sales Order permissions still apply.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

DOCTYPE = "Sales Order"

CHANNEL_ECOM = "E-com"
# The user's call: General Trade is an offline channel.
OFFLINE_CHANNELS = ("Offline", "General Trade")

ECOM_ROLES = ("E-Commerce Admin", "E-Commerce Coordinator", "E-Commerce Manager")
OFFLINE_ROLES = ("Sales Manager", "Sales Admin", "Sales User")
UNRESTRICTED_ROLES = ("Warehouse Admin", "Warehouse Manager", "Accounts User")

DEFAULT_PAGE_LENGTH = 50
MAX_PAGE_LENGTH = 2000


# --------------------------------------------------------------------- access


def _roles(user=None):
	return set(frappe.get_roles(user or frappe.session.user))


def resolve_access(user=None):
	"""What channels this user may see, and whether the filter is theirs to change."""
	roles = _roles(user)

	if roles.intersection(UNRESTRICTED_ROLES) or "System Manager" in roles:
		return {"channels": None, "locked": False, "default": None, "group": "unrestricted"}
	if roles.intersection(ECOM_ROLES):
		return {
			"channels": [CHANNEL_ECOM], "locked": True,
			"default": CHANNEL_ECOM, "group": "ecom",
		}
	if roles.intersection(OFFLINE_ROLES):
		return {
			"channels": list(OFFLINE_CHANNELS), "locked": True,
			"default": OFFLINE_CHANNELS[0], "group": "offline",
		}
	# None of the nine named roles: unchanged from before, doc permissions still apply.
	return {"channels": None, "locked": False, "default": None, "group": "unnamed"}


@frappe.whitelist()
def get_access():
	"""What the page needs to draw and lock its Channel filter."""
	_assert_can_read()
	access = resolve_access()
	return {
		"channels": access["channels"],
		"locked": access["locked"],
		"default_channel": access["default"],
		"selectable": access["channels"] or _all_channels(),
	}


def _all_channels():
	return [c.name for c in frappe.get_all("Channel", fields=["name"], order_by="name")]


def _assert_can_read():
	if not frappe.has_permission(DOCTYPE, "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)


def _channel_condition(requested):
	"""(sql, params) restricting the query to what this user may see.

	`requested` narrows WITHIN the allowance; it can never widen it. A locked user
	asking for another channel is refused outright rather than silently ignored,
	because silently returning someone else's channel would be the worse failure.
	"""
	access = resolve_access()
	allowed = access["channels"]

	if requested:
		if allowed is not None and requested not in allowed:
			frappe.throw(
				_("You do not have access to the {0} channel.").format(requested),
				frappe.PermissionError,
			)
		return "so.custom_channel = %(channel)s", {"channel": requested}

	if allowed is None:
		return "1 = 1", {}
	return (
		"so.custom_channel IN %(allowed_channels)s",
		{"allowed_channels": tuple(allowed)},
	)


# -------------------------------------------------------------------- columns

# The catalogue every other part of this module reads: the page draws from it, the
# sort validates against it, and the export renders it. A column that is not here
# cannot be selected, sorted or exported, which is what keeps a crafted request from
# reaching a field nobody meant to expose.
#
# `select` is the SQL expression; `sortable` False marks a column computed in Python
# after the page is fetched, which cannot participate in an ORDER BY.
COLUMNS = {
	"channel":        {"label": "Channel",        "select": "so.custom_channel",       "type": "Data"},
	"order_date":     {"label": "Order Date",     "select": "so.transaction_date",     "type": "Date"},
	"dispatch_date":  {"label": "Dispatch Date",  "select": "so.custom_dispatch_date", "type": "Date"},
	"customer_type":  {"label": "Customer Type",  "select": "so.order_type",           "type": "Data"},
	"sales_order":    {"label": "Sales Order ID", "select": "so.name",                 "type": "Link"},
	"customer_po_no": {"label": "Customer PO No.",
	                   "select": "COALESCE(NULLIF(so.po_no, ''), NULLIF(so.custom_po_number, ''), '')",
	                   "type": "Data"},
	"customer_name":  {"label": "Customer",       "select": "so.customer_name",        "type": "Data"},
	"pl_po_no":       {"label": "PL PO No.",      "select": "pl.pl_po_no",             "type": "Data"},
	"state":          {"label": "State",          "select": "addr.state",              "type": "Data"},
	"invoice_id":     {"label": "Invoice Number", "select": "so.custom_invoice_no",    "type": "Data"},
	"transporter":    {"label": "Transporter",    "select": "pl.transporter",          "type": "Data"},
	"lr_number":      {"label": "LR No.",         "select": "dn.lr_no",                "type": "Data"},
	"so_amount":      {"label": "Sales Order Amount", "select": "so.grand_total",      "type": "Currency"},
	# Already maintained on the order by alpinos.so_invoice_value; read, never
	# recomputed, or the queue and the order would answer differently.
	"invoice_amount": {"label": "Invoice Amount",
	                   "select": "IFNULL(so.custom_total_invoice_value, 0)", "type": "Currency"},
	"amount_diff":    {"label": "Sales vs Invoice Difference Amount",
	                   "select": "(IFNULL(so.grand_total,0) - IFNULL(so.custom_total_invoice_value,0))",
	                   "type": "Currency"},
	"total_box":      {"label": "Total Box",      "select": "pl.total_box",            "type": "Float"},
	"weight":         {"label": "Weight",         "select": "pl.weight",               "type": "Float"},
	"owner_name":     {"label": "Owner (Sales Order Created By)",
	                   "select": "so.owner",      "type": "Data"},
	# Extras the page already showed, kept selectable so nothing regresses.
	"po_date":        {"label": "PO Date",        "select": "so.custom_po_date",       "type": "Date"},
	"pick_list":      {"label": "Pick List",      "select": "pl.pick_list",            "type": "Link"},
	"pdf_ready":      {"label": "PDF Ready",
	                   "select": "CASE WHEN IFNULL(so.custom_invoice_pdf,'') <> '' THEN 'Yes' ELSE 'No' END",
	                   "type": "Data"},
	"downloaded":     {"label": "Downloaded",
	                   "select": "CASE WHEN IFNULL(so.custom_invoice_downloaded,0) = 1 THEN 'Yes' ELSE 'No' END",
	                   "type": "Data"},
	# Combo-aware and per-row, so it is computed after the page is fetched.
	"undispatched":   {"label": "Undispatched Items / Qty", "select": None,
	                   "type": "Data", "sortable": False},
}

# The order the screen opens with, per the attached column sheet. `download` is not
# in COLUMNS at all: it is an action, not data, so it can never be reordered away,
# exported, or sorted on.
DEFAULT_COLUMNS = [
	"channel", "order_date", "dispatch_date", "customer_type", "sales_order",
	"customer_po_no", "customer_name", "pl_po_no", "state", "invoice_id",
	"transporter", "lr_number", "so_amount", "invoice_amount", "amount_diff",
	"undispatched", "total_box", "weight", "owner_name",
]


@frappe.whitelist()
def get_columns():
	"""The catalogue plus the default layout, so the client hard-codes neither."""
	_assert_can_read()
	return {
		"available": [
			{
				"key": k,
				"label": _(v["label"]),
				"type": v["type"],
				"sortable": v.get("sortable", True),
			}
			for k, v in COLUMNS.items()
		],
		"default": list(DEFAULT_COLUMNS),
	}


def _clean_columns(columns):
	"""Whatever the client asked for, narrowed to what the catalogue actually allows."""
	if isinstance(columns, str):
		columns = frappe.parse_json(columns)
	if not columns:
		return list(DEFAULT_COLUMNS)
	out = [c for c in columns if c in COLUMNS]
	return out or list(DEFAULT_COLUMNS)


# --------------------------------------------------------------------- query

_JOINS = """
	LEFT JOIN (
		SELECT custom_sales_order_id           AS so_id,
		       MIN(name)                       AS pick_list,
		       MAX(custom_po_no)               AS pl_po_no,
		       MAX(custom_transporter)         AS transporter,
		       SUM(IFNULL(custom_total_box, 0))     AS total_box,
		       SUM(IFNULL(custom_gross_weight, 0))  AS weight
		FROM `tabPick List`
		WHERE docstatus < 2 AND IFNULL(custom_sales_order_id, '') <> ''
		GROUP BY custom_sales_order_id
	) pl ON pl.so_id = so.name
	LEFT JOIN (
		SELECT custom_sales_order_id AS so_id,
		       GROUP_CONCAT(DISTINCT NULLIF(custom_lr_gr_no, '') SEPARATOR ', ') AS lr_no
		FROM `tabDelivery Note`
		WHERE docstatus < 2 AND IFNULL(is_return, 0) = 0
		  AND IFNULL(custom_sales_order_id, '') <> ''
		GROUP BY custom_sales_order_id
	) dn ON dn.so_id = so.name
	LEFT JOIN `tabAddress` addr ON addr.name = so.shipping_address_name
"""

# Filter key -> (SQL, how the value is bound)
_FILTERS = {
	"channel":        None,  # handled by _channel_condition, never as a plain filter
	"sales_order":    ("so.name LIKE %(sales_order)s", "like"),
	"customer_po_no": ("COALESCE(NULLIF(so.po_no,''), NULLIF(so.custom_po_number,'')) LIKE %(customer_po_no)s", "like"),
	"invoice_id":     ("so.custom_invoice_no LIKE %(invoice_id)s", "like"),
	"lr_number":      ("dn.lr_no LIKE %(lr_number)s", "like"),
	"customer":       ("so.customer = %(customer)s", "eq"),
	"customer_type":  ("so.order_type = %(customer_type)s", "eq"),
	"state":          ("addr.state = %(state)s", "eq"),
	"order_date_from":    ("so.transaction_date >= %(order_date_from)s", "eq"),
	"order_date_to":      ("so.transaction_date <= %(order_date_to)s", "eq"),
	"dispatch_date_from": ("so.custom_dispatch_date >= %(dispatch_date_from)s", "eq"),
	"dispatch_date_to":   ("so.custom_dispatch_date <= %(dispatch_date_to)s", "eq"),
}


def _escape_like(term):
	"""A typed underscore is a character, not a wildcard."""
	return (term or "").replace("\\", "\\\\").replace("%", "").replace("_", "\\_")


def _build(filters, columns, sort_field, sort_dir):
	filters = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})

	# Membership of the queue is unchanged: an order with an invoice number, not
	# cancelled. This mirrors the Pending Invoice Downloads report deliberately.
	conditions = ["IFNULL(so.custom_invoice_no, '') <> ''", "so.docstatus < 2"]
	params = {}

	chan_sql, chan_params = _channel_condition((filters.get("channel") or "").strip() or None)
	conditions.append(chan_sql)
	params.update(chan_params)

	for key, spec in _FILTERS.items():
		if not spec:
			continue
		value = filters.get(key)
		if value in (None, ""):
			continue
		sql, mode = spec
		conditions.append(sql)
		params[key] = f"%{_escape_like(value)}%" if mode == "like" else value

	select_keys = _clean_columns(columns)
	selects = ["so.name AS sales_order"]
	for key in select_keys:
		spec = COLUMNS[key]
		if spec["select"] and key != "sales_order":
			selects.append(f"{spec['select']} AS `{key}`")
	# The page always needs these, whether or not they are on screen: the download
	# buttons key off them.
	for key in ("pick_list", "pdf_ready", "downloaded", "invoice_id"):
		if key not in select_keys:
			selects.append(f"{COLUMNS[key]['select']} AS `{key}`")

	sort_key = sort_field if sort_field in COLUMNS else "order_date"
	if not COLUMNS[sort_key].get("sortable", True) or not COLUMNS[sort_key]["select"]:
		sort_key = "order_date"
	direction = "ASC" if str(sort_dir or "desc").lower() == "asc" else "DESC"
	order_by = f"{COLUMNS[sort_key]['select']} {direction}, so.name {direction}"

	return " AND ".join(conditions), params, selects, order_by, select_keys


@frappe.whitelist()
def get_rows(
	filters=None, columns=None, sort_field=None, sort_dir=None,
	start=0, page_length=DEFAULT_PAGE_LENGTH,
):
	"""One page of the queue, respecting role access, filters, sorting and columns."""
	_assert_can_read()
	where, params, selects, order_by, select_keys = _build(filters, columns, sort_field, sort_dir)

	start = max(cint(start), 0)
	page_length = min(max(cint(page_length) or DEFAULT_PAGE_LENGTH, 1), MAX_PAGE_LENGTH)

	rows = frappe.db.sql(
		f"""
		SELECT {", ".join(selects)}
		FROM `tabSales Order` so
		{_JOINS}
		WHERE {where}
		ORDER BY {order_by}
		LIMIT {page_length} OFFSET {start}
		""",
		params,
		as_dict=True,
	)

	total = frappe.db.sql(
		f"SELECT COUNT(*) FROM `tabSales Order` so {_JOINS} WHERE {where}", params
	)[0][0]

	if "owner_name" in select_keys:
		_attach_owner_names(rows)
	if "undispatched" in select_keys:
		attach_undispatched(rows)

	return {
		"rows": rows,
		"total": cint(total),
		"start": start,
		"page_length": page_length,
		"columns": select_keys,
	}


def _attach_owner_names(rows):
	"""Show the person, not their login."""
	users = {r.get("owner_name") for r in rows if r.get("owner_name")}
	if not users:
		return
	full = {
		u.name: (u.full_name or u.name)
		for u in frappe.get_all(
			"User", filters={"name": ("in", list(users))}, fields=["name", "full_name"]
		)
	}
	for r in rows:
		r["owner_name"] = full.get(r.get("owner_name"), r.get("owner_name"))


# --------------------------------------------------- customers for the dropdown


@frappe.whitelist()
def get_customers(channel=None, search=None, limit=50):
	"""Customers that actually appear in the queue, narrowed to the chosen channel.

	Driven off the orders rather than the Customer master so the dropdown can only
	offer a party the user is allowed to see: the same channel condition that filters
	the rows filters this list.
	"""
	_assert_can_read()
	where, params, _sel, _ob, _keys = _build({"channel": channel}, None, None, None)
	if search:
		where += " AND so.customer_name LIKE %(search)s"
		params["search"] = f"%{_escape_like(search)}%"

	rows = frappe.db.sql(
		f"""
		SELECT DISTINCT so.customer AS value, so.customer_name AS label
		FROM `tabSales Order` so {_JOINS}
		WHERE {where}
		ORDER BY so.customer_name
		LIMIT {min(max(cint(limit) or 50, 1), 500)}
		""",
		params,
		as_dict=True,
	)
	return rows


@frappe.whitelist()
def get_filter_options(channel=None):
	"""Customer types and states present in what this user may see."""
	_assert_can_read()
	where, params, _sel, _ob, _keys = _build({"channel": channel}, None, None, None)
	types = frappe.db.sql(
		f"SELECT DISTINCT so.order_type AS v FROM `tabSales Order` so {_JOINS} "
		f"WHERE {where} AND IFNULL(so.order_type,'') <> '' ORDER BY so.order_type",
		params,
	)
	states = frappe.db.sql(
		f"SELECT DISTINCT addr.state AS v FROM `tabSales Order` so {_JOINS} "
		f"WHERE {where} AND IFNULL(addr.state,'') <> '' ORDER BY addr.state",
		params,
	)
	return {
		"customer_types": [t[0] for t in types],
		"states": [s[0] for s in states],
	}


# ------------------------------------------------------------ undispatched qty


def attach_undispatched(rows):
	"""Ordered less dispatched, per item, expressed in INDIVIDUAL units.

	A Product Bundle is ordered as combos but picked and shipped as its components,
	so comparing the order line to the delivery line compares two different units.
	The sheet spells the rule out: a combo of 2 units ordered 20 times is 40 units;
	20 units dispatched is 10 combos, so 10 combos remain. Everything below is
	therefore done in component units and converted back only for the label.
	"""
	names = [r["sales_order"] for r in rows if r.get("sales_order")]
	if not names:
		return

	ordered = frappe.db.sql(
		"""
		SELECT soi.parent AS so, soi.item_code, soi.item_name, SUM(soi.qty) AS qty
		FROM `tabSales Order Item` soi
		WHERE soi.parent IN %(names)s
		GROUP BY soi.parent, soi.item_code, soi.item_name
		""",
		{"names": names},
		as_dict=True,
	)
	delivered = frappe.db.sql(
		"""
		SELECT dn.custom_sales_order_id AS so, dni.item_code, SUM(dni.qty) AS qty
		FROM `tabDelivery Note Item` dni
		JOIN `tabDelivery Note` dn ON dn.name = dni.parent
		WHERE dn.custom_sales_order_id IN %(names)s
		  AND dn.docstatus = 1 AND IFNULL(dn.is_return, 0) = 0
		GROUP BY dn.custom_sales_order_id, dni.item_code
		""",
		{"names": names},
		as_dict=True,
	)

	# item -> [(component, qty per combo)]. Only bundles appear here.
	bundles = {}
	for row in frappe.get_all(
		"Product Bundle Item",
		filters={"parent": ("in", list({o.item_code for o in ordered}))},
		fields=["parent", "item_code", "qty"],
	):
		bundles.setdefault(row.parent, []).append((row.item_code, flt(row.qty)))

	shipped = {}
	for d in delivered:
		shipped.setdefault(d.so, {})[d.item_code] = flt(d.qty)

	pending = {}
	for o in ordered:
		got = shipped.get(o.so, {})
		components = bundles.get(o.item_code)
		if components:
			# Fewest whole combos the dispatched components can account for.
			per_combo = min(
				(flt(got.get(c, 0)) / q) for c, q in components if q
			) if components else 0
			short = flt(o.qty) - per_combo
		else:
			short = flt(o.qty) - flt(got.get(o.item_code, 0))
		if short > 0.0001:
			label = o.item_code
			pending.setdefault(o.so, []).append(f"{label} ({_trim(short)})")

	for r in rows:
		r["undispatched"] = ", ".join(pending.get(r["sales_order"], []))


def _trim(value):
	"""120.0 reads as 120; 12.5 stays 12.5."""
	v = flt(value)
	return int(v) if abs(v - int(v)) < 0.0001 else round(v, 2)


# --------------------------------------------------------------------- export


@frappe.whitelist()
def export_rows(filters=None, columns=None, sort_field=None, sort_dir=None):
	"""The current view as rows for a spreadsheet — same access, filters and order.

	The Download column is an action and is not in COLUMNS, so it cannot reach an
	export: what comes out is exactly the data columns that are on screen.
	"""
	_assert_can_read()
	out = get_rows(
		filters=filters, columns=columns, sort_field=sort_field, sort_dir=sort_dir,
		start=0, page_length=MAX_PAGE_LENGTH,
	)
	keys = out["columns"]
	header = [_(COLUMNS[k]["label"]) for k in keys]
	body = []
	for row in out["rows"]:
		body.append([_cell(row.get(k)) for k in keys])
	return {"header": header, "rows": body, "total": out["total"]}


def _cell(value):
	if value is None:
		return ""
	return value
