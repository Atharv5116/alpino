"""Production Reports (FRD Phase 12) + Audit Trail view (5.6), served to the
production_reports page.

One engine, many reports: run_report(report, filters) -> {columns, rows, totals, message}.
Columns of fieldtype Link (or Dynamic Link) are clickable on the page (12.4 drill-down).

Guards: every doctype owned by another builder (Production Run, Process Inward, Production
QC, Filling Plan, Filling Inward, Final QC, Production Yield Record) is checked with
frappe.db.exists("DocType", ...) and its field names with meta.has_field, so each report
returns empty rows -- never an error -- before that data exists.

RBAC (12.4): Production Admin / Production Manager / Plant Head / System Manager only.
Heavy reports default to the last 30 days when no date range is given (12.4 performance).
"""

import datetime
import json

import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, flt, get_fullname, getdate, nowdate

from alpinos.production import inventory_common as IC

WO = "Work Order"
PO = "Production Order"
PARENT_FIELD = "custom_parent_production_order"
EXEC_FIELD = "custom_execution_status"
DEFAULT_DAYS = 30

ALL_FILTERS = ("from_date", "to_date", "parent_po", "sub_order", "sku", "batch", "line",
               "status", "shift")


# ========================================================================== helpers

def _assert_access():
	IC.assert_roles(IC.REPORT_ROLES, _("view Production Reports"))


def col(fieldname, label, fieldtype="Data", options=None, width=120):
	c = {"fieldname": fieldname, "label": _(label), "fieldtype": fieldtype, "width": width}
	if options:
		c["options"] = options
	return c


def _range(f, default_days=DEFAULT_DAYS):
	to_date = getdate(f.get("to_date") or nowdate())
	from_date = getdate(f.get("from_date") or add_days(to_date, -default_days))
	return from_date, to_date


def _exists(doctype):
	return IC.doctype_exists(doctype)


def _pick(doctype, *candidates):
	return IC.first_field(doctype, candidates)


def _sub_filters(f):
	filters = {PARENT_FIELD: ("is", "set"), "docstatus": ("<", 2)}
	if f.get("parent_po"):
		filters[PARENT_FIELD] = f.parent_po
	if f.get("sub_order"):
		filters["name"] = f.sub_order
	if f.get("sku"):
		filters["production_item"] = f.sku
	return filters


def _net_issued_kg(sub_names, kinds=("RM", "Additive")):
	"""{sub: KG} issued through Material Issues minus Material Returns, RM + Additive only
	(PM is counted in pieces and is not raw material input)."""
	sub_names = [s for s in set(sub_names or []) if s]
	if not sub_names or not IC.has_field("Stock Entry", "custom_entry_kind"):
		return {}
	rows = frappe.db.sql(
		"""select se.custom_sub_production_order as sub, se.custom_entry_kind as kind,
		          sed.item_code, sum(sed.transfer_qty) as qty
		   from `tabStock Entry Detail` sed join `tabStock Entry` se on se.name = sed.parent
		   where se.docstatus = 1 and se.custom_entry_kind in ('Material Issue', 'Material Return')
		     and se.custom_sub_production_order in %(subs)s
		   group by sub, kind, sed.item_code""", {"subs": tuple(sub_names)}, as_dict=True)
	info = IC.item_meta([r.item_code for r in rows])
	out = {}
	for r in rows:
		meta = info.get(r.item_code)
		if kinds and (not meta or meta.material_type not in kinds):
			continue
		sign = 1 if r.kind == "Material Issue" else -1
		out[r.sub] = flt(out.get(r.sub)) + sign * IC.qty_in_kg(r.qty, meta)
	return out


def _baked_output(sub_names):
	"""{sub: KG} produced by submitted Manufacture entries (finished rows) per Sub PO."""
	sub_names = [s for s in set(sub_names or []) if s]
	if not sub_names:
		return {}
	rows = frappe.db.sql(
		"""select se.work_order as sub, sed.item_code, sum(sed.transfer_qty) as qty
		   from `tabStock Entry Detail` sed join `tabStock Entry` se on se.name = sed.parent
		   where se.docstatus = 1 and se.purpose = 'Manufacture' and se.work_order in %(subs)s
		     and ifnull(sed.t_warehouse, '') != '' and sed.is_finished_item = 1
		   group by se.work_order, sed.item_code""", {"subs": tuple(sub_names)}, as_dict=True)
	info = IC.item_meta([r.item_code for r in rows])
	out = {}
	for r in rows:
		out[r.sub] = flt(out.get(r.sub)) + IC.qty_in_kg(r.qty, info.get(r.item_code))
	return out


# ----------------------------------------------------------------------- shifts

_SHIFT_CACHE = "_alpinos_report_shifts"


def _shifts():
	cached = getattr(frappe.local, _SHIFT_CACHE, None)
	if cached is not None:
		return cached
	out = []
	from alpinos.production.shifts import _seconds, all_shifts
	for name, start, end in all_shifts():
		s, e = _seconds(start), _seconds(end)
		if s is None or e is None or s == e:
			continue
		out.append((name, s, e))
	setattr(frappe.local, _SHIFT_CACHE, out)
	return out


def shift_of(posting_time):
	"""Shift name for a time of day (overnight shifts handled), or ''."""
	if posting_time in (None, ""):
		return ""
	from alpinos.production.shifts import _in_shift, _seconds
	secs = _seconds(posting_time)
	if secs is None:
		return ""
	# Same rule as shifts.current_shift: of overlapping shifts, the most recently started.
	best, best_age = "", None
	for name, s, e in _shifts():
		if _in_shift(secs, s, e):
			age = (secs - s) % 86400
			if best_age is None or age < best_age:
				best, best_age = name, age
	return best


def _time_of(value):
	if isinstance(value, datetime.datetime):
		return value.time()
	if isinstance(value, str) and " " in value:
		return value.split(" ", 1)[1]
	return None


# ======================================================== 12.1 Order & Planning

