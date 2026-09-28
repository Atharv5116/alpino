"""Store Planning — projected stock, allocated live to planned Sub POs.

Nothing is reserved or stored. Every answer is worked out from three things that already
exist:

    physical   Bin.actual_qty summed over the USABLE warehouses only
               (production_settings.usable_warehouses -- never Rejected, Quarantine, QC
               Hold, the WIP floor, ...).
    allocated  what the planned Sub POs still need: for every Sub PO in Assigned / Pending
               Store Issue / Ready to Run / In Progress, its required qty minus what has
               already been issued to it. Allocation is "consumed" in planned-date order,
               so the Sub PO planned first gets the stock first.
    projected  physical - allocated.

A Sub PO going back to Unassigned drops out of the allocated statuses, which is all that
"releasing" its stock means here.

A shortage is a WARNING (VAL-STK-01): the board shows it, nothing here ever throws on it.
"""

import datetime

import frappe
from frappe.utils import flt, getdate

from alpinos.production.work_order_fields import (
	EXECUTION_STATUS_FIELD,
	PARENT_FIELD,
	PLANNED_DATE_FIELD,
)

WORK_ORDER = "Work Order"

STATUS_ASSIGNED = "Assigned"
STATUS_PENDING_STORE_ISSUE = "Pending Store Issue"
STATUS_READY_TO_RUN = "Ready to Run"
STATUS_IN_PROGRESS = "In Progress"

#: The execution statuses whose remaining material counts as allocated.
ALLOCATING_STATUSES = (
	STATUS_ASSIGNED,
	STATUS_PENDING_STORE_ISSUE,
	STATUS_READY_TO_RUN,
	STATUS_IN_PROGRESS,
)

ISSUE_PURPOSE = "Material Transfer for Manufacture"

#: Fallback only, used when Production Settings is not available yet: warehouses whose
#: name says they are not stock anyone may plan against.
_NON_USABLE_WORDS = ("quarantine", "rejected", "qc sample", "control sample", "qc hold")

_LAST = datetime.date.max


# ---------------------------------------------------------------- warehouses

def usable_warehouses(company=None):
	"""production_settings.usable_warehouses(), with a conservative fallback.

	The fallback exists only so the board still opens on a site where Production Settings
	has not been migrated yet; it applies every rule except the configured exclusions.
	"""
	try:
		from alpinos.production import production_settings
	except ImportError:
		production_settings = None
	if production_settings is not None:
		try:
			return list(production_settings.usable_warehouses(company) or [])
		except Exception:
			frappe.log_error(frappe.get_traceback(), "Store Planning: usable warehouses")

	filters = {"is_group": 0, "disabled": 0}
	if company:
		filters["company"] = company
	fields = ["name"]
	if frappe.get_meta("Warehouse").has_field("is_rejected_warehouse"):
		fields.append("is_rejected_warehouse")
	out = []
	for row in frappe.get_all("Warehouse", filters=filters, fields=fields):
		if row.get("is_rejected_warehouse"):
			continue
		lowered = (row.name or "").lower()
		if any(word in lowered for word in _NON_USABLE_WORDS):
			continue
		out.append(row.name)
	return out


def physical_stock(items, company=None):
	"""{item: actual qty} over the usable warehouses."""
	items = [i for i in set(items or []) if i]
	if not items:
		return {}
	warehouses = usable_warehouses(company)
	if not warehouses:
		return {item: 0.0 for item in items}
	out = {item: 0.0 for item in items}
	for row in frappe.get_all(
		"Bin",
		filters={"item_code": ("in", items), "warehouse": ("in", warehouses)},
		fields=["item_code", "sum(actual_qty) as qty"],
		group_by="item_code",
	):
		out[row.item_code] = flt(row.qty)
	return out


# ------------------------------------------------------------- requirements

