"""GRN generation — the Draft Purchase Receipt minted from a QC-completed Purchase Inward.

BRD "Purchase Inward Part -1" section 5: BR-GRN-01 .. BR-GRN-05, VAL-GRN-01 / VAL-GRN-02.

Quantity mapping (field surface documented in alpinos/purchase/purchase_receipt_fields.py):

	QC Approved Qty  ->  Purchase Receipt Item.qty           (core label "Accepted Quantity")
	QC Rejected Qty  ->  Purchase Receipt Item.rejected_qty
	                     received_qty is never written — BuyingController.
	                     validate_accepted_rejected_qty forces it to accepted + rejected and
	                     raises QtyMismatchError for anything else.

So the store's received quantity is NOT what lands on the GRN once QC has drawn samples:
approved + rejected is what ERPNext takes into stock, and the sampled quantity stays on the
Purchase QC. A received_qty larger than accepted + rejected cannot be expressed on a
Purchase Receipt at all, so there is nothing to choose here.

Manufacturing and expiry date have no home on Purchase Receipt Item in v15 — ERPNext models
them on the Batch. This module links a Batch that already exists and never mints one;
minting the internal batch is BR-QC-11 / BR-QC-12's job, and this module picks the link up
on the next sync once it does.

Registered in alpinos/hooks.py (owned by the orchestrator): nothing. `make_debit_note` is
reached from the Purchase Receipt `on_submit` adapter in hooks_glue; the user-facing entry
points are whitelisted methods called from the form and the list page:

	alpinos.purchase.grn.generate_grn
	alpinos.purchase.grn.sync_from_inward
	alpinos.purchase.grn.generate_debit_note
"""

import re

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, now_datetime, nowtime

from alpinos.purchase import constants as C
from alpinos.purchase import workflow
from alpinos.purchase.settings import warehouse as settings_warehouse

DOCTYPE = "Purchase Receipt"
ITEM_DOCTYPE = "Purchase Receipt Item"
# BR-GRN-09's "Debit Note" has no doctype of its own: in ERPNext a purchase debit note IS a
# Purchase Invoice with is_return=1 and negative quantities, which is what the read-only
# `debit_note` Link fields on Purchase Inward / Purchase QC already point at.
DEBIT_NOTE_DOCTYPE = "Purchase Invoice"
DEBIT_NOTE_NAMING_SERIES = "ACC-PINV-RET-.YYYY.-"

# "Row 3: Rejected Warehouse", "Row #3 — Rejected Warehouse" — the row-scoped shape a GRN
# Change Log entry uses for a grid edit (BR-GRN-05).
_ROW_LABEL = re.compile(r"^\s*row\s*#?\s*(\d+)\s*[:\-–—]\s*(.+)$", re.IGNORECASE)


# --------------------------------------------------------------- public API


def existing_grn(purchase_inward):
	"""The live GRN for an inward, or None. A cancelled one does not count (BR-GRN-02)."""
	_assert_grn_fields()
	rows = frappe.get_all(
		DOCTYPE,
		filters={"custom_purchase_inward": purchase_inward, "docstatus": ("<", 2)},
		pluck="name",
		order_by="creation asc",
		limit=1,
	)
	return rows[0] if rows else None


def make_purchase_receipt(purchase_inward):
	"""Mint (or return) the one Draft Purchase Receipt for `purchase_inward`.

	Not whitelisted: `generate_grn` is the guarded entry point. This is the mapper, called
	by that action and by anything else that legitimately needs the GRN to exist.

	The insert runs with ignore_permissions because BR-GRN-03 makes this the *system*
	generating the GRN, not the user pressing the button; who may press it is decided by
	`generate_grn`'s workflow transition, which is the single source of truth for that.
	"""
	inward = _inward(purchase_inward)

	# BR-GRN-02: one inward yields exactly one Purchase Receipt. Re-running is a no-op, so
	# a double-clicked button or a retried job cannot mint a second receipt against the
	# same PO lines. A cancelled receipt is skipped, which lets a fresh draft be raised.
	# The row lock serialises two concurrent generators on the inward; without it both read
	# "no GRN yet" and both insert, and nothing downstream would catch the duplicate.
	frappe.db.get_value("Purchase Inward", inward.name, "name", for_update=True)
	found = existing_grn(inward.name)
	if found:
		return frappe.get_doc(DOCTYPE, found)

	qc = _assert_qc_complete(inward)
	rows = _grn_rows(inward, qc)
	if not rows:
		frappe.throw(
			_("GRN cannot be generated because there is no approved quantity."),
			title=_("VAL-GRN-02"),
		)

	pr = frappe.new_doc(DOCTYPE)
	_apply_header(pr, inward, qc)
	for source in rows:
		_apply_row(pr.append("items", {}), source)

	pr.insert(ignore_permissions=True)
	return pr


