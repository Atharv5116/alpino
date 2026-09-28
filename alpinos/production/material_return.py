"""Material Return (MRT) -- tasks 25-28.

An MRT is a Stock Entry, purpose "Material Transfer" (NOT Material Receipt -- nothing new
enters the business, it only comes back off the floor), WIP -> Main, marked
custom_entry_kind = "Material Return" and linked to one submitted Material Issue.

Each row points at the issue row it returns (custom_mi_detail). The balance a row may still
return is what that issue row issued minus every submitted return against it; that is
recomputed on every save, so two returns typed at once cannot both take the same balance.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, get_fullname, getdate, nowdate

from alpinos.production import material_common as MC
from alpinos.production import material_constants as M
from alpinos.production.material_request import SUB_FIELD
from alpinos.production.production_settings import main_warehouse, wip_warehouse

SE = M.SE_DOCTYPE

LIST_FIELDS = (
	"name", "custom_material_issue", "custom_material_request", SUB_FIELD,
	"custom_parent_production_order", "custom_target_fg_item", "custom_production_type",
	"posting_date", "docstatus", "owner",
)


def is_return(doc):
	return doc.get("custom_entry_kind") == M.KIND_RETURN


def returned_by_row(issue_name, exclude_entry=None):
	"""{MI row name: qty} already returned by SUBMITTED returns against this issue."""
	conditions = ""
	values = {"mi": issue_name, "kind": M.KIND_RETURN}
	if exclude_entry:
		conditions = "and se.name != %(exclude)s"
		values["exclude"] = exclude_entry
	rows = frappe.db.sql(
		f"""
		select sed.custom_mi_detail as mi_detail, sum(sed.qty) as qty
		from `tabStock Entry Detail` sed
		join `tabStock Entry` se on se.name = sed.parent
		where se.docstatus = 1 and se.custom_entry_kind = %(kind)s
		  and se.custom_material_issue = %(mi)s {conditions}
		group by sed.custom_mi_detail
		""", values, as_dict=True)
	return {r.mi_detail: flt(r.qty) for r in rows if r.mi_detail}


def _check_issue(issue_name):
	if not issue_name:
		frappe.throw(_("A Material Return must be linked to a Material Issue."),
		             title=_("Material Issue Required"))
	mi = frappe.db.get_value(SE, issue_name, [
		"name", "docstatus", "custom_entry_kind", "custom_material_request", SUB_FIELD,
		"custom_parent_production_order", "custom_target_fg_item", "custom_production_type",
		"company"], as_dict=True)
	if not mi or mi.custom_entry_kind != M.KIND_ISSUE:
		frappe.throw(_("{0} is not a Material Issue.").format(issue_name), title=_("Wrong Document"))
	if cint(mi.docstatus) != 1:
		frappe.throw(_("Material Issue {0} is not submitted, so nothing can be returned against it.").format(
			issue_name), title=_("Issue Not Submitted"))
	return mi


def _mi_rows(issue_name):
	return {r.name: r for r in frappe.get_all(
		"Stock Entry Detail", filters={"parent": issue_name, "parenttype": SE},
		fields=["name", "idx", "item_code", "item_name", "qty", "uom", "stock_uom", "batch_no",
		        "custom_material_type", "t_warehouse", "s_warehouse"],
		order_by="idx asc")}


def validate_return(doc):
	mi = _check_issue(doc.get("custom_material_issue"))
	doc.purpose = M.RETURN_PURPOSE
	doc.stock_entry_type = M.RETURN_PURPOSE
	doc.work_order = None
	doc.company = mi.company or doc.company
	doc.set("custom_material_request", mi.custom_material_request)
	doc.set(SUB_FIELD, mi.get(SUB_FIELD))
	doc.set("custom_parent_production_order", mi.custom_parent_production_order)
	doc.set("custom_target_fg_item", mi.custom_target_fg_item)
	doc.set("custom_production_type", mi.custom_production_type)

	if doc.posting_date and getdate(doc.posting_date) > getdate(nowdate()):
		frappe.throw(_("The Return Date cannot be in the future."), title=_("Invalid Return Date"))

	rows = doc.get("items") or []
	if not rows:
		frappe.throw(_("Enter a Return Qty on at least one row."), title=_("Nothing To Return"))

	mi_rows = _mi_rows(mi.name)
	returned = returned_by_row(mi.name, exclude_entry=None if doc.is_new() else doc.name)
	reason_all = doc.get("custom_return_reason_all")
	claimed = {}

	for r in rows:
		src = mi_rows.get(r.get("custom_mi_detail"))
		if not src or src.item_code != r.item_code:
			frappe.throw(_("Row {0}: {1} is not a row of Material Issue {2}.").format(
				r.idx, r.item_code, mi.name), title=_("Row Not In Issue"))
		uom = src.stock_uom or src.uom or ""
		if flt(r.qty) <= 0:
			frappe.throw(_("Row {0}: the Return Qty of {1} must be greater than 0.").format(
				r.idx, r.item_code), title=_("Return Qty Required"))
		already = flt(returned.get(src.name))
		balance = max(flt(src.qty) - already - flt(claimed.get(src.name)), 0)
		if flt(r.qty) > balance + 0.0000001:
			frappe.throw(
				_("Row {0}: you can return at most {1} {2}; {3} was issued and {4} already returned.").format(
					r.idx, flt(balance), uom, flt(src.qty), already + flt(claimed.get(src.name))),
				title=_("More Than Issued"))
		claimed[src.name] = flt(claimed.get(src.name)) + flt(r.qty)

		if not r.get("custom_return_reason") and reason_all:
			r.custom_return_reason = reason_all
		if not r.get("custom_return_reason"):
			frappe.throw(_("Row {0}: choose a Return Reason for {1}.").format(r.idx, r.item_code),
			             title=_("Reason Required"))
		if r.custom_return_reason not in M.RETURN_REASONS:
			frappe.throw(_("Row {0}: {1} is not a valid Return Reason.").format(
				r.idx, r.custom_return_reason), title=_("Invalid Reason"))
		if r.custom_return_reason == M.RETURN_REASON_OTHER and not (r.get("custom_line_remarks") or "").strip():
			frappe.throw(_("Row {0}: the reason is Other, so please write a remark saying why.").format(r.idx),
			             title=_("Remark Required"))
		if not r.s_warehouse:
			frappe.throw(_("Row {0}: choose the warehouse {1} is returned from.").format(r.idx, r.item_code),
			             title=_("Source Warehouse Required"))
		if not r.t_warehouse:
			frappe.throw(_("Row {0}: choose the warehouse {1} is returned to.").format(r.idx, r.item_code),
			             title=_("Target Warehouse Required"))
		if r.s_warehouse == r.t_warehouse:
			frappe.throw(_("Row {0}: the source and target warehouse cannot be the same.").format(r.idx),
			             title=_("Same Warehouse"))
		# The same batch that went out comes back: a return is not a place to swap batches.
		r.batch_no = src.batch_no or None
		if r.batch_no:
			r.use_serial_batch_fields = 1

		r.custom_material_type = r.get("custom_material_type") or src.custom_material_type
		r.custom_previously_returned = already
		r.custom_balance_return = max(flt(src.qty) - already, 0)
		r.custom_required_qty = flt(src.qty)


# ================================================================== screens

@frappe.whitelist()
def get_mrt_list(search=None, status=None, material_issue=None, sub_order=None, parent=None,
                 fg_item=None, date_from=None, date_to=None, start=0,
                 page_length=M.DEFAULT_PAGE_LENGTH):
	MC.assert_may_read()
	from alpinos.production.material_issue import _entry_list
	return _entry_list(M.KIND_RETURN, LIST_FIELDS, search, status, sub_order, parent, fg_item,
	                   date_from, date_to, start, page_length,
	                   extra={"custom_material_issue": material_issue} if material_issue else None)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def mi_query(doctype, txt, searchfield, start, page_len, filters):
	"""Submitted Material Issues that still have something left to return."""
	rows = frappe.db.sql(
		f"""
		select se.name, se.{SUB_FIELD}, se.custom_target_fg_item,
		       sum(sed.qty) as issued,
		       (select ifnull(sum(rd.qty), 0)
		          from `tabStock Entry Detail` rd join `tabStock Entry` r on r.name = rd.parent
		         where r.docstatus = 1 and r.custom_entry_kind = %(ret)s
		           and r.custom_material_issue = se.name) as returned
		from `tabStock Entry` se
		join `tabStock Entry Detail` sed on sed.parent = se.name
		where se.docstatus = 1 and se.custom_entry_kind = %(iss)s
		  and (se.name like %(txt)s or se.{SUB_FIELD} like %(txt)s)
		group by se.name
		having issued > returned
		order by se.posting_date desc, se.name desc
		limit %(start)s, %(page_len)s
		""",
		{"iss": M.KIND_ISSUE, "ret": M.KIND_RETURN, "txt": f"%{txt or ''}%",
		 "start": cint(start), "page_len": cint(page_len) or 20},
	)
	return [(r[0], r[1], r[2]) for r in rows]


def _safe(fn):
	try:
		return fn()
	except frappe.ValidationError:
		frappe.local.message_log = []
		return None


@frappe.whitelist()
def issue_balance_rows(material_issue):
	"""Header and grid for a new MRT: the issue's rows that still have a balance."""
	MC.assert_may_read()
	mi = _check_issue(material_issue)
	returned = returned_by_row(mi.name)
	main = _safe(main_warehouse)
	wip = _safe(wip_warehouse)
	rows = []
	for r in _mi_rows(mi.name).values():
		already = flt(returned.get(r.name))
		balance = max(flt(r.qty) - already, 0)
		if balance <= 0:
			continue
		rows.append({
			"mi_detail": r.name, "item_code": r.item_code, "item_name": r.item_name,
			"uom": r.stock_uom or r.uom, "material_type": r.custom_material_type,
			"batch_no": r.batch_no, "issued_qty": flt(r.qty), "previously_returned": already,
			"balance": balance, "qty": 0, "reason": "",
			"s_warehouse": r.t_warehouse or wip, "t_warehouse": r.s_warehouse or main,
			"line_remarks": "",
		})
	return {
		"material_issue": mi.name, "material_request": mi.custom_material_request,
		"sub_order": mi.get(SUB_FIELD), "parent": mi.custom_parent_production_order,
		"fg_item": mi.custom_target_fg_item,
		"fg_item_name": frappe.db.get_value("Item", mi.custom_target_fg_item, "item_name"),
		"production_type": mi.custom_production_type, "rows": rows,
	}


