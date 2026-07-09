"""
Dispatch Report API for Alpinos.

Returns all data needed to render the daily dispatch report:
- Today's dispatch: Pick Lists with custom_dispatch_date = report date
- Pending dispatch: Sales Orders with custom_dispatch_date = report date, not fully delivered
- Today's stock: Bin.actual_qty for the selected warehouse
- Inward date approx: nearest upcoming date from Inward Planning
- Customer type breakdown via Sales Order.order_type → Alpino Customer Type
"""

import frappe
from frappe.utils import today, getdate


@frappe.whitelist()
def get_dispatch_report_data(date=None, warehouse=None, include_material_issue=0):
	if not date:
		date = today()

	# Frappe sends checkbox values as strings ("0"/"1") over the wire.
	include_material_issue = int(include_material_issue or 0)

	customer_types = _get_customer_types()
	items = _get_sequenced_items()
	dispatch_data = _get_dispatch_data(date)
	if include_material_issue:
		_merge_dispatch_data(dispatch_data, _get_material_issue_data(date))
	pending_data = _get_pending_data(date)
	stock_data = _get_stock_data(warehouse)
	inward_data = _get_inward_data()
	summary = _build_summary(date, customer_types, dispatch_data, pending_data)

	result_items = []
	for item in items:
		ic = item["item_code"]
		d = dispatch_data.get(ic, {})
		p = pending_data.get(ic, {})
		today_dispatch = d.get("total", 0)
		pending_dispatch = p.get("total", 0)
		today_stock = stock_data.get(ic, 0)
		net_unit = today_stock - today_dispatch - pending_dispatch

		result_items.append({
			"item_code": ic,
			"item_name": item["item_name"] or ic,
			"color": item.get("color") or "",
			"sequence": item["sequence"] or 0,
			"today_dispatch": today_dispatch,
			"pending_dispatch": pending_dispatch,
			"today_stock": today_stock,
			"net_unit": net_unit,
			"inward_date": str(inward_data.get(ic) or ""),
			"dispatch_by_ct": d.get("by_ct", {}),
			"pending_by_ct": p.get("by_ct", {}),
		})

	return {
		"date": date,
		"warehouse": warehouse or "",
		"customer_types": customer_types,
		"items": result_items,
		"summary": summary,
	}


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------

def _get_customer_types():
	"""
	Returns a list of {name, abbr} dicts, ordered by `sequence` (ascending,
	with un-sequenced rows pushed to the end), then by name. The dispatch /
	pending data dicts still key off the full name; `abbr` is purely for
	display in the report columns.
	"""
	rows = frappe.db.sql(
		"""
		SELECT name, abbreviation, sequence
		FROM `tabAlpino Customer Type`
		ORDER BY
			CASE WHEN COALESCE(sequence, 0) = 0 THEN 1 ELSE 0 END,
			sequence ASC,
			name ASC
		""",
		as_dict=True,
	)
	return [
		{"name": r.name, "abbr": (r.abbreviation or r.name)}
		for r in rows
	]


def _get_sequenced_items():
	"""Return all items that have a sequence assigned, ordered by sequence."""
	return frappe.db.sql(
		"""
		SELECT name AS item_code, item_name, custom_sequence AS sequence,
			custom_color AS color
		FROM `tabItem`
		WHERE disabled = 0
		  AND COALESCE(custom_sequence, 0) > 0
		ORDER BY custom_sequence ASC, name ASC
		""",
		as_dict=True,
	)


def _get_dispatch_data(date):
	"""
	Today's dispatch: Pick List items where the Pick List has custom_dispatch_date = date.
	Customer type is pulled from the linked Sales Order's order_type.
	"""
	rows = frappe.db.sql(
		"""
		SELECT
			pli.item_code,
			SUM(pli.qty) AS qty,
			COALESCE(so.order_type, 'Other') AS customer_type
		FROM `tabPick List` pl
		JOIN `tabPick List Item` pli ON pli.parent = pl.name
		LEFT JOIN `tabSales Order` so ON so.name = pl.custom_sales_order_id
		WHERE pl.custom_dispatch_date = %(date)s
		  AND pl.docstatus != 2
		  AND pl.purpose = 'Delivery'
		GROUP BY pli.item_code, so.order_type
		""",
		{"date": date},
		as_dict=True,
	)
	return _aggregate_by_item(rows)


def _get_material_issue_data(date):
	"""
	Material Issue dispatch: Stock Entry rows where purpose = 'Material Issue',
	posting_date = report date, and docstatus = 1. Customer type is read from
	the custom_customer_type field on the Stock Entry header.
	"""
	rows = frappe.db.sql(
		"""
		SELECT
			sed.item_code,
			SUM(sed.qty) AS qty,
			COALESCE(se.custom_customer_type, 'Other') AS customer_type
		FROM `tabStock Entry` se
		JOIN `tabStock Entry Detail` sed ON sed.parent = se.name
		WHERE se.posting_date = %(date)s
		  AND se.docstatus = 1
		  AND se.purpose = 'Material Issue'
		GROUP BY sed.item_code, se.custom_customer_type
		""",
		{"date": date},
		as_dict=True,
	)
	return _aggregate_by_item(rows)


