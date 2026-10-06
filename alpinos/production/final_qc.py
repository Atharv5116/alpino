"""Post-Filling QC (Final QC) -- FRD Phase 9.

Every FG batch made by a Filling Inward starts FG-Hold in the FG Hold warehouse. A Final QC
inspects one batch and ends in one of three decisions (9.1):

    Approve Batch    approved pcs -> FG warehouse, batch FG-Cleared
    Reject Batch     every pc -> Rejected warehouse, batch QC-Rejected
    Partial Approval approved -> FG warehouse, rejected -> Rejected warehouse, batch FG-Cleared

The destructive sample is written off (Material Issue) in every case (9.2). A Lab Test left
Pending saves the form only; the batch stays FG-Hold (9.4.1). A QC Manager can Revoke an
approval unless the batch is on an active Delivery Note (9.4.2). Rejections in the Chance of
Repair / Improvement Required categories open a rework Sub PO under the same Parent.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime, nowdate

from alpinos.production import filling_common as F


# ------------------------------------------------------------------------ helpers

def _batch(batch_no):
	fields = ["name", "item", "manufacturing_date", "disabled"]
	for f in (F.B_SUB, F.B_PARENT, F.B_STATUS, F.B_LINE, F.B_INWARD):
		if F.has_field("Batch", f):
			fields.append(f)
	row = frappe.db.get_value("Batch", batch_no, fields, as_dict=True)
	if not row:
		frappe.throw(_("Batch {0} does not exist.").format(batch_no), title=_("Unknown Batch"))
	return row


def hold_qty(batch_no, item=None):
	try:
		wh = F.S().fg_hold_warehouse()
	except Exception:
		return 0
	return cint(round(F.batch_qty(batch_no, wh, item)))


def batch_details(batch_no):
	b = _batch(batch_no)
	return {
		"fg_batch": b.name,
		"target_sku": b.item,
		"sku_name": F.sku_name(b.item),
		"size_kg": F.pack_size(b.item),
		"filling_line": b.get(F.B_LINE),
		"line_label": frappe.db.get_value("Machine", b.get(F.B_LINE), "machine_name") if b.get(F.B_LINE) else "",
		"production_date": b.manufacturing_date,
		"filling_inward": b.get(F.B_INWARD),
		"sub_order": b.get(F.B_SUB),
		"parent_po": b.get(F.B_PARENT),
		"fg_status": b.get(F.B_STATUS),
		"total_inward_pcs": hold_qty(b.name, b.item),
	}


def batch_on_active_dn(batch_no):
	"""Delivery Notes (draft or submitted) that carry this batch -- FRD 9.4.2."""
	found = set(frappe.get_all("Delivery Note Item", filters={"batch_no": batch_no, "docstatus": ("<", 2)},
	                           pluck="parent"))
	if frappe.db.exists("DocType", "Serial and Batch Entry"):
		for r in frappe.db.sql(
				"""
				select b.voucher_no from `tabSerial and Batch Entry` e
				join `tabSerial and Batch Bundle` b on b.name = e.parent
				where e.batch_no = %s and b.voucher_type = 'Delivery Note' and b.docstatus < 2
				  and ifnull(b.is_cancelled, 0) = 0
				""", batch_no):
			if r[0] and cint(frappe.db.get_value("Delivery Note", r[0], "docstatus")) < 2:
				found.add(r[0])
	return sorted(found)


def _set_batch_status(batch_no, status):
	if F.has_field("Batch", F.B_STATUS):
		frappe.db.set_value("Batch", batch_no, F.B_STATUS, status, update_modified=False)


# --------------------------------------------------------------------- validation

def validate_qc(doc):
	if not doc.flags.get("alpinos_final_qc"):
		frappe.throw(_("Final QC is recorded on the Final QC screen."), title=_("Use The Final QC Screen"))
	if cint(doc.docstatus) != 0:
		return
	if not doc.fg_batch:
		frappe.throw(_("Please choose the FG Batch Code."), title=_("Batch Required"))
	details = batch_details(doc.fg_batch)
	if details["fg_status"] != F.FG_HOLD:
		frappe.throw(_("Batch {0} is {1}. Only FG-Hold batches go through Final QC.").format(
			doc.fg_batch, details["fg_status"] or _("not an FG batch")), title=_("Not On Hold"))
	other = frappe.get_all(F.FINAL_QC, filters={"fg_batch": doc.fg_batch, "docstatus": ("<", 2),
	                                            "name": ("!=", doc.name or "")}, pluck="name", limit=1)
	if other:
		frappe.throw(_("Batch {0} already has Final QC {1}. Open that one instead.").format(
			doc.fg_batch, other[0]), title=_("Duplicate Final QC"))
	for key in ("target_sku", "sku_name", "filling_line", "production_date", "filling_inward",
	            "sub_order", "parent_po", "size_kg", "total_inward_pcs"):
		doc.set(key, details[key])

	if not doc.get("tests"):
		for test in F.STANDARD_TESTS:
			doc.append("tests", {"test_name": test})
	for row in doc.tests:
		if row.test_result and row.test_result not in (F.TEST_PASS, F.TEST_FAIL, F.TEST_PENDING):
			row.test_result = ""
	for f in ("approved_pcs", "rejected_pcs", "sample_size"):
		doc.set(f, cint(doc.get(f)))
		if doc.get(f) < 0:
			frappe.throw(_("Quantities cannot be negative."), title=_("Invalid Quantity"))
	pending = any(r.test_result == F.TEST_PENDING for r in doc.tests)
	doc.qc_status = F.QC_PENDING_LAB if pending else F.QC_DRAFT
	doc.inspector = doc.inspector or frappe.session.user


def before_submit_qc(doc):
	"""The decision rules (9.1, 9.2.1 VAL-QC-01..03, 9.4.1)."""
	if doc.decision not in F.DECISIONS:
		frappe.throw(_("Choose Approve Batch, Reject Batch or Partial Approval."), title=_("Decision Required"))
	tests = doc.get("tests") or []
	if any(r.test_result == F.TEST_PENDING for r in tests):
		frappe.throw(_("A test is still Pending. Save the form and come back when the result is in; "
		               "the batch stays FG-Hold."), title=_("Lab Test Pending"))
	missing = [r.test_name for r in tests if not r.test_result]
	if missing:
		frappe.throw(_("Enter a result for: {0}.").format(", ".join(missing)), title=_("Test Result Missing"))
	if any(r.test_result == F.TEST_FAIL for r in tests) and not (doc.qc_remarks or "").strip():
		frappe.throw(_("QC Remarks are mandatory when any parameter is marked Fail."),
		             title=_("QC Remarks Required"))
	if doc.filling_inward and frappe.db.get_value(F.INWARD, doc.filling_inward, "approval_status") == \
			F.APPROVAL_PENDING:
		frappe.throw(_("Filling wastage on {0} is awaiting approval by the Production Manager. The batch "
		               "cannot be released until it is approved.").format(doc.filling_inward),
		             title=_("Awaiting Wastage Approval"))

	total = hold_qty(doc.fg_batch, doc.target_sku)
	doc.total_inward_pcs = total
	approved, rejected, sample = cint(doc.approved_pcs), cint(doc.rejected_pcs), cint(doc.sample_size)
	if doc.decision == F.DECISION_PARTIAL and approved <= 0:
		frappe.throw(_(F.MSG_VAL_QC_03), title=_("Approved Quantity Required"))
	if approved + rejected + sample != total:
		frappe.throw(_(F.MSG_VAL_QC_01) + " " + _("({0} + {1} + {2} vs {3} pcs in FG Hold)").format(
			approved, rejected, sample, total), title=_("QC Quantity Mismatch"))
	if rejected > 0 and not doc.rejection_reason:
		frappe.throw(_(F.MSG_VAL_QC_02), title=_("Rejection Reason Required"))
	if doc.decision == F.DECISION_APPROVE and rejected > 0:
		frappe.throw(_("Some pieces are rejected. Use Partial Approval instead."), title=_("Use Partial Approval"))
	if doc.decision == F.DECISION_APPROVE and approved <= 0:
		frappe.throw(_("Approved Quantity must be greater than zero to approve the batch."),
		             title=_("Approved Quantity Required"))
	if doc.decision == F.DECISION_REJECT and approved > 0:
		frappe.throw(_("Reject Batch rejects every piece. Use Partial Approval to approve some."),
		             title=_("Use Partial Approval"))
	if doc.decision == F.DECISION_PARTIAL and rejected <= 0:
		frappe.throw(_("Nothing is rejected. Use Approve Batch instead."), title=_("Use Approve Batch"))
	if rejected > 0:
		if doc.rejection_category not in F.REJECTION_CATEGORIES:
			frappe.throw(_("Choose the rejection category: Direct Reject, Chance of Repair or "
			               "Improvement Required."), title=_("Rejection Category Required"))
		if doc.rejection_category in F.REWORK_CATEGORIES:
			if flt(doc.rework_qty_kg) <= 0 or not doc.rework_process or not (doc.rework_remark or "").strip():
				frappe.throw(_("{0} needs the rework Quantity (KG), Process and Remark.").format(
					doc.rejection_category), title=_("Rework Details Required"))
	doc.inspector = doc.inspector or frappe.session.user
	doc.inspected_on = now_datetime()


def on_submit_qc(doc):
	settings = F.S()
	hold = settings.fg_hold_warehouse()
	approved, rejected, sample = cint(doc.approved_pcs), cint(doc.rejected_pcs), cint(doc.sample_size)
	company = frappe.db.get_value(F.WORK_ORDER, doc.sub_order, "company") if doc.sub_order else None
	common = dict(company=company, posting_date=nowdate(), sub=doc.sub_order, parent=doc.parent_po,
	              fg_item=doc.target_sku)
	rows = []
	if approved:
		rows.append({"item_code": doc.target_sku, "qty": approved, "s_warehouse": hold,
		             "t_warehouse": settings.fg_warehouse(), "batch_no": doc.fg_batch})
	if rejected:
		rows.append({"item_code": doc.target_sku, "qty": rejected, "s_warehouse": hold,
		             "t_warehouse": settings.rejected_warehouse(), "batch_no": doc.fg_batch})
	transfer = F.make_stock_entry("Material Transfer", rows, remarks=_("Final QC {0}").format(doc.name),
	                              **common) if rows else None
	sample_entry = None
	if sample:
		sample_entry = F.make_stock_entry(
			"Material Issue", [{"item_code": doc.target_sku, "qty": sample, "s_warehouse": hold,
			                    "batch_no": doc.fg_batch}],
			remarks=_("Final QC {0}: destructive test sample").format(doc.name), **common)

	status = {F.DECISION_APPROVE: F.QC_APPROVED, F.DECISION_REJECT: F.QC_REJECTED_STATUS,
	          F.DECISION_PARTIAL: F.QC_PARTIAL}[doc.decision]
	_set_batch_status(doc.fg_batch, F.QC_REJECTED if doc.decision == F.DECISION_REJECT else F.FG_CLEARED)

	rework = None
	if rejected and doc.rejection_category in F.REWORK_CATEGORIES:
		rework = _create_rework_sub_order(doc)

	doc.db_set({"qc_status": status, "transfer_entry": transfer, "sample_entry": sample_entry,
	            "rework_sub_order": rework}, update_modified=False)

	user = frappe.utils.get_fullname(frappe.session.user) or frappe.session.user
	at = frappe.utils.format_datetime(now_datetime(), "dd-MM-yyyy HH:mm")
	if approved:
		F.notify((F.ROLE_QC_MANAGER, F.C.ROLE_PRODUCTION_MANAGER, F.ROLE_PLANT_HEAD, "Store Manager"),
		         _("{0} Batch {1} cleared by {2} at {3}").format(doc.sku_name or doc.target_sku,
		                                                         doc.fg_batch, user, at),
		         "Batch", doc.fg_batch)
	if rejected:
		F.notify((F.ROLE_PLANT_HEAD, F.C.ROLE_PRODUCTION_MANAGER),
		         _("Material Review Required: {0} pcs of batch {1} ({2}) rejected in Final QC {3} - {4}").format(
			         rejected, doc.fg_batch, doc.sku_name or doc.target_sku, doc.name,
			         doc.rejection_category or doc.rejection_reason),
		         F.FINAL_QC, doc.name, email=True)
	F.audit(F.FINAL_QC, doc.name, doc.decision,
	        _("approved {0}, rejected {1}, sample {2} of batch {3}").format(approved, rejected, sample, doc.fg_batch),
	        doc.qc_remarks or "")
	if rework:
		F.audit(F.FINAL_QC, doc.name, "Rework Sub PO", _("{0} created for {1} KG").format(rework, doc.rework_qty_kg))


def _create_rework_sub_order(doc):
	"""default pending BA confirmation: a rework (Chance of Repair / Improvement Required) is
	a new Sub PO of the same Parent, same bulk item / BOM, qty = rework KG, Unassigned and
	unlocked, created the way sub_order.split_sub_order creates one (next letter via
	AlpinosWorkOrder.autoname). It is outside BR-PO-03's 'sub orders add up to the Parent'."""
	from alpinos.production.work_order_naming import next_suffix
	from alpinos.production.work_order_fields import (
		BATCH_FIELD, CLIENT_FIELD, EXECUTION_STATUS_FIELD, IS_LOCKED_FIELD, PARENT_FIELD,
		PRODUCTION_TYPE_FIELD, SPLIT_FROM_FIELD)

	if not doc.sub_order:
		frappe.throw(_("Batch {0} is not linked to a Sub-PO, so no rework order can be made.").format(
			doc.fg_batch), title=_("No Sub-PO"))
	src = frappe.get_doc(F.WORK_ORDER, doc.sub_order)
	parent = src.get(PARENT_FIELD)
	if not next_suffix(parent):
		frappe.throw(_("{0} already has as many sub orders as the naming allows.").format(parent),
		             title=_("Too Many Sub Orders"))
	new = frappe.new_doc(F.WORK_ORDER)
	new.set(PARENT_FIELD, parent)
	new.production_item = src.production_item
	# frappe.new_doc pre-fills stock_uom from the global default (Nos), and fetch_from does
	# not overwrite it, so a KG bulk item would fail "cannot be a fraction for UOM Nos".
	new.stock_uom = frappe.db.get_value("Item", src.production_item, "stock_uom") or src.stock_uom
	new.bom_no = src.bom_no
	new.qty = flt(doc.rework_qty_kg, 3)
	new.company = src.company
	new.fg_warehouse = src.fg_warehouse
	new.skip_transfer = 1
	new.planned_start_date = now_datetime()
	new.expected_delivery_date = src.expected_delivery_date
	new.set(BATCH_FIELD, src.get(BATCH_FIELD))
	new.set(PRODUCTION_TYPE_FIELD, src.get(PRODUCTION_TYPE_FIELD))
	new.set(CLIENT_FIELD, src.get(CLIENT_FIELD))
	new.set(EXECUTION_STATUS_FIELD, "Unassigned")
	new.set(IS_LOCKED_FIELD, 0)
	new.set(SPLIT_FROM_FIELD, None)
	new.flags.alpinos_sub_order = True
	new.insert(ignore_permissions=True)
	process_label = frappe.db.get_value("Process Master", doc.rework_process, "process_name") or doc.rework_process
	frappe.get_doc({
		"doctype": "Comment", "comment_type": "Comment",
		"reference_doctype": F.WORK_ORDER, "reference_name": new.name,
		"content": frappe.utils.escape_html(
			_("Rework ({0}) from Final QC {1}, batch {2}, Sub-PO {3}. Process: {4}. {5}").format(
				doc.rejection_category, doc.name, doc.fg_batch, doc.sub_order, process_label,
				doc.rework_remark or "")),
	}).insert(ignore_permissions=True)
	return new.name


