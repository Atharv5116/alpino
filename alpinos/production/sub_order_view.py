"""Sub Production Order -- the read-only view page (`sub_order_view`).

One call, `get_sub_order_view`, returns everything the page shows: the header, the
planning, the materials with issued / returned / pending, the linked store documents and
which actions the current user may take. The page itself changes nothing; every action
button calls the existing server function that owns that rule (assign_process,
split_sub_order_action, generate_mr), and those still enforce it.

Also here: the guard that keeps a Sub PO from being submitted or cancelled from the
standard Work Order form. System code that legitimately does either (generate_mr submits
it; cancelling the Parent cancels it) already sets `doc.flags.alpinos_sub_order`, the same
flag SPO-02 reads, and the guard lets exactly those through.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

from alpinos.production import material_common as MC
from alpinos.production import material_constants as M
from alpinos.production.work_order_fields import (
	ASSIGNED_MACHINE_FIELD,
	ASSIGNED_PROCESS_FIELD,
	BATCH_FIELD,
	CLIENT_FIELD,
	EXECUTION_STATUS_FIELD,
	IS_LOCKED_FIELD,
	MATERIAL_REQUEST_FIELD,
	PARENT_FIELD,
	PLAN_LOCKED_FIELD,
	PLANNED_DATE_FIELD,
	PRODUCTION_TYPE_FIELD,
	SPLIT_FROM_FIELD,
)

WORK_ORDER = "Work Order"
SUB_FIELD = "custom_sub_production_order"
MACHINE_RUN = "Machine Run"
MACHINE_RUN_FIELD = "custom_machine_run"
DOCSTATUS_LABELS = {0: "Draft", 1: "Submitted", 2: "Cancelled"}


def _has(doctype, field):
	return frappe.get_meta(doctype).has_field(field)


def _entries(kind, sub_name, extra_fields=()):
	if not _has(M.SE_DOCTYPE, "custom_entry_kind") or not _has(M.SE_DOCTYPE, SUB_FIELD):
		return []
	fields = ["name", "posting_date", "docstatus"] + [
		f for f in extra_fields if _has(M.SE_DOCTYPE, f)]
	rows = frappe.get_all(M.SE_DOCTYPE,
	                      filters={"custom_entry_kind": kind, SUB_FIELD: sub_name},
	                      fields=fields, order_by="creation asc")
	for r in rows:
		r["status"] = MC.se_status(r.docstatus)
	return rows


def _qty_by_item(entry_names):
	"""Submitted entries' quantities per item (stock UOM)."""
	if not entry_names:
		return {}
	out = {}
	for r in frappe.get_all("Stock Entry Detail",
	                        filters={"parent": ("in", entry_names), "docstatus": 1},
	                        fields=["item_code", "transfer_qty", "qty"]):
		out[r.item_code] = out.get(r.item_code, 0) + flt(r.transfer_qty or r.qty)
	return out


def _material_requests(sub_name):
	meta = frappe.get_meta("Material Request")
	links = [f for f in (SUB_FIELD, "work_order") if meta.has_field(f)]
	if not links:
		return []
	fields = ["name", "transaction_date", "schedule_date", "docstatus"]
	for f in ("custom_mr_status", "custom_mr_source"):
		if meta.has_field(f):
			fields.append(f)
	seen, rows = set(), []
	for link in links:
		for r in frappe.get_all("Material Request", filters={link: sub_name}, fields=fields,
		                        order_by="creation asc"):
			if r.name in seen:
				continue
			seen.add(r.name)
			r["status"] = r.get("custom_mr_status") or DOCSTATUS_LABELS.get(cint(r.docstatus))
			rows.append(r)
	return rows


def _machine_run(sub):
	run = sub.get(MACHINE_RUN_FIELD) if _has(WORK_ORDER, MACHINE_RUN_FIELD) else None
	if not run or not frappe.db.exists(MACHINE_RUN, run):
		return None
	info = frappe.db.get_value(MACHINE_RUN, run,
	                           ["name", "status", "planned_date", "machine", "total_qty"],
	                           as_dict=True) or {"name": run}
	members = frappe.get_all("Machine Run Sub Order",
	                         filters={"parent": run, "parenttype": MACHINE_RUN},
	                         pluck="sub_order", order_by="idx asc")
	info["members"] = members
	info["others"] = [m for m in members if m != sub.name]
	return info