@frappe.whitelist()
def get_mrt_context(stock_entry=None):
	MC.assert_may_read()
	may_write, may_manage = MC.may_write(), MC.may_manage()
	ctx = {"reasons": list(M.RETURN_REASONS), "main_warehouse": _safe(main_warehouse),
	       "wip_warehouse": _safe(wip_warehouse)}
	if not stock_entry:
		ctx.update({"doc": None, "can_write": int(may_write), "can_submit": 0, "can_cancel": 0,
		            "returned_by": get_fullname(frappe.session.user)})
		return ctx
	doc = frappe.get_doc(SE, stock_entry)
	if not is_return(doc):
		frappe.throw(_("{0} is not a Material Return.").format(stock_entry), title=_("Not A Material Return"))
	draft = cint(doc.docstatus) == 0
	ctx.update({
		"doc": {
			"name": doc.name, "material_issue": doc.get("custom_material_issue"),
			"material_request": doc.get("custom_material_request"),
			"sub_order": doc.get(SUB_FIELD), "parent": doc.get("custom_parent_production_order"),
			"fg_item": doc.get("custom_target_fg_item"),
			"fg_item_name": frappe.db.get_value("Item", doc.get("custom_target_fg_item"), "item_name"),
			"production_type": doc.get("custom_production_type"),
			"posting_date": doc.posting_date, "remarks": doc.remarks or "",
			"reason_all": doc.get("custom_return_reason_all") or "",
			"docstatus": doc.docstatus, "status": MC.se_status(doc.docstatus),
			"returned_by": get_fullname(doc.owner),
			"items": [{
				"name": r.name, "mi_detail": r.get("custom_mi_detail"), "item_code": r.item_code,
				"item_name": r.item_name, "uom": r.stock_uom or r.uom,
				"material_type": r.get("custom_material_type"), "batch_no": r.get("batch_no"),
				"issued_qty": flt(r.get("custom_required_qty")),
				"previously_returned": flt(r.get("custom_previously_returned")),
				"balance": flt(r.get("custom_balance_return")), "qty": flt(r.qty),
				"reason": r.get("custom_return_reason") or "",
				"s_warehouse": r.s_warehouse, "t_warehouse": r.t_warehouse,
				"line_remarks": r.get("custom_line_remarks") or "",
			} for r in doc.items],
		},
		"can_write": int(draft and may_write),
		"can_submit": int(draft and may_write),
		"can_cancel": int(cint(doc.docstatus) == 1 and may_manage),
		"can_delete": int(draft and may_write),
	})
	return ctx


