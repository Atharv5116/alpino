"""Server side of the Order Fulfilment Report (formerly the Invoice Download Queue):
access, columns, filters, sorting, export.

The DOWNLOAD logic is not here. Downloading still goes through alpinos.sales_order_api,
and membership of the queue still comes from alpinos.pending_invoice_api. This file
decides WHICH ROWS a user may see, WHICH COLUMNS they may ask for, how those rows are
filtered, ordered and exported, and that nobody downloads an order outside their channel.

CHANNEL ACCESS
--------------
Three role groups, enforced here rather than in the page, so a crafted API call, a
saved view, a sort, an export or a download URL cannot reach rows the screen would
have hidden:

  * E-Commerce Admin / Coordinator / Manager -> E-com only, locked.
  * Sales Manager / Admin / User            -> Offline only, locked.
  * Warehouse Admin / Manager, Accounts User -> every channel, free to choose.

"Offline" is the offline FAMILY, `Offline` and `General Trade` together (the user's
call: General Trade is an offline channel). That holds wherever the word is used: a
Sales user locked to Offline sees General Trade orders, and anyone choosing Offline in
the filter gets both. Choosing General Trade on its own narrows to just that.

A user holding roles from BOTH restricted groups (E-Commerce and Sales) sees both
channel families and may choose between them; nothing is locked, because no single
channel describes them. Holding a Warehouse or Accounts role makes a user
unrestricted whatever else they hold.

A user holding NONE of the nine named roles is left unrestricted, which is what the
page did before; their ordinary Sales Order permissions still apply.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint, flt

DOCTYPE = "Sales Order"

# The role -> channel rule is shared with the Sales Order / Pick List / Delivery Note
# permission hooks (Changes(HP) #22), so it lives in one place.
from alpinos.channel_access import (  # noqa: E402
	CHANNEL_ECOM,
	CHANNEL_OFFLINE,
	ECOM_ROLES,
	OFFLINE_CHANNELS,
	OFFLINE_ROLES,
	UNRESTRICTED_ROLES,
	resolve_access,
)

# Every role the spec names may open the page; alpinos.workflow_role_access applies it.
PAGE_ROLES = ECOM_ROLES + OFFLINE_ROLES + UNRESTRICTED_ROLES

DEFAULT_PAGE_LENGTH = 50
MAX_PAGE_LENGTH = 2000
_CHUNK = 500


# --------------------------------------------------------------------- access


def _roles(user=None):
	return set(frappe.get_roles(user or frappe.session.user))


def expand_channel(channel):
	"""The stored channel values a filter value stands for. Offline is the family."""
	return list(OFFLINE_CHANNELS) if channel == CHANNEL_OFFLINE else [channel]


@frappe.whitelist()
def get_access():
	"""What the page needs to draw and lock its Channel filter."""
	_assert_can_read()
	access = resolve_access()
	if access["locked"]:
		# One option: the role's channel. For Sales that is "Offline", which already
		# covers General Trade, so there is nothing left to choose.
		selectable = [access["default"]]
	else:
		selectable = access["channels"] or _all_channels()
	return {
		"channels": access["channels"],
		"locked": access["locked"],
		"default_channel": access["default"],
		"selectable": selectable,
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
	allowed = resolve_access()["channels"]

	if requested:
		wanted = expand_channel(requested)
		if allowed is not None and not set(wanted).issubset(allowed):
			frappe.throw(
				_("You do not have access to the {0} channel.").format(requested),
				frappe.PermissionError,
			)
		return "so.custom_channel IN %(channels)s", {"channels": tuple(wanted)}

	if allowed is None:
		return "1 = 1", {}
	return "so.custom_channel IN %(channels)s", {"channels": tuple(allowed)}


def assert_orders_in_channel(names):
	"""Refuse a download that includes an order outside this user's channels.

	The queue only ever offers orders the user may see, so this is for the request
	that did not come from the queue's own rows: a hand-edited download URL.
	"""
	allowed = resolve_access()["channels"]
	if allowed is None or not names:
		return
	outside = [
		r.name
		for r in frappe.get_all(
			DOCTYPE, filters={"name": ("in", list(names))}, fields=["name", "custom_channel"]
		)
		if r.custom_channel not in allowed
	]
	if outside:
		frappe.throw(
			_("You do not have access to the channel of {0}, so it cannot be downloaded.").format(
				", ".join(outside[:5]) + (" ..." if len(outside) > 5 else "")
			),
			frappe.PermissionError,
		)


# -------------------------------------------------------------------- columns

# The report columns from the attached sheet. The page draws from the catalogue, the
# sort validates against it, and the export renders it. A column that is not in the
# catalogue cannot be selected, sorted or exported, which keeps a crafted request from
# reaching a field nobody meant to expose.
#
# `select` is the SQL expression; `sortable` False marks a column computed in Python
# after the page is fetched, which cannot participate in an ORDER BY.
REPORT_GROUP = "Report"
COLUMNS = {
	"channel":        {"label": "Channel",        "select": "so.custom_channel",       "type": "Data"},
	"order_date":     {"label": "Order Date",     "select": "so.transaction_date",     "type": "Date"},
	# The sheet sources Dispatch Date from the Pick List, not the order's own field.
	"dispatch_date":  {"label": "Dispatch Date",  "select": "pl.dispatch_date",        "type": "Date"},
	"customer_type":  {"label": "Customer Type",  "select": "so.order_type",           "type": "Data"},
	"sales_order":    {"label": "Sales Order ID", "select": "so.name",                 "type": "Link"},
	"customer_po_no": {"label": "Customer PO No.",
	                   "select": "COALESCE(NULLIF(so.po_no, ''), NULLIF(so.custom_po_number, ''), '')",
	                   "type": "Data"},
	"customer_name":  {"label": "Customer",       "select": "so.customer_name",        "type": "Data"},
	"pl_po_no":       {"label": "PL PO No.",      "select": "pl.pl_po_no",             "type": "Data"},
	# The state the ORDER itself works on: its billing address, which is what decides
	# IGST vs CGST/SGST (alpinos.sales_order_api._apply_tax_mode_from_billing). The
	# shipping address is the fallback, since most orders carry no shipping address at
	# all and the column was blank for them.
	"state":          {"label": "State",          "select": "__STATE__",               "type": "Data"},
	# Shown as AHF/<financial year>/<number> (Changes(HP) #42). The year is the order's
	# Dispatch Date's (the invoice is raised on dispatch), else its Order Date; a number
	# already stored with the prefix is shown as it is. Sorted by the number itself.
	"invoice_id":     {"label": "Invoice Number", "select": "__INVOICE_DISPLAY__",
	                   "sort": "LPAD(so.custom_invoice_no, 20, '0')", "type": "Data"},
	"transporter":    {"label": "Transporter",    "select": "pl.transporter",          "type": "Data"},
	"lr_number":      {"label": "LR No.",         "select": "dn.lr_no",                "type": "Data"},
	"so_amount":      {"label": "Sales Order Amount", "select": "so.grand_total",      "type": "Currency"},
	# What the submitted Delivery Notes invoiced, read live; before anything is
	# dispatched, the value alpinos.so_invoice_value keeps on the order (the picked share
	# of its selling price). Reading only the stored value showed 0 on every order whose
	# notes went out before that value was maintained (Changes(HP) #42).
	"invoice_amount": {"label": "Invoice Amount", "select": "__INVOICE_AMOUNT__", "type": "Currency"},
	"amount_diff":    {"label": "Sales vs Invoice Difference Amount",
	                   "select": "(IFNULL(so.grand_total, 0) - __INVOICE_AMOUNT__)",
	                   "type": "Currency"},
	"total_box":      {"label": "Total Box",      "select": "pl.total_box",            "type": "Float"},
	"weight":         {"label": "Weight",         "select": "pl.weight",               "type": "Float"},
	# The name, not the login, so sorting orders what the user actually reads.
	"owner_name":     {"label": "Owner (Sales Order Created By)",
	                   "select": "COALESCE(NULLIF(own.full_name, ''), so.owner)", "type": "Data"},
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

# What was dispatched, priced by the SALES ORDER's own rates: for each delivered line,
# the share of that order line it covers, applied to the order's grand total. The Delivery
# Note's own grand_total is NOT used -- free rows (freebies, scheme, additional units) are
# priced from the Item Price list on the note, which invoiced samples nobody charges for,
# and the note carries none of the order's cash discount rules either. Scaling by
# grand_total / net_total carries the order's GST, discounts and rounding across unchanged,
# so a fully dispatched order reads exactly its own grand total.
_INVOICE_AMOUNT = (
	"COALESCE("
	"NULLIF(ROUND(dnv.ordered_value * so.grand_total / NULLIF(so.net_total, 0), 2), 0),"
	" NULLIF(so.custom_total_invoice_value, 0), 0)"
)
_STATE = "COALESCE(NULLIF(baddr.state, ''), NULLIF(addr.state, ''))"
_FY_DATE = "COALESCE(so.custom_dispatch_date, so.transaction_date)"
_FY_START = f"(YEAR({_FY_DATE}) - IF(MONTH({_FY_DATE}) < 4, 1, 0))"
# The stored number without a file extension some orders carry ("6057.pdf"), Changes(HP) #42.3.
_INVOICE_NO = "REGEXP_REPLACE(TRIM(so.custom_invoice_no), '[.][pP][dD][fF]$', '')"
_INVOICE_DISPLAY = (
	"CASE WHEN IFNULL(so.custom_invoice_no, '') = '' THEN so.custom_invoice_no"
	f" WHEN so.custom_invoice_no LIKE 'AHF/%%' THEN {_INVOICE_NO}"
	f" WHEN {_FY_DATE} IS NULL THEN {_INVOICE_NO}"
	f" ELSE CONCAT('AHF/', LPAD(MOD({_FY_START}, 100), 2, '0'), '-',"
	f" LPAD(MOD({_FY_START} + 1, 100), 2, '0'), '/', {_INVOICE_NO}) END"
)
for _spec in COLUMNS.values():
	if _spec["select"]:
		_spec["select"] = (
			_spec["select"]
			.replace("__INVOICE_AMOUNT__", _INVOICE_AMOUNT)
			.replace("__INVOICE_DISPLAY__", _INVOICE_DISPLAY)
			.replace("__STATE__", _STATE)
		)

# The order the screen opens with, per the attached column sheet. `download` is not
# in the catalogue at all: it is an action, not data, so it can never be reordered
# away, exported, or sorted on.
DEFAULT_COLUMNS = [
	"channel", "order_date", "dispatch_date", "customer_type", "sales_order",
	"customer_po_no", "customer_name", "pl_po_no", "state", "invoice_id",
	"transporter", "lr_number", "so_amount", "invoice_amount", "amount_diff",
	"undispatched", "total_box", "weight", "owner_name",
]

# Dynamic columns: any plain field of these documents, per the spec's "fields available
# from Sales Order, Pick List, Delivery Note, and Post Dispatch". Keys are
# "<prefix>:<fieldname>" and are only ever built from the doctype's own meta, so a
# fieldname reaching SQL is always a real column.
#
# An order can have several Pick Lists, Delivery Notes or Post Dispatch records, so
# their fields are rolled up to one value per order: amounts and quantities are
# added, dates show the latest, and text lists each distinct value.
SOURCES = (
	# prefix, doctype, field on that doctype pointing at the Sales Order
	("so", "Sales Order", None),
	("pl", "Pick List", "custom_sales_order_id"),
	("dn", "Delivery Note", "custom_sales_order_id"),
	("pd", "Post Dispatch", "sales_order"),
)
_DYNAMIC_TYPES = {
	"Data", "Link", "Dynamic Link", "Select", "Autocomplete", "Phone", "Small Text",
	"Date", "Datetime", "Time", "Currency", "Float", "Int", "Percent", "Check",
}
_SUMMED = {"Currency", "Float", "Int"}
_LATEST = {"Date", "Datetime", "Time", "Percent"}


def _dynamic_expression(prefix, doctype, link, df):
	f = df.fieldname
	if prefix == "so":
		if df.fieldtype == "Check":
			return f"CASE WHEN so.`{f}` = 1 THEN 'Yes' ELSE 'No' END"
		return f"so.`{f}`"

	col = f"x.`{f}`"
	where = f"x.`{link}` = so.name AND x.docstatus < 2"
	if doctype == "Delivery Note":
		where += " AND IFNULL(x.is_return, 0) = 0"
	if df.fieldtype in _SUMMED:
		agg = f"SUM({col})"
	elif df.fieldtype in _LATEST:
		agg = f"MAX({col})"
	elif df.fieldtype == "Check":
		agg = f"CASE WHEN MAX({col}) IS NULL THEN NULL WHEN MAX({col}) = 1 THEN 'Yes' ELSE 'No' END"
	else:
		agg = f"GROUP_CONCAT(DISTINCT NULLIF({col}, '') ORDER BY {col} SEPARATOR ', ')"
	return f"(SELECT {agg} FROM `tab{doctype}` x WHERE {where})"


def _display_type(fieldtype):
	if fieldtype == "Currency":
		return "Currency"
	if fieldtype in ("Float", "Percent"):
		return "Float"
	if fieldtype == "Int":
		return "Int"
	if fieldtype in ("Date", "Datetime"):
		return fieldtype
	return "Data"


def catalogue():
	"""Every column THIS user may ask for, report columns first.

	Built per request: the dynamic part depends on the user's read access (a Pick List
	field is offered only to someone who may read Pick Lists, a Sales Order field only
	at a permission level they hold).
	"""
	cache = getattr(frappe.local, "idq_catalogue", None)
	if cache and cache[0] == frappe.session.user:
		return cache[1]

	out = {}
	for key, spec in COLUMNS.items():
		out[key] = dict(spec, group=REPORT_GROUP)
	# A plain field the report already shows under its own name is not offered twice.
	already = {spec["select"].replace("`", "") for spec in COLUMNS.values() if spec["select"]}

	for prefix, doctype, link in SOURCES:
		if not frappe.db.exists("DocType", doctype):
			continue
		if not frappe.has_permission(doctype, "read"):
			continue
		if link and not frappe.get_meta(doctype).has_field(link):
			continue
		meta = frappe.get_meta(doctype)
		levels = set(meta.get_permlevel_access("read")) or {0}
		seen_labels = {}
		for df in meta.fields:
			if df.fieldtype not in _DYNAMIC_TYPES or df.hidden or cint(df.permlevel) not in levels:
				continue
			expr = _dynamic_expression(prefix, doctype, link, df)
			if expr.replace("`", "") in already:
				continue
			label = _(df.label or df.fieldname)
			if label in seen_labels:
				label = f"{label} ({df.fieldname})"
			seen_labels[label] = True
			out[f"{prefix}:{df.fieldname}"] = {
				"label": f"{_(doctype)}: {label}",
				"select": expr,
				"type": _display_type(df.fieldtype),
				"group": doctype,
			}

	frappe.local.idq_catalogue = (frappe.session.user, out)
	return out


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
				"group": v["group"],
				"sortable": v.get("sortable", True),
			}
			for k, v in catalogue().items()
		],
		"default": list(DEFAULT_COLUMNS),
	}


def _clean_columns(columns):
	"""Whatever the client asked for, narrowed to what this user's catalogue allows."""
	if isinstance(columns, str):
		columns = frappe.parse_json(columns)
	if not columns:
		return list(DEFAULT_COLUMNS)
	cat = catalogue()
	out = []
	for c in columns:
		if isinstance(c, str) and c in cat and c not in out:
			out.append(c)
	return out or list(DEFAULT_COLUMNS)