def _overall_status(raw, subs):
	if raw in ("Cancelled",):
		return "Cancelled"
	if raw in ("Draft", "Pending Approval", "Rejected"):
		return "Draft"
	if subs and all(s.get(EXEC_FIELD) == "Completed" for s in subs):
		return "Closed"
	return "Active"


def report_parent_po(f):
	columns = [
		col("name", "Parent PO", "Link", PO, 120), col("creation_date", "Date", "Date", width=95),
		col("fg_item", "Target SKU", "Link", "Item", 130), col("fg_item_name", "SKU Name", width=170),
		col("target_kg", "Total Target Qty (KG)", "Float", width=120),
		col("target_pcs", "Target Pcs", "Int", width=90),
		col("completed_kg", "Total Completed Qty (KG)", "Float", width=130),
		col("sub_count", "Sub POs", "Int", width=70), col("subs_completed", "Sub POs Completed", "Int", width=90),
		col("overall_status", "Overall Status", width=100), col("status", "Document Status", width=110),
	]
	if not _exists(PO):
		return columns, []
	filters = {}
	if f.get("parent_po"):
		filters["name"] = f.parent_po
	if f.get("sku"):
		filters["fg_item"] = f.sku
	if f.get("from_date") or f.get("to_date"):
		a, b = _range(f, 3650)
		filters["creation_date"] = ("between", [a, b])
	pos = frappe.get_all(PO, filters=filters,
	                     fields=["name", "creation_date", "fg_item", "fg_item_name", "production_qty_kg",
	                             "production_qty_pcs", "status"],
	                     order_by="creation_date desc, name desc", limit_page_length=2000)
	subs_by = {}
	if pos:
		for s in frappe.get_all(WO, filters={PARENT_FIELD: ("in", [p.name for p in pos]), "docstatus": ("<", 2)},
		                        fields=["name", PARENT_FIELD, EXEC_FIELD, "produced_qty"]):
			subs_by.setdefault(s.get(PARENT_FIELD), []).append(s)
	rows = []
	for p in pos:
		subs = subs_by.get(p.name, [])
		overall = _overall_status(p.status, subs)
		if f.get("status") and f.status not in (overall, p.status):
			continue
		rows.append({
			"name": p.name, "creation_date": p.creation_date, "fg_item": p.fg_item,
			"fg_item_name": p.fg_item_name, "target_kg": flt(p.production_qty_kg),
			"target_pcs": cint(p.production_qty_pcs),
			"completed_kg": flt(sum(flt(s.produced_qty) for s in subs), 3),
			"sub_count": len(subs), "subs_completed": len([s for s in subs if s.get(EXEC_FIELD) == "Completed"]),
			"overall_status": overall, "status": p.status,
		})
	return columns, rows


def _qc_status_map(sub_names):
	out = {}
	if not sub_names or not (_exists("Production QC") and IC.has_field("Production QC", "sub_order")):
		return out
	for r in frappe.get_all("Production QC", filters={"sub_order": ("in", sub_names), "docstatus": ("<", 2)},
	                        fields=["sub_order", "docstatus", "approved_kg", "rejected_kg", "modified"],
	                        order_by="modified asc"):
		if cint(r.docstatus) == 0:
			out[r.sub_order] = "Pending"
		elif flt(r.approved_kg) and flt(r.rejected_kg):
			out[r.sub_order] = "Partially Approved"
		elif flt(r.rejected_kg) and not flt(r.approved_kg):
			out[r.sub_order] = "Rejected"
		else:
			out[r.sub_order] = "Approved"
	return out


def _derived_qc(status):
	return {"Pending QC": "Pending", "QC Rejected": "Rejected", "Ready for Next Stage": "Approved",
	        "Completed": "Approved"}.get(status or "", "")


def report_sub_po(f):
	columns = [
		col("name", "Sub PO", "Link", WO, 120), col("parent", "Parent PO", "Link", PO, 110),
		col("production_item", "SKU", "Link", "Item", 130), col("item_name", "SKU Name", width=160),
		col("line", "Baking Line / Machine", "Link", "Machine", 130),
		col("qty", "Batch Size (KG)", "Float", width=100), col("batch", "Batch Number", width=110),
		col("planned_date", "Planned Date", "Date", width=95), col("status", "Status", width=120),
		col("qc_status", "QC Status", width=110), col("wip_qty", "Approved WIP (KG)", "Float", width=110),
	]
	filters = _sub_filters(f)
	if f.get("line"):
		filters["custom_assigned_machine"] = f.line
	if f.get("status"):
		filters[EXEC_FIELD] = f.status
	if f.get("from_date") or f.get("to_date"):
		a, b = _range(f, 3650)
		filters["custom_planned_date"] = ("between", [a, b])
	fields = ["name", PARENT_FIELD + " as parent", "production_item", "item_name",
	          "custom_assigned_machine as line", "qty", "custom_batch_number as batch",
	          "custom_planned_date as planned_date", EXEC_FIELD + " as status"]
	if IC.has_field(WO, "custom_wip_qty"):
		fields.append("custom_wip_qty as wip_qty")
	subs = frappe.get_all(WO, filters=filters, fields=fields, order_by="name desc", limit_page_length=3000)
	qc = _qc_status_map([s.name for s in subs])
	for s in subs:
		s["qc_status"] = qc.get(s.name) or _derived_qc(s.status)
	return columns, subs


