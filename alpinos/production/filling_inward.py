"""Filling Entry / Filling Inward -- FRD 6.3, 6.4, Phase 7 (7.1 - 7.4).

One Filling Inward = one operator submission against one row of a Filling Plan. It is
created and submitted in one step from the Filling Entry screen (operators have no edit
rights after submit, FRD 7.4.3), and posts:

    * a Stock Entry "Repack": bulk (Sub PO production item) KG out of the baked WIP
      warehouse (+ the SKU's PM per pack), target SKU pcs into the FG Hold warehouse under a
      new FG Batch `<Sub PO batch>-L<line>-<NN>` (FRD 7.3 smart suffix), FG-Hold status;
    * a Stock Entry "Material Issue" for wastage when nothing was filled, and for the
      residual WIP written off when a Final Inward empties the Sub PO's hopper.

Reverse & Adjust (Admin) cancels it with a reason and puts every counter back.
"""

import json
import re

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime, nowdate

from alpinos.production import filling_common as F
from alpinos.production.filling_plan import row_pending


# ------------------------------------------------------------------------ helpers

def _lock_plan(plan):
	frappe.db.sql("select name from `tabFilling Plan` where name = %s for update", plan)


def _plan_row(plan_doc, row_name):
	for row in plan_doc.get("rows") or []:
		if row.name == row_name:
			return row
	frappe.throw(_("That row is not part of {0}.").format(plan_doc.name), title=_("Unknown Plan Row"))


def _other_open_rows(sub_order, exclude_plan=None, exclude_row=None):
	"""Open rows of open plans of this Sub PO, other than the given row / plan."""
	params = {"sub": sub_order, "open": F.PLAN_OPEN_STATUSES, "row_open": F.ROW_OPEN,
	          "plan": exclude_plan or "", "row": exclude_row or ""}
	cond = " and p.name != %(plan)s" if exclude_plan else " and r.name != %(row)s"
	return frappe.db.sql(
		f"""
		select r.name from `tabFilling Plan Row` r join `tabFilling Plan` p on p.name = r.parent
		where p.sub_order = %(sub)s and p.status in %(open)s and r.row_status = %(row_open)s {cond}
		""", params)


def line_code(machine):
	"""default pending BA confirmation: the line's short code = the first digit group of the
	machine name (Line 1 - SO-CH -> 1), else of its ID, else its last 3 characters."""
	name = frappe.db.get_value("Machine", machine, "machine_name") or machine or ""
	for text in (name, machine or ""):
		m = re.search(r"\d+", text)
		if m:
			return m.group(0)
	clean = re.sub(r"[^A-Za-z0-9]", "", name).upper()
	return clean[-3:] or "X"


def _fg_code(sub, machine):
	base = (sub.get(F.BATCH_FIELD) or sub.name or "").strip()
	prefix = f"{base}-L{line_code(machine)}-"
	seq = 0
	if F.has_field("Batch", F.B_INWARD) and F.has_field("Batch", F.B_SUB):
		seq = frappe.db.count("Batch", {F.B_SUB: sub.name, F.B_INWARD: ("is", "set")})
	while True:
		seq += 1
		code = f"{prefix}{seq:02d}"
		if not frappe.db.exists("Batch", code):
			return code, seq


def _make_fg_batch(doc, sub):
	if not cint(frappe.db.get_value("Item", doc.target_sku, "has_batch_no")):
		frappe.throw(_("{0} is not batch-tracked. Turn on 'Has Batch No' for it in Item Master "
		               "so its FG batch code can be recorded.").format(frappe.bold(doc.target_sku)),
		             title=_("SKU Not Batch Tracked"))
	code, seq = _fg_code(sub, doc.filling_line)
	batch = frappe.new_doc("Batch")
	batch.batch_id = code
	batch.item = doc.target_sku
	batch.manufacturing_date = doc.posting_date
	batch.reference_doctype = F.INWARD
	batch.reference_name = doc.name
	values = {F.B_SUB: sub.name, F.B_PARENT: sub.get(F.PARENT_FIELD), F.B_STATUS: F.FG_HOLD,
	          F.B_LINE: doc.filling_line, F.B_INWARD: doc.name, F.B_BARCODE: F.code128_svg(code)}
	for field, value in values.items():
		if F.has_field("Batch", field):
			batch.set(field, value)
	batch.flags.ignore_permissions = True
	batch.insert(ignore_permissions=True)
	return batch.name, seq


