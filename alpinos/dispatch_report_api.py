"""
Dispatch Report API for Alpinos.

Returns all data needed to render the daily dispatch report:
- Today's dispatch: Pick Lists with custom_dispatch_date = report date
- Pending dispatch: Sales Orders with custom_dispatch_date = report date, not fully delivered
- Today's stock: Bin.actual_qty for the selected warehouse
- Inward date approx: nearest upcoming date from Inward Planning
- Customer type breakdown via Sales Order.order_type → Offline Buyer Customer Type
"""

import frappe
from frappe.utils import today, getdate


@frappe.whitelist()
def get_dispatch_report_data(date=None, warehouse=None):
	if not date:
		date = today()

	customer_types = _get_customer_types()
	items = _get_sequenced_items()
	dispatch_data = _get_dispatch_data(date)
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
	rows = frappe.db.sql(
		"SELECT name FROM `tabOffline Buyer Customer Type` ORDER BY name ASC",
		as_dict=True,
	)
	return [r.name for r in rows]


def _get_sequenced_items():
	"""Return all items that have a sequence assigned, ordered by sequence."""
	return frappe.db.sql(
		"""
		SELECT name AS item_code, item_name, custom_sequence AS sequence
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