@frappe.whitelist()
def generate_grn(purchase_inward):
	"""Workflow action behind the "Generate GRN" button (BRD 2.3, BR-GRN-03)."""
	inward = frappe.get_doc("Purchase Inward", purchase_inward)
	inward.check_permission("read")
	workflow.assert_transition(inward, "generate_grn", frappe.session.user)

	pr = make_purchase_receipt(inward)

	inward.db_set(
		{"purchase_receipt": pr.name, "grn_status": C.GRN_DRAFT}, update_modified=False
	)
	workflow.set_status(inward, C.PI_GRN_GENERATED)

	return {
		"purchase_receipt": pr.name,
		"grn_status": C.GRN_DRAFT,
		"inward_status": C.PI_GRN_GENERATED,
	}


def mark_submitted(pr):
	"""Stamp the final-submission trail on a just-submitted GRN (BRD 5.2.1, BR-GRN-06).

	C.GRN_COMPLETED was declared but assigned nowhere, so a final-submitted receipt kept
	custom_grn_status = "Draft" for ever. That field is in_list_view + in_standard_filter,
	so the Purchase Receipt list showed every completed GRN as Draft and filtering
	"Completed" returned nothing; "Final Submitted By" / "Final Submission Date & Time"
	were never written by anything at all.
	"""
	_stamp_grn_status(pr, C.GRN_COMPLETED, stamp_submitter=True)


def mark_cancelled(pr):
	"""Flip the GRN trail to Cancelled when the receipt is cancelled (BR-GRN-07).

	The submitter and timestamp are left in place — they record a submission that really
	happened — and generate_grn resets grn_status to Draft when a fresh receipt is raised.
	"""
	_stamp_grn_status(pr, C.GRN_CANCELLED)


def _stamp_grn_status(pr, status, stamp_submitter=False):
	"""Write `status` onto the receipt and roll it onto the parent Purchase Inward.

	db_set on both sides: on_submit / on_cancel run *after* the row has been written, so a
	plain assignment would never reach the database, and the inward's grn_status is an
	engine-owned field that PurchaseInward._guard_engine_owned_fields refuses on the save
	path — db_set is the bypass the engine is meant to use. Receipts that did not come from
	this module carry no inward and are left untouched.
	"""
	inward_name = pr.get("custom_purchase_inward")
	if not inward_name:
		return

	values = {"custom_grn_status": status}
	if stamp_submitter and frappe.get_meta(DOCTYPE).has_field("custom_final_submitted_by"):
		values["custom_final_submitted_by"] = frappe.session.user
		values["custom_final_submission_datetime"] = now_datetime()
	pr.db_set(values, update_modified=False)

	if frappe.db.exists("Purchase Inward", inward_name):
		frappe.get_doc("Purchase Inward", inward_name).db_set(
			"grn_status", status, update_modified=False
		)


def resync_draft_grn(inward):
	"""Re-pull a Draft GRN after its Purchase Inward changed (BR-GRN-04, task 299).

	`sync_from_inward` is the operator-facing endpoint and checks WRITE on the receipt.
	This is the system path, called from PurchaseInward.on_update_after_submit: the right
	to edit the receiving section is the gate, and the GRN re-pull is a consequence of it.
	Store roles hold only VIEW on Purchase Receipt, so going through the whitelisted
	function here would refuse the very people the BRD expects to correct a receipt.

	Deliberately quiet and best effort: a re-sync failure must never roll back a
	legitimate receiving correction. Nothing happens unless a DRAFT GRN exists.

	NOT whitelisted -- it must not be reachable from the client.
	"""
	name = getattr(inward, "name", inward)
	if not name:
		return None

	receipt = frappe.db.get_value(
		DOCTYPE,
		{"custom_purchase_inward": name, "docstatus": 0},
		"name",
	)
	if not receipt:
		return None

	try:
		return _sync_from_inward(frappe.get_doc(DOCTYPE, receipt))
	except Exception:
		frappe.log_error(
			title="Purchase Inward: draft GRN re-sync failed",
			message=f"{name} -> {receipt}\n{frappe.get_traceback()}",
		)
		return None