# --------------------------------------------------------------------- validation

def validate_inward(doc):
	"""Controller validate. FRD 7.1 + 7.3.5 (VAL-FILL-01..04) + 7.3.2 loss."""
	if not doc.flags.get("alpinos_filling"):
		frappe.throw(_("Filling Inwards are recorded on the Filling Entry screen."),
		             title=_("Use The Filling Entry Screen"))
	if cint(doc.docstatus) != 0:
		return
	plan = frappe.get_doc(F.PLAN, doc.filling_plan)
	if plan.status not in F.PLAN_OPEN_STATUSES:
		frappe.throw(_("{0} is {1}; nothing more can be filled against it.").format(plan.name, plan.status),
		             title=_("Plan Closed"))
	row = _plan_row(plan, doc.plan_row)
	if row.row_status != F.ROW_OPEN:
		frappe.throw(_("This SKU row of {0} is already closed.").format(plan.name), title=_("Row Closed"))
	from alpinos.production.filling import is_machine_available
	if not is_machine_available(plan.filling_line):
		frappe.throw(_("Filling Line {0} is not Active, so no production can be recorded on it.").format(
			plan.filling_line), title=_("Machine Not Active"))

	sub = F.sub_info(plan.sub_order)
	doc.filling_line = plan.filling_line
	doc.line_category = plan.line_category
	doc.parent_po = plan.parent_po
	doc.sub_order = plan.sub_order
	doc.bulk_item = sub.production_item
	doc.target_sku = row.target_sku
	doc.size_kg = flt(row.size_kg) or F.pack_size(row.target_sku)
	doc.planned_pcs = cint(row.planned_pcs)
	doc.completed_before_pcs = cint(row.completed_pcs)
	pending = row_pending(row)
	doc.pending_before_pcs = pending
	doc.posting_date = doc.posting_date or nowdate()
	if not doc.shift:
		doc.shift = F.current_shift_name()

	pcs = cint(doc.input_pcs)
	wastage = flt(doc.wastage_kg, 3)
	if pcs < 0 or wastage < 0:
		frappe.throw(_("Quantities cannot be negative."), title=_("Invalid Quantity"))
	doc.input_pcs, doc.wastage_kg = pcs, wastage
	if doc.submission_type not in F.SUBMISSION_TYPES:
		doc.submission_type = F.SUB_PARTIAL
	if cint(doc.mark_run_complete):
		# FRD 6.4.1 Ghost Pending: Mark Run Complete closes the run -- a Final Inward.
		doc.submission_type = F.SUB_FINAL
	is_final = doc.submission_type == F.SUB_FINAL

	if pcs == 0 and wastage == 0:
		frappe.throw(_(F.MSG_EMPTY), title=_("Empty Inward"))
	if pcs == 0 and not is_final:
		frappe.throw(_(F.MSG_VAL_FILL_01), title=_("Quantity Required"))
	if pcs > pending:
		frappe.throw(_(F.MSG_VAL_FILL_02), title=_("Exceeds Planned Quantity"))
	if is_final and pcs < pending and wastage <= 0:
		frappe.throw(_(F.MSG_VAL_FILL_03), title=_("Filling Wastage Required"))

	available = flt(sub.wip_qty, 3)
	filled = flt(pcs * flt(doc.size_kg), 3)
	doc.available_wip_kg = available
	doc.equivalent_kg = filled
	doc.filled_kg = filled
	if wastage > available + F.EPS:
		frappe.throw(_(F.MSG_VAL_FILL_04), title=_("Wastage Exceeds WIP"))
	if filled + wastage > available + F.EPS:
		frappe.throw(_("Today's Input ({0} KG) plus Filling Wastage ({1} KG) exceeds the available "
		               "WIP of {2} ({3} KG).").format(filled, wastage, doc.sub_order, available),
		             title=_("Exceeds Available WIP"))

	# FRD 7.3.2, literally: Process Loss = Available WIP - Actual Filled Weight -- for the
	# inward that empties the Sub PO's hopper (a Final Inward with no other open plan row).
	# For any other inward the loss is the wastage entered.
	# default pending BA confirmation: loss formula per inward type.
	exclude_plan = plan.name if cint(doc.mark_run_complete) else None
	last_open = is_final and not _other_open_rows(doc.sub_order, exclude_plan=exclude_plan,
	                                              exclude_row=None if exclude_plan else row.name)
	if last_open:
		doc.process_loss_kg = flt(max(available - filled, 0), 3)
		doc.residual_written_off_kg = flt(max(available - filled - wastage, 0), 3)
	else:
		doc.process_loss_kg = wastage
		doc.residual_written_off_kg = 0
	doc.process_loss_pct = flt(doc.process_loss_kg / available * 100, 2) if available else 0
	doc.written_off_pcs = max(pending - pcs, 0) if is_final else 0

	# FRD 7.1 Abnormal Wastage: soft hold. Run weight = filled + wastage of this inward.
	# default pending BA confirmation: run weight definition; approval replaces the PIN.
	tolerance = 5.0
	try:
		tolerance = flt(F.S().wastage_tolerance_pct())
	except Exception:
		pass
	run_weight = filled + wastage
	if wastage > 0 and run_weight > 0 and wastage > run_weight * tolerance / 100 + F.EPS:
		doc.needs_approval = 1
		doc.approval_status = F.APPROVAL_PENDING
	else:
		doc.needs_approval = 0
		doc.approval_status = F.APPROVAL_NOT_REQUIRED


