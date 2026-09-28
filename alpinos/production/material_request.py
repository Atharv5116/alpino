"""Material Request (MR) -- tasks 17-20, BR-MR-01..06.

An MR is ERPNext's own Material Request, type "Material Transfer", Main -> WIP, tied to one
Sub PO through custom_sub_production_order. That link is what makes an MR "ours": an MR
raised anywhere else on the site (purchase, reorder, ...) carries no Sub PO and every hook
below leaves it alone.

Two ways in:
    * Auto   -- generate_mr(), from a planned Sub PO. Submits the Sub PO, raises and
                submits the MR, locks the plan and moves the Sub PO to Pending Store Issue.
    * Manual -- the + New screen, for a Sub PO whose Parent is Sent To Store.

Status (custom_mr_status) is derived, never typed:
    Draft -> Pending Issue (submit) -> Partially Issued -> Fully Issued, or Cancelled
    (only from Pending Issue, with nothing issued).
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, get_fullname, getdate, nowdate

from alpinos.production import material_common as MC
from alpinos.production import material_constants as M
from alpinos.production.production_settings import main_warehouse, wip_warehouse
from alpinos.production.work_order_fields import (
	ASSIGNED_PROCESS_FIELD,
	EXECUTION_STATUS_FIELD,
	IS_LOCKED_FIELD,
	MATERIAL_REQUEST_FIELD,
	PARENT_FIELD,
	PLAN_LOCKED_FIELD,
	PLANNED_DATE_FIELD,
	PRODUCTION_TYPE_FIELD,
)

MR = M.MR_DOCTYPE
WORK_ORDER = "Work Order"
SUB_FIELD = "custom_sub_production_order"

LIST_FIELDS = (
	"name", SUB_FIELD, "custom_parent_production_order", "custom_target_fg_item",
	"custom_production_type", "custom_mr_source", "custom_mr_status", "transaction_date",
	"schedule_date", "docstatus", "owner", "company",
)


def is_production_mr(doc):
	return bool(doc.get(SUB_FIELD))


# ======================================================================== status

def compute_status(doc):
	if cint(doc.docstatus) == 2:
		return M.MR_CANCELLED
	if cint(doc.docstatus) == 0:
		return M.MR_DRAFT
	rows = doc.get("items") or []
	issued = sum(flt(r.get("custom_issued_qty")) for r in rows)
	if rows and all(flt(r.get("custom_pending_qty")) <= 0.0000001 for r in rows):
		return M.MR_FULLY_ISSUED
	if issued > 0:
		return M.MR_PARTIALLY_ISSUED
	return M.MR_PENDING_ISSUE


def issued_by_row(mr_name, exclude_entry=None):
	"""{MR row name: qty} issued through SUBMITTED Material Issues against this MR."""
	conditions = ""
	values = {"mr": mr_name, "kind": M.KIND_ISSUE}
	if exclude_entry:
		conditions = "and se.name != %(exclude)s"
		values["exclude"] = exclude_entry
	rows = frappe.db.sql(
		f"""
		select sed.custom_mr_item as mr_item, sum(sed.qty) as qty
		from `tabStock Entry Detail` sed
		join `tabStock Entry` se on se.name = sed.parent
		where se.docstatus = 1 and se.custom_entry_kind = %(kind)s
		  and se.custom_material_request = %(mr)s {conditions}
		group by sed.custom_mr_item
		""", values, as_dict=True)
	return {r.mr_item: flt(r.qty) for r in rows if r.mr_item}


def refresh_issue_status(mr_name):
	"""Recompute every row's Issued / Pending and the MR status from submitted issues.

	Written with db.set_value: the MR is submitted, and this is bookkeeping, not an edit.
	"""
	doc = frappe.get_doc(MR, mr_name)
	issued = issued_by_row(mr_name)
	for row in doc.items:
		done = flt(issued.get(row.name))
		pending = max(flt(row.qty) - done, 0)
		row.custom_issued_qty = done
		row.custom_pending_qty = pending
		frappe.db.set_value("Material Request Item", row.name,
		                    {"custom_issued_qty": done, "custom_pending_qty": pending},
		                    update_modified=False)
	status = compute_status(doc)
	frappe.db.set_value(MR, mr_name, "custom_mr_status", status)
	return status


# ================================================================= building an MR

def _pending_requirements(sub_name):
	"""Sub PO required_items still to be transferred, in the Sub PO's own row order."""
	rows = frappe.get_all(
		"Work Order Item",
		filters={"parent": sub_name, "parenttype": WORK_ORDER},
		fields=["item_code", "item_name", "required_qty", "transferred_qty", "stock_uom"],
		order_by="idx asc")
	out = []
	for row in rows:
		pending = flt(row.required_qty) - flt(row.transferred_qty)
		if row.item_code and pending > 0:
			out.append(frappe._dict(item_code=row.item_code, item_name=row.item_name,
			                        qty=pending, uom=row.stock_uom, required_qty=flt(row.required_qty)))
	return out