@frappe.whitelist()
def sync_from_inward(purchase_receipt):
	"""Re-pull warehouse / rate / batch / quantities onto a Draft GRN (BR-GRN-04).

	Fields a person edited on the draft are left alone. BR-GRN-05 makes the Purchase GRN
	Change Log the record of every Draft-GRN edit, so it is also the only trustworthy answer
	to "did a person set this, or did we?" — an empty log means nothing was hand-edited and
	a full re-pull is safe. A blank source value never blanks out a value already on the
	receipt, so a source field that has not been captured yet cannot erase one that has.

	Returns {"changed": [labels], "added_rows": n}.
	"""
	pr = frappe.get_doc(DOCTYPE, purchase_receipt)
	pr.check_permission("write")

	if not pr.get("custom_purchase_inward"):
		frappe.throw(_("{0} was not generated from a Purchase Inward.").format(pr.name))
	if pr.docstatus != 0:
		frappe.throw(_("Completed GRN cannot be edited."), title=_("VAL-GRN-07"))

	return _sync_from_inward(pr)


def _sync_from_inward(pr):
	"""The re-pull itself. Callers own the permission decision (see resync_draft_grn)."""
	if not pr.get("custom_purchase_inward") or pr.docstatus != 0:
		return None

	inward = _inward(pr.custom_purchase_inward)
	qc = _qc(inward)
	protected_parent, protected_rows = _protected_fields(pr)
	changed = []

	for fieldname, value, label in _header_values(inward, qc):
		_assign(pr, fieldname, value, protected_parent, changed, label)

	by_inward_item = {}
	by_po_detail = {}
	for row in pr.get("items") or []:
		if row.get("custom_purchase_inward_item"):
			by_inward_item[row.custom_purchase_inward_item] = row
		if row.get("purchase_order_item"):
			by_po_detail.setdefault(row.purchase_order_item, row)

	added = 0
	for source in _grn_rows(inward, qc):
		row = by_inward_item.get(source["purchase_inward_item"]) or by_po_detail.get(
			source["po_detail"]
		)
		if not row:
			# QC approved a line the draft has no row for (a re-decision, or a row deleted
			# before this module owned the sync). Add it rather than silently under-receive.
			_apply_row(pr.append("items", {}), source)
			added += 1
			continue
		guarded = protected_rows.get(cint(row.idx), set())
		for fieldname, value, label in _row_values(source):
			_assign(row, fieldname, value, guarded, changed, "Row {0}: {1}".format(row.idx, label))
		# A batch that only appeared after the draft was minted (QC mints the internal
		# batch at submit) arrives through _assign above, but batch_no alone is inert:
		# make_bundle_using_old_serial_batch_fields only reads it when this flag is on,
		# so without it ERPNext silently auto-mints a different batch at GRN submit.
		if row.get("batch_no") and not cint(row.get("use_serial_batch_fields")):
			row.use_serial_batch_fields = 1

	if not (changed or added):
		return {"changed": [], "added_rows": 0}

	pr.save()
	return {"changed": changed, "added_rows": added}


def existing_debit_note(purchase_receipt):
	"""The live Debit Note raised against a GRN, or None. A cancelled one does not count."""
	linked = frappe.db.get_value(DOCTYPE, purchase_receipt, "custom_debit_note")
	if linked and frappe.db.get_value(DEBIT_NOTE_DOCTYPE, linked, "docstatus") != 2:
		return linked
	# custom_debit_note is only the mirror on the GRN; the item rows are what the debit note
	# itself carries, so they are the authoritative answer for a GRN whose mirror was never
	# written (a generation that failed half way) or was cleared by hand. Without this second
	# look a retry would raise a SECOND debit note for the same rejected quantity.
	for name in frappe.get_all(
		"Purchase Invoice Item",
		filters={"purchase_receipt": purchase_receipt, "docstatus": ("<", 2)},
		pluck="parent",
		order_by="creation asc",
	):
		if cint(frappe.db.get_value(DEBIT_NOTE_DOCTYPE, name, "is_return")):
			# Repair the mirror we just fell back from, so the next reader (the list column,
			# the "View Debit Note" button, the print format) does not have to repeat this
			# scan and the GRN stops looking as though it has no debit note.
			if not linked:
				frappe.db.set_value(
					DOCTYPE, purchase_receipt, "custom_debit_note", name, update_modified=False
				)
			return name
	return None