# ------------------------------------------------------------------------- submit

def on_submit_inward(doc):
	_lock_plan(doc.filling_plan)
	plan = frappe.get_doc(F.PLAN, doc.filling_plan)
	row = _plan_row(plan, doc.plan_row)
	sub = F.sub_info(doc.sub_order)
	settings = F.S()
	baked = settings.baked_wip_warehouse()
	pcs, wastage, filled = cint(doc.input_pcs), flt(doc.wastage_kg), flt(doc.filled_kg)
	is_final = doc.submission_type == F.SUB_FINAL
	common = dict(company=sub.company, posting_date=doc.posting_date, sub=sub.name,
	              parent=sub.get(F.PARENT_FIELD), fg_item=doc.target_sku)

	fg_batch, seq, stock_entry, writeoff = None, 0, None, None
	if pcs > 0:
		fg_hold = settings.fg_hold_warehouse()
		fg_batch, seq = _make_fg_batch(doc, sub)
		# default pending BA confirmation: the wastage is consumed in the same Repack (normal
		# loss absorbed into the FG cost) rather than written off separately.
		rows = F.draw_rows(sub.production_item, filled + wastage, [baked], prefer_sub=sub.name)
		per = F.pm_per_pack(doc.target_sku) or {}
		for item, q in per.items():
			rows += F.draw_rows(item, q * pcs, F.pm_warehouses())
		rows.append({"item_code": doc.target_sku, "qty": pcs, "t_warehouse": fg_hold,
		             "batch_no": fg_batch, "is_finished_item": 1})
		stock_entry = F.make_stock_entry("Repack", rows, remarks=_("Filling Inward {0}").format(doc.name),
		                                 **common)
	elif wastage > 0:
		rows = F.draw_rows(sub.production_item, wastage, [baked], prefer_sub=sub.name)
		stock_entry = F.make_stock_entry("Material Issue", rows,
		                                 remarks=_("Filling wastage, Filling Inward {0}").format(doc.name),
		                                 **common)

	residual = flt(doc.residual_written_off_kg)
	if residual > F.EPS:
		# Only what is physically there: custom_wip_qty is a planning number.
		physical = F.bin_qty(sub.production_item, baked)
		residual = flt(min(residual, max(physical, 0)), 3)
		if residual > F.EPS:
			rows = F.draw_rows(sub.production_item, residual, [baked], prefer_sub=sub.name)
			writeoff = F.make_stock_entry("Material Issue", rows,
			                              remarks=_("Final Inward {0}: residual baked WIP written off as process loss").format(doc.name),
			                              **common)
		doc.db_set("residual_written_off_kg", residual, update_modified=False)

	# ---- plan counters (FRD 7.3.3 step 6)
	prev_plan_status = plan.status
	row.completed_pcs = cint(row.completed_pcs) + pcs
	row.filled_kg = flt(flt(row.filled_kg) + filled, 3)
	row.wastage_kg = flt(flt(row.wastage_kg) + wastage, 3)
	row.consumed_kg = flt(flt(row.consumed_kg) + filled + wastage, 3)
	closed_rows = {}
	if is_final:
		row.written_off_pcs = cint(row.written_off_pcs) + cint(doc.written_off_pcs)
		row.row_status = F.ROW_CLOSED
		if cint(doc.mark_run_complete):
			for other in plan.rows:
				if other.name != row.name and other.row_status == F.ROW_OPEN:
					left = row_pending(other)
					closed_rows[other.name] = left
					other.written_off_pcs = cint(other.written_off_pcs) + left
					other.row_status = F.ROW_CLOSED
	if doc.needs_approval:
		plan.has_pending_approval = 1
	plan.flags.alpinos_filling = True
	plan.flags.alpinos_counters = True
	plan.save(ignore_permissions=True)

	# ---- Sub PO WIP and completion
	new_wip = flt(sub.wip_qty) - filled - wastage - flt(doc.residual_written_off_kg)
	F.set_sub_wip(sub.name, new_wip)
	sub_completed, prev_sub_status = 0, sub.get(F.EXEC_FIELD)
	if new_wip <= 0.001 and not _other_open_rows(sub.name, exclude_plan=plan.name) and \
			plan.status not in F.PLAN_OPEN_STATUSES:
		frappe.db.set_value(F.WORK_ORDER, sub.name, F.EXEC_FIELD, "Completed", update_modified=False)
		sub_completed = 1

	for field, value in (("fg_batch", fg_batch), ("inward_seq", seq), ("stock_entry", stock_entry),
	                     ("writeoff_entry", writeoff), ("row_closed", 1 if is_final else 0),
	                     ("closed_rows", json.dumps(closed_rows) if closed_rows else None),
	                     ("prev_plan_status", prev_plan_status), ("sub_completed", sub_completed),
	                     ("prev_sub_status", prev_sub_status)):
		doc.db_set(field, value, update_modified=False)

	if sub_completed:
		from alpinos.production.filling_yield import check_parent_completion
		check_parent_completion(sub.get(F.PARENT_FIELD))

	_notify_after_submit(doc, plan, fg_batch, is_final)
	F.audit(F.INWARD, doc.name, "Filling Inward",
	        _("{0} pcs of {1} ({2} KG), wastage {3} KG, loss {4} KG ({5}%), batch {6}").format(
		        pcs, doc.target_sku, filled, wastage, doc.process_loss_kg, doc.process_loss_pct,
		        fg_batch or "-"))