def _suggested_rows(sub, source_warehouse):
	"""Rows for an MR against this Sub PO: pending requirements, with type, standard qty,
	stock and shortage filled in."""
	reqs = _pending_requirements(sub.name)
	parent = MC.parent_rows(sub.get(PARENT_FIELD))
	info = MC.item_info([r.item_code for r in reqs])
	stock = MC.bin_qty([r.item_code for r in reqs], source_warehouse)
	out = []
	for r in reqs:
		i = info.get(r.item_code) or frappe._dict()
		p = parent.get(r.item_code) or frappe._dict()
		available = flt(stock.get(r.item_code))
		out.append({
			"item_code": r.item_code,
			"item_name": r.item_name or i.get("item_name"),
			"uom": r.uom or i.get("stock_uom"),
			"material_type": p.get("material_type") or i.get("material_type") or "",
			"standard_qty": flt(p.get("standard_qty")),
			"qty": flt(r.qty),
			"available_qty": available,
			"shortage_qty": max(flt(r.qty) - available, 0),
			"from_warehouse": source_warehouse,
			"issued_qty": 0,
			"pending_qty": flt(r.qty),
			"line_remarks": "",
		})
	return out


def _apply_header(doc, sub):
	doc.set(SUB_FIELD, sub.name)
	doc.set("custom_parent_production_order", sub.get(PARENT_FIELD))
	doc.set("custom_target_fg_item", sub.production_item)
	doc.set("custom_production_type", sub.get(PRODUCTION_TYPE_FIELD))
	doc.company = sub.company or doc.company


def _set_rows(doc, rows, schedule_date, wip):
	doc.set("items", [])
	info = MC.item_info([r.get("item_code") for r in rows])
	for r in rows:
		r = frappe._dict(r)
		i = info.get(r.item_code) or frappe._dict()
		doc.append("items", {
			"item_code": r.item_code,
			"item_name": r.get("item_name") or i.get("item_name"),
			"qty": flt(r.qty),
			"uom": i.get("stock_uom") or r.get("uom"),
			"stock_uom": i.get("stock_uom") or r.get("uom"),
			"conversion_factor": 1,
			"schedule_date": schedule_date,
			"from_warehouse": r.get("from_warehouse"),
			"warehouse": wip,
			"custom_material_type": r.get("material_type") or i.get("material_type") or "",
			"custom_standard_qty": flt(r.get("standard_qty")),
			"custom_line_remarks": r.get("line_remarks") or "",
		})


# ============================================================ auto MR (generate_mr)

def _open_mr(sub_name):
	return frappe.db.get_value(
		MR, {SUB_FIELD: sub_name, "custom_mr_source": M.MR_SOURCE_AUTO, "docstatus": ("<", 2)},
		"name")