def _filling_plan_rows(sub_names):
	"""{sub: [dict(plan, sku, target_pcs, consumed_kg)]} from Filling Plan rows (guarded)."""
	out = {}
	if not sub_names or not _exists("Filling Plan"):
		return out
	sub_f = _pick("Filling Plan", "sub_order", "sub_production_order", "work_order")
	if not sub_f:
		return out
	meta = frappe.get_meta("Filling Plan")
	table = next((df for df in meta.get_table_fields()), None)
	if not table:
		return out
	child = table.options
	sku_f = _pick(child, "target_sku", "sku", "item_code")
	pcs_f = _pick(child, "planned_pcs", "target_pcs")
	kg_f = _pick(child, "equivalent_kg", "planned_kg")
	done_f = _pick(child, "completed_pcs")
	size_f = _pick(child, "size_kg", "pack_size_kg")
	plans = frappe.get_all("Filling Plan", filters={sub_f: ("in", sub_names), "docstatus": ("<", 2)},
	                       fields=["name", sub_f + " as sub"])
	if not plans:
		return out
	plan_sub = {p.name: p.sub for p in plans}
	fields = ["parent", "idx"] + [x for x in (sku_f, pcs_f, kg_f, done_f, size_f) if x]
	for r in frappe.get_all(child, filters={"parent": ("in", list(plan_sub)), "parenttype": "Filling Plan"},
	                        fields=fields, order_by="parent asc, idx asc"):
		consumed = flt(r.get(done_f)) * flt(r.get(size_f)) if (done_f and size_f and flt(r.get(done_f))) \
			else flt(r.get(kg_f)) if kg_f else 0
		out.setdefault(plan_sub[r.parent], []).append({
			"plan": r.parent, "sku": r.get(sku_f) if sku_f else "",
			"target_pcs": cint(r.get(pcs_f)) if pcs_f else 0, "consumed_kg": flt(consumed, 3)})
	return out


def report_split_history(f):
	columns = [
		col("sub_order", "Sub PO", "Link", WO, 120), col("split_from", "Split From", "Link", WO, 110),
		col("baked_kg", "Original Baked Wt (KG)", "Float", width=120),
		col("split_no", "Split #", "Int", width=60), col("plan", "Filling Plan", "Dynamic Link", "plan_doctype", 120),
		col("sku", "SKU", "Link", "Item", 130), col("target_pcs", "Target Pcs", "Int", width=90),
		col("consumed_kg", "Consumed Wt (KG)", "Float", width=110),
		col("remaining_kg", "Remaining WIP (KG)", "Float", width=110),
	]
	fields = ["name", "custom_split_from as split_from"]
	if IC.has_field(WO, "custom_wip_qty"):
		fields.append("custom_wip_qty as wip_qty")
	subs = frappe.get_all(WO, filters=_sub_filters(f), fields=fields, order_by="name desc",
	                      limit_page_length=2000)
	names = [s.name for s in subs]
	baked = _baked_output(names)
	splits = _filling_plan_rows(names)
	rows = []
	for s in subs:
		parts = splits.get(s.name) or [{}]
		for i, p in enumerate(parts, 1):
			if f.get("sku") and p.get("sku") and p.get("sku") != f.sku:
				continue
			rows.append({
				"sub_order": s.name, "split_from": s.split_from, "baked_kg": flt(baked.get(s.name), 3),
				"split_no": i if p else None, "plan": p.get("plan"), "plan_doctype": "Filling Plan",
				"sku": p.get("sku"), "target_pcs": p.get("target_pcs"), "consumed_kg": p.get("consumed_kg"),
				"remaining_kg": flt(s.get("wip_qty"), 3),
			})
	return columns, rows


def report_production_order(f):
	"""Filling / packaging orders: one row per Filling Inward (guarded)."""
	columns = [
		col("name", "Prod Order ID", "Link", "Filling Inward", 130), col("date", "Date", "Date", width=95),
		col("sub_order", "Sub PO", "Link", WO, 110), col("sku", "SKU", "Link", "Item", 130),
		col("line", "Machine Line", "Link", "Machine", 120), col("target", "Target Qty (Pcs)", "Float", width=100),
		col("actual", "Actual Output (Pcs)", "Float", width=110), col("operator", "Operator Name", width=140),
		col("status", "Status", width=90),
	]
	dt = "Filling Inward"
	if not _exists(dt):
		return columns, []
	date_f = _pick(dt, "posting_date", "inward_date", "date")
	sku_f = _pick(dt, "target_sku", "sku", "item_code", "fg_item")
	line_f = _pick(dt, "filling_line", "machine", "line")
	tgt_f = _pick(dt, "planned_pcs", "target_pcs")
	act_f = _pick(dt, "input_pcs", "todays_input_pcs", "today_input_pcs", "filled_pcs", "actual_pcs", "qty_pcs")
	sub_f = _pick(dt, "sub_order", "work_order")
	op_f = _pick(dt, "operator", "operator_name")
	st_f = _pick(dt, "status")
	fields = ["name", "owner", "docstatus"] + [x for x in (date_f, sku_f, line_f, tgt_f, act_f, sub_f, op_f, st_f) if x]
	filters = {"docstatus": ("<", 2)}
	if date_f:
		a, b = _range(f)
		filters[date_f] = ("between", [a, b])
	for key, fld in (("sku", sku_f), ("line", line_f), ("sub_order", sub_f)):
		if f.get(key) and fld:
			filters[fld] = f.get(key)
	rows = []
	for r in frappe.get_all(dt, filters=filters, fields=fields, order_by="creation desc", limit_page_length=3000):
		status = r.get(st_f) if st_f else {0: "Draft", 1: "Submitted"}.get(cint(r.docstatus))
		if f.get("status") and status != f.status:
			continue
		op = r.get(op_f) if op_f else r.owner
		rows.append({"name": r.name, "date": r.get(date_f) if date_f else None,
		             "sub_order": r.get(sub_f) if sub_f else None, "sku": r.get(sku_f) if sku_f else None,
		             "line": r.get(line_f) if line_f else None, "target": flt(r.get(tgt_f)) if tgt_f else None,
		             "actual": flt(r.get(act_f)) if act_f else None,
		             "operator": get_fullname(op) if op and "@" in str(op) else op, "status": status})
	return columns, rows


