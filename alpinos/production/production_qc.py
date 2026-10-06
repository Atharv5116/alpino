"""Production QC (FRD Phase 5). Pages `production_qc_list` and `production_qc_entry`.

A draft Production QC is created when a Process Inward is sent for QC. The inspector
records observations, Approved KG and Rejected KG (+ reason) and clicks Send For Filling,
which submits (locks) the QC and:

    * moves the Rejected KG from the baked WIP warehouse to the Rejected warehouse
      (Stock Entry "Material Transfer", custom_production_qc set) -- only when the inward
      actually posted stock;
    * adds each Sub PO's share of the Approved KG to its custom_wip_qty (what Filling sees);
    * appends the process to custom_completed_processes and sets the Sub PO to
      Ready for Next Stage (or QC Rejected when nothing was approved), clears its planning
      fields (assigned process / machine / date) so it returns to the planning backlog;
    * notifies Plant Head / Production Manager (with email) when anything was rejected.

For a merged run the approved / rejected KG are split over the Sub POs by their share of
the output (BR-MRG-04).
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, get_fullname, now_datetime, nowdate

from alpinos.production import execution_common as X
from alpinos.production import material_common as MC

QC = X.QC_DOCTYPE
INWARD = X.INWARD_DOCTYPE

QC_DRAFT = "Draft"
QC_SENT = "Sent For Filling"
QC_REJECTED = "QC Rejected"
TOLERANCE = 0.001


def _inward(name):
	if not name or not frappe.db.exists(INWARD, name):
		frappe.throw(_("Process Inward {0} does not exist.").format(name or ""), title=_("Not Found"))
	return frappe.get_doc(INWARD, name)


def validate_qc(doc):
	if cint(doc.docstatus) == 2:
		return
	inward = _inward(doc.process_inward)
	if cint(inward.docstatus) != 1:
		frappe.throw(_("Process Inward {0} is not submitted.").format(inward.name),
		             title=_("Inward Not Submitted"))
	if cint(doc.docstatus) == 0:
		if doc.is_new():
			other = frappe.get_all(QC, filters={"process_inward": inward.name, "docstatus": ("<", 2)},
			                       pluck="name", limit=1)
			if other:
				frappe.throw(_("Production QC {0} already exists for {1}.").format(other[0], inward.name),
				             title=_("Duplicate QC"))
		for f in ("production_run", "sub_order", "machine_run", "member_sub_orders",
		          "parent_production_order", "process_master", "production_item", "item_name",
		          "batch_number"):
			doc.set(f, inward.get(f))
		doc.total_baked_output_kg = flt(inward.actual_output_kg, 3)
		doc.status = QC_DRAFT

	for field, label in (("approved_kg", "Approved Qty (KG)"), ("rejected_kg", "Rejected Qty (KG)")):
		if flt(doc.get(field)) < 0:
			frappe.throw(_("{0} cannot be negative.").format(_(label)), title=_("Invalid Value"))
	if flt(doc.rejected_kg) > 0:
		if not doc.rejection_reason:
			frappe.throw(_("Rejection Reason is mandatory when any quantity is rejected."),
			             title=_("Rejection Reason Required"))
		if doc.rejection_reason == "Other" and not (doc.rejection_remarks or "").strip():
			frappe.throw(_("Enter the Rejection Remarks for reason Other."), title=_("Remarks Required"))
	elif doc.rejection_reason and not flt(doc.rejected_kg):
		doc.rejection_reason = None

	if doc.get("_action") == "submit" or cint(doc.docstatus) == 1:
		total = flt(doc.total_baked_output_kg, 3)
		if abs(flt(doc.approved_kg) + flt(doc.rejected_kg) - total) > TOLERANCE:
			frappe.throw(
				_("Approved ({0} KG) + Rejected ({1} KG) must equal the Total Baked Output ({2} KG).").format(
					flt(doc.approved_kg, 3), flt(doc.rejected_kg, 3), total),
				title=_("Quantities Do Not Match"))
		doc.inspector = frappe.session.user
		doc.status = QC_SENT if flt(doc.approved_kg) > 0 else QC_REJECTED
		doc.submitted_on = now_datetime()


def _split_by_output(total, allocations):
	outputs = [flt(a.output_kg) for a in allocations]
	whole = sum(outputs)
	shares = [(o / whole) if whole else (1.0 / len(outputs)) for o in outputs]
	out, used = [], 0.0
	for i, s in enumerate(shares):
		if i == len(shares) - 1:
			out.append(flt(total - used, 3))
		else:
			part = flt(total * s, 3)
			used += part
			out.append(part)
	return out


def _move_rejected(doc, inward, alloc, qty):
	sub = X.sub_info(alloc.sub_order)
	baked = X.baked_wip_warehouse()
	rejected = X.rejected_warehouse()
	item = sub.production_item
	stock_uom = frappe.db.get_value("Item", item, "stock_uom")
	if alloc.batch_no:
		available = MC.batch_qty(alloc.batch_no, baked, item)
	else:
		available = flt(MC.bin_qty([item], baked).get(item))
	if flt(qty) > flt(available) + TOLERANCE:
		frappe.throw(_("Only {0} KG of {1} for {2} is left in {3}; cannot move {4} KG to Rejected.").format(
			flt(available, 3), item, sub.name, baked, flt(qty, 3)), title=_("Insufficient Stock"))
	se = frappe.new_doc("Stock Entry")
	se.purpose = "Material Transfer"
	se.stock_entry_type = "Material Transfer"
	se.company = sub.company
	se.posting_date = nowdate()
	se.set(X.SUB_FIELD, sub.name)
	if X.se_has("custom_parent_production_order"):
		se.set("custom_parent_production_order", sub.get("custom_parent_production_order"))
	if X.se_has(X.SE_QC_FIELD):
		se.set(X.SE_QC_FIELD, doc.name)
	se.remarks = _("Production QC {0}: rejected ({1})").format(doc.name, doc.rejection_reason or "")
	row = {"item_code": item, "s_warehouse": baked, "t_warehouse": rejected, "qty": flt(qty, 6),
	       "transfer_qty": flt(qty, 6), "uom": stock_uom, "stock_uom": stock_uom, "conversion_factor": 1}
	if alloc.batch_no:
		row.update({"batch_no": alloc.batch_no, "use_serial_batch_fields": 1})
	se.append("items", row)
	se.flags.alpinos_execution = True
	se.flags.ignore_permissions = True
	se.insert(ignore_permissions=True)
	se.submit()
	return se.name


def on_submit_qc(doc):
	inward = _inward(doc.process_inward)
	allocs = [a for a in inward.allocations]
	if not allocs:
		frappe.throw(_("{0} has no Sub PO distribution.").format(inward.name), title=_("No Sub POs"))
	approved = _split_by_output(flt(doc.approved_kg), allocs)
	rejected = _split_by_output(flt(doc.rejected_kg), allocs)
	entries = []
	for alloc, ok, bad in zip(allocs, approved, rejected):
		if cint(inward.stock_posted) and bad > 0:
			entries.append(_move_rejected(doc, inward, alloc, bad))
		frappe.db.set_value("Process Inward Allocation", alloc.name,
		                    {"approved_kg": ok, "rejected_kg": bad})
		if cint(inward.stock_posted):
			X.add_wip_qty(alloc.sub_order, ok)
		# default pending BA confirmation: a fully rejected Sub PO does not count the process
		# as done (it is QC Rejected); one with any approved KG does.
		if ok > 0:
			X.add_completed_process(alloc.sub_order, inward.process_master)
			X.set_sub_status([alloc.sub_order], X.ST_READY_NEXT, clear_run=True)
		else:
			X.set_sub_status([alloc.sub_order], X.ST_QC_REJECTED, clear_run=True)
	X.clear_planning([a.sub_order for a in allocs])
	if entries:
		doc.db_set("stock_entries", ", ".join(entries))
	frappe.db.set_value(INWARD, inward.name, "status", "QC Done")
	if inward.production_run:
		frappe.db.set_value(X.RUN_DOCTYPE, inward.production_run, "status", X.RUN_CLOSED)

	details = _("approved {0} KG, rejected {1} KG").format(flt(doc.approved_kg, 3), flt(doc.rejected_kg, 3))
	X.log_event(QC, doc.name, "QC Sent For Filling", details,
	            doc.rejection_reason if flt(doc.rejected_kg) else "")
	for a in allocs:
		X.log_event(X.WORK_ORDER, a.sub_order, "Production QC", f"{doc.name}: {details}")
	if flt(doc.rejected_kg) > 0:
		X.notify(X.REJECTION_NOTIFY_ROLES,
		         _("Production QC {0}: {1} KG of batch {2} ({3}) rejected - {4}").format(
			         doc.name, flt(doc.rejected_kg, 3), doc.batch_number or doc.sub_order or "",
			         doc.production_item, doc.rejection_reason),
		         QC, doc.name, email=True)


def before_cancel_qc(doc):
	frappe.throw(_("A Production QC that has been sent for filling is locked and cannot be cancelled."),
	             title=_("QC Locked"))


# ===================================================================== page API

LIST_FIELDS = ["name", "process_inward", "sub_order", "machine_run", "member_sub_orders",
               "parent_production_order", "production_item", "item_name", "batch_number",
               "total_baked_output_kg", "approved_kg", "rejected_kg", "rejection_reason", "status",
               "inspector", "inspection_date", "docstatus", "creation"]


@frappe.whitelist()
def get_qc_list(status=None, search=None, date_from=None, date_to=None, start=0, page_length=50):
	X.assert_roles(X.QC_READ_ROLES, _("open Production QC"))
	start, page_length = max(cint(start), 0), min(max(cint(page_length) or 50, 1), 200)
	filters = {}
	if status:
		filters["status"] = status
	if date_from and date_to:
		filters["creation"] = ("between", [date_from, f"{date_to} 23:59:59"])
	elif date_from:
		filters["creation"] = (">=", date_from)
	elif date_to:
		filters["creation"] = ("<=", f"{date_to} 23:59:59")
	or_filters = None
	if search:
		like = f"%{search}%"
		or_filters = {"name": ("like", like), "sub_order": ("like", like), "batch_number": ("like", like),
		              "production_item": ("like", like), "process_inward": ("like", like),
		              "member_sub_orders": ("like", like)}
	rows = frappe.get_all(QC, filters=filters, or_filters=or_filters, fields=LIST_FIELDS,
	                      order_by="docstatus asc, creation desc", limit_start=start,
	                      limit_page_length=page_length + 1)
	has_more = len(rows) > page_length
	rows = rows[:page_length]
	for r in rows:
		r["inspector_name"] = get_fullname(r.inspector) if r.inspector else None
	return {"data": rows, "has_more": int(has_more), "start": start, "page_length": page_length,
	        "statuses": [QC_DRAFT, QC_SENT, QC_REJECTED]}


@frappe.whitelist()
def get_qc_context(name):
	X.assert_roles(X.QC_READ_ROLES, _("open Production QC"))
	doc = frappe.get_doc(QC, name)
	inward = frappe.get_doc(INWARD, doc.process_inward) if doc.process_inward else None
	draft = cint(doc.docstatus) == 0
	may_write = X.may(X.QC_WRITE_ROLES)
	return {
		"doc": {f: doc.get(f) for f in LIST_FIELDS + [
			"production_run", "process_master", "observations", "approval_remarks",
			"rejection_remarks", "stock_entries", "submitted_on"]},
		"inspector_name": get_fullname(doc.inspector or frappe.session.user),
		"inward": {
			"name": inward.name, "posting_date": inward.posting_date, "shift": inward.shift,
			"total_issued_rm": inward.total_issued_rm, "process_loss_kg": inward.process_loss_kg,
			"yield_pct": inward.yield_pct, "stock_posted": inward.stock_posted,
			"allocations": [{f: a.get(f) for f in ("sub_order", "output_kg", "batch_no", "approved_kg",
			                                       "rejected_kg")} for a in inward.allocations],
		} if inward else None,
		"rejection_reasons": list(X.QC_REJECTION_REASONS),
		"can_write": int(draft and may_write),
	}


EDITABLE = ("inspection_date", "observations", "approved_kg", "approval_remarks", "rejected_kg",
            "rejection_reason", "rejection_remarks")


def _apply(doc, p):
	for f in EDITABLE:
		if f in p:
			doc.set(f, p.get(f) if p.get(f) != "" else None)


@frappe.whitelist()
def save_qc(payload):
	X.assert_roles(X.QC_WRITE_ROLES, _("save a Production QC"))
	p = X.parse(payload)
	doc = frappe.get_doc(QC, p.get("name"))
	if cint(doc.docstatus) != 0:
		frappe.throw(_("{0} has been sent and is locked.").format(doc.name), title=_("Locked"))
	_apply(doc, p)
	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"name": doc.name}


@frappe.whitelist()
def send_for_filling(payload):
	"""5.4: lock the QC and release only the Approved KG to Filling."""
	X.assert_roles(X.QC_WRITE_ROLES, _("send a Production QC for filling"))
	p = X.parse(payload)
	doc = frappe.get_doc(QC, p.get("name"))
	if cint(doc.docstatus) != 0:
		frappe.throw(_("{0} has already been sent.").format(doc.name), title=_("Already Sent"))
	_apply(doc, p)
	doc.flags.ignore_permissions = True
	doc.submit()
	frappe.db.commit()
	return {"name": doc.name, "status": doc.status}
