"""Material Issue (MI) -- tasks 21-24.

An MI is a Stock Entry, purpose "Material Transfer for Manufacture", Main -> WIP, marked
custom_entry_kind = "Material Issue" and always linked to a Pending / Partially Issued MR.
Its rows point back at the MR rows (custom_mr_item, and ERPNext's own material_request /
material_request_item, so the MR's native per-transferred figures stay right too).

For an Auto MR the entry also carries work_order = the Sub PO, which is what makes
ERPNext count the transfer against the Work Order's required items. A manual MR is extra
material on top of the plan, so its issue is linked by custom_sub_production_order only --
ERPNext would otherwise refuse anything above the Work Order's own requirement.

On submit: the MR's Issued / Pending / status are recomputed, and the first submitted issue
moves the Sub PO from Pending Store Issue to Ready to Run. Cancel reverses both.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, get_fullname, getdate, nowdate

from alpinos.production import material_common as MC
from alpinos.production import material_constants as M
from alpinos.production.material_request import (
	SUB_FIELD,
	issued_by_row,
	refresh_issue_status,
)
from alpinos.production.production_settings import main_warehouse, wip_warehouse
from alpinos.production.work_order_fields import EXECUTION_STATUS_FIELD

SE = M.SE_DOCTYPE
MR = M.MR_DOCTYPE
WORK_ORDER = "Work Order"

LIST_FIELDS = (
	"name", "custom_material_request", SUB_FIELD, "custom_parent_production_order",
	"custom_target_fg_item", "custom_production_type", "posting_date", "docstatus", "owner",
	"from_warehouse", "to_warehouse",
)


def is_issue(doc):
	return doc.get("custom_entry_kind") == M.KIND_ISSUE


# ================================================================== validation

def _mr_rows(mr_name):
	return {r.name: r for r in frappe.get_all(
		"Material Request Item", filters={"parent": mr_name, "parenttype": MR},
		fields=["name", "item_code", "item_name", "qty", "uom", "stock_uom", "from_warehouse",
		        "custom_material_type"])}


def _check_mr(mr_name, submitting=False):
	if not mr_name:
		frappe.throw(_("A Material Issue must be linked to a Material Request."),
		             title=_("Material Request Required"))
	mr = frappe.db.get_value(MR, mr_name, ["name", "docstatus", "custom_mr_status", SUB_FIELD,
	                                       "custom_parent_production_order",
	                                       "custom_target_fg_item", "custom_production_type",
	                                       "custom_mr_source", "company"], as_dict=True)
	if not mr or not mr.get(SUB_FIELD):
		frappe.throw(_("{0} is not a production Material Request.").format(mr_name),
		             title=_("Wrong Material Request"))
	if cint(mr.docstatus) != 1 or mr.custom_mr_status not in M.MR_ISSUABLE_STATUSES:
		frappe.throw(
			_("Material Request {0} is {1}. Materials can only be issued against a Pending Issue "
			  "or Partially Issued request.").format(mr_name, mr.custom_mr_status or _("a draft")),
			title=_("Request Not Open"))
	return mr


def validate_issue(doc):
	mr = _check_mr(doc.get("custom_material_request"))
	doc.purpose = M.ISSUE_PURPOSE
	doc.stock_entry_type = M.ISSUE_PURPOSE
	doc.company = mr.company or doc.company
	doc.set(SUB_FIELD, mr.get(SUB_FIELD))
	doc.set("custom_parent_production_order", mr.custom_parent_production_order)
	doc.set("custom_target_fg_item", mr.custom_target_fg_item)
	doc.set("custom_production_type", mr.custom_production_type)
	sub_submitted = cint(frappe.db.get_value(WORK_ORDER, mr.get(SUB_FIELD), "docstatus")) == 1
	doc.work_order = mr.get(SUB_FIELD) if (mr.custom_mr_source == M.MR_SOURCE_AUTO and sub_submitted) \
		else None

	if doc.posting_date and getdate(doc.posting_date) > getdate(nowdate()):
		frappe.throw(_("The Issue Date cannot be in the future."), title=_("Invalid Issue Date"))

	rows = doc.get("items") or []
	if not rows:
		frappe.throw(_("Enter an Actual Issue Qty on at least one row."), title=_("Nothing To Issue"))

	mr_rows = _mr_rows(mr.name)
	issued = issued_by_row(mr.name, exclude_entry=None if doc.is_new() else doc.name)
	wip = doc.get("to_warehouse") or wip_warehouse()
	info = MC.item_info([r.item_code for r in rows])
	claimed = {}

	for r in rows:
		src = mr_rows.get(r.get("custom_mr_item"))
		if not src or src.item_code != r.item_code:
			frappe.throw(_("Row {0}: {1} is not a row of Material Request {2}.").format(
				r.idx, r.item_code, mr.name), title=_("Row Not In Request"))
		uom = src.stock_uom or src.uom or ""
		if flt(r.qty) <= 0:
			frappe.throw(_("Row {0}: the Actual Issue Qty of {1} must be greater than 0.").format(
				r.idx, r.item_code), title=_("Issue Qty Required"))
		claimed[src.name] = claimed.get(src.name, 0) + flt(r.qty)
		pending = max(flt(src.qty) - flt(issued.get(src.name)), 0)
		if claimed[src.name] > pending + 0.0000001:
			frappe.throw(
				_("Row {0}: you can issue at most {1} {2} of {3}; the request is for {4} and {5} "
				  "has already been issued.").format(r.idx, flt(pending), uom, r.item_code,
				                                    flt(src.qty), flt(issued.get(src.name))),
				title=_("More Than Requested"))
		if not r.s_warehouse:
			frappe.throw(_("Row {0}: choose the source warehouse for {1}.").format(r.idx, r.item_code),
			             title=_("Source Warehouse Required"))
		if not r.t_warehouse:
			r.t_warehouse = wip
		if r.s_warehouse == r.t_warehouse:
			frappe.throw(_("Row {0}: the source and target warehouse cannot be the same.").format(r.idx),
			             title=_("Same Warehouse"))

		i = info.get(r.item_code) or frappe._dict()
		if cint(i.get("has_batch_no")):
			if not r.get("batch_no"):
				frappe.throw(_("Row {0}: {1} is batch-managed; choose a Batch No.").format(
					r.idx, r.item_code), title=_("Batch Required"))
			r.use_serial_batch_fields = 1
			available = MC.batch_qty(r.batch_no, r.s_warehouse, r.item_code)
			where = _("{0}, batch {1}").format(r.s_warehouse, r.batch_no)
		else:
			available = flt(MC.bin_qty([r.item_code], r.s_warehouse).get(r.item_code))
			where = r.s_warehouse
		if flt(r.qty) > available + 0.0000001:
			frappe.throw(
				_("Row {0}: only {1} {2} of {3} is available in {4}.").format(
					r.idx, flt(available), uom, r.item_code, where),
				title=_("Not Enough Stock"))

		r.custom_available_qty = available
		r.custom_required_qty = pending
		r.custom_material_type = r.get("custom_material_type") or src.custom_material_type or \
			i.get("material_type") or ""
		r.material_request = mr.name
		r.material_request_item = src.name


def on_submit_issue(doc):
	refresh_issue_status(doc.get("custom_material_request"))
	sub = doc.get(SUB_FIELD)
	if sub and frappe.db.get_value(WORK_ORDER, sub, EXECUTION_STATUS_FIELD) == \
			M.SUB_EXECUTION_PENDING_STORE_ISSUE:
		# db.set_value rather than a save: the Sub PO is a submitted Work Order, and this is
		# a status move, not an edit of it.
		frappe.db.set_value(WORK_ORDER, sub, EXECUTION_STATUS_FIELD, M.SUB_EXECUTION_READY_TO_RUN)


def before_cancel_issue(doc):
	if not doc.flags.get("alpinos_material"):
		MC.assert_may_manage(_("cancel a Material Issue"))
	returns = frappe.get_all(SE, filters={"custom_material_issue": doc.name, "docstatus": ("<", 2),
	                                     "custom_entry_kind": M.KIND_RETURN}, pluck="name")
	if returns:
		frappe.throw(
			_("{0} cannot be cancelled: Material Return(s) {1} exist against it. Cancel or delete "
			  "them first.").format(doc.name, ", ".join(returns)),
			title=_("Returns Exist"))


def on_cancel_issue(doc):
	mr_name = doc.get("custom_material_request")
	if mr_name and cint(frappe.db.get_value(MR, mr_name, "docstatus")) == 1:
		refresh_issue_status(mr_name)
	sub = doc.get(SUB_FIELD)
	if not sub:
		return
	others = frappe.get_all(SE, filters={SUB_FIELD: sub, "custom_entry_kind": M.KIND_ISSUE,
	                                    "docstatus": 1, "name": ("!=", doc.name)}, limit=1)
	if not others and frappe.db.get_value(WORK_ORDER, sub, EXECUTION_STATUS_FIELD) == \
			M.SUB_EXECUTION_READY_TO_RUN:
		frappe.db.set_value(WORK_ORDER, sub, EXECUTION_STATUS_FIELD,
		                    M.SUB_EXECUTION_PENDING_STORE_ISSUE)


# =========================================================== Stock Entry dispatch

def se_before_validate(doc, method=None):
	kind = doc.get("custom_entry_kind")
	if not kind:
		return
	if not doc.flags.get("alpinos_material"):
		MC.assert_may_write()
	if kind == M.KIND_ISSUE:
		validate_issue(doc)
	elif kind == M.KIND_RETURN:
		from alpinos.production.material_return import validate_return
		validate_return(doc)


def se_on_submit(doc, method=None):
	if is_issue(doc):
		on_submit_issue(doc)


def se_before_cancel(doc, method=None):
	kind = doc.get("custom_entry_kind")
	if kind == M.KIND_ISSUE:
		before_cancel_issue(doc)
	elif kind == M.KIND_RETURN and not doc.flags.get("alpinos_material"):
		MC.assert_may_manage(_("cancel a Material Return"))


def se_on_cancel(doc, method=None):
	if is_issue(doc):
		on_cancel_issue(doc)


def se_before_update_after_submit(doc, method=None):
	if doc.get("custom_entry_kind") and not doc.flags.get("alpinos_material"):
		MC.assert_may_manage(_("change a submitted store document"))


# ================================================================== screens

@frappe.whitelist()
def get_mi_list(search=None, status=None, material_request=None, sub_order=None, parent=None,
                fg_item=None, date_from=None, date_to=None, start=0,
                page_length=M.DEFAULT_PAGE_LENGTH):
	MC.assert_may_read()
	return _entry_list(M.KIND_ISSUE, LIST_FIELDS, search, status, sub_order, parent, fg_item,
	                   date_from, date_to, start, page_length,
	                   extra={"custom_material_request": material_request} if material_request else None)


def _entry_list(kind, fields, search, status, sub_order, parent, fg_item, date_from, date_to,
                start, page_length, extra=None):
	start, page_length = MC.page_args(start, page_length)
	filters = {"custom_entry_kind": kind}
	if status:
		filters["docstatus"] = {M.SE_DRAFT: 0, M.SE_SUBMITTED: 1, M.SE_CANCELLED: 2}.get(status, 0)
	if sub_order:
		filters[SUB_FIELD] = sub_order
	if parent:
		filters["custom_parent_production_order"] = parent
	if fg_item:
		filters["custom_target_fg_item"] = fg_item
	for k, v in (extra or {}).items():
		filters[k] = v
	MC.date_range(filters, "posting_date", date_from, date_to)
	or_filters = None
	if search:
		like = f"%{search}%"
		or_filters = {"name": ("like", like), SUB_FIELD: ("like", like),
		              "custom_material_request": ("like", like),
		              "custom_material_issue": ("like", like)}
	count = frappe.get_all(SE, fields=["count(name) as total"], filters=filters,
	                       or_filters=or_filters, limit_page_length=0)
	total = cint(count[0].get("total")) if count else 0
	rows = frappe.get_all(SE, filters=filters, or_filters=or_filters, fields=list(fields),
	                      order_by="creation desc", limit_start=start,
	                      limit_page_length=page_length + 1)
	has_more = len(rows) > page_length
	rows = rows[:page_length]
	for r in rows:
		r["status"] = MC.se_status(r.docstatus)
		r["by"] = get_fullname(r.owner)
	return {
		"data": rows, "has_more": int(has_more), "start": start, "page_length": page_length,
		"total": total, "page_lengths": list(M.PAGE_LENGTHS),
		"statuses": [M.SE_DRAFT, M.SE_SUBMITTED, M.SE_CANCELLED],
		"can_create": int(MC.may_write()),
	}


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def mr_query(doctype, txt, searchfield, start, page_len, filters):
	"""The MR picker: open production MRs only. A Fully Issued one drops out."""
	return frappe.db.sql(
		f"""
		select name, {SUB_FIELD}, custom_target_fg_item, custom_mr_status
		from `tabMaterial Request`
		where docstatus = 1
		  and ifnull({SUB_FIELD}, '') != ''
		  and custom_mr_status in %(statuses)s
		  and (name like %(txt)s or {SUB_FIELD} like %(txt)s or custom_target_fg_item like %(txt)s)
		order by schedule_date asc, name asc
		limit %(start)s, %(page_len)s
		""",
		{"statuses": tuple(M.MR_ISSUABLE_STATUSES), "txt": f"%{txt or ''}%",
		 "start": cint(start), "page_len": cint(page_len) or 20},
	)


@frappe.whitelist()
def item_batches(item_code, warehouse):
	"""FEFO batch list for the Batch picker."""
	MC.assert_may_read()
	return MC.batches_fefo(item_code, warehouse)


def _suggest_batch(item_code, warehouse, qty):
	batches = MC.batches_fefo(item_code, warehouse)
	for b in batches:
		if flt(b["qty"]) >= flt(qty):
			return b["batch_no"]
	return batches[0]["batch_no"] if batches else None


@frappe.whitelist()
def mr_pending_rows(material_request, source_warehouse=None):
	"""Header and grid for a new MI: the MR's rows that still have something pending."""
	MC.assert_may_read()
	mr = _check_mr(material_request)
	issued = issued_by_row(mr.name)
	wip = _safe(wip_warehouse)
	default_source = source_warehouse or _safe(main_warehouse)
	src_rows = frappe.get_all(
		"Material Request Item", filters={"parent": mr.name, "parenttype": MR},
		fields=["name", "item_code", "item_name", "qty", "uom", "stock_uom", "from_warehouse",
		        "custom_material_type"], order_by="idx asc")
	info = MC.item_info([r.item_code for r in src_rows])
	rows = []
	for r in src_rows:
		pending = max(flt(r.qty) - flt(issued.get(r.name)), 0)
		if pending <= 0:
			continue
		source = r.from_warehouse or default_source
		i = info.get(r.item_code) or frappe._dict()
		batch = _suggest_batch(r.item_code, source, pending) if cint(i.get("has_batch_no")) else None
		available = MC.batch_qty(batch, source, r.item_code) if batch else \
			flt(MC.bin_qty([r.item_code], source).get(r.item_code))
		rows.append({
			"mr_item": r.name, "item_code": r.item_code, "item_name": r.item_name,
			"uom": r.stock_uom or r.uom, "material_type": r.custom_material_type or i.get("material_type"),
			"required_qty": pending, "qty": pending, "available_qty": available,
			"has_batch_no": cint(i.get("has_batch_no")), "batch_no": batch,
			"s_warehouse": source, "t_warehouse": wip, "line_remarks": "",
		})
	return {
		"material_request": mr.name, "sub_order": mr.get(SUB_FIELD),
		"parent": mr.custom_parent_production_order, "fg_item": mr.custom_target_fg_item,
		"fg_item_name": frappe.db.get_value("Item", mr.custom_target_fg_item, "item_name"),
		"production_type": mr.custom_production_type, "mr_status": mr.custom_mr_status,
		"rows": rows,
	}