def make_debit_note(purchase_receipt):
	"""Mint (or return) the one Draft Debit Note for a final-submitted GRN.

	BR-GRN-09 / VAL-GRN-08 / BR-QC-21 / VAL-QC-17: a rejected quantity greater than zero
	raises the applicable Debit Note. BR-GRN-10 / VAL-GRN-09: a GRN with no rejected quantity
	raises none, and this returns None.

	BRD 5 puts the trigger at final submission -- "Once submitted, the GRN becomes the
	finalized GRN document. If the QC Rejected Quantity is greater than zero, the system
	shall generate the applicable Debit Note against the GRN" -- which is also the first
	moment the rejected quantity is real stock sitting in the Rejected warehouse.

	It is left in DRAFT on purpose. BR-GRN-14 hands "financial invoice creation and
	subsequent payment processing" to the Purchase Invoice process, which is BRD section 6
	and outside this build; Accounts owns posting it to the ledger, exactly as the module
	greys out create_purchase_invoice / complete_payment rather than posting them itself.

	update_stock stays off: the rejected quantity is already in the Rejected warehouse,
	posted by the GRN itself, so a stock-updating return would take it out a second time.

	Returns the Purchase Invoice document, or None when there is nothing to raise.
	"""
	pr = (
		frappe.get_doc(DOCTYPE, purchase_receipt)
		if isinstance(purchase_receipt, str)
		else purchase_receipt
	)
	if pr.docstatus != 1:
		return None

	rejected = [row for row in (pr.get("items") or []) if flt(row.rejected_qty) > 0]
	if not rejected:
		# BR-GRN-10 / VAL-GRN-09 -- nothing rejected, no Debit Note.
		return None

	# The same row lock make_purchase_receipt takes: without it a double-clicked retry or two
	# concurrent submits both read "no debit note yet" and both insert one.
	frappe.db.get_value(DOCTYPE, pr.name, "name", for_update=True)
	found = existing_debit_note(pr.name)
	if found:
		return frappe.get_doc(DEBIT_NOTE_DOCTYPE, found)

	inward = _inward(pr.custom_purchase_inward) if pr.get("custom_purchase_inward") else None

	note = frappe.new_doc(DEBIT_NOTE_DOCTYPE)
	note.company = pr.company
	note.supplier = pr.supplier
	note.is_return = 1
	note.update_stock = 0
	# The rejected quantity was never part of the GRN's billable amount (`qty` is the accepted
	# quantity), so letting this debit note write back a billed amount would make the GRN look
	# part-billed and the real Purchase Invoice over-billed later.
	note.update_billed_amount_in_purchase_receipt = 0
	note.posting_date = getdate()
	note.posting_time = nowtime()
	note.set_posting_time = 0
	note.currency = pr.currency
	note.conversion_rate = flt(pr.conversion_rate) or 1.0
	note.buying_price_list = pr.buying_price_list
	note.taxes_and_charges = pr.taxes_and_charges
	if inward:
		# BRD 5.6 "Link Debit Note": vendor, GRN, Purchase Inward, Invoice Number and the
		# rejected quantity. bill_no is ERPNext's home for the vendor's invoice number.
		note.bill_no = inward.invoice_number
		note.bill_date = inward.invoice_date
	series = _debit_note_naming_series()
	if series:
		note.naming_series = series
	note.remarks = _("Debit Note for the quantity rejected at QC on GRN {0}.").format(pr.name)

	for row in rejected:
		note.append(
			"items",
			{
				"item_code": row.item_code,
				"item_name": row.item_name,
				"description": row.description,
				"uom": row.uom,
				"stock_uom": row.stock_uom,
				"conversion_factor": flt(row.conversion_factor) or 1.0,
				# A return line is a negative line; is_return is what makes it legal.
				"qty": -abs(flt(row.rejected_qty)),
				"rate": flt(row.rate),
				"warehouse": row.rejected_warehouse or row.warehouse,
				"cost_center": row.cost_center,
				"project": row.project,
				"purchase_order": row.purchase_order,
				"po_detail": row.purchase_order_item,
				"purchase_receipt": pr.name,
				"pr_detail": row.name,
			},
		)

	note.insert(ignore_permissions=True)

	# db_set, not save(): every one of these is a read_only / allow_on_submit engine-owned
	# link on a submitted document, and PurchaseInward._guard_engine_owned_fields refuses
	# anything that arrives through the save path.
	pr.db_set("custom_debit_note", note.name, update_modified=False)
	if inward:
		inward.db_set("debit_note", note.name, update_modified=False)
	if pr.get("custom_purchase_qc"):
		frappe.db.set_value(
			"Purchase QC", pr.custom_purchase_qc, "debit_note", note.name, update_modified=False
		)
	return note


