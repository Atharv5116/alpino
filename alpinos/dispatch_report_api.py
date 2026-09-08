"""Daily dispatch report data API for Alpinos."""

import frappe
from frappe.utils import today, getdate


@frappe.whitelist()
def get_dispatch_report_data(date=None, warehouse=None, include_material_issue=0, group_by_parent=0):
	"""Daily dispatch grid.

	group_by_parent swaps the breakdown columns from Customer Type to the buyer FAMILY:
	every order is attributed to its Parent Buyer (or to itself when it is the root), so
	the sites of one chain read as a single column instead of being spread across the
	types their individual Buyer Masters happen to carry.
	"""
	if not date:
		date = today()

	# Frappe sends checkbox values as strings ("0"/"1") over the wire.
	include_material_issue = int(include_material_issue or 0)
	group_by_parent = int(group_by_parent or 0)

	items = _get_sequenced_items()
	dispatch_data = _get_dispatch_data(date, group_by_parent)
	if include_material_issue:
		_merge_dispatch_data(dispatch_data, _get_material_issue_data(date, group_by_parent))
	pending_data = _get_pending_data(date, group_by_parent)
	stock_data = _get_stock_data(warehouse, date)
	inward_data = _get_inward_data()
	# Both views draw their headings from the Customer Type master, so the columns keep
	# their configured sequence either way. The toggle only drops the types that are
	# rolled up into a parent, and re-adds "Other" when the day put something there.
	customer_types = _get_customer_types(roots_only=bool(group_by_parent))
	if group_by_parent:
		customer_types = _with_other(customer_types, dispatch_data, pending_data)
	summary = _build_summary(date, customer_types, dispatch_data, pending_data, group_by_parent)

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
		"group_by_parent": group_by_parent,
		"customer_types": customer_types,
		"items": result_items,
		"summary": summary,
	}


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------

def _group_sql(group_by_parent):
	"""(column-key expression, extra JOINs) for a query that has `so` in scope.

	Both modes group by Customer Type -- Sales Order order_type carries it, populated
	from Buyer Master.customer_type by get_offline_buyer_for_customer. The toggle is
	what decides how far UP the type hierarchy the order is reported:

	  off  every Customer Type gets its own column, which is the detailed view
	  on   a type that names a Parent Customer Type is reported inside its parent's
	       column, so the several types belonging to one chain read as one column

	An order whose type is missing or unknown lands in "Other" rather than vanishing,
	which is also where a Material Issue goes -- it has no Sales Order and so no type.
	"""
	if not group_by_parent:
		return "COALESCE(so.order_type, 'Other')", ""
	joins = " LEFT JOIN `tabAlpino Customer Type` act ON act.name = so.order_type"
	expr = "COALESCE(NULLIF(act.parent_customer_type, ''), so.order_type, 'Other')"
	return expr, joins


def _with_other(columns, dispatch_data, pending_data):
	"""Append an "Other" column when the day actually put something there.

	Without this the roll-up view would silently drop every quantity that has no
	Customer Type -- Material Issues especially -- because the headings come from the
	master and "Other" is not a row in it.
	"""
	for source in (dispatch_data, pending_data):
		for entry in source.values():
			if entry.get("by_ct", {}).get("Other"):
				return columns + [{"name": "Other", "abbr": "Other"}]
	return columns