def before_cancel_qc(doc):
	if not doc.flags.get("alpinos_final_qc"):
		frappe.throw(_("Use Revoke QC Approval on the Final QC screen."), title=_("Not Allowed"))


def on_cancel_qc(doc):
	for name in (doc.sample_entry, doc.transfer_entry):
		F.cancel_stock_entry(name)
	_set_batch_status(doc.fg_batch, F.FG_HOLD)
	doc.db_set("qc_status", F.QC_REVOKED, update_modified=False)


# ------------------------------------------------------------------------ actions

def _apply(doc, p):
	for f in ("approved_pcs", "rejected_pcs", "sample_size"):
		if f in p:
			doc.set(f, cint(p.get(f)))
	for f in ("rejection_reason", "rejection_category", "rework_process", "rework_remark", "qc_remarks"):
		if f in p:
			doc.set(f, p.get(f) or None)
	if "rework_qty_kg" in p:
		doc.rework_qty_kg = flt(p.get("rework_qty_kg"))
	if p.get("tests") is not None:
		doc.set("tests", [])
		for t in p.get("tests") or []:
			t = frappe._dict(t)
			if t.get("test_name"):
				doc.append("tests", {"test_name": t.test_name, "test_result": t.get("test_result") or "",
				                     "test_remarks": t.get("test_remarks") or ""})