def _debit_note_naming_series():
	"""The return series, but only while it is still offered on Purchase Invoice.

	A debit note that fell back to ACC-PINV- would eat the vendor-invoice counter and be
	indistinguishable from a real purchase invoice in every list and report.
	"""
	options = frappe.get_meta(DEBIT_NOTE_DOCTYPE).get_field("naming_series")
	options = (options.options or "") if options else ""
	return DEBIT_NOTE_NAMING_SERIES if DEBIT_NOTE_NAMING_SERIES in options.splitlines() else None


@frappe.whitelist()
def generate_debit_note(purchase_receipt):
	"""Re-run debit-note generation for a GRN whose automatic attempt failed (BR-GRN-09).

	Gated on the authority that final-submits the GRN, because that submission is what
	should have raised it; nobody else may mint a financial document from this module.
	"""
	from alpinos.purchase.roles import assert_can_submit_grn

	pr = frappe.get_doc(DOCTYPE, purchase_receipt)
	pr.check_permission("read")

	# assert_can_submit_grn is a before_submit doc_event: it returns SILENTLY for any
	# receipt that is not one of this module's GRNs. Without this marker check the only
	# remaining gate on a non-module receipt would be read permission, and make_debit_note
	# inserts with ignore_permissions -- so anyone who could read an ordinary alpinos
	# stock receipt could mint a financial document against it.
	if not pr.get("custom_purchase_inward"):
		frappe.throw(
			_("{0} is not a Purchase Inward GRN, so no Debit Note can be raised for it.").format(
				pr.name
			),
			title=_("Not a GRN"),
		)

	assert_can_submit_grn(pr)
	note = make_debit_note(pr)
	return {"debit_note": note.name if note else None}


# ------------------------------------------------------------------ sources


def _inward(purchase_inward):
	if isinstance(purchase_inward, str):
		return frappe.get_doc("Purchase Inward", purchase_inward)
	return purchase_inward


def _qc(inward):
	return frappe.get_doc("Purchase QC", inward.purchase_qc) if inward.purchase_qc else None


def _assert_qc_complete(inward):
	"""VAL-GRN-01 / VAL-GRN-02 — QC must have finished and approved something."""
	qc = _qc(inward)
	if not qc or qc.docstatus == 2 or qc.qc_status != C.QC_COMPLETED:
		frappe.throw(
			_("Cannot generate GRN. Quality Control process is not completed."),
			title=_("VAL-GRN-01"),
		)
	if qc.qc_result not in C.QC_RESULTS_ALLOWING_GRN:
		frappe.throw(
			_("GRN cannot be generated because there is no approved quantity."),
			title=_("VAL-GRN-02"),
		)
	return qc


def _qc_row_maps(qc):
	"""({inward row name: QC row}, {po_detail: QC row}) — Purchase QC Item autonames by hash,
	so the inward row name is the only identity that survives duplicate item codes."""
	by_row, by_po = {}, {}
	for row in (qc.get("items") if qc else None) or []:
		if row.get("purchase_inward_item"):
			by_row[row.purchase_inward_item] = row
		if row.get("po_detail"):
			by_po.setdefault(row.po_detail, row)
	return by_row, by_po


