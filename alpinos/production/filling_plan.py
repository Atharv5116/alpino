"""Filling Line Planning -- FRD Phase 6 (6.1, 6.2, 6.4.3 Re-Route, 6.6 Calendar).

A Filling Plan puts QC-approved baked WIP of one Sub PO onto one filling line, split into
rows by target SKU (pack size). It reserves, for every open row, `pending pcs x pack size`
KG of the Sub PO's WIP (Work Order.custom_wip_qty), so two plans can never promise the same
kilos twice.

Plans are created and changed only through this module (the Filling Planning screen); the
desk form is read-only by rule, like a Sub PO.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from alpinos.production import constants as C
from alpinos.production import filling_common as F


# ------------------------------------------------------------------ reservations

def reserved_kg(sub_order, exclude_plan=None):
	"""KG of this Sub PO's WIP promised to open plan rows (pending pcs x size)."""
	if not sub_order or not frappe.db.exists("DocType", F.PLAN):
		return 0.0
	params = {"sub": sub_order, "open": F.PLAN_OPEN_STATUSES, "row_open": F.ROW_OPEN,
	          "exclude": exclude_plan or ""}
	value = frappe.db.sql(
		"""
		select coalesce(sum(r.pending_pcs * r.size_kg), 0)
		from `tabFilling Plan Row` r
		join `tabFilling Plan` p on p.name = r.parent
		where p.sub_order = %(sub)s and p.status in %(open)s and r.row_status = %(row_open)s
		  and p.name != %(exclude)s
		""", params)
	return flt(value[0][0]) if value else 0.0


def available_wip(sub_order, exclude_plan=None):
	sub = F.sub_info(sub_order)
	if not sub:
		return 0.0
	return max(flt(sub.wip_qty) - reserved_kg(sub_order, exclude_plan), 0.0)


def parent_available(parent_po):
	"""FRD 6.1: with only the Parent PO chosen, the total for the PO."""
	if not parent_po or not F.has_field(F.WORK_ORDER, F.WIP_QTY_FIELD):
		return 0.0
	subs = frappe.get_all(F.WORK_ORDER, filters={F.PARENT_FIELD: parent_po, "docstatus": ("<", 2),
	                                             F.WIP_QTY_FIELD: (">", 0)}, pluck="name")
	return sum(available_wip(s) for s in subs)


# -------------------------------------------------------------------- validation

def _line(machine):
	row = frappe.db.get_value("Machine", machine, ["name", "machine_name", "status",
	                                               "filling_process_category"], as_dict=True)
	if not row:
		frappe.throw(_("Filling Line {0} does not exist.").format(machine), title=_("Unknown Line"))
	if row.status not in C.MACHINE_ASSIGNABLE_STATUSES:
		frappe.throw(_("Filling Line {0} is {1}. Only Active machines can be planned.").format(
			row.machine_name or machine, row.status), title=_("Machine Not Active"))
	if not row.filling_process_category:
		frappe.throw(_("{0} has no Filling Process Category, so it is not a filling line.").format(
			row.machine_name or machine), title=_("Not A Filling Line"))
	return row


def _check_sku(sku, machine):
	if not sku:
		frappe.throw(_("Choose the Target SKU on every row."), title=_("Target SKU Required"))
	if F.has_field("Item", "custom_material_type"):
		mtype = frappe.db.get_value("Item", sku, "custom_material_type")
		if mtype and mtype != C.MATERIAL_FG:
			frappe.throw(_("{0} is not an FG item and cannot be a filling target.").format(sku),
			             title=_("Not An FG Item"))
	size = F.pack_size(sku)
	if size <= 0:
		frappe.throw(_("Set the Pack Size (KG) on {0} in Item Master before planning it.").format(
			frappe.bold(sku)), title=_("Pack Size Missing"))
	from alpinos.production.filling import check_compatibility, MISMATCH_MESSAGE
	verdict = check_compatibility(machine, sku)
	if not verdict.get("ok"):
		frappe.throw(verdict.get("reason") or _(MISMATCH_MESSAGE), title=_("Machine and SKU Do Not Match"))
	return size