def _generate_mr(sub_order):
	sub_doc = frappe.get_doc(WORK_ORDER, sub_order)
	sub = MC.sub_order_header(sub_order)       # Parent Sent To Store, not locked, not cancelled

	status = sub_doc.get(EXECUTION_STATUS_FIELD)
	if status != "Assigned":
		frappe.throw(
			_("{0} is {1}. A Material Request can only be generated for a sub order that is "
			  "planned (status Assigned).").format(sub_order, status or _("Unassigned")),
			title=_("Sub Order Not Planned"))
	if not sub_doc.get(ASSIGNED_PROCESS_FIELD) or not sub_doc.get(PLANNED_DATE_FIELD):
		frappe.throw(
			_("{0} needs an assigned process and a planned date before its Material Request "
			  "can be generated.").format(sub_order),
			title=_("Planning Incomplete"))
	if cint(sub_doc.get(IS_LOCKED_FIELD)):
		frappe.throw(_("{0} is locked until its Parent is sent to store.").format(sub_order),
		             title=_("Sub PO Locked"))
	existing = _open_mr(sub_order)
	if existing:
		frappe.throw(_("Material Request {0} already exists for {1}.").format(existing, sub_order),
		             title=_("Material Request Exists"))

	source, wip = main_warehouse(), wip_warehouse()
	rows = _suggested_rows(sub, source)
	if not rows:
		frappe.throw(_("{0} has no materials left to request.").format(sub_order),
		             title=_("Nothing To Request"))

	schedule_date = sub_doc.get(PLANNED_DATE_FIELD)
	if getdate(schedule_date) < getdate(nowdate()):
		schedule_date = nowdate()

	# 1. The Sub PO is submitted -- it is now a real Work Order the store issues against --
	#    and its plan is locked in the same step.
	if cint(sub_doc.docstatus) == 0:
		sub_doc.flags.alpinos_sub_order = True
		sub_doc.flags.ignore_permissions = True
		sub_doc.set(PLAN_LOCKED_FIELD, 1)
		sub_doc.set(EXECUTION_STATUS_FIELD, M.SUB_EXECUTION_PENDING_STORE_ISSUE)
		sub_doc.submit()
	else:
		frappe.db.set_value(WORK_ORDER, sub_order, {
			PLAN_LOCKED_FIELD: 1,
			EXECUTION_STATUS_FIELD: M.SUB_EXECUTION_PENDING_STORE_ISSUE,
		})

	# 2. The MR, submitted at once: an auto MR is the plan, there is nothing to review.
	mr = frappe.new_doc(MR)
	mr.naming_series = M.MR_NAMING_SERIES
	mr.material_request_type = M.MR_TYPE
	mr.transaction_date = nowdate()
	mr.schedule_date = schedule_date
	mr.set_from_warehouse = source
	mr.set_warehouse = wip
	_apply_header(mr, sub)
	mr.set("custom_mr_source", M.MR_SOURCE_AUTO)
	mr.set("custom_remarks", _("Generated from the plan of {0}.").format(sub_order))
	_set_rows(mr, rows, schedule_date, wip)
	mr.flags.alpinos_material = True
	mr.flags.ignore_permissions = True
	mr.insert()
	mr.submit()

	frappe.db.set_value(WORK_ORDER, sub_order, MATERIAL_REQUEST_FIELD, mr.name)

	MC.notify(
		M.MR_NOTIFY_ROLES,
		_("Material Request {0} raised for {1} ({2}), required by {3}.").format(
			mr.name, sub_order, sub.production_item, frappe.format_value(schedule_date, {"fieldtype": "Date"})),
		MR, mr.name)
	return {"material_request": mr.name, "sub_order": sub_order}


@frappe.whitelist()
def generate_mr(sub_order):
	"""Generate, submit and link the MR for one planned Sub PO."""
	MC.assert_may_plan()
	out = _generate_mr(sub_order)
	frappe.db.commit()
	return out


def _clean(message):
	import re
	return re.sub(r"<[^>]+>", "", str(message or "")).strip()


@frappe.whitelist()
def generate_mr_bulk(sub_orders):
	"""generate_mr for many Sub POs. One failure does not stop the rest: each is its own
	savepoint, and the result says what happened to every row."""
	MC.assert_may_plan()
	names = frappe.parse_json(sub_orders) if isinstance(sub_orders, str) else (sub_orders or [])
	results = []
	for name in [n for n in names if n]:
		savepoint = "alp_mr_bulk"
		frappe.db.savepoint(savepoint)
		try:
			out = _generate_mr(name)
			results.append({"sub_order": name, "ok": 1, "material_request": out["material_request"]})
		except frappe.ValidationError as e:
			frappe.db.rollback(save_point=savepoint)
			results.append({"sub_order": name, "ok": 0, "error": _clean(e) or _("Not generated.")})
		except Exception:
			frappe.db.rollback(save_point=savepoint)
			frappe.log_error(frappe.get_traceback(), "Generate MR (bulk)")
			results.append({"sub_order": name, "ok": 0,
			                "error": _("Something went wrong; the error has been logged.")})
		# The per-row throws are reported in `results`; they must not also pop up one by one.
		frappe.local.message_log = []
	frappe.db.commit()
	return {
		"results": results,
		"created": sum(1 for r in results if r["ok"]),
		"failed": sum(1 for r in results if not r["ok"]),
	}