@frappe.whitelist()
def save_mrt(payload):
	MC.assert_may_write()
	p = MC.parse(payload)
	if p.get("name"):
		doc = frappe.get_doc(SE, p.name)
		if not is_return(doc) or cint(doc.docstatus) != 0:
			frappe.throw(_("{0} is not a draft Material Return.").format(p.name), title=_("Not A Draft"))
	else:
		doc = frappe.new_doc(SE)
		doc.naming_series = M.MRT_NAMING_SERIES
		doc.set("custom_entry_kind", M.KIND_RETURN)

	mi = _check_issue(p.get("material_issue") or doc.get("custom_material_issue"))
	doc.set("custom_material_issue", mi.name)
	doc.purpose = M.RETURN_PURPOSE
	doc.stock_entry_type = M.RETURN_PURPOSE
	doc.company = mi.company
	posting_date = p.get("posting_date") or nowdate()
	if getdate(posting_date) > getdate(nowdate()):
		frappe.throw(_("The Return Date cannot be in the future."), title=_("Invalid Return Date"))
	doc.posting_date = posting_date
	doc.set_posting_time = 1 if getdate(posting_date) != getdate(nowdate()) else 0
	doc.remarks = p.get("remarks") or ""
	doc.set("custom_return_reason_all", p.get("reason_all") or "")

	rows = [frappe._dict(r) for r in (p.get("items") or []) if flt((r or {}).get("qty")) > 0]
	if not rows:
		frappe.throw(_("Enter a Return Qty on at least one row."), title=_("Nothing To Return"))
	mi_rows = _mi_rows(mi.name)
	doc.from_warehouse = None
	doc.to_warehouse = None
	doc.set("items", [])
	for r in rows:
		src = mi_rows.get(r.get("mi_detail"))
		if not src:
			frappe.throw(_("{0} is not a row of Material Issue {1}.").format(r.get("item_code"), mi.name),
			             title=_("Row Not In Issue"))
		doc.append("items", {
			"item_code": src.item_code,
			"item_name": src.item_name,
			"qty": flt(r.qty),
			"uom": src.stock_uom or src.uom,
			"stock_uom": src.stock_uom or src.uom,
			"conversion_factor": 1,
			"transfer_qty": flt(r.qty),
			"s_warehouse": r.get("s_warehouse") or src.t_warehouse,
			"t_warehouse": r.get("t_warehouse") or src.s_warehouse,
			"batch_no": src.batch_no or None,
			"use_serial_batch_fields": 1 if src.batch_no else 0,
			"custom_mi_detail": src.name,
			"custom_material_type": src.custom_material_type,
			"custom_return_reason": r.get("reason") or p.get("reason_all") or "",
			"custom_line_remarks": r.get("line_remarks") or "",
		})
	doc.flags.alpinos_material = True
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"name": doc.name}


@frappe.whitelist()
def submit_mrt(stock_entry):
	MC.assert_may_write()
	doc = frappe.get_doc(SE, stock_entry)
	if not is_return(doc) or cint(doc.docstatus) != 0:
		frappe.throw(_("{0} is not a draft Material Return.").format(stock_entry))
	doc.flags.alpinos_material = True
	doc.flags.ignore_permissions = True
	doc.submit()
	frappe.db.commit()
	return {"name": doc.name}


@frappe.whitelist()
def cancel_mrt(stock_entry):
	MC.assert_may_manage(_("cancel a Material Return"))
	doc = frappe.get_doc(SE, stock_entry)
	if not is_return(doc) or cint(doc.docstatus) != 1:
		frappe.throw(_("{0} is not a submitted Material Return.").format(stock_entry))
	doc.flags.alpinos_material = True
	doc.flags.ignore_permissions = True
	doc.cancel()
	frappe.db.commit()
	return {"name": doc.name}