def row_pending(row):
	if row.row_status == F.ROW_CLOSED:
		return 0
	return max(cint(row.planned_pcs) - cint(row.completed_pcs) - cint(row.written_off_pcs)
	           - cint(row.rerouted_pcs), 0)


def compute_status(doc):
	"""Planned / In Progress / Completed / Short-Closed. Re-Routed is set by reroute only."""
	if doc.status == F.PLAN_REROUTED:
		return F.PLAN_REROUTED
	rows = doc.get("rows") or []
	if rows and all(r.row_status == F.ROW_CLOSED for r in rows):
		return F.PLAN_SHORT_CLOSED if any(cint(r.written_off_pcs) for r in rows) else F.PLAN_COMPLETED
	if any(cint(r.completed_pcs) or flt(r.consumed_kg) for r in rows):
		return F.PLAN_IN_PROGRESS
	return F.PLAN_PLANNED


def validate_plan(doc):
	"""Called from the Filling Plan controller."""
	if not doc.flags.get("alpinos_filling"):
		frappe.throw(_("Filling Plans are created and changed on the Filling Planning screen."),
		             title=_("Use The Filling Planning Screen"))
	rerouting = bool(doc.flags.get("alpinos_reroute"))
	counters_only = bool(doc.flags.get("alpinos_counters"))

	if not doc.parent_po:
		frappe.throw(_("Please choose the Parent PO."), title=_("Parent PO Required"))
	if not doc.sub_order:
		# default pending BA confirmation: a plan needs one Sub-PO (Batch); the PO total is
		# shown on screen only, since stock is consumed per Sub PO.
		frappe.throw(_("Please choose the Sub-PO (Batch) to fill."), title=_("Sub-PO Required"))
	sub = F.sub_info(doc.sub_order)
	if not sub or sub.get(F.PARENT_FIELD) != doc.parent_po:
		frappe.throw(_("{0} is not a Sub-PO of {1}.").format(doc.sub_order, doc.parent_po),
		             title=_("Wrong Sub-PO"))
	if cint(sub.docstatus) == 2:
		frappe.throw(_("{0} is cancelled.").format(doc.sub_order), title=_("Sub-PO Cancelled"))
	doc.bulk_item = sub.production_item

	if not doc.plan_date:
		frappe.throw(_("Please enter the Date."), title=_("Date Required"))
	if doc.is_new() and not rerouting and getdate(doc.plan_date) < getdate(nowdate()):
		frappe.throw(_("The plan date cannot be in the past."), title=_("Invalid Date"))

	before = None if doc.is_new() else doc.get_doc_before_save()
	if before and not counters_only:
		if before.status not in F.PLAN_OPEN_STATUSES:
			frappe.throw(_("{0} is {1} and can no longer be changed.").format(doc.name, before.status),
			             title=_("Plan Closed"))
		if before.filling_line != doc.filling_line and before.status != F.PLAN_PLANNED:
			frappe.throw(_("Filling has started on this plan. Use Re-Route Pending to move the "
			               "pending pieces to another line."), title=_("Line Cannot Change"))
		if before.sub_order != doc.sub_order and before.status != F.PLAN_PLANNED:
			frappe.throw(_("Filling has started on this plan, so its Sub-PO cannot change."),
			             title=_("Sub-PO Cannot Change"))

	line = _line(doc.filling_line) if not counters_only else frappe._dict(
		filling_process_category=frappe.db.get_value("Machine", doc.filling_line, "filling_process_category"))
	doc.line_category = line.filling_process_category

	rows = doc.get("rows") or []
	if not rows:
		frappe.throw(_("Add at least one Target SKU row."), title=_("No Rows"))

	old_rows = {r.name: r for r in (before.get("rows") or [])} if before else {}
	kept = {r.name for r in rows if r.name in old_rows}
	for name, old in old_rows.items():
		if name not in kept and (cint(old.completed_pcs) or flt(old.consumed_kg)):
			frappe.throw(_("Row {0} ({1}) already has filling recorded and cannot be removed.").format(
				old.idx, old.target_sku), title=_("Row In Use"))

	for row in rows:
		old = old_rows.get(row.name)
		if old and (cint(old.completed_pcs) or flt(old.consumed_kg)) and old.target_sku != row.target_sku:
			frappe.throw(_("Row {0} already has filling recorded; its SKU cannot change.").format(row.idx),
			             title=_("Row In Use"))
		if not counters_only:
			row.size_kg = _check_sku(row.target_sku, doc.filling_line)
		else:
			row.size_kg = flt(row.size_kg) or F.pack_size(row.target_sku)
		row.sku_name = F.sku_name(row.target_sku)
		if cint(row.planned_pcs) <= 0:
			frappe.throw(_("Row {0}: Planned Qty (Pcs) must be greater than zero.").format(row.idx),
			             title=_("Invalid Quantity"))
		row.planned_pcs = cint(row.planned_pcs)
		done = cint(row.completed_pcs) + cint(row.written_off_pcs) + cint(row.rerouted_pcs)
		if row.planned_pcs < done and row.row_status != F.ROW_CLOSED:
			frappe.throw(_("Row {0}: Planned Qty cannot be less than what is already filled ({1}).").format(
				row.idx, done), title=_("Invalid Quantity"))
		if not row.row_status:
			row.row_status = F.ROW_OPEN
		row.equivalent_kg = flt(row.planned_pcs * flt(row.size_kg), 3)
		row.pending_pcs = row_pending(row)
		packs = F.available_pm_packs(row.target_sku)
		row.available_pm_stock = packs if packs is not None else 0

	if not counters_only:
		_check_capacity(doc, rows)
		_check_pm(rows)

	doc.total_planned_pcs = sum(cint(r.planned_pcs) for r in rows)
	doc.total_planned_kg = flt(sum(flt(r.equivalent_kg) for r in rows), 3)
	doc.total_completed_pcs = sum(cint(r.completed_pcs) for r in rows)
	doc.total_pending_pcs = sum(cint(r.pending_pcs) for r in rows)
	doc.total_wastage_kg = flt(sum(flt(r.wastage_kg) for r in rows), 3)
	doc.available_wip_kg = flt(available_wip(doc.sub_order, exclude_plan=doc.name if not doc.is_new() else None), 3)
	doc.status = compute_status(doc)


