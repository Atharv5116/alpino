"""Process Inward -- the Mixing & Baking data sheet (FRD 4.8 / 4.9). Page `process_inward_entry`.

One Process Inward per Production Run, holding both the Mass Mixing and the Baking sections
(the FRD's "two backend records" are the two sections of this one document; reports read
the sections separately).
# default pending BA confirmation: one document with both sections instead of two records.

Submit            -> Inward Logged (or straight to Ready for Next Stage when the process does
                     not require QC)
Submit & Send QC  -> Pending QC, a draft Production QC is created and QC is notified

Stock (only for the output stage -- see execution_common.is_output_stage): for every Sub PO
of the run, its share of the Actual Output (BR-MRG-04: by planned qty) is produced into the
baked WIP warehouse, consuming that Sub PO's net issued material from the WIP warehouse.
A "Manufacture" entry against the Sub PO (Work Order) is tried first; if ERPNext refuses it
(over-production, job cards, BOM quantity checks ...), a "Repack" entry with the same rows
is posted instead, tagged to the Sub PO. Both carry custom_process_inward.
# default pending BA confirmation: Manufacture with Repack fallback.

Reverse Inward (Production Admin, reason mandatory) cancels the stock entries and puts the
run back to Process Completed.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime, nowdate

from alpinos.production import execution_common as X
from alpinos.production import material_common as MC
from alpinos.production import material_constants as M
from alpinos.production.work_order_fields import EXECUTION_STATUS_FIELD, PARENT_FIELD

INWARD = X.INWARD_DOCTYPE
RUN = X.RUN_DOCTYPE

IN_DRAFT = "Draft"
IN_LOGGED = "Inward Logged"
IN_PENDING_QC = "Pending QC"
IN_READY_NEXT = "Ready for Next Stage"
IN_QC_DONE = "QC Done"
IN_REVERSED = "Reversed"

NUMERIC_NON_NEGATIVE = (
	("total_batch", "Total Batch"), ("mixing_wastage_kg", "Mixing Wastage (KG)"),
	("total_output_kg", "Total Output (KG)"), ("baking_wastage_kg", "Total Baking Wastage (KG)"),
	("actual_output_kg", "Actual Output (KG)"), ("total_wastage_kg", "Total Wastage (KG)"),
	("supervisor_count", "Supervisor"), ("operator_count", "Operator"),
	("hh_labour_count", "HH Labour"), ("ahf_labour_count", "AHF Labour"),
)


# ===================================================================== helpers

def _run(name):
	if not name or not frappe.db.exists(RUN, name):
		frappe.throw(_("Production Run {0} does not exist.").format(name or ""), title=_("Not Found"))
	return frappe.get_doc(RUN, name)


def _baking_process():
	for p in X.active_processes():
		if (p.process_code or "").upper() == "PRC-BAK" or "bak" in (p.process_name or "").lower():
			return p.name
	return None


def oven_options(run_process=None):
	"""Active machines whose type is linked to the Baking process (else the run's process)."""
	process = _baking_process() or run_process
	if not process:
		return []
	types = frappe.get_all("Process Machine Type", filters={"parent": process, "parenttype": "Process Master"},
	                       pluck="machine_type")
	if not types:
		return []
	return frappe.get_all("Machine", filters={"machine_type": ("in", types), "status": "Active"},
	                      fields=["name", "machine_name"], order_by="machine_name asc")


def _existing_inward(run_name, exclude=None):
	filters = {"production_run": run_name, "docstatus": ("<", 2)}
	if exclude:
		filters["name"] = ("!=", exclude)
	rows = frappe.get_all(INWARD, filters=filters, pluck="name", limit=1)
	return rows[0] if rows else None


def _allocations(members):
	"""BR-MRG-04: each Sub PO's share by its planned quantity."""
	rows = frappe.get_all(X.WORK_ORDER, filters={"name": ("in", members)}, fields=["name", "qty"])
	qty = {r.name: flt(r.qty) for r in rows}
	total = sum(qty.get(m, 0) for m in members)
	out = []
	for m in members:
		share = (qty.get(m, 0) / total) if total else (1.0 / len(members))
		out.append(frappe._dict(sub_order=m, planned_qty=flt(qty.get(m), 3), share=share,
		                        issued_rm_kg=X.issued_rm_kg(m)))
	return out


def _split(total, shares, precision=3):
	"""Split a total by shares; the last one takes the rounding remainder."""
	out, used = [], 0.0
	for i, s in enumerate(shares):
		if i == len(shares) - 1:
			out.append(flt(total - used, precision))
		else:
			part = flt(total * s, precision)
			used += part
			out.append(part)
	return out


# ===================================================================== validation

def _copy_header(doc, run):
	doc.production_run = run.name
	doc.sub_order = run.sub_order
	doc.machine_run = run.machine_run
	doc.member_sub_orders = run.member_sub_orders
	doc.parent_production_order = run.parent_production_order
	doc.process_master = run.process_master
	doc.machine = run.machine
	doc.production_item = run.production_item
	doc.item_name = frappe.db.get_value("Item", run.production_item, "item_name") if run.production_item else None
	doc.batch_number = run.batch_number
	doc.run_start = run.started_on
	doc.run_end = run.completed_on


def validate_inward(doc):
	if cint(doc.docstatus) == 2:
		return  # a reversal keeps the sheet exactly as it was submitted
	run = _run(doc.production_run)
	if cint(doc.docstatus) == 0:
		if run.status in (X.RUN_RUNNING, X.RUN_PAUSED, X.RUN_READY):
			frappe.throw(
				_("The Inward Entry cannot be created while production is {0}. Click Complete "
				  "Production first (BR-EXEC-05).").format(run.status), title=_("Production Not Completed"))
		if run.status == X.RUN_CLOSED and not run.get("process_inward"):
			frappe.throw(_("{0} is Closed: its process does not take an Inward Entry.").format(run.name),
			             title=_("No Inward Entry"))
		if run.status != X.RUN_COMPLETED:
			frappe.throw(_("{0} is {1}; its Inward Entry has already been submitted.").format(
				run.name, run.status), title=_("Inward Already Logged"))
		other = _existing_inward(run.name, exclude=None if doc.is_new() else doc.name)
		if other:
			frappe.throw(_("Inward Entry {0} already exists for {1}.").format(other, run.name),
			             title=_("Duplicate Inward"))
		_copy_header(doc, run)
		doc.status = IN_DRAFT
		if not doc.posting_date:
			doc.posting_date = nowdate()
		if doc.is_new() and not doc.shift:
			shift = X.current_shift()
			if shift:
				doc.shift, doc.shift_start, doc.shift_end = shift.get("name"), shift.get("start"), shift.get("end")

	for field, label in NUMERIC_NON_NEGATIVE:
		if flt(doc.get(field)) < 0:
			frappe.throw(_("{0} cannot be negative.").format(_(label)), title=_("Invalid Value"))

	allowed = {m.name for m in oven_options(run.process_master)}
	for row in doc.get("ovens") or []:
		if not row.oven:
			frappe.throw(_("Oven row {0}: select the oven.").format(row.idx), title=_("Oven Required"))
		if allowed and row.oven not in allowed:
			frappe.throw(_("Oven row {0}: {1} is not an Active machine of the Baking process.").format(
				row.idx, row.oven), title=_("Invalid Oven"))
		for f, label in (("no_of_batches", "No of Batch"), ("time_mins", "Time (Mins)")):
			if cint(row.get(f)) < 0:
				frappe.throw(_("Oven row {0}: {1} cannot be negative.").format(row.idx, _(label)),
				             title=_("Invalid Value"))

	if not flt(doc.total_wastage_kg):
		doc.total_wastage_kg = flt(flt(doc.mixing_wastage_kg) + flt(doc.baking_wastage_kg), 3)

	members = X.run_members(run)
	allocs = _allocations(members)
	issued = flt(sum(a.issued_rm_kg for a in allocs), 3)
	output = flt(doc.actual_output_kg)
	# FRD 4.9.5 -- default pending BA confirmation (formula to be confirmed by Production).
	doc.total_issued_rm = issued
	doc.process_loss_kg = flt(issued - (output + flt(doc.mixing_wastage_kg) + flt(doc.baking_wastage_kg)), 3)
	doc.yield_pct = flt(output / issued * 100, 2) if issued else 0

	if cint(doc.docstatus) == 0:
		outputs = _split(output, [a.share for a in allocs])
		losses = _split(doc.process_loss_kg, [a.share for a in allocs])
		doc.set("allocations", [])
		for a, out, loss in zip(allocs, outputs, losses):
			doc.append("allocations", {
				"sub_order": a.sub_order, "planned_qty": a.planned_qty,
				"share_pct": flt(a.share * 100, 2), "issued_rm_kg": a.issued_rm_kg,
				"output_kg": out, "loss_kg": loss,
			})


def before_submit_inward(doc):
	X.assert_roles(X.FLOOR_WRITE_ROLES, _("submit an Inward Entry"))
	run = _run(doc.production_run)
	if run.status != X.RUN_COMPLETED:
		frappe.throw(_("{0} is {1}; only a completed run can be inwarded.").format(run.name, run.status),
		             title=_("Production Not Completed"))
	posts_stock = X.is_output_stage(doc.process_master)
	if posts_stock and flt(doc.actual_output_kg) <= 0:
		frappe.throw(_("Enter the Actual Output (KG)."), title=_("Actual Output Required"))
	if cint(doc.send_for_qc) and flt(doc.actual_output_kg) <= 0:
		frappe.throw(_("Enter the Actual Output (KG) before sending it for QC."),
		             title=_("Actual Output Required"))
	doc.submitted_by = frappe.session.user
	doc.submitted_on = now_datetime()
	qc_required = cint((X.process_row(doc.process_master) or {}).get("qc_required"))
	if cint(doc.send_for_qc):
		doc.status = IN_PENDING_QC
	elif not qc_required:
		doc.status = IN_READY_NEXT
	else:
		doc.status = IN_LOGGED


def on_submit_inward(doc):
	run = _run(doc.production_run)
	members = X.run_members(run)
	if X.is_output_stage(doc.process_master) and flt(doc.actual_output_kg) > 0:
		for row in doc.allocations:
			if flt(row.output_kg) <= 0:
				continue
			se, batch = post_output(doc, row)
			frappe.db.set_value("Process Inward Allocation", row.name,
			                    {"stock_entry": se, "batch_no": batch})
			row.stock_entry, row.batch_no = se, batch
		doc.db_set("stock_posted", 1)

	if doc.status == IN_PENDING_QC:
		qc = create_qc(doc)
		frappe.db.set_value(RUN, run.name, {"status": X.RUN_PENDING_QC, "process_inward": doc.name})
		X.set_sub_status(members, X.ST_PENDING_QC, run=run.name)
		_notify_qc(doc, qc)
	elif doc.status == IN_READY_NEXT:
		frappe.db.set_value(RUN, run.name, {"status": X.RUN_CLOSED, "process_inward": doc.name})
		for row in doc.allocations:
			X.add_completed_process(row.sub_order, doc.process_master)
			if cint(doc.stock_posted):
				X.add_wip_qty(row.sub_order, row.output_kg)
		X.set_sub_status(members, X.ST_READY_NEXT, clear_run=True)
		X.clear_planning(members)
	else:
		frappe.db.set_value(RUN, run.name, {"status": X.RUN_INWARD_LOGGED, "process_inward": doc.name})
		X.set_sub_status(members, X.ST_INWARD_LOGGED, run=run.name)

	details = _("output {0} KG, loss {1} KG, yield {2}%").format(
		flt(doc.actual_output_kg, 3), flt(doc.process_loss_kg, 3), flt(doc.yield_pct, 2))
	X.log_event(INWARD, doc.name, "Inward Submitted", details)
	for m in members:
		X.log_event(X.WORK_ORDER, m, "Inward Submitted", f"{doc.name}: {details} -> {doc.status}")


def create_qc(inward):
	existing = frappe.get_all(X.QC_DOCTYPE, filters={"process_inward": inward.name, "docstatus": ("<", 2)},
	                          pluck="name", limit=1)
	if existing:
		return existing[0]
	qc = frappe.new_doc(X.QC_DOCTYPE)
	qc.process_inward = inward.name
	qc.flags.ignore_permissions = True
	qc.insert(ignore_permissions=True)
	frappe.db.set_value(INWARD, inward.name, {"production_qc": qc.name, "send_for_qc": 1})
	return qc.name


def _notify_qc(inward, qc_name):
	X.notify(X.QC_NOTIFY_ROLES,
	         _("Batch {0} ({1}) is ready for Production QC: {2} KG").format(
		         inward.batch_number or inward.sub_order or inward.name, inward.production_item,
		         flt(inward.actual_output_kg, 3)),
	         X.QC_DOCTYPE, qc_name)


# ===================================================================== stock

def _consumed_already(sub_name, wip):
	"""Material this Sub PO has already consumed out of WIP through earlier inward entries."""
	if not X.se_has(X.SE_INWARD_FIELD):
		return {}
	names = frappe.get_all("Stock Entry", filters={X.SE_INWARD_FIELD: ("is", "set"), "docstatus": 1,
	                                               X.SUB_FIELD: sub_name}, pluck="name")
	out = {}
	if not names:
		return out
	for r in frappe.get_all("Stock Entry Detail", filters={"parent": ("in", names), "s_warehouse": wip},
	                        fields=["item_code", "transfer_qty"]):
		out[r.item_code] = out.get(r.item_code, 0) + flt(r.transfer_qty)
	return out


def _issued_batches(sub_name, wip):
	"""Batches that were issued into WIP for this Sub PO, per item (preferred on consumption)."""
	names = frappe.get_all("Stock Entry", filters={"custom_entry_kind": M.KIND_ISSUE, "docstatus": 1,
	                                               X.SUB_FIELD: sub_name}, pluck="name")
	out = {}
	if names:
		for r in frappe.get_all("Stock Entry Detail",
		                        filters={"parent": ("in", names), "t_warehouse": wip,
		                                 "batch_no": ("is", "set")},
		                        fields=["item_code", "batch_no"]):
			out.setdefault(r.item_code, [])
			if r.batch_no not in out[r.item_code]:
				out[r.item_code].append(r.batch_no)
	return out


def _consumption_rows(sub_name, wip):
	net = X.net_issued_by_item(sub_name)
	done = _consumed_already(sub_name, wip)
	info = MC.item_info(list(net))
	in_wip = MC.bin_qty(list(net), wip)
	preferred = _issued_batches(sub_name, wip)
	rows = []
	for code, qty in net.items():
		qty = min(flt(qty) - flt(done.get(code)), flt(in_wip.get(code)))
		if qty <= 0.0000001:
			continue
		i = info.get(code) or frappe._dict()
		base = {"item_code": code, "s_warehouse": wip, "uom": i.stock_uom, "stock_uom": i.stock_uom,
		        "conversion_factor": 1}
		if not cint(i.get("has_batch_no")):
			rows.append(dict(base, qty=flt(qty, 6), transfer_qty=flt(qty, 6)))
			continue
		batches = MC.batches_fefo(code, wip)
		pref = preferred.get(code) or []
		batches.sort(key=lambda b: (b["batch_no"] not in pref,))
		left = qty
		for b in batches:
			if left <= 0.0000001:
				break
			take = min(left, flt(b["qty"]))
			if take <= 0:
				continue
			rows.append(dict(base, qty=flt(take, 6), transfer_qty=flt(take, 6), batch_no=b["batch_no"],
			                 use_serial_batch_fields=1))
			left -= take
	return rows


def _output_batch(inward, sub_name, item_code):
	if not cint(frappe.db.get_value("Item", item_code, "has_batch_no")):
		return None
	base = frappe.db.get_value(X.WORK_ORDER, sub_name, "custom_batch_number") or sub_name
	batch_id = f"{base}-{inward.name}"
	if len([a for a in inward.allocations]) > 1:
		batch_id = f"{batch_id}-{sub_name.split('-')[-1]}"
	if not frappe.db.exists("Batch", batch_id):
		frappe.get_doc({"doctype": "Batch", "batch_id": batch_id, "item": item_code,
		                "manufacturing_date": nowdate()}).insert(ignore_permissions=True)
	return batch_id


def _build_entry(inward, sub, purpose, consumption, fg_row):
	se = frappe.new_doc("Stock Entry")
	se.purpose = purpose
	se.stock_entry_type = purpose
	se.company = sub.company
	se.posting_date = nowdate()
	se.set(X.SUB_FIELD, sub.name)
	if X.se_has("custom_parent_production_order"):
		se.set("custom_parent_production_order", sub.get(PARENT_FIELD))
	if X.se_has("custom_target_fg_item"):
		se.set("custom_target_fg_item", sub.production_item)
	if X.se_has(X.SE_INWARD_FIELD):
		se.set(X.SE_INWARD_FIELD, inward.name)
	se.remarks = _("Process Inward {0} ({1})").format(inward.name, inward.process_master)
	if purpose == "Manufacture":
		se.work_order = sub.name
		se.from_bom = 1
		se.bom_no = sub.bom_no
		se.use_multi_level_bom = cint(frappe.db.get_value(X.WORK_ORDER, sub.name, "use_multi_level_bom"))
		se.fg_completed_qty = flt(fg_row["qty"])
	for r in consumption:
		se.append("items", dict(r))
	se.append("items", dict(fg_row))
	se.flags.alpinos_execution = True
	se.flags.ignore_permissions = True
	return se


def post_output(inward, alloc):
	"""Post one Sub PO's share of the output. Returns (stock entry, batch)."""
	sub = X.sub_info(alloc.sub_order)
	wip = X.wip_warehouse()
	baked = X.baked_wip_warehouse()
	consumption = _consumption_rows(sub.name, wip)
	if not consumption:
		frappe.throw(_("{0} has no issued material left in {1} to consume. Check its Material "
		               "Issues and Returns.").format(sub.name, wip), title=_("No Material In WIP"))
	item = sub.production_item
	stock_uom = frappe.db.get_value("Item", item, "stock_uom")
	batch = _output_batch(inward, sub.name, item)
	# Output is declared in KG; the bulk item is expected to be stocked in KG.
	# default pending BA confirmation: conversion factor 1 between KG and the item's stock UOM.
	fg_row = {"item_code": item, "t_warehouse": baked, "qty": flt(alloc.output_kg, 6),
	          "transfer_qty": flt(alloc.output_kg, 6), "uom": stock_uom, "stock_uom": stock_uom,
	          "conversion_factor": 1, "is_finished_item": 1}
	if batch:
		fg_row.update({"batch_no": batch, "use_serial_batch_fields": 1})

	if cint(sub.docstatus) == 1 and sub.status not in ("Completed", "Stopped", "Closed", "Cancelled"):
		frappe.db.savepoint("alpinos_inward_mfg")
		try:
			se = _build_entry(inward, sub, "Manufacture", consumption, fg_row)
			se.insert(ignore_permissions=True)
			se.submit()
			return se.name, batch
		except Exception:
			frappe.db.rollback(save_point="alpinos_inward_mfg")
			frappe.local.message_log = []
			frappe.log_error(frappe.get_traceback(),
			                 f"Process Inward {inward.name}: Manufacture refused, Repack used")

	se = _build_entry(inward, sub, "Repack", consumption, fg_row)
	try:
		se.insert(ignore_permissions=True)
		se.submit()
	except frappe.ValidationError as e:
		frappe.throw(_("The stock entry for {0} could not be posted: {1}").format(sub.name, e),
		             title=_("Stock Not Posted"))
	return se.name, batch


# ===================================================================== reverse

def before_cancel_inward(doc):
	if not doc.flags.get("alpinos_reverse"):
		X.assert_roles(X.REVERSE_ROLES, _("reverse an Inward Entry"))
	if not (doc.reversal_reason or "").strip():
		frappe.throw(_("Please enter the reason for reversing this Inward Entry."),
		             title=_("Reason Required"))
	if doc.production_qc:
		qc_status = cint(frappe.db.get_value(X.QC_DOCTYPE, doc.production_qc, "docstatus"))
		if qc_status == 1:
			frappe.throw(_("Production QC {0} has already been sent; this Inward Entry cannot be "
			               "reversed.").format(doc.production_qc), title=_("QC Already Done"))
	if doc.status == IN_READY_NEXT:
		run = _run(doc.production_run)
		for m in X.run_members(run):
			status = frappe.db.get_value(X.WORK_ORDER, m, EXECUTION_STATUS_FIELD)
			if status != X.ST_READY_NEXT:
				frappe.throw(_("{0} has moved on to its next process ({1}); this Inward Entry can no "
				               "longer be reversed.").format(m, status), title=_("Already Moved On"))


def on_cancel_inward(doc):
	run = _run(doc.production_run)
	members = X.run_members(run)
	qc = doc.production_qc
	if qc and frappe.db.exists(X.QC_DOCTYPE, qc) and cint(frappe.db.get_value(X.QC_DOCTYPE, qc, "docstatus")) == 0:
		frappe.db.set_value(INWARD, doc.name, "production_qc", None)
		frappe.delete_doc(X.QC_DOCTYPE, qc, ignore_permissions=True, force=True)

	for row in reversed(doc.allocations or []):
		if not row.stock_entry or cint(frappe.db.get_value("Stock Entry", row.stock_entry, "docstatus")) != 1:
			continue
		se = frappe.get_doc("Stock Entry", row.stock_entry)
		if se.purpose == "Manufacture" and se.work_order and \
				frappe.db.get_value(X.WORK_ORDER, se.work_order, "status") == "Completed":
			# ERPNext refuses to cancel against a Completed Work Order; the status is
			# recomputed by ERPNext itself as soon as the entry is cancelled.
			frappe.db.set_value(X.WORK_ORDER, se.work_order, "status", "In Process", update_modified=False)
		se.flags.ignore_permissions = True
		se.flags.alpinos_execution = True
		try:
			se.cancel()
		except frappe.ValidationError as e:
			frappe.throw(_("Stock Entry {0} could not be cancelled: {1}").format(se.name, e),
			             title=_("Reverse Failed"))

	if doc.status == IN_READY_NEXT:
		for row in doc.allocations or []:
			X.remove_completed_process(row.sub_order, doc.process_master)
			if cint(doc.stock_posted):
				X.add_wip_qty(row.sub_order, -flt(row.output_kg))
		X.restore_planning(members, run.process_master, run.machine, run.planned_date, run.machine_run)

	frappe.db.set_value(RUN, run.name, {"status": X.RUN_COMPLETED, "process_inward": None})
	X.set_sub_status(members, X.ST_PROCESS_COMPLETED, run=run.name)
	doc.db_set("status", IN_REVERSED)
	X.log_event(INWARD, doc.name, "Inward Reversed", "", doc.reversal_reason)
	for m in members:
		X.log_event(X.WORK_ORDER, m, "Inward Reversed", doc.name, doc.reversal_reason)


# ===================================================================== page API

def _doc_payload(doc):
	return {
		"name": doc.name, "docstatus": cint(doc.docstatus), "status": doc.status,
		**{f: doc.get(f) for f in (
			"production_run", "sub_order", "machine_run", "member_sub_orders",
			"parent_production_order", "process_master", "machine", "production_item", "item_name",
			"batch_number", "posting_date", "shift", "shift_start", "shift_end", "run_start", "run_end",
			"mixing_start", "mixing_end", "total_batch", "mixing_wastage_kg", "total_output_kg",
			"first_batch_in", "last_batch_out", "baking_wastage_kg", "actual_output_kg",
			"total_wastage_kg", "supervisor_count", "operator_count", "hh_labour_count",
			"ahf_labour_count", "remark", "total_issued_rm", "process_loss_kg", "yield_pct",
			"send_for_qc", "stock_posted", "production_qc", "submitted_by", "submitted_on",
			"reversal_reason")},
		"ovens": [{"oven": r.oven, "no_of_batches": r.no_of_batches, "time_mins": r.time_mins,
		           "temp_c": r.temp_c} for r in doc.get("ovens") or []],
		"allocations": [{f: r.get(f) for f in ("sub_order", "planned_qty", "share_pct", "issued_rm_kg",
		                                       "output_kg", "loss_kg", "batch_no", "stock_entry",
		                                       "approved_kg", "rejected_kg")}
		                for r in doc.get("allocations") or []],
	}


@frappe.whitelist()
def get_inward_context(name=None, production_run=None):
	X.assert_roles(X.FLOOR_READ_ROLES, _("open the Inward Entry"))
	may_write = X.may(X.FLOOR_WRITE_ROLES)
	if not name and production_run:
		name = _existing_inward(production_run)
	if name:
		doc = frappe.get_doc(INWARD, name)
	else:
		run = _run(production_run)
		if run.status != X.RUN_COMPLETED:
			frappe.throw(_("The Inward Entry can only be created after Complete Production ({0} is "
			               "{1}).").format(run.name, run.status), title=_("Production Not Completed"))
		doc = frappe.new_doc(INWARD)
		doc.production_run = run.name
		doc.posting_date = nowdate()
		_copy_header(doc, run)
		shift = X.current_shift()
		if shift:
			doc.shift, doc.shift_start, doc.shift_end = shift.get("name"), shift.get("start"), shift.get("end")
		members = X.run_members(run)
		allocs = _allocations(members)
		doc.total_issued_rm = flt(sum(a.issued_rm_kg for a in allocs), 3)
		for a in allocs:
			doc.append("allocations", {"sub_order": a.sub_order, "planned_qty": a.planned_qty,
			                           "share_pct": flt(a.share * 100, 2), "issued_rm_kg": a.issued_rm_kg})
	draft = cint(doc.docstatus) == 0
	qc_required = cint((X.process_row(doc.process_master) or {}).get("qc_required"))
	return {
		"doc": _doc_payload(doc),
		"is_new": 1 if doc.is_new() else 0,  # is_new() is None, not False, on a saved doc
		"ovens": oven_options(doc.process_master),
		"qc_required": qc_required,
		"posts_stock": int(X.is_output_stage(doc.process_master)),
		"process_label": frappe.db.get_value("Process Master", doc.process_master, "process_name"),
		"can_write": int(draft and may_write),
		"can_submit": int(draft and may_write),
		"can_send_qc": int(cint(doc.docstatus) == 1 and doc.status == IN_LOGGED and may_write),
		"can_reverse": int(cint(doc.docstatus) == 1 and X.may(X.REVERSE_ROLES)
		                   and doc.status in (IN_LOGGED, IN_PENDING_QC, IN_READY_NEXT)),
		"submitted_by_name": frappe.utils.get_fullname(doc.submitted_by) if doc.submitted_by else None,
	}


EDITABLE = ("posting_date", "shift", "shift_start", "shift_end", "mixing_start", "mixing_end",
            "total_batch", "mixing_wastage_kg", "total_output_kg", "first_batch_in", "last_batch_out",
            "baking_wastage_kg", "actual_output_kg", "total_wastage_kg", "supervisor_count",
            "operator_count", "hh_labour_count", "ahf_labour_count", "remark")


@frappe.whitelist()
def save_inward(payload):
	X.assert_roles(X.FLOOR_WRITE_ROLES, _("save an Inward Entry"))
	p = X.parse(payload)
	if p.get("name"):
		doc = frappe.get_doc(INWARD, p.name)
		if cint(doc.docstatus) != 0:
			frappe.throw(_("{0} is submitted and locked.").format(doc.name), title=_("Locked"))
	else:
		doc = frappe.new_doc(INWARD)
		doc.production_run = p.get("production_run")
	for f in EDITABLE:
		if f in p:
			doc.set(f, p.get(f) if p.get(f) not in ("",) else None)
	doc.set("ovens", [])
	for r in p.get("ovens") or []:
		r = frappe._dict(r)
		if not (r.get("oven") or r.get("no_of_batches") or r.get("time_mins") or r.get("temp_c")):
			continue
		doc.append("ovens", {"oven": r.get("oven"), "no_of_batches": cint(r.get("no_of_batches")),
		                     "time_mins": cint(r.get("time_mins")), "temp_c": cint(r.get("temp_c"))})
	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"name": doc.name}