def _safe(fn):
	try:
		return fn()
	except frappe.ValidationError:
		frappe.local.message_log = []
		return None


def returns_of(issue_name):
	rows = frappe.get_all(SE, filters={"custom_material_issue": issue_name,
	                                  "custom_entry_kind": M.KIND_RETURN},
	                      fields=["name", "posting_date", "docstatus", "owner"],
	                      order_by="creation asc")
	for r in rows:
		r["status"] = MC.se_status(r.docstatus)
		r["by"] = get_fullname(r.owner)
		r["qty"] = flt(frappe.db.sql(
			"select sum(qty) from `tabStock Entry Detail` where parent=%s", r.name)[0][0])
	return rows


@frappe.whitelist()
def get_mi_context(stock_entry=None):
	MC.assert_may_read()
	may_write, may_manage = MC.may_write(), MC.may_manage()
	ctx = {"main_warehouse": _safe(main_warehouse), "wip_warehouse": _safe(wip_warehouse)}
	if not stock_entry:
		ctx.update({"doc": None, "can_write": int(may_write), "can_submit": 0, "can_cancel": 0,
		            "can_return": 0, "issued_by": get_fullname(frappe.session.user), "returns": []})
		return ctx
	doc = frappe.get_doc(SE, stock_entry)
	if not is_issue(doc):
		frappe.throw(_("{0} is not a Material Issue.").format(stock_entry), title=_("Not A Material Issue"))
	info = MC.item_info([r.item_code for r in doc.items])
	returns = returns_of(doc.name)
	submitted_returns = [r for r in returns if cint(r.docstatus) == 1]
	draft = cint(doc.docstatus) == 0
	has_balance = False
	if cint(doc.docstatus) == 1:
		from alpinos.production.material_return import returned_by_row
		done = returned_by_row(doc.name)
		has_balance = any(flt(r.qty) - flt(done.get(r.name)) > 0 for r in doc.items)
	ctx.update({
		"doc": {
			"name": doc.name, "material_request": doc.get("custom_material_request"),
			"sub_order": doc.get(SUB_FIELD), "parent": doc.get("custom_parent_production_order"),
			"fg_item": doc.get("custom_target_fg_item"),
			"fg_item_name": frappe.db.get_value("Item", doc.get("custom_target_fg_item"), "item_name"),
			"production_type": doc.get("custom_production_type"),
			"posting_date": doc.posting_date, "remarks": doc.remarks or "",
			"docstatus": doc.docstatus, "status": MC.se_status(doc.docstatus),
			"issued_by": get_fullname(doc.owner),
			"items": [{
				"name": r.name, "mr_item": r.get("custom_mr_item"), "item_code": r.item_code,
				"item_name": r.item_name, "uom": r.stock_uom or r.uom,
				"material_type": r.get("custom_material_type"),
				"required_qty": flt(r.get("custom_required_qty")), "qty": flt(r.qty),
				"available_qty": flt(r.get("custom_available_qty")),
				"has_batch_no": cint((info.get(r.item_code) or {}).get("has_batch_no")),
				"batch_no": r.get("batch_no"), "s_warehouse": r.s_warehouse,
				"t_warehouse": r.t_warehouse, "line_remarks": r.get("custom_line_remarks") or "",
			} for r in doc.items],
		},
		"can_write": int(draft and may_write),
		"can_submit": int(draft and may_write),
		"can_cancel": int(cint(doc.docstatus) == 1 and may_manage and not submitted_returns
		                  and not [r for r in returns if cint(r.docstatus) == 0]),
		"can_return": int(cint(doc.docstatus) == 1 and may_write and has_balance),
		"can_delete": int(draft and may_write),
		"returns": returns,
	})
	return ctx