def _check_capacity(doc, rows):
	"""FRD 6.1 WIP lock: what the open rows still need may not exceed the Available WIP."""
	need = flt(sum(cint(r.pending_pcs) * flt(r.size_kg) for r in rows), 3)
	avail = flt(available_wip(doc.sub_order, exclude_plan=None if doc.is_new() else doc.name), 3)
	if need > avail + F.EPS:
		frappe.throw(
			_("The plan needs {0} KG but only {1} KG of approved baked WIP is available for {2}.").format(
				need, avail, doc.sub_order), title=_("Exceeds Available WIP"))


def _check_pm(rows):
	"""FRD 6.2 Edge Case 3 (PM blind spot): Planned Qty may not exceed Available PM Stock."""
	need = {}
	no_bom = []
	for row in rows:
		if row.row_status == F.ROW_CLOSED or not cint(row.pending_pcs):
			continue
		per = F.pm_per_pack(row.target_sku)
		if per is None:
			no_bom.append(row.target_sku)
			continue
		for item, q in per.items():
			need[item] = need.get(item, 0) + q * cint(row.pending_pcs)
	short = []
	for item, qty in need.items():
		have = F.pm_stock(item)
		if qty > have + F.EPS:
			short.append(_("{0}: needs {1}, stock {2}").format(item, flt(qty, 3), flt(have, 3)))
	if short:
		frappe.throw(_("Planned Qty exceeds the Available PM Stock.") + "<br>" + "<br>".join(short),
		             title=_("Not Enough Packing Material"))
	if no_bom:
		frappe.msgprint(
			_("No active BOM for {0}, so its packing material could not be checked.").format(
				", ".join(sorted(set(no_bom)))), indicator="orange", alert=True)