def report_weekly_planning(f):
	columns = [
		col("week", "Week Commencing", "Date", width=110), col("line", "Machine Line", "Link", "Machine", 130),
		col("process", "Process", "Link", "Process Master", 110), col("skus", "Scheduled SKUs", width=220),
		col("sub_orders", "Sub POs", width=200), col("planned_kg", "Total Planned KG", "Float", width=110),
		col("material_kg", "Estimated Material Requirement (KG)", "Float", width=150),
	]
	a = getdate(f.get("from_date") or nowdate())
	b = getdate(f.get("to_date") or add_days(a, 27))
	filters = _sub_filters(f)
	filters["custom_planned_date"] = ("between", [a, b])
	if f.get("line"):
		filters["custom_assigned_machine"] = f.line
	if f.get("status"):
		filters[EXEC_FIELD] = f.status
	subs = frappe.get_all(WO, filters=filters,
	                      fields=["name", "production_item", "qty", "custom_planned_date as planned_date",
	                              "custom_assigned_machine as line", "custom_assigned_process as process"],
	                      limit_page_length=5000)
	need = {}
	if subs:
		rows = frappe.get_all("Work Order Item", filters={"parent": ("in", [s.name for s in subs]),
		                                                  "parenttype": WO},
		                      fields=["parent", "item_code", "required_qty"])
		info = IC.item_meta([r.item_code for r in rows])
		for r in rows:
			meta = info.get(r.item_code)
			if meta and meta.material_type in ("RM", "Additive"):
				need[r.parent] = flt(need.get(r.parent)) + IC.qty_in_kg(r.required_qty, meta)
	groups = {}
	for s in subs:
		d = getdate(s.planned_date)
		week = add_days(d, -d.weekday())
		g = groups.setdefault((str(week), s.line or "", s.process or ""), {
			"week": week, "line": s.line, "process": s.process, "skus": set(), "sub_orders": [],
			"planned_kg": 0.0, "material_kg": 0.0})
		g["skus"].add(s.production_item)
		g["sub_orders"].append(s.name)
		g["planned_kg"] += flt(s.qty)
		g["material_kg"] += flt(need.get(s.name))
	out = []
	for key in sorted(groups):
		g = groups[key]
		g["skus"] = ", ".join(sorted(x for x in g["skus"] if x))
		g["sub_orders"] = ", ".join(g["sub_orders"])
		g["planned_kg"] = flt(g["planned_kg"], 3)
		g["material_kg"] = flt(g["material_kg"], 3)
		out.append(g)
	return columns, out


# ===================================================== 12.2 Material & Inventory

def report_material_availability(f):
	"""Live (12.4): current usable stock vs. stock reserved by planned Sub POs."""
	columns = [
		col("item_code", "Item", "Link", "Item", 130), col("item_name", "Item Name", width=180),
		col("category", "Category", width=90), col("uom", "UOM", width=60),
		col("current", "Current Stock", "Float", width=110), col("reserved", "Reserved Stock (Planned)", "Float", width=140),
		col("net", "Net Available", "Float", width=110),
	]
	if not IC.has_field("Item", "custom_material_type"):
		return columns, []
	item_filters = {"custom_material_type": ("in", ["RM", "PM", "Additive"]), "disabled": 0}
	if f.get("sku"):
		item_filters["name"] = f.sku
	items = frappe.get_all("Item", filters=item_filters, pluck="name", limit_page_length=0)
	if not items:
		return columns, []
	from alpinos.production.stock_allocation import projected_stock
	proj = projected_stock(items)
	info = IC.item_meta(items)
	rows = []
	for item in sorted(items):
		p = proj.get(item) or {}
		if not flt(p.get("physical")) and not flt(p.get("allocated")):
			continue
		meta = info.get(item) or frappe._dict()
		rows.append({"item_code": item, "item_name": meta.get("item_name"), "category": meta.get("material_type"),
		             "uom": meta.get("stock_uom"), "current": flt(p.get("physical"), 3),
		             "reserved": flt(p.get("allocated"), 3), "net": flt(p.get("projected"), 3)})
	return columns, rows


def _consumption(f, kinds=None):
	columns = [
		col("date", "Date", "Date", width=95), col("item_code", "Item Code", "Link", "Item", 130),
		col("item_name", "Item Name", width=170), col("category", "Category", width=80),
		col("qty", "Consumed Qty", "Float", width=100), col("uom", "UOM", width=60),
		col("qty_kg", "Consumed (KG)", "Float", width=100),
		col("sub_order", "Tagged Sub PO", "Link", WO, 110), col("parent", "Tagged Prod Order", "Link", PO, 110),
		col("stock_entry", "Stock Entry", "Link", "Stock Entry", 140), col("purpose", "Entry", width=100),
	]
	a, b = _range(f)
	has_sub = IC.has_field("Stock Entry", "custom_sub_production_order")
	sub_expr = "coalesce(nullif(se.custom_sub_production_order, ''), se.work_order)" if has_sub else "se.work_order"
	cond = ["se.docstatus = 1", "se.purpose in ('Manufacture', 'Repack')",
	        "ifnull(sed.s_warehouse, '') != ''", "se.posting_date between %(a)s and %(b)s"]
	values = {"a": a, "b": b}
	if f.get("sub_order"):
		cond.append(f"{sub_expr} = %(sub)s")
		values["sub"] = f.sub_order
	if f.get("sku"):
		cond.append("sed.item_code = %(sku)s")
		values["sku"] = f.sku
	if f.get("batch"):
		cond.append("sed.batch_no = %(batch)s")
		values["batch"] = f.batch
	rows = frappe.db.sql(
		f"""select se.posting_date as date, se.posting_time, sed.item_code, sed.item_name,
		           sed.transfer_qty as qty, sed.stock_uom as uom, {sub_expr} as sub_order,
		           se.name as stock_entry, se.purpose
		    from `tabStock Entry Detail` sed join `tabStock Entry` se on se.name = sed.parent
		    where {" and ".join(cond)}
		    order by se.posting_date desc, se.name desc limit 20000""", values, as_dict=True)
	info = IC.item_meta([r.item_code for r in rows])
	parents = {}
	subs = list({r.sub_order for r in rows if r.sub_order})
	if subs:
		parents = dict(frappe.get_all(WO, filters={"name": ("in", subs)}, fields=["name", PARENT_FIELD], as_list=True))
	out = []
	for r in rows:
		meta = info.get(r.item_code) or frappe._dict()
		cat = meta.get("material_type") or ""
		if kinds and cat not in kinds:
			continue
		parent = parents.get(r.sub_order)
		if f.get("parent_po") and parent != f.parent_po:
			continue
		if f.get("shift") and shift_of(r.posting_time) != f.shift:
			continue
		r["category"] = cat
		r["parent"] = parent
		r["qty_kg"] = flt(IC.qty_in_kg(r.qty, meta), 3)
		r.pop("posting_time", None)
		out.append(r)
	return columns, out