def _load(p):
	if p.get("name"):
		doc = frappe.get_doc(F.FINAL_QC, p.name)
		if cint(doc.docstatus) != 0:
			frappe.throw(_("{0} is already decided.").format(doc.name), title=_("Not A Draft"))
	else:
		doc = frappe.new_doc(F.FINAL_QC)
		doc.fg_batch = p.get("fg_batch")
	return doc


@frappe.whitelist()
def save_qc(payload):
	"""Save without a decision (e.g. Lab Test Pending -- 9.4.1)."""
	F.require(F.QC_ROLES, _("record Final QC"))
	p = F.parse(payload)
	doc = _load(p)
	_apply(doc, p)
	doc.flags.alpinos_final_qc = True
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"name": doc.name, "qc_status": doc.qc_status}


@frappe.whitelist()
def decide_qc(payload, decision):
	"""Approve Batch / Reject Batch / Partial Approval."""
	F.require(F.QC_ROLES, _("decide Final QC"))
	p = F.parse(payload)
	doc = _load(p)
	_apply(doc, p)
	doc.decision = decision
	doc.flags.alpinos_final_qc = True
	doc.save(ignore_permissions=True)
	doc.flags.alpinos_final_qc = True
	doc.submit()
	frappe.db.commit()
	doc.reload()
	return {"name": doc.name, "qc_status": doc.qc_status, "rework_sub_order": doc.rework_sub_order}