def _notify_after_submit(doc, plan, fg_batch, is_final):
	if is_final:
		# Spam rule: QC is told once, on the Final Inward, about every FG-Hold batch of the run.
		batches = frappe.get_all(F.INWARD, filters={"filling_plan": plan.name, "plan_row": doc.plan_row,
		                                            "docstatus": 1, "fg_batch": ("is", "set")},
		                         pluck="fg_batch")
		if fg_batch and fg_batch not in batches:
			batches.append(fg_batch)
		if batches:
			F.notify(F.QC_ROLES[:2], _("New Batch {0} ready for QC").format(", ".join(batches)),
			         "Batch", batches[-1])
	if cint(doc.needs_approval):
		F.notify((F.C.ROLE_PRODUCTION_MANAGER, F.ROLE_PLANT_HEAD),
		         _("Abnormal filling wastage on {0}: {1} KG for {2} pcs of {3}. Approval required.").format(
			         doc.name, doc.wastage_kg, doc.input_pcs, doc.target_sku),
		         F.INWARD, doc.name, email=True)


# -------------------------------------------------------------------------- cancel

def before_cancel_inward(doc):
	if not doc.flags.get("alpinos_filling"):
		frappe.throw(_("Use Reverse & Adjust Inward on the Filling Entry screen."),
		             title=_("Not Allowed"))