def report_material_consumption(f):
	return _consumption(f)


def report_rm_consumption(f):
	return _consumption(f, ("RM",))


def report_additive_consumption(f):
	return _consumption(f, ("Additive",))


def report_pm_consumption(f):
	return _consumption(f, ("PM",))


def report_wip_aging(f):
	columns = [
		col("name", "Sub-PO Batch", "Link", WO, 120), col("batch", "Batch Number", width=110),
		col("parent", "Parent PO", "Link", PO, 110), col("production_item", "Item", "Link", "Item", 130),
		col("wip_qty", "Current WIP Weight (KG)", "Float", width=130),
		col("baked_on", "Baked On", "Date", width=95), col("aging_days", "Time Since Baking (Days)", "Int", width=130),
		col("status", "Status", width=120),
	]
	if not IC.has_field(WO, "custom_wip_qty"):
		return columns, []
	filters = _sub_filters(f)
	filters["custom_wip_qty"] = (">", 0)
	subs = frappe.get_all(WO, filters=filters,
	                      fields=["name", "custom_batch_number as batch", PARENT_FIELD + " as parent",
	                              "production_item", "custom_wip_qty as wip_qty", EXEC_FIELD + " as status"],
	                      limit_page_length=3000)
	last = {}
	if subs:
		for r in frappe.db.sql(
				"""select work_order, max(posting_date) as d from `tabStock Entry`
				   where docstatus = 1 and purpose = 'Manufacture' and work_order in %(s)s
				   group by work_order""", {"s": tuple(s.name for s in subs)}, as_dict=True):
			last[r.work_order] = r.d
	today = nowdate()
	for s in subs:
		s["baked_on"] = last.get(s.name)
		s["aging_days"] = date_diff(today, s["baked_on"]) if s["baked_on"] else None
	subs.sort(key=lambda s: -(s["aging_days"] or 0))
	return columns, subs


def report_category_stock(f):
	columns = [
		col("category", "Category", width=120), col("item_count", "Total Item Count", "Int", width=120),
		col("total_qty", "Total Aggregate Qty", "Float", width=140),
		col("total_kg", "Total Aggregate Weight (KG)", "Float", width=160),
		col("total_value", "Total Value", "Currency", width=130),
	]
	if not IC.has_field("Item", "custom_material_type"):
		return columns, []
	bins = frappe.db.sql(
		"""select b.item_code, ifnull(i.custom_material_type, '') as category,
		          sum(b.actual_qty) as qty, sum(b.stock_value) as value
		   from `tabBin` b join `tabItem` i on i.name = b.item_code
		   where b.actual_qty > 0 group by b.item_code, category""", as_dict=True)
	info = IC.item_meta([b.item_code for b in bins])
	groups = {}
	for b in bins:
		cat = b.category or "Other"
		g = groups.setdefault(cat, {"category": cat, "items": set(), "total_qty": 0.0, "total_kg": 0.0,
		                            "total_value": 0.0})
		g["items"].add(b.item_code)
		g["total_qty"] += flt(b.qty)
		g["total_kg"] += IC.qty_in_kg(b.qty, info.get(b.item_code))
		g["total_value"] += flt(b.value)
	order = {"RM": 0, "PM": 1, "Additive": 2, "FG": 3}
	out = []
	for cat in sorted(groups, key=lambda c: (order.get(c, 9), c)):
		g = groups[cat]
		out.append({"category": cat, "item_count": len(g["items"]), "total_qty": flt(g["total_qty"], 3),
		            "total_kg": flt(g["total_kg"], 3), "total_value": flt(g["total_value"], 2)})
	return columns, out


# ===================================================== 12.3 Performance & Quality

def _target_yield_pct():
	# default pending BA confirmation: Target Yield % = 100 - filling wastage tolerance %
	# (Production Settings, default 5) until the BA gives a per-SKU target.
	tol = IC.setting("filling_wastage_tolerance_pct")
	return 100.0 - (flt(tol) if tol not in (None, "") else 5.0)


def report_yield(f):
	columns = [
		col("parent", "Prod Order ID", "Link", PO, 120), col("fg_item", "SKU", "Link", "Item", 130),
		col("input_kg", "Total Input (KG)", "Float", width=110), col("output_kg", "Total Output (KG)", "Float", width=110),
		col("yield_pct", "Actual Yield %", "Percent", width=100), col("target_pct", "Target Yield %", "Percent", width=100),
		col("variance", "Variance", "Float", width=90), col("source", "Source", width=150),
	]
	target = _target_yield_pct()
	rows = []
	done = set()
	yr = "Production Yield Record"
	if _exists(yr):
		pf = _pick(yr, "parent_po", "production_order", "parent_production_order")
		fields = ["name"] + [x for x in (pf, _pick(yr, "fg_item"), _pick(yr, "issued_rm_kg"),
		                                 _pick(yr, "filled_kg")) if x]
		filters = {}
		if f.get("parent_po") and pf:
			filters[pf] = f.parent_po
		for r in frappe.get_all(yr, filters=filters, fields=fields, limit_page_length=3000):
			inp, out = flt(r.get("issued_rm_kg")), flt(r.get("filled_kg"))
			y = flt(out / inp * 100, 2) if inp else 0
			parent = r.get(pf) if pf else None
			if f.get("sku") and r.get("fg_item") != f.sku:
				continue
			done.add(parent)
			rows.append({"parent": parent, "fg_item": r.get("fg_item"), "input_kg": flt(inp, 3),
			             "output_kg": flt(out, 3), "yield_pct": y, "target_pct": target,
			             "variance": flt(y - target, 2), "source": _("Filled (final)")})
	# Parent POs not closed yet: baking yield from issued RM vs. baked output so far.
	po_filters = {"status": ("not in", ["Cancelled", "Draft", "Rejected"])}
	if f.get("parent_po"):
		po_filters["name"] = f.parent_po
	if f.get("sku"):
		po_filters["fg_item"] = f.sku
	if f.get("from_date") or f.get("to_date"):
		a, b = _range(f, 3650)
		po_filters["creation_date"] = ("between", [a, b])
	if _exists(PO):
		pos = [p for p in frappe.get_all(PO, filters=po_filters, fields=["name", "fg_item"],
		                                 limit_page_length=1000) if p.name not in done]
		if pos:
			subs = frappe.get_all(WO, filters={PARENT_FIELD: ("in", [p.name for p in pos]), "docstatus": ("<", 2)},
			                      fields=["name", PARENT_FIELD + " as parent"])
			issued = _net_issued_kg([s.name for s in subs])
			baked = _baked_output([s.name for s in subs])
			agg = {}
			for s in subs:
				a_ = agg.setdefault(s.parent, [0.0, 0.0])
				a_[0] += flt(issued.get(s.name))
				a_[1] += flt(baked.get(s.name))
			for p in pos:
				inp, out = agg.get(p.name, [0.0, 0.0])
				if not inp and not out:
					continue
				y = flt(out / inp * 100, 2) if inp else 0
				rows.append({"parent": p.name, "fg_item": p.fg_item, "input_kg": flt(inp, 3),
				             "output_kg": flt(out, 3), "yield_pct": y, "target_pct": target,
				             "variance": flt(y - target, 2), "source": _("Baked (in progress)")})
	return columns, rows


