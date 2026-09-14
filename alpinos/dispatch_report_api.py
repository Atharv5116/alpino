"""Daily dispatch report data API for Alpinos.

Section logic (Changes(HP) #36):

  Pending Dispatch  every order the warehouse has approved and not finished, whatever
                    its Dispatch Date or workflow status, less what SUBMITTED Delivery
                    Notes have already covered. A draft note or a Pick List moves nothing.
  Dispatch (date)   what SUBMITTED Delivery Notes carrying that Dispatch Date took out.
                    The note's Dispatch Date decides the section, not the day it was
                    submitted: dated the 11th and submitted on the 12th, it is the 11th.

Quantities are in the SKUs that physically leave, so a combo counts as its components
(the note's packed items; the order's own packed items for what is still pending).
"""

from math import ceil

import frappe
from frappe.utils import add_days, cint, flt, getdate, today

# An approved order stops waiting for dispatch once it reaches one of these. Draft and
# Warehouse Approval Pending have not been approved yet; the forced statuses close the
# order at whatever went out, so their remainder will never be dispatched.
_NOT_PENDING = (
	"Draft", "Warehouse Approval Pending", "Rejected", "Cancelled",
	"Dispatched", "Forced Dispatched", "Completed", "Forced Completed",
)
_CHUNK = 500
_EPS = 1e-6


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
	delivery_notes = _delivery_notes_dispatched_on(date)
	dispatch_data = _get_dispatch_data(date, group_by_parent, delivery_notes)
	if include_material_issue:
		_merge_dispatch_data(dispatch_data, _get_material_issue_data(date, group_by_parent))
	pending_data, pending_box_by_ct = _get_pending_data(date, group_by_parent)
	stock_data = _get_stock_data(warehouse, date)
	inward_data = _get_inward_data()
	# Both views draw their headings from the Customer Type master, so the columns keep
	# their configured sequence either way. The toggle only drops the types that are
	# rolled up into a parent, and re-adds "Other" when the day put something there.
	customer_types = _get_customer_types(roots_only=bool(group_by_parent))
	if group_by_parent:
		customer_types = _with_other(customer_types, dispatch_data, pending_data)
	summary = _build_summary(
		date, customer_types, dispatch_data, pending_data, group_by_parent,
		delivery_notes, pending_box_by_ct,
	)

	result_items = []
	for item in items:
		ic = item["item_code"]
		d = dispatch_data.get(ic, {})
		p = pending_data.get(ic, {})
		today_dispatch = d.get("total", 0)
		pending_dispatch = p.get("total", 0)
		today_stock = stock_data.get(ic, 0)
		# Stock as of the date already excludes every note POSTED by then; subtracting
		# those again would count them twice. Only a note dated today but posted later
		# (dated the 11th, submitted the 12th) is still sitting in the stock figure.
		net_unit = today_stock - d.get("unposted", 0) - pending_dispatch

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


def _delivery_notes_dispatched_on(date):
	"""Submitted, non-return Delivery Notes whose Dispatch Date falls on `date`.

	The field is a Datetime, so the whole day is matched, not midnight.
	"""
	day = getdate(date)
	return frappe.db.sql_list(
		"""
		SELECT name FROM `tabDelivery Note`
		WHERE docstatus = 1 AND IFNULL(is_return, 0) = 0
		  AND custom_dispatch_date >= %(start)s AND custom_dispatch_date < %(end)s
		""",
		{"start": f"{day} 00:00:00", "end": f"{add_days(day, 1)} 00:00:00"},
	)