def on_cancel_inward(doc):
	_lock_plan(doc.filling_plan)
	for name in (doc.writeoff_entry, doc.stock_entry):
		F.cancel_stock_entry(name)
	if doc.fg_batch and frappe.db.exists("Batch", doc.fg_batch):
		frappe.db.set_value("Batch", doc.fg_batch, "disabled", 1, update_modified=False)

	plan = frappe.get_doc(F.PLAN, doc.filling_plan)
	row = _plan_row(plan, doc.plan_row)
	pcs, wastage, filled = cint(doc.input_pcs), flt(doc.wastage_kg), flt(doc.filled_kg)
	row.completed_pcs = max(cint(row.completed_pcs) - pcs, 0)
	row.filled_kg = max(flt(flt(row.filled_kg) - filled, 3), 0)
	row.wastage_kg = max(flt(flt(row.wastage_kg) - wastage, 3), 0)
	row.consumed_kg = max(flt(flt(row.consumed_kg) - filled - wastage, 3), 0)
	if cint(doc.row_closed):
		row.written_off_pcs = max(cint(row.written_off_pcs) - cint(doc.written_off_pcs), 0)
		row.row_status = F.ROW_OPEN
	closed = json.loads(doc.closed_rows) if doc.closed_rows else {}
	for other in plan.rows:
		if other.name in closed:
			other.written_off_pcs = max(cint(other.written_off_pcs) - cint(closed[other.name]), 0)
			other.row_status = F.ROW_OPEN
	if plan.status in (F.PLAN_COMPLETED, F.PLAN_SHORT_CLOSED):
		plan.status = F.PLAN_IN_PROGRESS  # recomputed by validate
	plan.has_pending_approval = _plan_has_pending(plan.name, exclude=doc.name)
	plan.flags.alpinos_filling = True
	plan.flags.alpinos_counters = True
	plan.save(ignore_permissions=True)

	sub = F.sub_info(doc.sub_order)
	F.set_sub_wip(sub.name, flt(sub.wip_qty) + filled + wastage + flt(doc.residual_written_off_kg))
	if cint(doc.sub_completed):
		frappe.db.set_value(F.WORK_ORDER, sub.name, F.EXEC_FIELD,
		                    doc.prev_sub_status or "Ready for Next Stage", update_modified=False)
		# The yield record was computed on a completion that no longer holds.
		for name in frappe.get_all(F.YIELD, filters={"parent_po": doc.parent_po}, pluck="name") \
				if frappe.db.exists("DocType", F.YIELD) else []:
			frappe.delete_doc(F.YIELD, name, ignore_permissions=True, force=True)
	F.audit(F.INWARD, doc.name, "Reverse Inward",
	        _("{0} pcs / {1} KG reversed, batch {2} disabled").format(pcs, filled, doc.fg_batch or "-"),
	        doc.reversal_reason or "")


def _plan_has_pending(plan, exclude=None):
	filters = {"filling_plan": plan, "docstatus": 1, "approval_status": F.APPROVAL_PENDING}
	if exclude:
		filters["name"] = ("!=", exclude)
	return 1 if frappe.get_all(F.INWARD, filters=filters, limit=1) else 0


# ------------------------------------------------------------------------ actions

@frappe.whitelist()
def submit_inward(payload):
	"""Submit Inward (FRD 7.2). Validates, records and posts stock in one step."""
	F.require(F.OPERATOR_ROLES, _("record a Filling Inward"))
	p = F.parse(payload)
	if not p.get("filling_plan") or not p.get("plan_row"):
		frappe.throw(_("Choose the plan row you are filling."), title=_("Plan Required"))
	_lock_plan(p.filling_plan)
	doc = frappe.new_doc(F.INWARD)
	doc.filling_plan = p.filling_plan
	doc.plan_row = p.plan_row
	doc.posting_date = nowdate()
	doc.input_pcs = cint(p.get("input_pcs"))
	doc.wastage_kg = flt(p.get("wastage_kg"))
	doc.submission_type = p.get("submission_type") or F.SUB_PARTIAL
	doc.mark_run_complete = cint(p.get("mark_run_complete"))
	for field in ("mfg_date", "rm_batch_ref", "manpower_count", "premix_code", "remarks"):
		if p.get(field) not in (None, ""):
			doc.set(field, p.get(field))
	doc.flags.alpinos_filling = True
	doc.insert(ignore_permissions=True)
	doc.flags.alpinos_filling = True
	doc.submit()
	frappe.db.commit()
	doc.reload()
	return {"name": doc.name, "fg_batch": doc.fg_batch, "input_pcs": doc.input_pcs,
	        "needs_approval": cint(doc.needs_approval), "process_loss_kg": doc.process_loss_kg,
	        "process_loss_pct": doc.process_loss_pct}