# ------------------------------------------------------------------------ screens

LIST_FIELDS = ["name", "plan_date", "parent_po", "sub_order", "filling_line", "status",
               "total_planned_pcs", "total_completed_pcs", "total_pending_pcs", "total_planned_kg",
               "has_pending_approval", "rerouted_from", "rerouted_to"]


@frappe.whitelist()
def get_plan_list(search=None, status=None, parent_po=None, sub_order=None, filling_line=None,
                  date_from=None, date_to=None, start=0, page_length=50):
	F.require(F.FILLING_READ_ROLES, _("view Filling Plans"))
	filters = {}
	if status:
		filters["status"] = status
	if parent_po:
		filters["parent_po"] = parent_po
	if sub_order:
		filters["sub_order"] = sub_order
	if filling_line:
		filters["filling_line"] = filling_line
	if date_from and date_to:
		filters["plan_date"] = ("between", [date_from, date_to])
	elif date_from:
		filters["plan_date"] = (">=", date_from)
	elif date_to:
		filters["plan_date"] = ("<=", date_to)
	or_filters = None
	if search:
		like = f"%{search}%"
		or_filters = {"name": ("like", like), "sub_order": ("like", like), "parent_po": ("like", like)}
	start, page_length = max(cint(start), 0), min(max(cint(page_length) or 50, 1), 200)
	total = frappe.db.count(F.PLAN, filters) if not or_filters else len(
		frappe.get_all(F.PLAN, filters=filters, or_filters=or_filters, pluck="name"))
	rows = frappe.get_all(F.PLAN, filters=filters, or_filters=or_filters, fields=LIST_FIELDS,
	                      order_by="plan_date desc, name desc", limit_start=start,
	                      limit_page_length=page_length + 1)
	has_more = len(rows) > page_length
	rows = rows[:page_length]
	names = [r.name for r in rows]
	skus = {}
	if names:
		for r in frappe.get_all(F.PLAN_ROW, filters={"parent": ("in", names), "parenttype": F.PLAN},
		                        fields=["parent", "target_sku"], order_by="idx asc"):
			skus.setdefault(r.parent, []).append(r.target_sku)
	lines = _line_labels([r.filling_line for r in rows])
	for r in rows:
		r["skus"] = ", ".join(skus.get(r.name, []))
		r["line_label"] = lines.get(r.filling_line) or r.filling_line
	return {"data": rows, "total": total, "start": start, "page_length": page_length,
	        "has_more": int(has_more), "statuses": list(F.PLAN_STATUSES),
	        "can_create": int(F.has_any(F.PLANNER_ROLES))}


def _line_labels(machines):
	machines = [m for m in set(machines or []) if m]
	if not machines:
		return {}
	return dict(frappe.get_all("Machine", filters={"name": ("in", machines)},
	                           fields=["name", "machine_name"], as_list=True))


@frappe.whitelist()
def get_plan_context(plan=None):
	F.require(F.FILLING_READ_ROLES, _("view Filling Plans"))
	can_plan = F.has_any(F.PLANNER_ROLES)
	if not plan:
		return {"doc": None, "can_write": int(can_plan), "statuses": list(F.PLAN_STATUSES)}
	doc = frappe.get_doc(F.PLAN, plan)
	data = doc.as_dict()
	data["line_label"] = frappe.db.get_value("Machine", doc.filling_line, "machine_name")
	data["parent_available_kg"] = flt(parent_available(doc.parent_po), 3)
	inwards = frappe.get_all(F.INWARD, filters={"filling_plan": plan, "docstatus": ("<", 2)},
	                         fields=["name", "posting_date", "target_sku", "input_pcs", "filled_kg",
	                                 "wastage_kg", "process_loss_kg", "process_loss_pct",
	                                 "submission_type", "fg_batch", "approval_status", "docstatus"],
	                         order_by="creation asc")
	open_plan = doc.status in F.PLAN_OPEN_STATUSES
	return {
		"doc": data,
		"inwards": inwards,
		"can_write": int(can_plan and open_plan),
		"can_reroute": int(bool(can_plan and open_plan)),
		"can_delete": int(can_plan and doc.status == F.PLAN_PLANNED and not inwards),
		"statuses": list(F.PLAN_STATUSES),
	}