# --------------------------------------------------------------------- query

_JOINS = """
	LEFT JOIN (
		SELECT custom_sales_order_id           AS so_id,
		       MIN(name)                       AS pick_list,
		       MAX(custom_po_no)               AS pl_po_no,
		       MAX(custom_transporter)         AS transporter,
		       MAX(custom_dispatch_date)       AS dispatch_date,
		       SUM(IFNULL(custom_total_box, 0))     AS total_box,
		       SUM(IFNULL(custom_gross_weight, 0))  AS weight
		FROM `tabPick List`
		WHERE docstatus < 2 AND IFNULL(custom_sales_order_id, '') <> ''
		GROUP BY custom_sales_order_id
	) pl ON pl.so_id = so.name
	LEFT JOIN (
		SELECT custom_sales_order_id AS so_id,
		       GROUP_CONCAT(DISTINCT NULLIF(custom_lr_gr_no, '') SEPARATOR ', ') AS lr_no,
		       SUM(CASE WHEN docstatus = 1
		                THEN COALESCE(NULLIF(grand_total, 0), base_grand_total, 0) ELSE 0 END) AS dispatched_value
		FROM `tabDelivery Note`
		WHERE docstatus < 2 AND IFNULL(is_return, 0) = 0
		  AND IFNULL(custom_sales_order_id, '') <> ''
		GROUP BY custom_sales_order_id
	) dn ON dn.so_id = so.name
	LEFT JOIN (
		SELECT d.so_id, SUM(d.line_value) AS ordered_value
		FROM (
			SELECT dn.custom_sales_order_id AS so_id,
			       IFNULL(soi.amount, 0) * (SUM(dni.stock_qty) / NULLIF(soi.stock_qty, 0)) AS line_value
			FROM `tabDelivery Note Item` dni
			JOIN `tabDelivery Note` dn ON dn.name = dni.parent
			     AND dn.docstatus = 1 AND IFNULL(dn.is_return, 0) = 0
			JOIN `tabSales Order Item` soi ON soi.name = dni.so_detail
			WHERE IFNULL(dn.custom_sales_order_id, '') <> ''
			GROUP BY dn.custom_sales_order_id, dni.so_detail, soi.amount, soi.stock_qty
		) d
		GROUP BY d.so_id
	) dnv ON dnv.so_id = so.name
	LEFT JOIN `tabAddress` addr ON addr.name = so.shipping_address_name
	LEFT JOIN `tabAddress` baddr ON baddr.name = so.customer_address
	LEFT JOIN `tabUser` own ON own.name = so.owner
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
	"state":          (f"{_STATE} = %(state)s", "eq"),
	"order_date_from":    ("so.transaction_date >= %(order_date_from)s", "eq"),
	"order_date_to":      ("so.transaction_date <= %(order_date_to)s", "eq"),
	"dispatch_date_from": ("pl.dispatch_date >= %(dispatch_date_from)s", "eq"),
	"dispatch_date_to":   ("pl.dispatch_date <= %(dispatch_date_to)s", "eq"),
	"po_date":        ("so.custom_po_date = %(po_date)s", "eq"),
	# Changes(HP) #41: the user who created the Sales Order.
	"created_by":     ("so.owner = %(created_by)s", "eq"),
}
FILTER_KEYS = tuple(_FILTERS)


def _strip_invoice_prefix(value):
	import re

	return re.sub(r"^\s*AHF/\d{2}-\d{2}/", "", str(value or ""), flags=re.I).strip()


def _escape_like(term):
	"""A typed underscore is a character, not a wildcard."""
	return (term or "").replace("\\", "\\\\").replace("%", "").replace("_", "\\_")


def _parse(value, default):
	if isinstance(value, str):
		value = frappe.parse_json(value) if value else None
	return value if value is not None else default


def _build(filters, columns, sort_field, sort_dir):
	filters = _parse(filters, {}) or {}

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
		if key == "invoice_id":
			# The column shows AHF/26-27/6055 but the order stores 6055: accept either.
			value = _strip_invoice_prefix(value)
		conditions.append(sql)
		params[key] = f"%{_escape_like(value)}%" if mode == "like" else value

	cat = catalogue()
	select_keys = _clean_columns(columns)
	selects = ["so.name AS sales_order"]
	for key in select_keys:
		spec = cat[key]
		if spec["select"] and key != "sales_order":
			selects.append(f"{spec['select']} AS `{key}`")
	# The page always needs these, whether or not they are on screen: the download
	# buttons key off them.
	for key in ("pick_list", "pdf_ready", "downloaded", "invoice_id"):
		if key not in select_keys:
			selects.append(f"{COLUMNS[key]['select']} AS `{key}`")

	sort_key = sort_field if sort_field in cat else "order_date"
	if not cat[sort_key].get("sortable", True) or not cat[sort_key]["select"]:
		sort_key = "order_date"
	direction = "ASC" if str(sort_dir or "desc").lower() == "asc" else "DESC"
	sort_expr = cat[sort_key].get("sort") or cat[sort_key]["select"]
	order_by = f"{sort_expr} {direction}, so.name {direction}"

	return " AND ".join(conditions), params, selects, order_by, select_keys


def _fetch(filters, columns, sort_field, sort_dir, start=0, limit=None):
	where, params, selects, order_by, select_keys = _build(filters, columns, sort_field, sort_dir)
	paging = f"LIMIT {cint(limit)} OFFSET {max(cint(start), 0)}" if limit else ""
	rows = frappe.db.sql(
		f"""
		SELECT {", ".join(selects)}
		FROM `tabSales Order` so
		{_JOINS}
		WHERE {where}
		ORDER BY {order_by}
		{paging}
		""",
		params,
		as_dict=True,
	)
	total = frappe.db.sql(
		f"SELECT COUNT(*) FROM `tabSales Order` so {_JOINS} WHERE {where}", params
	)[0][0]
	if "undispatched" in select_keys:
		attach_undispatched(rows)
	return rows, cint(total), select_keys


@frappe.whitelist()
def get_rows(
	filters=None, columns=None, sort_field=None, sort_dir=None,
	start=0, page_length=DEFAULT_PAGE_LENGTH,
):
	"""One page of the queue, respecting role access, filters, sorting and columns."""
	_assert_can_read()
	start = max(cint(start), 0)
	page_length = min(max(cint(page_length) or DEFAULT_PAGE_LENGTH, 1), MAX_PAGE_LENGTH)
	rows, total, select_keys = _fetch(filters, columns, sort_field, sort_dir, start, page_length)
	return {
		"rows": rows,
		"total": total,
		"start": start,
		"page_length": page_length,
		"columns": select_keys,
	}


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
		f"SELECT DISTINCT {_STATE} AS v FROM `tabSales Order` so {_JOINS} "
		f"WHERE {where} AND IFNULL({_STATE},'') <> '' ORDER BY v",
		params,
	)
	return {
		"customer_types": [t[0] for t in types],
		"states": [s[0] for s in states],
	}


# ------------------------------------------------------------ undispatched qty


def _bundle_units(item_codes):
	"""item_code -> individual units in ONE combo, for the codes that are bundles.

	The native Product Bundle is the stock engine's source (alpinos.product_bundle_sync
	keeps it in step with the Item's own mapping); the Item mapping is the fallback for a
	bundle whose native record is missing.
	"""
	if not item_codes:
		return {}
	units = {}
	for r in frappe.db.sql(
		"""
		SELECT pb.new_item_code AS item, SUM(pbi.qty) AS units
		FROM `tabProduct Bundle` pb
		JOIN `tabProduct Bundle Item` pbi ON pbi.parent = pb.name
		WHERE pb.new_item_code IN %(codes)s
		GROUP BY pb.new_item_code
		""",
		{"codes": tuple(item_codes)},
		as_dict=True,
	):
		if flt(r.units) > 0:
			units[r.item] = flt(r.units)

	missing = [c for c in item_codes if c not in units]
	if missing and frappe.db.table_exists("Product Bundle Mapping"):
		for r in frappe.db.sql(
			"""
			SELECT parent AS item, SUM(base_qty) AS units
			FROM `tabProduct Bundle Mapping`
			WHERE parenttype = 'Item' AND parent IN %(codes)s
			GROUP BY parent
			""",
			{"codes": tuple(missing)},
			as_dict=True,
		):
			if flt(r.units) > 0:
				units[r.item] = flt(r.units)
	return units


def attach_undispatched(rows):
	"""Ordered less dispatched, per item. Combos are counted in INDIVIDUAL units.

	A combo is ordered as the combo but leaves the warehouse as its components: the
	Delivery Note keeps the combo line and records the components as packed items. The
	sheet's rule: a combo of 2 units ordered 20 times is 40 units; 20 units dispatched
	is 10 combos, so "Combo 1 (10)" remains. So the dispatched COMPONENT units are
	totalled and divided by the units in one combo -- never the combo line's own qty,
	and never the scarcest component, both of which disagree with the sheet when the
	components go out unevenly.
	"""
	names = [r["sales_order"] for r in rows if r.get("sales_order")]
	pending = {}
	for i in range(0, len(names), _CHUNK):
		pending.update(_undispatched_for(names[i : i + _CHUNK]))
	for r in rows:
		items = pending.get(r.get("sales_order"), [])
		r["undispatched"] = ", ".join(f"{i['item_code']} ({i['qty']})" for i in items)
		# The full list behind the compact cell (Changes(HP) #41); not an export column.
		r["undispatched_items"] = items


def _undispatched_for(names):
	if not names:
		return {}
	params = {"names": tuple(names)}
	ordered = frappe.db.sql(
		"""
		SELECT soi.parent AS so, soi.item_code, MAX(soi.item_name) AS item_name,
		       SUM(soi.qty) AS qty, MIN(soi.idx) AS idx
		FROM `tabSales Order Item` soi
		WHERE soi.parent IN %(names)s
		GROUP BY soi.parent, soi.item_code
		ORDER BY soi.parent, idx
		""",
		params,
		as_dict=True,
	)
	# Delivery Note lines as written: a plain item's own quantity, or a combo line's.
	delivered = {}
	for d in frappe.db.sql(
		"""
		SELECT dn.custom_sales_order_id AS so, dni.item_code, SUM(dni.qty) AS qty
		FROM `tabDelivery Note Item` dni
		JOIN `tabDelivery Note` dn ON dn.name = dni.parent
		WHERE dn.custom_sales_order_id IN %(names)s
		  AND dn.docstatus = 1 AND IFNULL(dn.is_return, 0) = 0
		GROUP BY dn.custom_sales_order_id, dni.item_code
		""",
		params,
		as_dict=True,
	):
		delivered[(d.so, d.item_code)] = flt(d.qty)
	# The components that actually left, per combo.
	packed = {}
	for p in frappe.db.sql(
		"""
		SELECT dn.custom_sales_order_id AS so, pi.parent_item, SUM(pi.qty) AS qty
		FROM `tabPacked Item` pi
		JOIN `tabDelivery Note` dn ON dn.name = pi.parent AND pi.parenttype = 'Delivery Note'
		WHERE dn.custom_sales_order_id IN %(names)s
		  AND dn.docstatus = 1 AND IFNULL(dn.is_return, 0) = 0
		GROUP BY dn.custom_sales_order_id, pi.parent_item
		""",
		params,
		as_dict=True,
	):
		packed[(p.so, p.parent_item)] = flt(p.qty)

	units = _bundle_units(list({o.item_code for o in ordered}))

	pending = {}
	for o in ordered:
		per_combo = units.get(o.item_code)
		if per_combo:
			key = (o.so, o.item_code)
			if key in packed:
				shipped = packed[key] / per_combo
			else:
				# No packed rows recorded: the combo line is all there is to go on.
				shipped = delivered.get(key, 0)
		else:
			shipped = delivered.get((o.so, o.item_code), 0)
		short = flt(o.qty) - flt(shipped)
		if short > 0.0001:
			pending.setdefault(o.so, []).append(
				{"item_code": o.item_code, "item_name": o.item_name or o.item_code, "qty": _trim(short)}
			)
	return pending


def _trim(value):
	"""120.0 reads as 120; 12.5 stays 12.5."""
	v = flt(value)
	return int(v) if abs(v - int(v)) < 0.0001 else round(v, 2)


# --------------------------------------------------------------------- export


@frappe.whitelist()
def export_rows(filters=None, columns=None, sort_field=None, sort_dir=None):
	"""The current view as rows for a spreadsheet: same access, filters and order.

	EVERY filtered row, not a page of them. The Download column is an action and is not
	in the catalogue, so it cannot reach an export: what comes out is exactly the data
	columns that are on screen, in their on-screen order.
	"""
	_assert_can_read()
	rows, total, keys = _fetch(filters, columns, sort_field, sort_dir)
	cat = catalogue()
	header = [_(cat[k]["label"]) for k in keys]
	body = [[_cell(row.get(k)) for k in keys] for row in rows]
	return {"header": header, "rows": body, "total": total}


def _cell(value):
	if value is None:
		return ""
	return value


# ----------------------------------------------------------------- downloads


def _names(names):
	if isinstance(names, str):
		names = json.loads(names) if names else []
	return [n for n in (names or []) if n]


@frappe.whitelist()
def download_invoices_zip(names):
	"""The queue's Download Selected / Download All: the channel check, then the SAME
	alpinos.sales_order_api.download_sales_invoices_zip every other screen uses.

	The shared endpoint is not changed. It also serves the Sales Order lists, and a Sales
	user legitimately downloads E-com invoices from the E-com order list they are given,
	so the channel rule belongs to the queue's own door rather than to that one.
	"""
	from alpinos.sales_order_api import download_sales_invoices_zip

	names = _names(names)
	assert_orders_in_channel(names)
	return download_sales_invoices_zip(names)


# The per-row SO / PL / INV links and the Club Downloads go straight to
# alpinos.sales_order_api.download_order_bundle, which only this queue calls, so the
# channel check sits inside it.


# ---------------------------------------------------------------- saved views

VIEW_DOCTYPE = "Alpino Saved View"
PAGE_ROUTE = "invoice-download-queue"


@frappe.whitelist()
def list_views():
	"""This user's saved views for this page, the default first."""
	_assert_can_read()
	rows = frappe.get_all(
		VIEW_DOCTYPE,
		filters={"user": frappe.session.user, "page_route": PAGE_ROUTE},
		fields=["name", "view_name", "is_default", "columns_json", "filters_json",
		        "sort_field", "sort_dir"],
		order_by="is_default desc, view_name asc",
	)
	for r in rows:
		# Re-checked on the way OUT as well as in: a column the user has since lost
		# access to (a Pick List field after losing Pick List read) is dropped here.
		r["columns"] = _clean_columns(frappe.parse_json(r.pop("columns_json") or "[]"))
		r["filters"] = _clean_filters(frappe.parse_json(r.pop("filters_json") or "{}"))
	return rows