@frappe.whitelist()
def preview_inward(payload):
	"""Read-only numbers for the screen (Equivalent KG, Process Loss) before submitting."""
	F.require(F.OPERATOR_ROLES, _("record a Filling Inward"))
	p = F.parse(payload)
	plan = frappe.get_doc(F.PLAN, p.filling_plan)
	row = _plan_row(plan, p.plan_row)
	sub = F.sub_info(plan.sub_order)
	size = flt(row.size_kg)
	pcs, wastage = cint(p.get("input_pcs")), flt(p.get("wastage_kg"))
	is_final = p.get("submission_type") == F.SUB_FINAL or cint(p.get("mark_run_complete"))
	available = flt(sub.wip_qty, 3)
	filled = flt(pcs * size, 3)
	exclude_plan = plan.name if cint(p.get("mark_run_complete")) else None
	last_open = is_final and not _other_open_rows(plan.sub_order, exclude_plan=exclude_plan,
	                                              exclude_row=None if exclude_plan else row.name)
	loss = max(available - filled, 0) if last_open else wastage
	return {"equivalent_kg": filled, "available_wip_kg": available, "process_loss_kg": flt(loss, 3),
	        "process_loss_pct": flt(loss / available * 100, 2) if available else 0,
	        "empties_hopper": int(bool(last_open))}


@frappe.whitelist()
def reverse_inward(inward, reason):
	"""Reverse & Adjust Inward (FRD 7.4.3): Admin only, reason mandatory, audit-logged."""
	F.require(F.REVERSE_ROLES, _("reverse a Filling Inward"))
	if not (reason or "").strip():
		frappe.throw(_("Please give the reason for the reversal."), title=_("Reason Required"))
	doc = frappe.get_doc(F.INWARD, inward)
	if cint(doc.docstatus) != 1:
		frappe.throw(_("{0} is not a submitted inward.").format(inward), title=_("Cannot Reverse"))
	if frappe.db.get_value(F.PLAN, doc.filling_plan, "status") == F.PLAN_REROUTED:
		frappe.throw(_("{0} has been re-routed; its inwards can no longer be reversed.").format(
			doc.filling_plan), title=_("Cannot Reverse"))
	latest = frappe.get_all(F.INWARD, filters={"filling_plan": doc.filling_plan, "docstatus": 1},
	                        pluck="name", order_by="creation desc", limit=1)
	if latest and latest[0] != doc.name:
		frappe.throw(_("Reverse the latest inward of this plan first ({0}).").format(latest[0]),
		             title=_("Not The Latest Inward"))
	if doc.fg_batch and frappe.db.exists("DocType", F.FINAL_QC):
		qc = frappe.get_all(F.FINAL_QC, filters={"fg_batch": doc.fg_batch, "docstatus": ("<", 2)},
		                    pluck="name", limit=1)
		if qc:
			frappe.throw(_("Final QC {0} exists for batch {1}. It must be revoked or deleted first.").format(
				qc[0], doc.fg_batch), title=_("Batch Already In QC"))
	doc.flags.alpinos_filling = True
	doc.flags.ignore_permissions = True
	doc.db_set({"reversal_reason": reason.strip(), "reversed_by": frappe.session.user},
	           update_modified=False)
	doc.reversal_reason = reason.strip()
	doc.cancel()
	frappe.db.commit()
	return {"reversed": doc.name}