# ============================================================ doc_events (MR)

def before_validate(doc, method=None):
	"""BR-MR rules, on the doctype, so the desk form and the API cannot walk past them."""
	if not is_production_mr(doc):
		return
	if not doc.flags.get("alpinos_material") and not MC.may_write():
		MC.assert_may_write()

	sub = MC.sub_order_header(doc.get(SUB_FIELD))
	_apply_header(doc, sub)
	if not doc.get("custom_target_fg_item"):
		frappe.throw(_("The Target FG Item is missing."), title=_("FG Item Required"))
	if not doc.get("custom_mr_source"):
		doc.set("custom_mr_source", M.MR_SOURCE_MANUAL)
	if doc.material_request_type != M.MR_TYPE:
		frappe.throw(_("A production Material Request must be of type {0}.").format(M.MR_TYPE),
		             title=_("Wrong Request Type"))

	rows = doc.get("items") or []
	if not rows:
		frappe.throw(_("Add at least one material row."), title=_("No Materials"))

	wip = doc.get("set_warehouse") or wip_warehouse()
	doc.set_warehouse = wip
	info = MC.item_info([r.item_code for r in rows])
	by_wh = {}
	for r in rows:
		by_wh.setdefault(r.from_warehouse, []).append(r.item_code)
	stock = {wh: MC.bin_qty(codes, wh) for wh, codes in by_wh.items() if wh}

	for r in rows:
		if not r.item_code:
			frappe.throw(_("Row {0}: choose an item.").format(r.idx), title=_("Item Required"))
		i = info.get(r.item_code) or frappe._dict()
		if r.item_code == doc.get("custom_target_fg_item") or i.get("material_type") == "FG":
			frappe.throw(_("Row {0}: {1} is a finished good; only RM, PM and Additive items may be "
			               "requested.").format(r.idx, r.item_code), title=_("Wrong Material Type"))
		if flt(r.qty) <= 0:
			frappe.throw(_("Row {0}: the quantity of {1} must be greater than 0.").format(
				r.idx, r.item_code), title=_("Quantity Required"))
		if not r.from_warehouse:
			frappe.throw(_("Row {0}: choose the warehouse {1} is issued from.").format(
				r.idx, r.item_code), title=_("Warehouse Required"))
		if r.from_warehouse == wip:
			frappe.throw(_("Row {0}: the source warehouse cannot be the WIP warehouse.").format(r.idx),
			             title=_("Wrong Warehouse"))
		r.warehouse = wip
		if not r.schedule_date:
			r.schedule_date = doc.schedule_date
		if not r.get("custom_material_type"):
			r.custom_material_type = i.get("material_type") or ""
		available = flt((stock.get(r.from_warehouse) or {}).get(r.item_code))
		r.custom_available_qty = available
		r.custom_shortage_qty = max(flt(r.qty) - available, 0)
		if cint(doc.docstatus) == 0:
			r.custom_issued_qty = 0
			r.custom_pending_qty = flt(r.qty)

	if doc.schedule_date and cint(doc.docstatus) == 0 and doc.is_new() \
			and getdate(doc.schedule_date) < getdate(nowdate()):
		frappe.throw(_("The Required Date cannot be in the past."), title=_("Invalid Required Date"))

	doc.set("custom_mr_status", compute_status(doc))


def before_update_after_submit(doc, method=None):
	if not is_production_mr(doc) or doc.flags.get("alpinos_material"):
		return
	MC.assert_may_manage(_("change a submitted Material Request"))