@frappe.whitelist()
def get_wip_info(parent_po=None, sub_order=None, plan=None):
	"""Available WIP (KG) for the header (FRD 6.1 WIP lock)."""
	F.require(F.FILLING_READ_ROLES, _("view Filling Plans"))
	out = {"parent_available_kg": flt(parent_available(parent_po), 3) if parent_po else 0}
	if sub_order:
		sub = F.sub_info(sub_order) or {}
		out.update({
			"available_wip_kg": flt(available_wip(sub_order, exclude_plan=plan), 3),
			"wip_qty": flt(sub.get("wip_qty"), 3),
			"bulk_item": sub.get("production_item"),
			"batch_number": sub.get(F.BATCH_FIELD),
		})
	return out


@frappe.whitelist()
def get_sku_info(sku, filling_line=None):
	F.require(F.FILLING_READ_ROLES, _("view Filling Plans"))
	out = {"size_kg": F.pack_size(sku), "sku_name": F.sku_name(sku)}
	packs = F.available_pm_packs(sku)
	out["available_pm_stock"] = packs if packs is not None else 0
	out["pm_checked"] = int(packs is not None)
	if filling_line:
		from alpinos.production.filling import check_compatibility
		verdict = check_compatibility(filling_line, sku)
		out["compatible"] = int(bool(verdict.get("ok")))
		out["reason"] = verdict.get("reason")
	return out


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def sub_order_query(doctype, txt, searchfield, start, page_len, filters):
	"""Sub-POs of the Parent with QC-approved baked WIP (custom_wip_qty > 0)."""
	parent = (filters or {}).get("parent_po")
	if not parent or not F.has_field(F.WORK_ORDER, F.WIP_QTY_FIELD):
		return []
	return frappe.db.sql(
		f"""
		select name, {F.BATCH_FIELD}, {F.WIP_QTY_FIELD}
		from `tabWork Order`
		where {F.PARENT_FIELD} = %(parent)s and docstatus < 2 and {F.WIP_QTY_FIELD} > 0
		  and name like %(txt)s
		order by name asc limit %(start)s, %(page_len)s
		""", {"parent": parent, "txt": f"%{txt or ''}%", "start": cint(start),
		      "page_len": cint(page_len) or 20})


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def parent_query(doctype, txt, searchfield, start, page_len, filters):
	"""Parent POs that have at least one Sub PO with approved baked WIP."""
	if not F.has_field(F.WORK_ORDER, F.WIP_QTY_FIELD):
		return []
	return frappe.db.sql(
		f"""
		select distinct {F.PARENT_FIELD}
		from `tabWork Order`
		where {F.PARENT_FIELD} is not null and {F.PARENT_FIELD} like %(txt)s and docstatus < 2
		  and {F.WIP_QTY_FIELD} > 0
		order by {F.PARENT_FIELD} desc limit %(start)s, %(page_len)s
		""", {"txt": f"%{txt or ''}%", "start": cint(start), "page_len": cint(page_len) or 20})


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def line_query(doctype, txt, searchfield, start, page_len, filters):
	"""Active filling machines (with a Filling Process Category), FRD 8.4.4."""
	exclude = (filters or {}).get("exclude") or ""
	return frappe.db.sql(
		"""
		select name, machine_name, filling_process_category
		from `tabMachine`
		where status = %(active)s and ifnull(filling_process_category, '') != ''
		  and name != %(exclude)s and (name like %(txt)s or machine_name like %(txt)s)
		order by machine_name asc limit %(start)s, %(page_len)s
		""", {"active": C.MACHINE_ACTIVE, "exclude": exclude, "txt": f"%{txt or ''}%",
		      "start": cint(start), "page_len": cint(page_len) or 20})


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def sku_query(doctype, txt, searchfield, start, page_len, filters):
	"""FG items with a pack size; narrowed to the line's category when a line is given."""
	if not F.has_field("Item", F.PACK_SIZE_FIELD):
		return []
	line = (filters or {}).get("filling_line")
	cond, params = "", {"txt": f"%{txt or ''}%", "start": cint(start), "page_len": cint(page_len) or 20}
	if line:
		cat = frappe.db.get_value("Machine", line, "filling_process_category")
		if cat:
			cond = """ and exists (select 1 from `tabItem Filling Category` c where c.parent = i.name
			           and c.parenttype = 'Item' and c.filling_process_category = %(cat)s)"""
			params["cat"] = cat
	if F.has_field("Item", "custom_material_type"):
		cond += " and ifnull(i.custom_material_type, '') in ('', 'FG')"
	return frappe.db.sql(
		f"""
		select i.name, i.item_name, i.{F.PACK_SIZE_FIELD}
		from `tabItem` i
		where i.disabled = 0 and ifnull(i.{F.PACK_SIZE_FIELD}, 0) > 0
		  and (i.name like %(txt)s or i.item_name like %(txt)s) {cond}
		order by i.item_name asc limit %(start)s, %(page_len)s
		""", params)