@frappe.whitelist()
def approve_wastage(inward, remarks=None):
	"""Abnormal-wastage override (FRD 7.1, replaces the Supervisor PIN)."""
	F.require(F.APPROVER_ROLES, _("approve abnormal filling wastage"))
	doc = frappe.get_doc(F.INWARD, inward)
	if cint(doc.docstatus) != 1 or doc.approval_status != F.APPROVAL_PENDING:
		frappe.throw(_("{0} is not awaiting approval.").format(inward), title=_("Nothing To Approve"))
	doc.db_set({"approval_status": F.APPROVAL_APPROVED, "approved_by": frappe.session.user,
	            "approved_on": now_datetime(), "approval_remarks": remarks or ""})
	frappe.db.set_value(F.PLAN, doc.filling_plan, "has_pending_approval",
	                    _plan_has_pending(doc.filling_plan), update_modified=False)
	F.audit(F.INWARD, doc.name, "Wastage Approved", _("{0} KG").format(doc.wastage_kg), remarks or "")
	frappe.db.commit()
	return {"approved": doc.name}


# ------------------------------------------------------------------------ screens

@frappe.whitelist()
def get_entry_context():
	"""Filling Entry: the open plan rows an operator can fill, recent inwards, approvals."""
	F.require(F.FILLING_READ_ROLES, _("open Filling Entry"))
	plans = frappe.get_all(F.PLAN, filters={"status": ("in", F.PLAN_OPEN_STATUSES)},
	                       fields=["name", "plan_date", "parent_po", "sub_order", "filling_line",
	                               "line_category", "status"],
	                       order_by="plan_date asc, name asc", limit_page_length=500)
	names = [p.name for p in plans]
	rows = {}
	if names:
		for r in frappe.get_all(F.PLAN_ROW, filters={"parent": ("in", names), "parenttype": F.PLAN,
		                                             "row_status": F.ROW_OPEN},
		                        fields=["name", "parent", "target_sku", "sku_name", "size_kg",
		                                "planned_pcs", "completed_pcs", "pending_pcs"],
		                        order_by="idx asc"):
			rows.setdefault(r.parent, []).append(r)
	machines = {m.name: m for m in frappe.get_all(
		"Machine", filters={"name": ("in", [p.filling_line for p in plans] or [""])},
		fields=["name", "machine_name", "status"])}
	options = []
	for p in plans:
		m = machines.get(p.filling_line) or frappe._dict()
		sub = F.sub_info(p.sub_order) or {}
		for r in rows.get(p.name, []):
			options.append({
				"plan": p.name, "row": r.name, "plan_date": p.plan_date, "parent_po": p.parent_po,
				"sub_order": p.sub_order, "batch_number": sub.get(F.BATCH_FIELD),
				"filling_line": p.filling_line, "line_label": m.get("machine_name") or p.filling_line,
				"line_active": int(m.get("status") == F.C.MACHINE_ACTIVE),
				"line_category": p.line_category, "target_sku": r.target_sku, "sku_name": r.sku_name,
				"size_kg": r.size_kg, "planned_pcs": r.planned_pcs, "completed_pcs": r.completed_pcs,
				"pending_pcs": r.pending_pcs, "wip_qty": flt(sub.get("wip_qty"), 3),
			})
	recent = frappe.get_all(F.INWARD, filters={"docstatus": ("<", 2)},
	                        fields=["name", "posting_date", "filling_plan", "filling_line", "sub_order",
	                                "target_sku", "input_pcs", "wastage_kg", "process_loss_kg",
	                                "process_loss_pct", "submission_type", "fg_batch",
	                                "approval_status", "owner"],
	                        order_by="creation desc", limit_page_length=30)
	return {
		"options": options, "recent": recent, "shift": F.current_shift_name(),
		"can_submit": int(F.has_any(F.OPERATOR_ROLES)),
		"can_reverse": int(F.has_any(F.REVERSE_ROLES)),
		"can_approve": int(F.has_any(F.APPROVER_ROLES)),
		"tolerance_pct": _tolerance(),
	}


def _tolerance():
	try:
		return flt(F.S().wastage_tolerance_pct())
	except Exception:
		return 5.0