def _merge_dispatch_data(target, extra):
	"""Add extra dispatch data into target in place, summing totals and per-CT qty."""
	for ic, e in extra.items():
		if ic not in target:
			target[ic] = {"total": 0, "by_ct": {}}
		target[ic]["total"] += e.get("total", 0)
		for ct, qty in e.get("by_ct", {}).items():
			target[ic]["by_ct"][ct] = target[ic]["by_ct"].get(ct, 0) + qty


def _get_pending_data(date):
	"""
	Pending dispatch: Sales Order items where the SO has custom_dispatch_date <= date
	(overdue + today's pending) and the order is not yet completed/cancelled.
	"""
	rows = frappe.db.sql(
		"""
		SELECT
			soi.item_code,
			SUM(soi.qty) AS qty,
			COALESCE(so.order_type, 'Other') AS customer_type
		FROM `tabSales Order` so
		JOIN `tabSales Order Item` soi ON soi.parent = so.name
		WHERE so.custom_dispatch_date <= %(date)s
		  AND so.docstatus = 1
		  AND so.status NOT IN ('Completed', 'Cancelled', 'Closed')
		GROUP BY soi.item_code, so.order_type
		""",
		{"date": date},
		as_dict=True,
	)
	return _aggregate_by_item(rows)


def _get_stock_data(warehouse):
	"""Current stock from Bin for the given warehouse (or all warehouses if blank)."""
	if warehouse:
		rows = frappe.db.get_all(
			"Bin",
			filters={"warehouse": warehouse},
			fields=["item_code", "actual_qty"],
		)
	else:
		rows = frappe.db.sql(
			"""
			SELECT item_code, SUM(actual_qty) AS actual_qty
			FROM `tabBin`
			GROUP BY item_code
			""",
			as_dict=True,
		)
	return {r["item_code"]: (r["actual_qty"] or 0) for r in rows}


def _get_inward_data():
	"""Nearest upcoming expected inward date per item from Inward Planning."""
	rows = frappe.db.sql(
		"""
		SELECT item_code, MIN(expected_inward_date) AS inward_date
		FROM `tabInward Planning`
		WHERE expected_inward_date >= CURDATE()
		GROUP BY item_code
		""",
		as_dict=True,
	)
	return {r["item_code"]: r["inward_date"] for r in rows}


def _build_summary(date, customer_types, dispatch_data, pending_data):
	"""Build top-level summary totals."""

	# Unit totals per CT (for the merged section headers row)
	dispatch_by_ct = {}
	pending_by_ct = {}
	dispatch_total = 0
	pending_total = 0
	stock_total = 0
	net_total = 0

	for ic, d in dispatch_data.items():
		dispatch_total += d.get("total", 0)
		for ct, qty in d.get("by_ct", {}).items():
			dispatch_by_ct[ct] = dispatch_by_ct.get(ct, 0) + qty

	for ic, p in pending_data.items():
		pending_total += p.get("total", 0)
		for ct, qty in p.get("by_ct", {}).items():
			pending_by_ct[ct] = pending_by_ct.get(ct, 0) + qty

	# Box totals per CT from Pick List (dispatch)
	pl_box = frappe.db.sql(
		"""
		SELECT
			COALESCE(so.order_type, 'Other') AS ct,
			SUM(pl.custom_total_box) AS box,
			SUM(pl.custom_gross_weight) AS gw
		FROM `tabPick List` pl
		LEFT JOIN `tabSales Order` so ON so.name = pl.custom_sales_order_id
		WHERE pl.custom_dispatch_date = %(date)s
		  AND pl.docstatus != 2
		  AND pl.purpose = 'Delivery'
		GROUP BY so.order_type
		""",
		{"date": date},
		as_dict=True,
	)
	box_by_ct = {r["ct"]: (r["box"] or 0) for r in pl_box}
	gw_by_ct = {r["ct"]: (r["gw"] or 0) for r in pl_box}
	total_box = sum(box_by_ct.values())
	total_gw = sum(gw_by_ct.values())

	# Box totals per CT from Sales Order Items (pending)
	so_box = frappe.db.sql(
		"""
		SELECT
			COALESCE(so.order_type, 'Other') AS ct,
			SUM(soi.custom_box) AS box
		FROM `tabSales Order` so
		JOIN `tabSales Order Item` soi ON soi.parent = so.name
		WHERE so.custom_dispatch_date <= %(date)s
		  AND so.docstatus = 1
		  AND so.status NOT IN ('Completed', 'Cancelled', 'Closed')
		GROUP BY so.order_type
		""",
		{"date": date},
		as_dict=True,
	)
	pending_box_by_ct = {r["ct"]: (r["box"] or 0) for r in so_box}

	return {
		"dispatch_total": dispatch_total,
		"pending_total": pending_total,
		"total_box": total_box,
		"total_gw": total_gw,
		"dispatch_by_ct": dispatch_by_ct,
		"pending_by_ct": pending_by_ct,
		"box_by_ct": box_by_ct,
		"gw_by_ct": gw_by_ct,
		"pending_box_by_ct": pending_box_by_ct,
	}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _aggregate_by_item(rows):
	"""Convert flat rows (item_code, qty, customer_type) into {item_code: {total, by_ct}}."""
	data = {}
	for row in rows:
		ic = row["item_code"]
		qty = row["qty"] or 0
		ct = row["customer_type"] or "Other"
		if ic not in data:
			data[ic] = {"total": 0, "by_ct": {}}
		data[ic]["total"] += qty
		data[ic]["by_ct"][ct] = data[ic]["by_ct"].get(ct, 0) + qty
	return data