@frappe.whitelist()
def save_plan(payload):
	F.require(F.PLANNER_ROLES, _("create or change Filling Plans"))
	p = F.parse(payload)
	if p.get("name"):
		doc = frappe.get_doc(F.PLAN, p.name)
	else:
		doc = frappe.new_doc(F.PLAN)
		doc.status = F.PLAN_PLANNED
	for field in ("plan_date", "parent_po", "sub_order", "filling_line", "remarks"):
		if field in p:
			doc.set(field, p.get(field))
	old = {r.name: r for r in (doc.get("rows") or [])}
	counters = ("completed_pcs", "written_off_pcs", "rerouted_pcs", "consumed_kg", "filled_kg",
	            "wastage_kg", "row_status")
	new_rows = []
	for r in (p.get("rows") or []):
		r = frappe._dict(r)
		if not r.get("target_sku") and not cint(r.get("planned_pcs")):
			continue
		row = {"target_sku": r.target_sku, "planned_pcs": cint(r.planned_pcs)}
		prev = old.get(r.get("name")) if r.get("name") else None
		if prev:
			row["name"] = prev.name
			for c in counters:
				row[c] = prev.get(c)
		new_rows.append(row)
	doc.set("rows", [])
	for row in new_rows:
		doc.append("rows", row)
	doc.flags.alpinos_filling = True
	doc.save(ignore_permissions=True)
	F.audit(F.PLAN, doc.name, "Plan Saved",
	        _("{0} pcs / {1} KG on {2}").format(doc.total_planned_pcs, doc.total_planned_kg, doc.filling_line))
	frappe.db.commit()
	return {"name": doc.name}


@frappe.whitelist()
def delete_plan(plan):
	F.require(F.PLANNER_ROLES, _("delete Filling Plans"))
	doc = frappe.get_doc(F.PLAN, plan)
	if doc.status != F.PLAN_PLANNED or frappe.get_all(F.INWARD, filters={"filling_plan": plan}, limit=1):
		frappe.throw(_("Only a plan with no filling recorded can be deleted."), title=_("Cannot Delete"))
	doc.flags.alpinos_filling = True
	frappe.delete_doc(F.PLAN, plan, ignore_permissions=True)
	frappe.db.commit()
	return {"deleted": plan}


# ------------------------------------------------------------------ Re-Route (6.4.3)