def _clean_filters(filters):
	filters = _parse(filters, {}) or {}
	if not isinstance(filters, dict):
		return {}
	return {k: v for k, v in filters.items() if k in FILTER_KEYS and v not in (None, "")}


@frappe.whitelist()
def save_view(view_name, columns=None, filters=None, sort_field=None, sort_dir=None,
              is_default=0):
	"""Create or REPLACE one of this user's views. Saving the same name updates it."""
	_assert_can_read()
	view_name = (view_name or "").strip()
	if not view_name:
		frappe.throw(_("Please name the view."))

	# Never store a column the catalogue does not allow, or a saved view becomes a
	# way to smuggle one back in later.
	columns = _clean_columns(columns)
	filters = _clean_filters(filters)
	if sort_field and sort_field not in catalogue():
		sort_field = None

	existing = frappe.db.exists(
		VIEW_DOCTYPE,
		{"user": frappe.session.user, "page_route": PAGE_ROUTE, "view_name": view_name},
	)
	doc = frappe.get_doc(VIEW_DOCTYPE, existing) if existing else frappe.new_doc(VIEW_DOCTYPE)
	doc.update({
		"view_name": view_name,
		"page_route": PAGE_ROUTE,
		"user": frappe.session.user,
		"columns_json": frappe.as_json(columns),
		"filters_json": frappe.as_json(filters),
		"sort_field": sort_field or "",
		"sort_dir": sort_dir or "desc",
		"is_default": cint(is_default),
	})
	doc.save(ignore_permissions=True)
	return {"name": doc.name, "view_name": doc.view_name}