def before_cancel(doc, method=None):
	if not is_production_mr(doc):
		return
	if not doc.flags.get("alpinos_material"):
		MC.assert_may_manage(_("cancel a Material Request"))
	issued = issued_by_row(doc.name)
	total = sum(issued.values())
	if total > 0:
		frappe.throw(
			_("{0} cannot be cancelled: materials have already been issued against it. Cancel "
			  "its Material Issues first.").format(doc.name),
			title=_("Materials Already Issued"))
	drafts = frappe.get_all(M.SE_DOCTYPE, filters={"custom_material_request": doc.name,
	                                                "docstatus": 0}, pluck="name")
	if drafts:
		frappe.throw(
			_("{0} cannot be cancelled while draft Material Issue(s) {1} point at it. Delete them "
			  "first.").format(doc.name, ", ".join(drafts)),
			title=_("Draft Issues Exist"))


def on_cancel(doc, method=None):
	"""Cancelled with nothing issued: the auto MR's Sub PO goes back to Assigned, unlocked."""
	if not is_production_mr(doc):
		return
	frappe.db.set_value(MR, doc.name, "custom_mr_status", M.MR_CANCELLED)
	if doc.get("custom_mr_source") != M.MR_SOURCE_AUTO:
		return
	sub_name = doc.get(SUB_FIELD)
	row = frappe.db.get_value(WORK_ORDER, sub_name,
	                          [EXECUTION_STATUS_FIELD, MATERIAL_REQUEST_FIELD], as_dict=True)
	if not row:
		return
	if row.get(MATERIAL_REQUEST_FIELD) and row.get(MATERIAL_REQUEST_FIELD) != doc.name:
		return
	values = {PLAN_LOCKED_FIELD: 0, MATERIAL_REQUEST_FIELD: None}
	if row.get(EXECUTION_STATUS_FIELD) == M.SUB_EXECUTION_PENDING_STORE_ISSUE:
		values[EXECUTION_STATUS_FIELD] = "Assigned"
	frappe.db.set_value(WORK_ORDER, sub_name, values)


# ================================================================ screens: list

@frappe.whitelist()
def get_mr_list(search=None, status=None, sub_order=None, parent=None, fg_item=None,
                source=None, date_from=None, date_to=None, start=0,
                page_length=M.DEFAULT_PAGE_LENGTH):
	MC.assert_may_read()
	start, page_length = MC.page_args(start, page_length)

	filters = {SUB_FIELD: ("is", "set")}
	if status:
		filters["custom_mr_status"] = status
	if sub_order:
		filters[SUB_FIELD] = sub_order
	if parent:
		filters["custom_parent_production_order"] = parent
	if fg_item:
		filters["custom_target_fg_item"] = fg_item
	if source:
		filters["custom_mr_source"] = source
	MC.date_range(filters, "transaction_date", date_from, date_to)

	or_filters = None
	if search:
		like = f"%{search}%"
		or_filters = {"name": ("like", like), SUB_FIELD: ("like", like),
		              "custom_target_fg_item": ("like", like)}

	count = frappe.get_all(MR, fields=["count(name) as total"], filters=filters,
	                       or_filters=or_filters, limit_page_length=0)
	total = cint(count[0].get("total")) if count else 0
	rows = frappe.get_all(MR, filters=filters, or_filters=or_filters, fields=list(LIST_FIELDS),
	                      order_by="creation desc", limit_start=start,
	                      limit_page_length=page_length + 1)
	has_more = len(rows) > page_length
	rows = rows[:page_length]
	names = {r.custom_target_fg_item for r in rows if r.custom_target_fg_item}
	labels = {}
	if names:
		labels = {i.name: i.item_name for i in frappe.get_all(
			"Item", filters={"name": ("in", list(names))}, fields=["name", "item_name"])}
	for r in rows:
		r["fg_item_name"] = labels.get(r.custom_target_fg_item) or ""
		r["requested_by"] = get_fullname(r.owner)
	return {
		"data": rows, "has_more": int(has_more), "start": start, "page_length": page_length,
		"total": total, "page_lengths": list(M.PAGE_LENGTHS),
		"statuses": list(M.MR_STATUSES), "sources": list(M.MR_SOURCES),
		"can_create": int(MC.may_write()), "can_issue": int(MC.may_write()),
	}


# =============================================================== screens: entry

