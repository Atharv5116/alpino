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
def get_dispatch_report_data(date=None, warehouse=None, include_material_issue=0, group_by_parent=0,
                             include_marketing_material=0):
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
	# Changes(HP) #62: off by default. Marketing Material then counts for nothing -- not in
	# the grid, not in any total -- rather than being shown and quietly inflating the day.
	include_marketing_material = int(include_marketing_material or 0)

	items = _get_sequenced_items()
	mm_items = _marketing_material_items()
	delivery_notes = _delivery_notes_dispatched_on(date)
	dispatch_data = _get_dispatch_data(date, group_by_parent, delivery_notes)
	if include_material_issue:
		_merge_dispatch_data(dispatch_data, _get_material_issue_data(date, group_by_parent))
	pending_data, pending_box_by_ct = _get_pending_data(date, group_by_parent)
	if not include_marketing_material and mm_items:
		# Dropped before the summary is built, so every quantity total below is computed
		# from Finished Goods alone without each total having to remember to exclude it.
		dispatch_data = {k: v for k, v in dispatch_data.items() if k not in mm_items}
		pending_data = {k: v for k, v in pending_data.items() if k not in mm_items}
		items = [i for i in items if i["item_code"] not in mm_items]
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
		exclude_marketing_material=not include_marketing_material,
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
			# The grid draws its separator off this, so Marketing Material never sits
			# interleaved with Finished Goods even when it is included.
			"is_marketing_material": 1 if ic in mm_items else 0,
			"today_dispatch": today_dispatch,
			"pending_dispatch": pending_dispatch,
			"today_stock": today_stock,
			"net_unit": net_unit,
			"inward_date": str(inward_data.get(ic) or ""),
			"dispatch_by_ct": d.get("by_ct", {}),
			"pending_by_ct": p.get("by_ct", {}),
		})

	# Marketing Material always comes last, below the separator the page draws.
	result_items.sort(key=lambda r: (r["is_marketing_material"], r["sequence"], r["item_code"]))

	return {
		"date": date,
		"warehouse": warehouse or "",
		"group_by_parent": group_by_parent,
		"include_marketing_material": include_marketing_material,
		"has_marketing_material": any(r["is_marketing_material"] for r in result_items),
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


#: Changes(HP) #62. Marketing Material is an Item Group, so membership is a property of the
#: SKU rather than of the line it arrived on.
MARKETING_MATERIAL_GROUP = "Marketing Material"


def _marketing_material_items():
	"""Item codes in the Marketing Material group, including any sub-group of it."""
	groups = frappe.db.sql_list(
		"""
		SELECT name FROM `tabItem Group`
		WHERE name = %(g)s
			OR lft > (SELECT lft FROM `tabItem Group` WHERE name = %(g)s)
			AND rgt < (SELECT rgt FROM `tabItem Group` WHERE name = %(g)s)
		""",
		{"g": MARKETING_MATERIAL_GROUP},
	) or [MARKETING_MATERIAL_GROUP]
	return set(
		frappe.db.sql_list(
			"SELECT name FROM `tabItem` WHERE item_group IN %(groups)s", {"groups": tuple(groups)}
		)
	)


def _marketing_material_boxes(pick_lists, group_by_parent=0):
	"""Boxes contributed by Marketing Material lines, keyed the way box_by_ct is keyed.

	The Pick List's header box count covers the whole document, so the only honest way to
	take Marketing Material out of it is to measure what those lines contributed -- and to
	measure it against the same grouping, or the subtraction lands in the wrong column.
	"""
	if not pick_lists:
		return {}
	mm = _marketing_material_items()
	if not mm:
		return {}
	key, joins = _group_sql(group_by_parent)
	out = {}
	for names in _chunks(sorted(set(pick_lists))):
		for r in frappe.db.sql(
			f"""
			SELECT {key} AS ct, SUM(IFNULL(pli.custom_box, 0)) AS box
			FROM `tabPick List Item` pli
			INNER JOIN `tabPick List` pl ON pl.name = pli.parent
			LEFT JOIN `tabSales Order` so ON so.name = pl.custom_sales_order_id{joins}
			WHERE pli.parent IN %(names)s AND pli.item_code IN %(mm)s
			GROUP BY {key}
			""",
			{"names": tuple(names), "mm": tuple(mm)},
			as_dict=True,
		):
			out[r["ct"]] = out.get(r["ct"], 0) + (r["box"] or 0)
	return out


def _get_sequenced_items():
	"""Return all items that have a sequence assigned, ordered by sequence."""
	return frappe.db.sql(
		"""
		SELECT name AS item_code, item_name, custom_sequence AS sequence,
			custom_color AS color, item_group
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


def _get_dispatch_data(date, group_by_parent=0, delivery_notes=None, collect=None):
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
	if collect is not None:
		for names in _chunks(delivery_notes):
			for r in frappe.db.sql(
				f"""
				SELECT x.item_code, dn.custom_sales_order_id AS sales_order,
					SUM(x.qty) AS qty, {key} AS customer_type
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
				GROUP BY x.item_code, dn.custom_sales_order_id, {key}
				""",
				{"names": tuple(names)}, as_dict=True,
			):
				if not r.sales_order:
					continue
				bucket = collect.setdefault((r.item_code, r.customer_type or "Other"), {})
				bucket[r.sales_order] = bucket.get(r.sales_order, 0) + flt(r.qty)
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


def _get_pending_data(date, group_by_parent=0, collect=None):
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
				if collect is not None:
					# Changes(HP) #58: the breakup is recorded by the same pass that builds
					# the figure, so the popup cannot disagree with the cell it opened from.
					bucket = collect.setdefault((item, ct or "Other"), {})
					bucket[line.parent] = bucket.get(line.parent, 0) + qty
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
                   delivery_notes=None, pending_box_by_ct=None, exclude_marketing_material=False):
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
	if exclude_marketing_material:
		# The header box count covers the whole Pick List, so take out what the Marketing
		# Material lines contributed -- column by column, so the subtraction lands where
		# those boxes were counted.
		for ct, box in _marketing_material_boxes(pick_lists, group_by_parent).items():
			if ct in box_by_ct:
				box_by_ct[ct] = max(box_by_ct[ct] - box, 0)
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


@frappe.whitelist()
def get_quantity_breakup(date=None, item_code=None, kind="dispatch", customer_type=None,
                         group_by_parent=0, include_material_issue=0):
	"""Changes(HP) #58: the Sales Orders behind one quantity in the Dispatch Report.

	    "In every Dispatch Report section, make each quantity value clickable. When the user
	     clicks a quantity, open a pop-up showing the Sales Orders contributing to that
	     quantity."

	`kind` is "dispatch" or "pending", and `customer_type` narrows it to one column -- the
	same cell the user clicked. The figures are collected by the very pass that builds the
	grid, so the popup cannot disagree with the number it opened from.
	"""
	if not date:
		date = today()
	kind = (kind or "dispatch").strip().lower()
	group_by_parent = int(group_by_parent or 0)

	collected = {}
	if kind == "pending":
		_get_pending_data(date, group_by_parent, collect=collected)
	else:
		notes = _delivery_notes_dispatched_on(date)
		_get_dispatch_data(date, group_by_parent, notes, collect=collected)

	if customer_type:
		buckets = [collected.get((item_code, customer_type), {})]
	else:
		buckets = [v for (ic, _ct), v in collected.items() if ic == item_code]

	totals = {}
	for b in buckets:
		for so, qty in b.items():
			totals[so] = totals.get(so, 0) + flt(qty)
	if not totals:
		# Same shape as the populated path: the dialog reads item_name for its title, and a
		# payload that drops a key when empty is a contract that only half holds.
		return {
			"date": str(date), "item_code": item_code,
			"item_name": frappe.db.get_value("Item", item_code, "item_name") or item_code,
			"kind": kind, "customer_type": customer_type or "", "rows": [], "total": 0,
		}

	names = list(totals)
	customers = {
		r.name: (r.customer_name or r.customer or "")
		for r in frappe.db.sql(
			"""SELECT name, customer, customer_name FROM `tabSales Order` WHERE name IN %(n)s""",
			{"n": tuple(names)}, as_dict=True,
		)
	}
	rows = [
		{"sales_order": so, "customer": customers.get(so, ""), "qty": flt(qty)}
		for so, qty in sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))
	]
	return {
		"date": str(date),
		"item_code": item_code,
		"item_name": frappe.db.get_value("Item", item_code, "item_name") or item_code,
		"kind": kind,
		"customer_type": customer_type or "",
		"rows": rows,
		"total": sum(r["qty"] for r in rows),
	}