@frappe.whitelist()
def revoke_qc(final_qc, reason):
	"""Revoke QC Approval (9.4.2): QC Manager only; hard block when on an active Dispatch."""
	F.require(F.QC_MANAGER_ROLES, _("revoke a QC approval"))
	if not (reason or "").strip():
		frappe.throw(_("Please give the reason for revoking."), title=_("Reason Required"))
	doc = frappe.get_doc(F.FINAL_QC, final_qc)
	if cint(doc.docstatus) != 1:
		frappe.throw(_("{0} is not a decided Final QC.").format(final_qc), title=_("Cannot Revoke"))
	dns = batch_on_active_dn(doc.fg_batch)
	if dns:
		frappe.throw(_("Batch {0} is already on Delivery Note {1}. The approval cannot be revoked.").format(
			doc.fg_batch, ", ".join(dns)), title=_("Batch In Dispatch"))
	doc.db_set({"revoke_reason": reason.strip(), "revoked_by": frappe.session.user}, update_modified=False)
	doc.flags.alpinos_final_qc = True
	doc.flags.ignore_permissions = True
	doc.cancel()
	F.audit(F.FINAL_QC, doc.name, "Revoke QC Approval",
	        _("batch {0} back to FG-Hold").format(doc.fg_batch)
	        + (_("; rework Sub PO {0} is left as is").format(doc.rework_sub_order) if doc.rework_sub_order else ""),
	        reason.strip())
	F.audit("Batch", doc.fg_batch, "Revoke QC Approval", doc.name, reason.strip())
	frappe.db.commit()
	return {"revoked": doc.name}