def _row_out(r):
	return {
		"name": r.name, "item_code": r.item_code, "item_name": r.item_name, "uom": r.uom,
		"material_type": r.get("custom_material_type") or "",
		"standard_qty": flt(r.get("custom_standard_qty")), "qty": flt(r.qty),
		"available_qty": flt(r.get("custom_available_qty")),
		"shortage_qty": flt(r.get("custom_shortage_qty")),
		"from_warehouse": r.from_warehouse, "warehouse": r.warehouse,
		"issued_qty": flt(r.get("custom_issued_qty")),
		"pending_qty": flt(r.get("custom_pending_qty")),
		"line_remarks": r.get("custom_line_remarks") or "",
	}


def _warehouses():
	out = {"main_warehouse": None, "wip_warehouse": None}
	try:
		out["main_warehouse"] = main_warehouse()
		out["wip_warehouse"] = wip_warehouse()
	except frappe.ValidationError:
		frappe.local.message_log = []
	return out


@frappe.whitelist()
def get_mr_context(material_request=None):
	MC.assert_may_read()
	ctx = {"material_types": list(M.MR_MATERIAL_TYPES), "statuses": list(M.MR_STATUSES)}
	ctx.update(_warehouses())
	may_write, may_manage = MC.may_write(), MC.may_manage()
	if not material_request:
		ctx.update({"doc": None, "can_write": int(may_write), "can_submit": 0, "can_cancel": 0,
		            "can_issue": 0, "requested_by": get_fullname(frappe.session.user),
		            "issues": []})
		return ctx

	doc = frappe.get_doc(MR, material_request)
	if not is_production_mr(doc):
		frappe.throw(_("{0} is not a production Material Request.").format(material_request),
		             title=_("Not A Production MR"))
	status = doc.get("custom_mr_status") or compute_status(doc)
	draft = cint(doc.docstatus) == 0
	issues = frappe.get_all(
		M.SE_DOCTYPE, filters={"custom_material_request": doc.name, "custom_entry_kind": M.KIND_ISSUE},
		fields=["name", "posting_date", "docstatus", "owner"], order_by="creation asc")
	for i in issues:
		i["status"] = MC.se_status(i.docstatus)
		i["issued_by"] = get_fullname(i.owner)
	ctx.update({
		"doc": {
			"name": doc.name, "sub_order": doc.get(SUB_FIELD),
			"parent": doc.get("custom_parent_production_order"),
			"fg_item": doc.get("custom_target_fg_item"),
			"fg_item_name": frappe.db.get_value("Item", doc.get("custom_target_fg_item"), "item_name"),
			"production_type": doc.get("custom_production_type"),
			"source": doc.get("custom_mr_source"), "status": status,
			"transaction_date": doc.transaction_date, "schedule_date": doc.schedule_date,
			"remarks": doc.get("custom_remarks") or "", "docstatus": doc.docstatus,
			"requested_by": get_fullname(doc.owner), "company": doc.company,
			"items": [_row_out(r) for r in doc.items],
		},
		"can_write": int(draft and may_write),
		"can_submit": int(draft and may_write),
		"can_cancel": int(cint(doc.docstatus) == 1 and status == M.MR_PENDING_ISSUE and may_manage),
		"can_issue": int(cint(doc.docstatus) == 1 and status in M.MR_ISSUABLE_STATUSES and may_write),
		"can_delete": int(draft and may_write),
		"issues": issues,
	})
	return ctx


@frappe.whitelist()
def sub_order_materials(sub_order, source_warehouse=None):
	"""The header and suggested rows for a manual MR on this Sub PO."""
	MC.assert_may_read()
	sub = MC.sub_order_header(sub_order)
	source = source_warehouse or main_warehouse()
	return {
		"sub_order": sub.name, "parent": sub.get(PARENT_FIELD), "fg_item": sub.production_item,
		"fg_item_name": sub.item_name, "production_type": sub.get(PRODUCTION_TYPE_FIELD),
		"planned_date": sub.get(PLANNED_DATE_FIELD), "rows": _suggested_rows(sub, source),
	}


@frappe.whitelist()
def item_row_info(item_code, warehouse=None):
	"""Type, name, UOM and stock for one item typed into the manual grid."""
	MC.assert_may_read()
	i = (MC.item_info([item_code]) or {}).get(item_code) or frappe._dict()
	return {
		"item_code": item_code, "item_name": i.get("item_name"), "uom": i.get("stock_uom"),
		"material_type": i.get("material_type") or "",
		"available_qty": flt(MC.bin_qty([item_code], warehouse).get(item_code)) if warehouse else 0,
	}