def _issued_qty(sub_names):
	"""{sub: {item: qty}} issued to each Sub PO through submitted Material Issues."""
	sub_names = list(sub_names or [])
	if not sub_names:
		return {}
	out = {}
	meta = frappe.get_meta("Stock Entry")
	conditions = ["se.work_order in %(subs)s"]
	if meta.has_field("custom_sub_production_order"):
		conditions.append("se.custom_sub_production_order in %(subs)s")
	link_expr = "se.work_order"
	if meta.has_field("custom_sub_production_order"):
		link_expr = "coalesce(nullif(se.custom_sub_production_order, ''), se.work_order)"
	rows = frappe.db.sql(
		f"""
		select {link_expr} as sub_order, sed.item_code, sum(sed.transfer_qty) as qty
		from `tabStock Entry Detail` sed
		join `tabStock Entry` se on se.name = sed.parent
		where se.docstatus = 1
		  and se.purpose = %(purpose)s
		  and ({" or ".join(conditions)})
		group by sub_order, sed.item_code
		""",
		{"subs": tuple(sub_names), "purpose": ISSUE_PURPOSE},
		as_dict=True,
	)
	for row in rows:
		out.setdefault(row.sub_order, {})[row.item_code] = flt(row.qty)
	return out


def pending_requirements(sub_names):
	"""{sub: {item: pending qty}} -- required minus already issued, never below zero."""
	sub_names = list(sub_names or [])
	if not sub_names:
		return {}
	issued = _issued_qty(sub_names)
	out = {name: {} for name in sub_names}
	for row in frappe.get_all(
		"Work Order Item",
		filters={"parent": ("in", sub_names), "parenttype": WORK_ORDER},
		fields=["parent", "item_code", "required_qty", "transferred_qty"],
	):
		if not row.item_code:
			continue
		done = max(flt(row.transferred_qty), flt(issued.get(row.parent, {}).get(row.item_code)))
		pending = max(flt(row.required_qty) - done, 0.0)
		bucket = out.setdefault(row.parent, {})
		bucket[row.item_code] = flt(bucket.get(row.item_code)) + pending
	return out


def _order_key(planned_date, name):
	return (getdate(planned_date) if planned_date else datetime.date.min, name or "")


def _allocating_sub_orders(company=None):
	"""Every Sub PO whose remaining material is allocated, in consumption order."""
	filters = {
		PARENT_FIELD: ("is", "set"),
		"docstatus": ("<", 2),
		EXECUTION_STATUS_FIELD: ("in", ALLOCATING_STATUSES),
	}
	if company:
		filters["company"] = company
	rows = frappe.get_all(
		WORK_ORDER, filters=filters,
		fields=["name", "company", PLANNED_DATE_FIELD + " as planned_date",
		        EXECUTION_STATUS_FIELD + " as execution_status"],
	)
	rows.sort(key=lambda r: _order_key(r.planned_date, r.name))
	return rows


# --------------------------------------------------------------- public API

def projected_stock(items, company=None, as_of_date=None, exclude_sub_order=None):
	"""{item: {physical, allocated, projected}}.

	`allocated` counts the planned Sub POs that come BEFORE the point asked about:
	    * with `exclude_sub_order`: those ahead of it in planned-date order (and never
	      itself); `as_of_date`, when given, is used as its planned date;
	    * with only `as_of_date`: those planned on or before that date;
	    * with neither: every planned Sub PO.
	"""
	items = [i for i in set(items or []) if i]
	if not items:
		return {}

	reference = None
	if exclude_sub_order:
		own_date = as_of_date or frappe.db.get_value(WORK_ORDER, exclude_sub_order, PLANNED_DATE_FIELD)
		reference = _order_key(own_date, exclude_sub_order) if own_date else (_LAST, exclude_sub_order)
	elif as_of_date:
		reference = (getdate(as_of_date), "￿")

	ahead = []
	for row in _allocating_sub_orders(company):
		if row.name == exclude_sub_order:
			continue
		if reference is not None and _order_key(row.planned_date, row.name) >= reference:
			continue
		ahead.append(row.name)

	pending = pending_requirements(ahead)
	allocated = {item: 0.0 for item in items}
	for need in pending.values():
		for item in items:
			allocated[item] += flt(need.get(item))

	physical = physical_stock(items, company)
	return {
		item: {
			"physical": flt(physical.get(item)),
			"allocated": flt(allocated[item]),
			"projected": flt(physical.get(item)) - flt(allocated[item]),
		}
		for item in items
	}