@frappe.whitelist()
def get_sub_order_view(sub_order):
	"""Everything the Sub Production Order view page shows, read-only."""
	if not sub_order or not frappe.db.exists(WORK_ORDER, sub_order):
		frappe.throw(_("Sub Production Order {0} does not exist.").format(sub_order or ""),
		             title=_("Not Found"))
	frappe.has_permission(WORK_ORDER, "read", doc=sub_order, throw=True)
	sub = frappe.get_doc(WORK_ORDER, sub_order)
	parent = sub.get(PARENT_FIELD)
	if not parent:
		frappe.throw(_("{0} is not a Sub Production Order.").format(sub_order),
		             title=_("Not A Sub PO"))

	parent_status = frappe.db.get_value("Production Order", parent, "status")
	process = sub.get(ASSIGNED_PROCESS_FIELD)
	machine = sub.get(ASSIGNED_MACHINE_FIELD)
	status = sub.get(EXECUTION_STATUS_FIELD) or "Unassigned"
	is_locked = cint(sub.get(IS_LOCKED_FIELD))
	plan_locked = cint(sub.get(PLAN_LOCKED_FIELD)) if _has(WORK_ORDER, PLAN_LOCKED_FIELD) else 0

	# ------------------------------------------------------ linked documents
	mrs = _material_requests(sub.name)
	issues = _entries(M.KIND_ISSUE, sub.name, ("custom_material_request",))
	returns = _entries(M.KIND_RETURN, sub.name, ("custom_material_issue",))
	split_children = frappe.get_all(
		WORK_ORDER, filters={SPLIT_FROM_FIELD: sub.name},
		fields=["name", "qty", "docstatus", EXECUTION_STATUS_FIELD], order_by="name asc")

	# ------------------------------------------------------------- materials
	issued = _qty_by_item([r.name for r in issues if cint(r.docstatus) == 1])
	returned = _qty_by_item([r.name for r in returns if cint(r.docstatus) == 1])
	codes = list({row.item_code for row in sub.required_items if row.item_code})
	types = {}
	if codes and _has("Item", "custom_material_type"):
		types = dict(frappe.get_all("Item", filters={"name": ("in", codes)},
		                            fields=["name", "custom_material_type"], as_list=True))
	materials = []
	for row in sub.required_items:
		code = row.item_code
		got = flt(issued.get(code))
		back = flt(returned.get(code))
		net = got - back
		required = flt(row.required_qty)
		materials.append({
			"material_type": types.get(code) or "",
			"item_code": code,
			"item_name": row.item_name,
			"uom": row.stock_uom,
			"required_qty": required,
			"issued_qty": net,
			"returned_qty": back,
			"pending_qty": max(required - net, 0),
		})

	# --------------------------------------------------------------- actions
	roles = set(frappe.get_roles())
	open_mr = sub.get(MATERIAL_REQUEST_FIELD) or next(
		(r.name for r in mrs if cint(r.docstatus) < 2), None)
	from alpinos.production import constants as C
	from alpinos.production.sub_order import _user_may_plan, activity_blockers
	not_cancelled = cint(sub.docstatus) < 2
	can_assign = bool(_user_may_plan() and not is_locked and not plan_locked and not_cancelled)
	# The same test split_context makes, so the button only shows when Split would work.
	can_split = bool(_user_may_plan() and not plan_locked and not_cancelled
	                 and parent_status in C.PO_PLANNABLE_STATUSES
	                 and not activity_blockers(sub.name))
	# generate_mr's own checks: planned (process + date), Parent Sent To Store, no open MR.
	can_generate_mr = bool(MC.may_plan() and status == "Assigned" and not is_locked
	                       and not plan_locked and not open_mr and not_cancelled
	                       and process and sub.get(PLANNED_DATE_FIELD)
	                       and parent_status == C.PO_SENT_TO_STORE)

	process_label = frappe.db.get_value("Process Master", process, "process_name") if process else None
	machine_label = frappe.db.get_value("Machine", machine, "machine_name") if machine else None

	return {
		"name": sub.name,
		"parent": parent,
		"parent_status": parent_status,
		"production_item": sub.production_item,
		"item_name": sub.item_name,
		"qty": flt(sub.qty),
		"uom": sub.stock_uom,
		"batch_number": sub.get(BATCH_FIELD),
		"production_type": sub.get(PRODUCTION_TYPE_FIELD),
		"client_name": sub.get(CLIENT_FIELD),
		"execution_status": status,
		"is_locked": is_locked,
		"plan_locked": plan_locked,
		"split_from": sub.get(SPLIT_FROM_FIELD),
		"docstatus": cint(sub.docstatus),
		"docstatus_label": DOCSTATUS_LABELS.get(cint(sub.docstatus)),
		"wo_status": sub.status,
		"process": process,
		"process_label": process_label,
		"machine": machine,
		"machine_label": machine_label,
		"planned_date": sub.get(PLANNED_DATE_FIELD),
		"machine_run": _machine_run(sub),
		"materials": materials,
		"material_requests": mrs,
		"material_issues": issues,
		"material_returns": returns,
		"split_children": split_children,
		"material_request": open_mr,
		"can_assign": int(can_assign),
		"can_split": int(can_split),
		"can_generate_mr": int(can_generate_mr),
		"can_open_form": int(frappe.session.user == "Administrator" or "System Manager" in roles),
	}


# ------------------------------------------------- no Submit / Cancel by hand

def block_manual_sub_order_submit(doc, method=None):
	"""Wired at Work Order `before_submit`. Ordinary Work Orders are left alone."""
	if not doc.get(PARENT_FIELD) or doc.flags.get("alpinos_sub_order"):
		return
	frappe.throw(
		_("A sub order is submitted by Generate MR on the Store Planning board, not from this form."),
		title=_("Sub Orders Are Not Submitted Directly"),
	)


def block_manual_sub_order_cancel(doc, method=None):
	"""Wired at Work Order `before_cancel`. Ordinary Work Orders are left alone."""
	if not doc.get(PARENT_FIELD) or doc.flags.get("alpinos_sub_order"):
		return
	if frappe.flags.get("alpinos_deleting_sub_orders"):
		return  # the Parent is being cancelled and takes its sub orders with it
	frappe.throw(
		_("A sub order cannot be cancelled from this form. Cancel its Parent Production Order "
		  "instead; to re-plan it, cancel its Material Request on the Store Planning board."),
		title=_("Sub Orders Are Not Cancelled Directly"),
	)