def _get_dispatch_data(date, group_by_parent=0, delivery_notes=None):
	"""What submitted Delivery Notes dated `date` took out, per SKU that left.

	A combo line is replaced by its packed components; every other line counts as is.
	`unposted` is the part whose note was posted AFTER the date, i.e. not yet in the
	date's stock figure.
	"""
	if not delivery_notes:
		return {}
	key, joins = _group_sql(group_by_parent)
	rows = []
	for names in _chunks(delivery_notes):
		rows += frappe.db.sql(
			f"""
			SELECT
				x.item_code,
				SUM(x.qty) AS qty,
				SUM(CASE WHEN dn.posting_date > %(date)s THEN x.qty ELSE 0 END) AS unposted,
				{key} AS customer_type
			FROM (
				SELECT dni.parent, dni.item_code, dni.stock_qty AS qty
				FROM `tabDelivery Note Item` dni
				WHERE dni.parent IN %(names)s
				  AND NOT EXISTS (
					SELECT 1 FROM `tabPacked Item` pi
					WHERE pi.parenttype = 'Delivery Note' AND pi.parent = dni.parent
					  AND pi.parent_detail_docname = dni.name
				  )
				UNION ALL
				SELECT pi.parent, pi.item_code, pi.qty
				FROM `tabPacked Item` pi
				WHERE pi.parenttype = 'Delivery Note' AND pi.parent IN %(names)s
			) x
			JOIN `tabDelivery Note` dn ON dn.name = x.parent
			LEFT JOIN `tabSales Order` so ON so.name = dn.custom_sales_order_id{joins}
			GROUP BY x.item_code, {key}
			""",
			{"date": getdate(date), "names": tuple(names)},
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
			target[ic] = {"total": 0, "by_ct": {}, "unposted": 0}
		target[ic]["total"] += e.get("total", 0)
		for ct, qty in e.get("by_ct", {}).items():
			target[ic]["by_ct"][ct] = target[ic]["by_ct"].get(ct, 0) + qty


def _get_pending_data(date, group_by_parent=0):
	"""Approved, unfinished order quantity not yet on a SUBMITTED Delivery Note.

	Returns ({item: {total, by_ct}}, {customer type: boxes}). Counted per order line so
	a partial dispatch leaves exactly its remainder, and a combo line is counted in its
	components against the components its notes packed. The date is not a filter: an
	approved order waits in Pending whatever Dispatch Date it carries.
	"""
	key, joins = _group_sql(group_by_parent)
	orders = frappe.db.sql(
		f"""
		SELECT so.name, {key} AS customer_type
		FROM `tabSales Order` so{joins}
		WHERE so.docstatus = 1
		  AND IFNULL(so.custom_workflow_status, '') NOT IN %(done)s
		  AND IFNULL(so.custom_force_closed, 0) = 0
		  AND so.status NOT IN ('Closed', 'Cancelled')
		""",
		{"done": _NOT_PENDING},
		as_dict=True,
	)
	if not orders:
		return {}, {}
	ct_of = {o.name: o.customer_type for o in orders}

	rows, boxes = [], {}
	factor_cache = {}
	for names in _chunks(list(ct_of)):
		lines = frappe.db.sql(
			"""
			SELECT name, parent, item_code, stock_qty AS qty
			FROM `tabSales Order Item` WHERE parent IN %(names)s
			""",
			{"names": tuple(names)},
			as_dict=True,
		)
		if not lines:
			continue
		line_names = tuple(l.name for l in lines)

		ordered_components = {}
		for r in frappe.db.sql(
			"""
			SELECT parent_detail_docname AS line, item_code, SUM(qty) AS qty
			FROM `tabPacked Item`
			WHERE parenttype = 'Sales Order' AND parent IN %(names)s
			GROUP BY parent_detail_docname, item_code
			""",
			{"names": tuple(names)},
			as_dict=True,
		):
			ordered_components.setdefault(r.line, {})[r.item_code] = flt(r.qty)

		delivered_line = {
			r.line: flt(r.qty)
			for r in frappe.db.sql(
				"""
				SELECT dni.so_detail AS line, SUM(dni.stock_qty) AS qty
				FROM `tabDelivery Note Item` dni
				JOIN `tabDelivery Note` dn ON dn.name = dni.parent
				WHERE dni.so_detail IN %(lines)s
				  AND dn.docstatus = 1 AND IFNULL(dn.is_return, 0) = 0
				GROUP BY dni.so_detail
				""",
				{"lines": line_names},
				as_dict=True,
			)
		}
		delivered_components = {
			(r.line, r.item_code): flt(r.qty)
			for r in frappe.db.sql(
				"""
				SELECT dni.so_detail AS line, pi.item_code, SUM(pi.qty) AS qty
				FROM `tabPacked Item` pi
				JOIN `tabDelivery Note Item` dni ON dni.name = pi.parent_detail_docname
				JOIN `tabDelivery Note` dn ON dn.name = pi.parent
				WHERE pi.parenttype = 'Delivery Note' AND dni.so_detail IN %(lines)s
				  AND dn.docstatus = 1 AND IFNULL(dn.is_return, 0) = 0
				GROUP BY dni.so_detail, pi.item_code
				""",
				{"lines": line_names},
				as_dict=True,
			)
		}

		for line in lines:
			ct = ct_of.get(line.parent)
			components = ordered_components.get(line.name) or _mapped_components(line)
			if components:
				remaining = {
					item: qty - delivered_components.get((line.name, item), 0)
					for item, qty in components.items()
				}
			else:
				remaining = {line.item_code: flt(line.qty) - delivered_line.get(line.name, 0)}
			for item, qty in remaining.items():
				if qty <= _EPS or not item:
					continue
				rows.append({"item_code": item, "qty": qty, "customer_type": ct})
				if item not in factor_cache:
					from alpinos.sales_order_api import get_box_conversion_factor

					factor_cache[item] = flt(get_box_conversion_factor(item)) or 1
				key_ct = ct or "Other"
				boxes[key_ct] = boxes.get(key_ct, 0) + ceil(qty / factor_cache[item] - _EPS)

	return _aggregate_by_item(rows), boxes


def _mapped_components(line):
	"""A combo line on an order saved before it had packed items: explode from the Item."""
	from alpinos.sales_order_api import _bundle_components

	mapping = _bundle_components(line.item_code)
	if not mapping:
		return None
	return {m.item: flt(m.base_qty) * flt(line.qty) for m in mapping if m.item}


def _chunks(values):
	values = list(values)
	for i in range(0, len(values), _CHUNK):
		yield values[i : i + _CHUNK]


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


def _build_summary(date, customer_types, dispatch_data, pending_data, group_by_parent=0,
                   delivery_notes=None, pending_box_by_ct=None):
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

	# Box / gross weight of the day's dispatch: the Pick Lists those notes were made from
	# (the note itself carries no box count).
	box_by_ct, gw_by_ct = {}, {}
	pick_lists = []
	for names in _chunks(delivery_notes or []):
		pick_lists += frappe.db.sql_list(
			"""
			SELECT DISTINCT against_pick_list FROM `tabDelivery Note Item`
			WHERE parent IN %(names)s AND IFNULL(against_pick_list, '') <> ''
			""",
			{"names": tuple(names)},
		)
	for names in _chunks(sorted(set(pick_lists))):
		for r in frappe.db.sql(
			f"""
			SELECT
				{key} AS ct,
				SUM(pl.custom_total_box) AS box,
				SUM(pl.custom_gross_weight) AS gw
			FROM `tabPick List` pl
			LEFT JOIN `tabSales Order` so ON so.name = pl.custom_sales_order_id{joins}
			WHERE pl.name IN %(names)s
			GROUP BY {key}
			""",
			{"names": tuple(names)},
			as_dict=True,
		):
			box_by_ct[r["ct"]] = box_by_ct.get(r["ct"], 0) + (r["box"] or 0)
			gw_by_ct[r["ct"]] = gw_by_ct.get(r["ct"], 0) + (r["gw"] or 0)
	total_box = sum(box_by_ct.values())
	total_gw = sum(gw_by_ct.values())

	# Boxes still to go, from the remaining quantity (see _get_pending_data).
	pending_box_by_ct = pending_box_by_ct or {}

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
		qty = flt(row["qty"])
		ct = row["customer_type"] or "Other"
		if ic not in data:
			data[ic] = {"total": 0, "by_ct": {}, "unposted": 0}
		data[ic]["total"] += qty
		data[ic]["unposted"] += flt(row.get("unposted"))
		data[ic]["by_ct"][ct] = data[ic]["by_ct"].get(ct, 0) + qty
	return data