def _grn_rows(inward, qc):
	"""One dict per GRN line, in inward order. QC decides the quantities."""
	by_row, by_po = _qc_row_maps(qc)
	rejected_warehouse = _rejected_warehouse(inward)
	out = []

	for line in inward.get("items") or []:
		if flt(line.received_qty) <= 0:
			continue
		decision = by_row.get(line.name) or by_po.get(line.po_detail)
		approved = flt(decision.approved_qty) if decision else 0.0
		rejected = flt(decision.rejected_qty) if decision else 0.0

		# A fully sampled or fully undecided line has nothing for stock to do. A 100%
		# rejected line does: accounts_controller carves it out of the zero-qty check and
		# it posts a real receipt into the rejected warehouse.
		if approved <= 0 and rejected <= 0:
			continue

		warehouse = (
			(decision.target_warehouse if decision else None)
			or line.target_warehouse
			or inward.target_warehouse
		)
		if rejected > 0:
			if not rejected_warehouse:
				frappe.throw(
					_(
						"Row {0}: Rejected Warehouse is not set in Purchase Inward Settings, "
						"so the rejected quantity has nowhere to go."
					).format(line.idx)
				)
			if rejected_warehouse == warehouse:
				frappe.throw(
					_("Row {0}: Accepted Warehouse and Rejected Warehouse cannot be the same.").format(
						line.idx
					)
				)

		out.append(
			{
				"idx": line.idx,
				"item_code": line.item_code,
				"item_name": line.item_name,
				"description": line.description,
				"uom": line.uom,
				"stock_uom": line.stock_uom,
				"conversion_factor": flt(line.conversion_factor) or 1.0,
				"qty": approved,
				"rejected_qty": rejected,
				"warehouse": warehouse,
				"rejected_warehouse": rejected_warehouse if rejected > 0 else None,
				"rate": flt(line.rate),
				"purchase_order": line.purchase_order or inward.purchase_order,
				"po_detail": line.po_detail,
				"purchase_inward_item": line.name,
				"rejection_reason": (decision.rejection_reason if decision else None)
				or (qc.rejection_reason if qc and rejected > 0 else None),
				"usp": line.usp,
				"mrp": flt(line.mrp),
				"batch_no": _batch_no(
					line.item_code,
					(decision.internal_batch_no if decision else None) or line.batch_no,
				),
			}
		)
	return out


def _rejected_warehouse(inward):
	return settings_warehouse(C.WH_REJECTED, inward.company)


def _batch_no(item_code, batch_id):
	"""The Batch to link, or None.

	batch_no is a Link to Batch, so writing a batch id that has no Batch document fails link
	validation on save. Purchase QC mints that Batch at submit (BR-QC-11 / BR-QC-12,
	PurchaseQC._mint_internal_batches), which is what lets this line carry the SAME id the QC
	document and the QC report show. A code with no Batch behind it — an item that is not
	batch tracked, or one whose expiry date could not be derived — still falls through to
	None and ERPNext auto-mints an id of its own at submit.
	"""
	if not (item_code and batch_id):
		return None
	if not cint(frappe.db.get_value("Item", item_code, "has_batch_no")):
		return None
	return batch_id if frappe.db.exists("Batch", batch_id) else None


# ------------------------------------------------------------------ mapping


def _apply_header(pr, inward, qc):
	pr.company = inward.company
	pr.supplier = inward.supplier
	# Posting date can never be in the future (purchase_receipt.py:267), so the GRN is
	# stamped now rather than carrying the inward's arrival timestamp forward.
	pr.posting_date = getdate()
	pr.posting_time = nowtime()
	pr.set_posting_time = 0
	pr.set_warehouse = inward.target_warehouse
	pr.rejected_warehouse = _rejected_warehouse(inward)

	series = _grn_naming_series()
	if series:
		pr.naming_series = series

	for fieldname, value, _label in _header_values(inward, qc):
		pr.set(fieldname, value)
	pr.set("custom_grn_status", C.GRN_DRAFT)


def _header_values(inward, qc):
	"""(fieldname, value, label) triples re-pulled from the inward on every sync."""
	arrival = inward.actual_arrival_datetime or inward.inward_datetime
	return [
		("supplier_delivery_note", inward.challan_no, _("Supplier Delivery Note")),
		# Core lr_no is already labelled "Vehicle Number"; the module deliberately adds no
		# vehicle field of its own (see purchase_receipt_fields.py).
		("lr_no", inward.actual_vehicle_no or inward.po_vehicle_no, _("Vehicle Number")),
		("lr_date", getdate(arrival) if arrival else None, _("Vehicle Date")),
		("custom_purchase_inward", inward.name, _("Purchase Inward")),
		("custom_purchase_qc", qc.name if qc else None, _("Purchase QC")),
		("custom_receiving_remarks", inward.receiving_remarks, _("Receiving Remarks")),
	]