def _loss_rows(f):
	"""[dict(date, shift, stage, waste_type, qty_kg, logged_by, ref_doctype, ref_name, sub_order)]."""
	a, b = _range(f)
	out = []

	def add(doctype, date_f, stage_fields, extra_filter=None, shift_f=None, by_f=None, sub_f=None):
		if not _exists(doctype):
			return
		date_f = _pick(doctype, *date_f) if isinstance(date_f, tuple) else date_f
		if not date_f:
			return
		present = [(fld, stage, wtype) for fld, stage, wtype in stage_fields if IC.has_field(doctype, fld)]
		if not present:
			return
		shift_f = _pick(doctype, *shift_f) if shift_f else None
		by_f = _pick(doctype, *by_f) if by_f else None
		sub_f = _pick(doctype, *sub_f) if sub_f else None
		fields = ["name", "owner", "modified", date_f] + [p[0] for p in present] + \
			[x for x in (shift_f, by_f, sub_f) if x]
		filters = {"docstatus": 1, date_f: ("between", [a, b])}
		filters.update(extra_filter or {})
		if f.get("sub_order") and sub_f:
			filters[sub_f] = f.sub_order
		for r in frappe.get_all(doctype, filters=filters, fields=list(dict.fromkeys(fields)),
		                        limit_page_length=10000):
			shift = (r.get(shift_f) if shift_f else "") or ""
			for fld, stage, wtype in present:
				if flt(r.get(fld)) <= 0:
					continue
				out.append({"date": r.get(date_f), "shift": shift, "stage": stage, "waste_type": wtype,
				            "qty_kg": flt(r.get(fld), 3),
				            "logged_by": get_fullname((r.get(by_f) if by_f else None) or r.owner),
				            "ref_doctype": doctype, "ref_name": r.name,
				            "sub_order": r.get(sub_f) if sub_f else None})

	add("Process Inward", ("posting_date",),
	    [("mixing_wastage_kg", "Mixing", "RM"), ("baking_wastage_kg", "Baking", "Baked")],
	    shift_f=("shift",), by_f=("submitted_by",), sub_f=("sub_order",))
	add("Production QC", ("inspection_date", "posting_date"),
	    [("rejected_kg", "Baking", "Baked (QC Rejected)")], sub_f=("sub_order",), by_f=("inspector",))
	add("Filling Inward", ("posting_date", "inward_date", "date"),
	    [("filling_wastage_kg", "Filling", "Baked"), ("wastage_kg", "Filling", "Baked"),
	     ("pm_wastage_pcs", "Filling", "PM")],
	    shift_f=("shift",), by_f=("operator", "submitted_by"), sub_f=("sub_order", "work_order"))
	if f.get("shift"):
		out = [r for r in out if r["shift"] == f.shift]
	out.sort(key=lambda r: (str(r["date"] or ""), r["stage"]), reverse=True)
	return out


def report_loss(f):
	columns = [
		col("date", "Date", "Date", width=95), col("shift", "Shift", width=80), col("stage", "Stage", width=90),
		col("waste_type", "Waste Type", width=140), col("qty_kg", "Waste Qty (KG)", "Float", width=110),
		col("logged_by", "Logged By", width=140), col("sub_order", "Sub PO", "Link", WO, 110),
		col("ref_name", "Document", "Dynamic Link", "ref_doctype", 140), col("ref_doctype", "Document Type", width=120),
	]
	return columns, _loss_rows(f)