@frappe.whitelist()
def save_mi(payload):
	MC.assert_may_write()
	p = MC.parse(payload)
	if p.get("name"):
		doc = frappe.get_doc(SE, p.name)
		if not is_issue(doc) or cint(doc.docstatus) != 0:
			frappe.throw(_("{0} is not a draft Material Issue.").format(p.name), title=_("Not A Draft"))
	else:
		doc = frappe.new_doc(SE)
		doc.naming_series = M.MI_NAMING_SERIES
		doc.set("custom_entry_kind", M.KIND_ISSUE)

	mr = _check_mr(p.get("material_request") or doc.get("custom_material_request"))
	doc.set("custom_material_request", mr.name)
	doc.purpose = M.ISSUE_PURPOSE
	doc.stock_entry_type = M.ISSUE_PURPOSE
	doc.company = mr.company
	posting_date = p.get("posting_date") or nowdate()
	if getdate(posting_date) > getdate(nowdate()):
		frappe.throw(_("The Issue Date cannot be in the future."), title=_("Invalid Issue Date"))
	doc.posting_date = posting_date
	doc.set_posting_time = 1 if getdate(posting_date) != getdate(nowdate()) else 0
	doc.remarks = p.get("remarks") or ""
	wip = wip_warehouse()
	doc.to_warehouse = wip

	# Zero rows are dropped here, before anything is validated: "not issuing this one today"
	# is an ordinary thing to do, and a row with nothing on it moves nothing.
	rows = [frappe._dict(r) for r in (p.get("items") or []) if flt((r or {}).get("qty")) > 0]
	if not rows:
		frappe.throw(_("Enter an Actual Issue Qty on at least one row."), title=_("Nothing To Issue"))
	mr_rows = _mr_rows(mr.name)
	sources = {r.get("s_warehouse") for r in rows if r.get("s_warehouse")}
	doc.from_warehouse = sources.pop() if len(sources) == 1 else None
	doc.set("items", [])
	for r in rows:
		src = mr_rows.get(r.get("mr_item"))
		if not src:
			frappe.throw(_("{0} is not a row of Material Request {1}.").format(
				r.get("item_code"), mr.name), title=_("Row Not In Request"))
		doc.append("items", {
			"item_code": src.item_code,
			"item_name": src.item_name,
			"qty": flt(r.qty),
			"uom": src.stock_uom or src.uom,
			"stock_uom": src.stock_uom or src.uom,
			"conversion_factor": 1,
			"transfer_qty": flt(r.qty),
			"s_warehouse": r.get("s_warehouse") or src.from_warehouse,
			"t_warehouse": r.get("t_warehouse") or wip,
			"batch_no": r.get("batch_no") or None,
			"use_serial_batch_fields": 1 if r.get("batch_no") else 0,
			"custom_mr_item": src.name,
			"custom_material_type": src.custom_material_type,
			"custom_line_remarks": r.get("line_remarks") or "",
			"material_request": mr.name,
			"material_request_item": src.name,
		})
	doc.flags.alpinos_material = True
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"name": doc.name}