@frappe.whitelist()
def reroute_plan(plan, filling_line, plan_date=None, reason=None):
	"""Duplicate the plan with the exact Pending (Pcs) on another Active line and close the
	original as Re-Routed."""
	F.require(F.PLANNER_ROLES, _("re-route Filling Plans"))
	orig = frappe.get_doc(F.PLAN, plan)
	if orig.status not in F.PLAN_OPEN_STATUSES:
		frappe.throw(_("{0} is {1}; only an open plan can be re-routed.").format(plan, orig.status),
		             title=_("Cannot Re-Route"))
	if not filling_line or filling_line == orig.filling_line:
		frappe.throw(_("Choose a different Filling Line."), title=_("Line Required"))
	_line(filling_line)
	pending = [r for r in orig.rows if r.row_status == F.ROW_OPEN and row_pending(r) > 0]
	if not pending:
		frappe.throw(_("Nothing is pending on {0}.").format(plan), title=_("Nothing To Re-Route"))
	for r in pending:
		_check_sku(r.target_sku, filling_line)

	# Release the original first so its reservation does not block the new plan.
	moved = {}
	for r in orig.rows:
		if r.row_status == F.ROW_OPEN:
			moved[r.name] = row_pending(r)
			r.rerouted_pcs = cint(r.rerouted_pcs) + moved[r.name]
			r.row_status = F.ROW_CLOSED
			r.pending_pcs = 0
	orig.status = F.PLAN_REROUTED
	orig.flags.alpinos_filling = True
	orig.flags.alpinos_counters = True
	orig.save(ignore_permissions=True)

	new = frappe.new_doc(F.PLAN)
	new.plan_date = plan_date or nowdate()
	new.parent_po = orig.parent_po
	new.sub_order = orig.sub_order
	new.filling_line = filling_line
	new.rerouted_from = orig.name
	new.remarks = _("Re-routed from {0}").format(orig.name) + (f": {reason}" if reason else "")
	new.status = F.PLAN_PLANNED
	for r in pending:
		new.append("rows", {"target_sku": r.target_sku, "planned_pcs": moved[r.name]})
	new.flags.alpinos_filling = True
	new.flags.alpinos_reroute = True
	new.insert(ignore_permissions=True)
	frappe.db.set_value(F.PLAN, orig.name, "rerouted_to", new.name, update_modified=False)
	F.audit(F.PLAN, orig.name, "Re-Routed", _("Pending moved to {0} on {1}").format(new.name, filling_line),
	        reason or "")
	frappe.db.commit()
	return {"new_plan": new.name}


# --------------------------------------------------------------------- Calendar (6.6)

@frappe.whitelist()
def get_calendar(date_from, date_to, filling_line=None, sku=None, status=None):
	F.require(F.FILLING_READ_ROLES, _("view the Filling Calendar"))
	filters = {"plan_date": ("between", [date_from, date_to])}
	if filling_line:
		filters["filling_line"] = filling_line
	if status:
		filters["status"] = status
	plans = frappe.get_all(F.PLAN, filters=filters, fields=LIST_FIELDS + ["total_wastage_kg"],
	                       order_by="plan_date asc, name asc", limit_page_length=1000)
	if not plans:
		return {"plans": []}
	names = [p.name for p in plans]
	rows = {}
	for r in frappe.get_all(F.PLAN_ROW, filters={"parent": ("in", names), "parenttype": F.PLAN},
	                        fields=["parent", "target_sku", "sku_name", "size_kg", "planned_pcs",
	                                "completed_pcs", "pending_pcs", "written_off_pcs", "rerouted_pcs",
	                                "filled_kg", "wastage_kg", "row_status"], order_by="idx asc"):
		rows.setdefault(r.parent, []).append(r)
	loss = {}
	for r in frappe.get_all(F.INWARD, filters={"filling_plan": ("in", names), "docstatus": 1},
	                        fields=["filling_plan", "sum(process_loss_kg) as loss_kg",
	                                "sum(wastage_kg) as wastage_kg"], group_by="filling_plan"):
		loss[r.filling_plan] = r
	lines = _line_labels([p.filling_line for p in plans])
	out = []
	for p in plans:
		p_rows = rows.get(p.name, [])
		if sku and not any(r.target_sku == sku for r in p_rows):
			continue
		p["rows"] = p_rows
		p["line_label"] = lines.get(p.filling_line) or p.filling_line
		p["loss_kg"] = flt((loss.get(p.name) or {}).get("loss_kg"), 3)
		out.append(p)
	return {"plans": out}