def summary_data(f):
	"""Rows by (date, shift): RM consumed, FG produced, yield, downtime, wastage."""
	a, b = _range(f)
	groups = {}

	def g(date, shift):
		key = (str(getdate(date)), shift or "")
		return groups.setdefault(key, {"date": getdate(date), "shift": shift or "", "rm_kg": 0.0, "fg_pcs": 0.0,
		                               "fg_kg": 0.0, "baked_kg": 0.0, "downtime_min": 0.0, "wastage_kg": 0.0})

	rows = frappe.db.sql(
		"""select se.posting_date, se.posting_time, se.purpose, sed.item_code, sed.transfer_qty as qty,
		          ifnull(sed.s_warehouse, '') as s_wh, ifnull(sed.t_warehouse, '') as t_wh
		   from `tabStock Entry Detail` sed join `tabStock Entry` se on se.name = sed.parent
		   where se.docstatus = 1 and se.purpose in ('Manufacture', 'Repack')
		     and se.posting_date between %(a)s and %(b)s""", {"a": a, "b": b}, as_dict=True)
	info = IC.item_meta([r.item_code for r in rows])
	for r in rows:
		meta = info.get(r.item_code) or frappe._dict()
		shift = shift_of(r.posting_time)
		bucket = g(r.posting_date, shift)
		if r.s_wh and meta.get("material_type") in ("RM", "Additive"):
			bucket["rm_kg"] += IC.qty_in_kg(r.qty, meta)
		if r.t_wh and r.purpose == "Repack" and meta.get("material_type") == "FG":
			bucket["fg_pcs"] += flt(r.qty)
			bucket["fg_kg"] += IC.qty_in_kg(r.qty, meta)
		if r.t_wh and r.purpose == "Manufacture":
			bucket["baked_kg"] += IC.qty_in_kg(r.qty, meta)
	if _exists("Production Run") and IC.has_field("Production Run", "downtime_minutes"):
		for r in frappe.get_all("Production Run",
		                        filters={"started_on": ("between", [f"{a} 00:00:00", f"{b} 23:59:59"])},
		                        fields=["started_on", "downtime_minutes"], limit_page_length=0):
			if not r.started_on:
				continue
			g(r.started_on, shift_of(_time_of(r.started_on)))["downtime_min"] += flt(r.downtime_minutes)
	for r in _loss_rows(frappe._dict(from_date=a, to_date=b)):
		if r["date"]:
			g(r["date"], r["shift"])["wastage_kg"] += flt(r["qty_kg"])
	out = []
	for key in sorted(groups):
		x = groups[key]
		if f.get("shift") and x["shift"] != f.shift:
			continue
		x["yield_pct"] = flt(x["fg_kg"] / x["rm_kg"] * 100, 2) if x["rm_kg"] else None
		for k in ("rm_kg", "fg_kg", "baked_kg", "wastage_kg", "fg_pcs", "downtime_min"):
			x[k] = flt(x[k], 3)
		out.append(x)
	return out


def report_production_summary(f):
	columns = [
		col("date", "Date", "Date", width=95), col("shift", "Shift", width=90),
		col("rm_kg", "Total RM Consumed (KG)", "Float", width=140),
		col("baked_kg", "Baked Output (KG)", "Float", width=120),
		col("fg_pcs", "Total FG Produced (Pcs)", "Float", width=140),
		col("fg_kg", "Total FG Produced (KG)", "Float", width=140),
		col("yield_pct", "Overall Factory Yield %", "Percent", width=130),
		col("downtime_min", "Total Downtime (Min)", "Float", width=120),
		col("wastage_kg", "Total Wastage (KG)", "Float", width=120),
	]
	return columns, summary_data(f)


# ============================================================ 5.6 Audit Trail

AUDIT_DOCTYPES = ("Production Order", "Work Order", "Stock Entry", "Production QC", "Final QC",
                  "Inventory Adjustment", "Production Transfer", "Delivery Note", "Process Inward",
                  "Filling Inward", "Production Run")


def _version_text(data):
	try:
		d = json.loads(data or "{}")
	except Exception:
		return ""
	parts = []
	for fld, old, new in (d.get("changed") or [])[:6]:
		parts.append(f"{fld}: {old} -> {new}")
	if d.get("added"):
		parts.append(_("{0} row(s) added").format(len(d["added"])))
	if d.get("removed"):
		parts.append(_("{0} row(s) removed").format(len(d["removed"])))
	if d.get("row_changed"):
		parts.append(_("{0} row(s) changed").format(len(d["row_changed"])))
	return "; ".join(str(p) for p in parts)


def report_audit_trail(f):
	columns = [
		col("at", "When", "Datetime", width=150), col("user", "Who", width=150),
		col("ref_doctype", "Document Type", width=130), col("ref_name", "Document", "Dynamic Link", "ref_doctype", 150),
		col("action", "Action", width=120), col("details", "What", width=380),
	]
	a, b = _range(f)
	doctypes = [d for d in AUDIT_DOCTYPES if _exists(d)]
	if f.get("status") and f.status in doctypes:
		doctypes = [f.status]
	if not doctypes:
		return columns, []
	values = {"dts": tuple(doctypes), "a": f"{a} 00:00:00", "b": f"{b} 23:59:59"}
	name_cond = ""
	if f.get("sub_order") or f.get("parent_po"):
		values["nm"] = f.get("sub_order") or f.get("parent_po")
		name_cond = " and {ref} = %(nm)s"
	comments = frappe.db.sql(
		"""select creation as at, owner as user, reference_doctype as ref_doctype,
		          reference_name as ref_name, comment_type as action, content as details
		   from `tabComment`
		   where reference_doctype in %(dts)s and creation between %(a)s and %(b)s
		     and comment_type in ('Info', 'Workflow', 'Comment', 'Cancelled', 'Submitted', 'Edit')"""
		+ name_cond.format(ref="reference_name") + " order by creation desc limit 2000", values, as_dict=True)
	versions = frappe.db.sql(
		"""select creation as at, owner as user, ref_doctype, docname as ref_name, data
		   from `tabVersion`
		   where ref_doctype in %(dts)s and creation between %(a)s and %(b)s"""
		+ name_cond.format(ref="docname") + " order by creation desc limit 2000", values, as_dict=True)
	rows = []
	for c in comments:
		c["details"] = frappe.utils.strip_html(c.details or "")[:500]
		c["user"] = get_fullname(c.user)
		rows.append(c)
	for v in versions:
		text = _version_text(v.pop("data", None))
		if not text:
			continue
		rows.append({"at": v.at, "user": get_fullname(v.user), "ref_doctype": v.ref_doctype,
		             "ref_name": v.ref_name, "action": "Changed", "details": text})
	# Work Order: only Sub POs; Stock Entry: only production store documents.
	sub_names = set()
	se_names = set()
	wo_refs = [r["ref_name"] for r in rows if r["ref_doctype"] == WO]
	if wo_refs:
		sub_names = set(frappe.get_all(WO, filters={"name": ("in", wo_refs), PARENT_FIELD: ("is", "set")},
		                               pluck="name"))
	se_refs = [r["ref_name"] for r in rows if r["ref_doctype"] == "Stock Entry"]
	if se_refs and IC.has_field("Stock Entry", "custom_entry_kind"):
		se_names = set(frappe.get_all("Stock Entry", filters={"name": ("in", se_refs),
		                                                      "custom_entry_kind": ("is", "set")},
		                              pluck="name"))
	rows = [r for r in rows if (r["ref_doctype"] != WO or r["ref_name"] in sub_names)
	        and (r["ref_doctype"] != "Stock Entry" or r["ref_name"] in se_names)]
	rows.sort(key=lambda r: str(r["at"]), reverse=True)
	return columns, rows[:2000]