def _row_values(source):
	"""(fieldname, value, label) triples re-pulled onto an existing GRN line."""
	return [
		("qty", source["qty"], _("Accepted Quantity")),
		("rejected_qty", source["rejected_qty"], _("Rejected Quantity")),
		("warehouse", source["warehouse"], _("Accepted Warehouse")),
		("rejected_warehouse", source["rejected_warehouse"], _("Rejected Warehouse")),
		("rate", source["rate"], _("Rate")),
		("batch_no", source["batch_no"], _("Batch No")),
		("custom_rejection_reason", source["rejection_reason"], _("Rejection Reason")),
		("custom_usp", source["usp"], _("USP")),
		("custom_mrp", source["mrp"], _("MRP")),
	]


def _apply_row(row, source):
	row.item_code = source["item_code"]
	row.item_name = source["item_name"]
	row.description = source["description"]
	row.uom = source["uom"]
	row.stock_uom = source["stock_uom"]
	row.conversion_factor = source["conversion_factor"]
	row.qty = source["qty"]
	row.rejected_qty = source["rejected_qty"]
	row.warehouse = source["warehouse"]
	row.rejected_warehouse = source["rejected_warehouse"]
	row.rate = source["rate"]
	# StatusUpdater joins Purchase Receipt Item back to Purchase Order Item through these
	# two, so per_received / received_qty / the PO status only move when both are set.
	row.purchase_order = source["purchase_order"]
	row.purchase_order_item = source["po_detail"]
	row.set("custom_purchase_inward_item", source["purchase_inward_item"])
	row.set("custom_rejection_reason", source["rejection_reason"])
	row.set("custom_usp", source["usp"])
	row.set("custom_mrp", source["mrp"])
	if source["batch_no"]:
		row.use_serial_batch_fields = 1
		row.batch_no = source["batch_no"]
	return row


def _grn_naming_series():
	"""The GRN series, but only once setup_purchase_receipt_fields() has offered it."""
	from alpinos.purchase.purchase_receipt_fields import GRN_NAMING_SERIES

	options = frappe.get_meta(DOCTYPE).get_field("naming_series")
	options = (options.options or "") if options else ""
	return GRN_NAMING_SERIES if GRN_NAMING_SERIES in options.splitlines() else None


def _assert_grn_fields():
	"""Without custom_purchase_inward there is no way to honour "one inward, one GRN"."""
	if not frappe.get_meta(DOCTYPE).has_field("custom_purchase_inward"):
		frappe.throw(
			_("The GRN fields are not installed on {0} yet. Run bench migrate first.").format(
				_(DOCTYPE)
			)
		)


# ------------------------------------------------- hand-edit protection ----


def _label_map(doctype):
	out = {}
	for field in frappe.get_meta(doctype).fields:
		out[(field.fieldname or "").lower()] = field.fieldname
		if field.label:
			out[field.label.strip().lower()] = field.fieldname
	return out


def _protected_fields(pr):
	"""(parent fieldnames, {row idx: fieldnames}) a person hand-edited on this Draft GRN."""
	parent, rows = set(), {}
	parent_map = _label_map(DOCTYPE)
	item_map = _label_map(ITEM_DOCTYPE)

	for entry in pr.get("custom_grn_change_log") or []:
		label = (entry.get("field_label") or "").strip()
		if not label:
			continue
		match = _ROW_LABEL.match(label)
		idx = cint(match.group(1)) if match else 0
		key = (match.group(2) if match else label).strip().lower()
		fieldname = (item_map if idx else parent_map).get(key, key)
		if idx:
			rows.setdefault(idx, set()).add(fieldname)
		else:
			parent.add(fieldname)
	return parent, rows


def _assign(target, fieldname, value, protected, changed, label):
	"""Write one synced value, unless it is protected, absent or already correct."""
	if fieldname in protected:
		return
	if not frappe.get_meta(target.doctype).has_field(fieldname):
		return
	if value in (None, "") and target.get(fieldname) not in (None, ""):
		return
	if not _differs(target.get(fieldname), value):
		return
	target.set(fieldname, value)
	changed.append(label)


def _differs(old, new):
	if isinstance(old, float) or isinstance(new, float) or isinstance(old, int):
		return flt(old) != flt(new)
	return (old or "") != (new or "")