def _rows_for(need, available, meta_by_item):
	rows = []
	for item, required in need.items():
		if flt(required) <= 0:
			continue
		avail = flt(available.get(item))
		deficit = max(flt(required) - max(avail, 0.0), 0.0)
		info = meta_by_item.get(item) or {}
		rows.append({
			"item": item,
			"item_name": info.get("item_name") or item,
			"uom": info.get("stock_uom") or "",
			"required": flt(required, 3),
			"available": flt(max(avail, 0.0), 3),
			"status": "Shortage" if deficit > 0.0005 else "OK",
			"deficit": flt(deficit, 3),
		})
	rows.sort(key=lambda r: (r["status"] != "Shortage", r["item"]))
	return rows


def _item_meta(items):
	items = [i for i in set(items or []) if i]
	if not items:
		return {}
	return {
		r.name: r for r in frappe.get_all(
			"Item", filters={"name": ("in", items)}, fields=["name", "item_name", "stock_uom"])
	}


def sub_order_stock(sub_order, as_of_date=None):
	"""Rows [item, item_name, uom, required, available, status OK/Shortage, deficit] for one
	Sub PO, against the stock left once everything planned ahead of it has taken its share."""
	sub = frappe.db.get_value(
		WORK_ORDER, sub_order, ["name", "company", PLANNED_DATE_FIELD + " as planned_date"],
		as_dict=True)
	if not sub:
		return []
	need = pending_requirements([sub.name]).get(sub.name) or {}
	if not need:
		return []
	projection = projected_stock(list(need), company=sub.company,
	                             as_of_date=as_of_date or sub.planned_date,
	                             exclude_sub_order=sub.name)
	available = {item: v["projected"] for item, v in projection.items()}
	return _rows_for(need, available, _item_meta(list(need)))


def stock_status_map(sub_names):
	"""Batch version of sub_order_stock for the board: {sub: [rows]}.

	One pass over the planned Sub POs in consumption order instead of one projection per
	card. A Sub PO that is not itself allocating (Unassigned) is measured against what is
	left after EVERY planned one.
	"""
	sub_names = [s for s in dict.fromkeys(sub_names or []) if s]
	if not sub_names:
		return {}

	planned = _allocating_sub_orders()
	planned_names = [r.name for r in planned]
	targets = frappe.get_all(
		WORK_ORDER, filters={"name": ("in", sub_names)}, fields=["name", "company"])
	company_of = {r.name: r.company for r in planned}
	company_of.update({r.name: r.company for r in targets})

	pending = pending_requirements(list(dict.fromkeys(planned_names + sub_names)))
	items = set()
	for need in pending.values():
		items.update(need)
	meta = _item_meta(list(items))

	physical = {}
	for company in set(company_of.values()):
		physical[company] = physical_stock(list(items), company)

	wanted = set(sub_names)
	out = {}
	running = {}
	for row in planned:
		company = row.company
		used = running.setdefault(company, {})
		need = pending.get(row.name) or {}
		if row.name in wanted:
			stock = physical.get(company) or {}
			available = {item: flt(stock.get(item)) - flt(used.get(item)) for item in need}
			out[row.name] = _rows_for(need, available, meta)
		for item, qty in need.items():
			used[item] = flt(used.get(item)) + flt(qty)

	for name in sub_names:
		if name in out:
			continue
		company = company_of.get(name)
		need = pending.get(name) or {}
		stock = physical.get(company) or {}
		used = running.get(company) or {}
		available = {item: flt(stock.get(item)) - flt(used.get(item)) for item in need}
		out[name] = _rows_for(need, available, meta)
	return out


def usable_stock_by_item(item_codes, company=None):
	"""{item: qty} over usable warehouses, or None when the usable set cannot be worked out.

	Used by the Parent PO "Check Stock" (production_order_api.material_shortage) when no
	warehouse is chosen; None tells it to keep its original all-warehouse behaviour.
	"""
	try:
		return physical_stock(item_codes, company)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Store Planning: usable stock")
		return None