# =================================================================== registry

REPORTS = {
	# key: (label, group, filters, function)
	"parent_po": ("Parent PO Report", "Order & Planning", ("from_date", "to_date", "parent_po", "sku", "status"), report_parent_po),
	"sub_po": ("Sub-PO Report", "Order & Planning", ("from_date", "to_date", "parent_po", "sub_order", "sku", "line", "status"), report_sub_po),
	"split_history": ("Split History Report", "Order & Planning", ("parent_po", "sub_order", "sku"), report_split_history),
	"production_order": ("Production Order Report (Filling)", "Order & Planning", ("from_date", "to_date", "sub_order", "sku", "line", "status"), report_production_order),
	"weekly_planning": ("Weekly Planning Report", "Order & Planning", ("from_date", "to_date", "parent_po", "sku", "line", "status"), report_weekly_planning),
	"material_availability": ("Material Availability", "Material & Inventory", ("sku",), report_material_availability),
	"material_consumption": ("Material Consumption", "Material & Inventory", ("from_date", "to_date", "parent_po", "sub_order", "sku", "batch", "shift"), report_material_consumption),
	"rm_consumption": ("RM Consumption", "Material & Inventory", ("from_date", "to_date", "parent_po", "sub_order", "sku", "batch", "shift"), report_rm_consumption),
	"additive_consumption": ("Additive Consumption", "Material & Inventory", ("from_date", "to_date", "parent_po", "sub_order", "sku", "batch", "shift"), report_additive_consumption),
	"pm_consumption": ("PM Consumption", "Material & Inventory", ("from_date", "to_date", "parent_po", "sub_order", "sku", "batch", "shift"), report_pm_consumption),
	"wip_aging": ("Production Stock (WIP Aging)", "Material & Inventory", ("parent_po", "sub_order", "sku"), report_wip_aging),
	"category_stock": ("Category Wise Stock", "Material & Inventory", (), report_category_stock),
	"yield": ("Yield Report", "Performance & Quality", ("from_date", "to_date", "parent_po", "sku"), report_yield),
	"loss": ("Loss Report", "Performance & Quality", ("from_date", "to_date", "sub_order", "shift"), report_loss),
	"production_summary": ("Production Summary", "Performance & Quality", ("from_date", "to_date", "shift"), report_production_summary),
	"audit_trail": ("Audit Trail", "Audit (5.6)", ("from_date", "to_date", "parent_po", "sub_order", "status"), report_audit_trail),
}


@frappe.whitelist()
def get_report_index():
	_assert_access()
	return {
		"reports": [{"key": k, "label": _(v[0]), "group": _(v[1]), "filters": list(v[2])} for k, v in REPORTS.items()],
		"audit_doctypes": [d for d in AUDIT_DOCTYPES if _exists(d)],
		"shifts": __import__("alpinos.production.shifts", fromlist=["shift_names"]).shift_names(),
		"statuses": {
			"parent_po": ["Draft", "Active", "Closed", "Cancelled"],
			"sub_po": _execution_statuses(),
			"weekly_planning": _execution_statuses(),
			"production_order": ["Draft", "Submitted"],
		},
	}


def _execution_statuses():
	try:
		from alpinos.production.work_order_fields import EXECUTION_STATUSES
		return list(EXECUTION_STATUSES)
	except Exception:
		return []


@frappe.whitelist()
def run_report(report, filters=None):
	_assert_access()
	if report not in REPORTS:
		frappe.throw(_("Unknown report {0}.").format(report), title=_("Unknown Report"))
	f = IC.parse(filters)
	f = frappe._dict({k: v for k, v in f.items() if k in ALL_FILTERS and v not in (None, "")})
	label, _group, _filters, fn = REPORTS[report]
	columns, rows = fn(f)
	totals = {}
	for c in columns:
		if c["fieldtype"] in ("Float", "Int", "Currency") and c["fieldname"] not in ("split_no", "aging_days", "target_pcs") \
				and report not in ("material_availability",):
			totals[c["fieldname"]] = flt(sum(flt(r.get(c["fieldname"])) for r in rows), 3)
	return {"report": report, "label": _(label), "columns": columns, "rows": rows, "totals": totals,
	        "count": len(rows)}


@frappe.whitelist()
def production_summary_html(filters=None):
	"""The end-of-day "Production Summary" print (14), rendered from the report data with the
	Print Format "Production Summary" template (editable in the desk)."""
	_assert_access()
	f = IC.parse(filters)
	rows = summary_data(frappe._dict({k: v for k, v in f.items() if k in ALL_FILTERS and v}))
	a, b = _range(frappe._dict(f))
	totals = {k: flt(sum(flt(r.get(k)) for r in rows), 3)
	          for k in ("rm_kg", "baked_kg", "fg_pcs", "fg_kg", "downtime_min", "wastage_kg")}
	totals["yield_pct"] = flt(totals["fg_kg"] / totals["rm_kg"] * 100, 2) if totals["rm_kg"] else None
	from alpinos.production.inventory_setup import SUMMARY_PF_NAME, summary_template
	template = frappe.db.get_value("Print Format", SUMMARY_PF_NAME, "html") or summary_template()
	company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
		"Global Defaults", "default_company")
	return frappe.render_template(template, {
		"rows": rows, "totals": totals, "from_date": a, "to_date": b, "shift": f.get("shift") or "",
		"company": company, "printed_by": get_fullname(), "printed_on": frappe.utils.now_datetime(),
		"doc": frappe._dict(),
	})