@frappe.whitelist()
def delete_view(name):
	"""Remove one of YOUR OWN views. Somebody else's is not yours to delete."""
	_assert_can_read()
	owner = frappe.db.get_value(VIEW_DOCTYPE, name, "user")
	if not owner:
		frappe.throw(_("That view no longer exists."))
	if owner != frappe.session.user and "System Manager" not in _roles():
		frappe.throw(_("That view belongs to another user."), frappe.PermissionError)
	frappe.delete_doc(VIEW_DOCTYPE, name, ignore_permissions=True)
	return {"deleted": name}


# ------------------------------------------------ customer link query helpers


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def customer_link_query(doctype, txt, searchfield, start, page_len, filters):
	"""Link-field query for Customer, narrowed to the channel the user may see.

	Driven off the ORDERS rather than the Customer master, so the dropdown can only
	ever offer a party that appears in rows this user is allowed to read. Clearing
	the Channel widens it back to everything they may see, never beyond.
	"""
	_assert_can_read()
	channel = (filters or {}).get("channel") or None
	where, params, _sel, _ob, _keys = _build({"channel": channel}, None, None, None)
	params["txt"] = f"%{_escape_like(txt)}%"
	return frappe.db.sql(
		f"""
		SELECT DISTINCT so.customer, so.customer_name
		FROM `tabSales Order` so {_JOINS}
		WHERE {where} AND (so.customer LIKE %(txt)s OR so.customer_name LIKE %(txt)s)
		ORDER BY so.customer_name
		LIMIT {cint(page_len) or 20} OFFSET {cint(start) or 0}
		""",
		params,
	)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def creator_link_query(doctype, txt, searchfield, start, page_len, filters):
	"""Link query for Created By: the users who created orders this user may see.

	Driven off the orders, like the customer list, so it never offers a user from a
	channel the role does not cover.
	"""
	_assert_can_read()
	channel = (filters or {}).get("channel") or None
	where, params, _sel, _ob, _keys = _build({"channel": channel}, None, None, None)
	params["txt"] = f"%{_escape_like(txt)}%"
	return frappe.db.sql(
		f"""
		SELECT DISTINCT so.owner, COALESCE(NULLIF(own.full_name, ''), so.owner)
		FROM `tabSales Order` so {_JOINS}
		WHERE {where} AND (so.owner LIKE %(txt)s OR own.full_name LIKE %(txt)s)
		ORDER BY 2
		LIMIT {cint(page_len) or 20} OFFSET {cint(start) or 0}
		""",
		params,
	)