def _get_customer_types(roots_only=False):
	"""Column headings, ordered by sequence then name.

	roots_only drops the types that are rolled up into another one: under the toggle
	_group_sql attributes their orders to the parent, so listing them would draw a
	column nothing can ever land in. With no parents configured the two are identical.
	"""
	# A literal, not user input -- there is nothing here to parameterise.
	where = "WHERE COALESCE(parent_customer_type, '') = ''" if roots_only else ""
	rows = frappe.db.sql(
		f"""
		SELECT name, abbreviation, sequence
		FROM `tabAlpino Customer Type`
		{where}
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


def _get_dispatch_data(date, group_by_parent=0):
	"""Today's dispatch from Pick List items dispatched on the given date."""
	key, joins = _group_sql(group_by_parent)
	rows = frappe.db.sql(
		f"""
		SELECT
			pli.item_code,
			SUM(pli.qty) AS qty,
			{key} AS customer_type
		FROM `tabPick List` pl
		JOIN `tabPick List Item` pli ON pli.parent = pl.name
		LEFT JOIN `tabSales Order` so ON so.name = pl.custom_sales_order_id{joins}
		WHERE pl.custom_dispatch_date = %(date)s
		  AND pl.docstatus != 2
		  AND pl.purpose = 'Delivery'
		GROUP BY pli.item_code, {key}
		""",
		{"date": date},
		as_dict=True,
	)
	return _aggregate_by_item(rows)


def _get_material_issue_data(date, group_by_parent=0):
	"""Material Issue dispatch from submitted Stock Entries on the given date.

	A Material Issue has no Sales Order, so there is no buyer family to attribute it to.
	Grouping by family puts it in "Other" rather than inventing a parent for it.
	"""
	key = "'Other'" if group_by_parent else "COALESCE(se.custom_customer_type, 'Other')"
	rows = frappe.db.sql(
		f"""
		SELECT
			sed.item_code,
			SUM(sed.qty) AS qty,
			{key} AS customer_type
		FROM `tabStock Entry` se
		JOIN `tabStock Entry Detail` sed ON sed.parent = se.name
		WHERE se.posting_date = %(date)s
		  AND se.docstatus = 1
		  AND se.purpose = 'Material Issue'
		GROUP BY sed.item_code, {key}
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


def _get_pending_data(date, group_by_parent=0):
	"""Pending dispatch: Future Dispatch orders scheduled beyond the report date."""
	key, joins = _group_sql(group_by_parent)
	rows = frappe.db.sql(
		f"""
		SELECT
			soi.item_code,
			SUM(soi.qty) AS qty,
			{key} AS customer_type
		FROM `tabSales Order` so
		JOIN `tabSales Order Item` soi ON soi.parent = so.name{joins}
		WHERE so.custom_workflow_status = 'Future Dispatch'
		  AND so.custom_dispatch_date > %(date)s
		  AND so.docstatus = 1
		  AND so.status NOT IN ('Completed', 'Cancelled', 'Closed')
		GROUP BY soi.item_code, {key}
		""",
		{"date": date},
		as_dict=True,
	)
	return _aggregate_by_item(rows)


def _get_stock_data(warehouse, date):
	"""Stock balance as of the report date from the Stock Ledger."""
	params = {"date": date}
	wh_cond = ""
	if warehouse:
		wh_cond = "AND warehouse = %(warehouse)s"
		params["warehouse"] = warehouse
	rows = frappe.db.sql(
		f"""
		SELECT item_code, SUM(actual_qty) AS actual_qty
		FROM `tabStock Ledger Entry`
		WHERE is_cancelled = 0
		  AND posting_date <= %(date)s
		  {wh_cond}
		GROUP BY item_code
		""",
		params,
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


def _build_summary(date, customer_types, dispatch_data, pending_data, group_by_parent=0):
	"""Build top-level summary totals.

	The box / gross-weight rollups group on the same key as the grid above them, or the
	two halves of the report would disagree about which column a chain belongs to.
	"""
	key, joins = _group_sql(group_by_parent)

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
		f"""
		SELECT
			{key} AS ct,
			SUM(pl.custom_total_box) AS box,
			SUM(pl.custom_gross_weight) AS gw
		FROM `tabPick List` pl
		LEFT JOIN `tabSales Order` so ON so.name = pl.custom_sales_order_id{joins}
		WHERE pl.custom_dispatch_date = %(date)s
		  AND pl.docstatus != 2
		  AND pl.purpose = 'Delivery'
		GROUP BY {key}
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
		f"""
		SELECT
			{key} AS ct,
			SUM(soi.custom_box) AS box
		FROM `tabSales Order` so
		JOIN `tabSales Order Item` soi ON soi.parent = so.name{joins}
		WHERE so.custom_workflow_status = 'Future Dispatch'
		  AND so.custom_dispatch_date > %(date)s
		  AND so.docstatus = 1
		  AND so.status NOT IN ('Completed', 'Cancelled', 'Closed')
		GROUP BY {key}
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