@frappe.whitelist()
def submit_inward(name, send_for_qc=0):
	X.assert_roles(X.FLOOR_WRITE_ROLES, _("submit an Inward Entry"))
	doc = frappe.get_doc(INWARD, name)
	if cint(doc.docstatus) != 0:
		frappe.throw(_("{0} is already submitted.").format(name), title=_("Already Submitted"))
	doc.send_for_qc = 1 if cint(send_for_qc) else 0
	doc.flags.ignore_permissions = True
	doc.submit()
	frappe.db.commit()
	return {"name": doc.name, "status": frappe.db.get_value(INWARD, doc.name, "status"),
	        "production_qc": frappe.db.get_value(INWARD, doc.name, "production_qc")}


@frappe.whitelist()
def send_inward_for_qc(name):
	"""An inward that was only Submitted (Inward Logged) is sent for QC afterwards."""
	X.assert_roles(X.FLOOR_WRITE_ROLES, _("send an Inward Entry for QC"))
	doc = frappe.get_doc(INWARD, name)
	if cint(doc.docstatus) != 1 or doc.status != IN_LOGGED:
		frappe.throw(_("Only a submitted Inward Entry that is Inward Logged can be sent for QC."),
		             title=_("Cannot Send For QC"))
	if flt(doc.actual_output_kg) <= 0:
		frappe.throw(_("{0} has no Actual Output to inspect.").format(name), title=_("Nothing To Inspect"))
	run = _run(doc.production_run)
	qc = create_qc(doc)
	doc.db_set("status", IN_PENDING_QC)
	frappe.db.set_value(RUN, run.name, "status", X.RUN_PENDING_QC)
	X.set_sub_status(X.run_members(run), X.ST_PENDING_QC, run=run.name)
	_notify_qc(doc, qc)
	X.log_event(INWARD, doc.name, "Sent For QC", qc)
	frappe.db.commit()
	return {"name": doc.name, "production_qc": qc}


@frappe.whitelist()
def reverse_inward(name, reason=None):
	"""Production Admin: cancel the inward and its stock entries, with a reason (5.6 audit)."""
	X.assert_roles(X.REVERSE_ROLES, _("reverse an Inward Entry"))
	if not (reason or "").strip():
		frappe.throw(_("Please enter the reason for reversing this Inward Entry."),
		             title=_("Reason Required"))
	doc = frappe.get_doc(INWARD, name)
	if cint(doc.docstatus) != 1:
		frappe.throw(_("Only a submitted Inward Entry can be reversed."), title=_("Not Submitted"))
	doc.db_set("reversal_reason", reason.strip())
	doc.reload()
	doc.flags.alpinos_reverse = True
	doc.flags.ignore_permissions = True
	doc.cancel()
	frappe.db.commit()
	return {"name": doc.name, "status": IN_REVERSED}