@frappe.whitelist()
def save_mr(payload):
	"""Create or update a MANUAL draft MR from the entry screen."""
	MC.assert_may_write()
	p = MC.parse(payload)
	if p.get("name"):
		doc = frappe.get_doc(MR, p.name)
		if cint(doc.docstatus) != 0:
			frappe.throw(_("{0} is submitted and cannot be edited.").format(doc.name),
			             title=_("Not A Draft"))
		if not is_production_mr(doc):
			frappe.throw(_("{0} is not a production Material Request.").format(doc.name))
	else:
		doc = frappe.new_doc(MR)
		doc.naming_series = M.MR_NAMING_SERIES
		doc.set("custom_mr_source", M.MR_SOURCE_MANUAL)
		doc.material_request_type = M.MR_TYPE
		doc.transaction_date = nowdate()

	sub_name = p.get("sub_order") if doc.get("custom_mr_source") != M.MR_SOURCE_AUTO \
		else doc.get(SUB_FIELD)
	sub = MC.sub_order_header(sub_name)
	_apply_header(doc, sub)
	if not p.get("schedule_date"):
		frappe.throw(_("Please enter the Required Date."), title=_("Required Date Missing"))
	doc.schedule_date = p.schedule_date
	wip = wip_warehouse()
	doc.set_warehouse = wip
	doc.set("custom_remarks", p.get("remarks") or "")
	rows = [r for r in (p.get("items") or []) if (r or {}).get("item_code")]
	_set_rows(doc, rows, doc.schedule_date, wip)
	doc.flags.alpinos_material = True
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"name": doc.name}


@frappe.whitelist()
def submit_mr(material_request):
	MC.assert_may_write()
	doc = frappe.get_doc(MR, material_request)
	if not is_production_mr(doc) or cint(doc.docstatus) != 0:
		frappe.throw(_("{0} is not a draft production Material Request.").format(material_request))
	doc.flags.alpinos_material = True
	doc.submit()
	frappe.db.commit()
	return {"name": doc.name, "status": doc.get("custom_mr_status")}


@frappe.whitelist()
def cancel_mr(material_request):
	MC.assert_may_manage(_("cancel a Material Request"))
	doc = frappe.get_doc(MR, material_request)
	if not is_production_mr(doc) or cint(doc.docstatus) != 1:
		frappe.throw(_("{0} is not a submitted production Material Request.").format(material_request))
	doc.flags.alpinos_material = True
	doc.flags.ignore_permissions = True
	doc.cancel()
	frappe.db.commit()
	return {"name": doc.name, "status": M.MR_CANCELLED}


@frappe.whitelist()
def delete_mr(material_request):
	MC.assert_may_write()
	doc = frappe.get_doc(MR, material_request)
	if not is_production_mr(doc) or cint(doc.docstatus) != 0:
		frappe.throw(_("Only a draft production Material Request can be deleted."))
	frappe.delete_doc(MR, doc.name, ignore_permissions=True)
	frappe.db.commit()
	return {"deleted": material_request}


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def sub_order_query(doctype, txt, searchfield, start, page_len, filters):
	"""Sub POs a manual MR may be raised for: Parent Sent To Store, unlocked, not cancelled,
	not completed."""
	from alpinos.production import constants as C
	return frappe.db.sql(
		f"""
		select wo.name, wo.production_item, wo.{PARENT_FIELD}
		from `tabWork Order` wo
		join `tabProduction Order` po on po.name = wo.{PARENT_FIELD}
		where po.status = %(sent)s
		  and ifnull(wo.{IS_LOCKED_FIELD}, 0) = 0
		  and wo.docstatus < 2
		  and ifnull(wo.{EXECUTION_STATUS_FIELD}, '') != 'Completed'
		  and (wo.name like %(txt)s or wo.production_item like %(txt)s)
		order by wo.name asc
		limit %(start)s, %(page_len)s
		""",
		{"sent": C.PO_SENT_TO_STORE, "txt": f"%{txt or ''}%", "start": cint(start),
		 "page_len": cint(page_len) or 20},
	)