# ------------------------------------------------------------------------ screens

@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def hold_batch_query(doctype, txt, searchfield, start, page_len, filters):
	"""FRD 9.1: only FG batches in FG-Hold."""
	if not F.has_field("Batch", F.B_STATUS):
		return []
	return frappe.db.sql(
		f"""
		select name, item, manufacturing_date from `tabBatch`
		where {F.B_STATUS} = %(hold)s and disabled = 0 and (name like %(txt)s or item like %(txt)s)
		order by creation desc limit %(start)s, %(page_len)s
		""", {"hold": F.FG_HOLD, "txt": f"%{txt or ''}%", "start": cint(start),
		      "page_len": cint(page_len) or 20})


@frappe.whitelist()
def get_batch_info(fg_batch):
	F.require(F.FILLING_READ_ROLES, _("view Final QC"))
	out = batch_details(fg_batch)
	out["existing_qc"] = (frappe.get_all(F.FINAL_QC, filters={"fg_batch": fg_batch, "docstatus": 0},
	                                     pluck="name", limit=1) or [None])[0]
	if out.get("filling_inward"):
		out["approval_status"] = frappe.db.get_value(F.INWARD, out["filling_inward"], "approval_status")
	return out


@frappe.whitelist()
def get_qc_list(search=None, qc_status=None, sku=None, date_from=None, date_to=None, start=0,
                page_length=50):
	F.require(F.FILLING_READ_ROLES, _("view Final QC"))
	filters = {}
	if qc_status:
		filters["qc_status"] = qc_status
	if sku:
		filters["target_sku"] = sku
	if date_from and date_to:
		filters["production_date"] = ("between", [date_from, date_to])
	or_filters = {"name": ("like", f"%{search}%"), "fg_batch": ("like", f"%{search}%")} if search else None
	start, page_length = max(cint(start), 0), min(max(cint(page_length) or 50, 1), 200)
	rows = frappe.get_all(F.FINAL_QC, filters=filters, or_filters=or_filters,
	                      fields=["name", "fg_batch", "target_sku", "sku_name", "filling_line",
	                              "production_date", "total_inward_pcs", "approved_pcs", "rejected_pcs",
	                              "sample_size", "qc_status", "inspector", "inspected_on", "docstatus"],
	                      order_by="modified desc", limit_start=start, limit_page_length=page_length + 1)
	has_more = len(rows) > page_length
	awaiting = []
	if F.has_field("Batch", F.B_STATUS):
		in_qc = set(frappe.get_all(F.FINAL_QC, filters={"docstatus": 0}, pluck="fg_batch"))
		for b in frappe.get_all("Batch", filters={F.B_STATUS: F.FG_HOLD, "disabled": 0},
		                        fields=["name", "item", "manufacturing_date", F.B_LINE, F.B_SUB, F.B_INWARD],
		                        order_by="creation asc", limit_page_length=200):
			qty = hold_qty(b.name, b.item)
			if qty <= 0:
				continue
			b["qty"] = qty
			b["sku_name"] = F.sku_name(b.item)
			b["draft_qc"] = b.name in in_qc
			b["awaiting_approval"] = int(bool(b.get(F.B_INWARD)) and frappe.db.get_value(
				F.INWARD, b.get(F.B_INWARD), "approval_status") == F.APPROVAL_PENDING)
			awaiting.append(b)
	return {"data": rows[:page_length], "has_more": int(has_more), "start": start,
	        "page_length": page_length, "awaiting": awaiting,
	        "statuses": [F.QC_DRAFT, F.QC_PENDING_LAB, F.QC_APPROVED, F.QC_REJECTED_STATUS,
	                     F.QC_PARTIAL, F.QC_REVOKED],
	        "can_create": int(F.has_any(F.QC_ROLES))}


@frappe.whitelist()
def get_qc_context(final_qc=None):
	F.require(F.FILLING_READ_ROLES, _("view Final QC"))
	base = {"tests": list(F.STANDARD_TESTS), "rejection_reasons": list(F.REJECTION_REASONS),
	        "rejection_categories": list(F.REJECTION_CATEGORIES), "decisions": list(F.DECISIONS),
	        "can_write": int(F.has_any(F.QC_ROLES)), "can_revoke": 0}
	if not final_qc:
		base["doc"] = None
		return base
	doc = frappe.get_doc(F.FINAL_QC, final_qc)
	base["doc"] = doc.as_dict()
	base["can_write"] = int(F.has_any(F.QC_ROLES) and cint(doc.docstatus) == 0)
	base["can_revoke"] = int(F.has_any(F.QC_MANAGER_ROLES) and cint(doc.docstatus) == 1)
	return base