@frappe.whitelist()
def customer_in_channel(customer, channel=None):
	"""Does this customer still appear in the chosen channel?

	The page asks before keeping a Customer when the Channel changes; a party that
	does not belong to the new channel is cleared instead of quietly filtering the
	list down to nothing.
	"""
	_assert_can_read()
	if not customer:
		return True
	where, params, _sel, _ob, _keys = _build({"channel": channel}, None, None, None)
	params["cust"] = customer
	row = frappe.db.sql(
		f"SELECT 1 FROM `tabSales Order` so {_JOINS} WHERE {where} AND so.customer = %(cust)s LIMIT 1",
		params,
	)
	return bool(row)


@frappe.whitelist()
def get_all_sales_orders(filters=None):
	"""Every Sales Order in the CURRENT FILTER, not just the page on screen.

	The queue is paged. Download All, the Club Download buttons and a header "select
	all" used to work from every row because every row was loaded; this keeps them
	meaning every filtered row rather than "this page".
	"""
	_assert_can_read()
	where, params, _sel, _ob, _keys = _build(filters, None, None, None)
	rows = frappe.db.sql(
		f"SELECT so.name FROM `tabSales Order` so {_JOINS} WHERE {where} ORDER BY so.name",
		params,
	)
	return [r[0] for r in rows]