@frappe.whitelist()
def submit_mi(stock_entry):
	MC.assert_may_write()
	doc = frappe.get_doc(SE, stock_entry)
	if not is_issue(doc) or cint(doc.docstatus) != 0:
		frappe.throw(_("{0} is not a draft Material Issue.").format(stock_entry))
	doc.flags.alpinos_material = True
	doc.flags.ignore_permissions = True
	doc.submit()
	frappe.db.commit()
	return {"name": doc.name}


@frappe.whitelist()
def cancel_mi(stock_entry):
	MC.assert_may_manage(_("cancel a Material Issue"))
	doc = frappe.get_doc(SE, stock_entry)
	if not is_issue(doc) or cint(doc.docstatus) != 1:
		frappe.throw(_("{0} is not a submitted Material Issue.").format(stock_entry))
	doc.flags.alpinos_material = True
	doc.flags.ignore_permissions = True
	doc.cancel()
	frappe.db.commit()
	return {"name": doc.name}


@frappe.whitelist()
def delete_entry(stock_entry):
	"""Delete a draft MI or MRT from its screen."""
	MC.assert_may_write()
	doc = frappe.get_doc(SE, stock_entry)
	if not doc.get("custom_entry_kind") or cint(doc.docstatus) != 0:
		frappe.throw(_("Only a draft Material Issue or Material Return can be deleted."))
	frappe.delete_doc(SE, doc.name, ignore_permissions=True)
	frappe.db.commit()
	return {"deleted": stock_entry}
