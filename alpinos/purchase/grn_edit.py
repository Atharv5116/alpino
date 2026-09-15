"""Draft GRN review on the GRN screen: edit, cancel, amend, submit.

The GRN (Purchase Receipt) is minted automatically from the QC decision. While it is a
Draft the Purchase Team reviews it on the GRN screen and may change any of its values;
once submitted it is read-only. Every edit is recorded in the GRN Change Log by
purchase_receipt_fields.log_draft_grn_edits, whichever screen it came from.

    Draft      -> Save / Submit (Admin) / Cancel
    Submitted  -> Cancel (Admin)
    Cancelled  -> Amend -> a new Draft (GRN-.....-1), editable, then Submit

Cancelling a DRAFT is not something Frappe offers: only a submitted document can be
cancelled. A draft GRN has posted nothing -- no stock, no ledger -- so cancelling it is
just marking it cancelled, which is what cancel_grn does for a draft. That is also what
makes the Amend flow possible from a draft, and what releases the Purchase QC: a live
draft GRN used to block the QC's cancel for good, since a draft could neither be
cancelled nor deleted (the inward's link refused the delete).
"""

import json

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, now_datetime, nowtime

from alpinos.purchase import constants as C
from alpinos.purchase import workflow

DOCTYPE = "Purchase Receipt"
INWARD = "Purchase Inward"
QC = "Purchase QC"
DEBIT_NOTE = "Purchase Invoice"

#: Who reviews and edits a Draft GRN, cancels a draft and amends a cancelled one.
EDIT_ROLES = tuple(C.PURCHASE_ROLES) + tuple(C.ADMIN_ROLES)

HEADER_FIELDS = (
	"posting_date",
	"posting_time",
	"supplier_delivery_note",
	"lr_no",
	"lr_date",
	"set_warehouse",
	"rejected_warehouse",
	"custom_receiving_remarks",
)
ITEM_FIELDS = (
	"qty",
	"rejected_qty",
	"warehouse",
	"rejected_warehouse",
	"batch_no",
	"rate",
	"custom_rejection_reason",
	"custom_usp",
	"custom_mrp",
)
_NUMERIC = {"qty", "rejected_qty", "rate", "custom_mrp"}


def _has_role(roles):
	return bool(set(frappe.get_roles()) & set(roles))


def _load_grn(purchase_receipt):
	pr = frappe.get_doc(DOCTYPE, purchase_receipt)
	pr.check_permission("read")
	if not pr.get("custom_purchase_inward"):
		frappe.throw(
			_("{0} is not a Purchase Inward GRN.").format(pr.name), title=_("Not a GRN")
		)
	if cint(pr.get("is_return")):
		frappe.throw(_("{0} is a Purchase Return, not a GRN.").format(pr.name))
	return pr


def _assert_edit_role():
	if not _has_role(EDIT_ROLES):
		frappe.throw(
			_("Only the Purchase Team or an Admin can change a Draft GRN."),
			frappe.PermissionError,
			title=_("Not Permitted"),
		)


def _amendment_of(name):
	return frappe.db.get_value(DOCTYPE, {"amended_from": name, "docstatus": ("<", 2)}, "name")


@frappe.whitelist()
def get_grn_context(purchase_receipt):
	"""What the GRN screen may offer, decided on the server."""
	from alpinos.purchase.purchase_invoice import rate_editable

	pr = _load_grn(purchase_receipt)
	docstatus = cint(pr.docstatus)
	may_edit = _has_role(EDIT_ROLES)
	may_submit = _has_role(C.GRN_FINAL_SUBMIT_ROLES)
	amended_to = _amendment_of(pr.name) if docstatus == 2 else None

	note = pr.get("custom_debit_note")
	note_docstatus = (
		cint(frappe.db.get_value(DEBIT_NOTE, note, "docstatus"))
		if note and frappe.db.exists(DEBIT_NOTE, note)
		else None
	)
	live_note = note_docstatus is not None and note_docstatus != 2
	rejected = any(flt(row.rejected_qty) > 0 for row in pr.get("items") or [])
	return {
		"docstatus": docstatus,
		"can_edit": docstatus == 0 and may_edit,
		"can_submit": docstatus == 0 and may_submit,
		"can_cancel": (docstatus == 0 and may_edit) or (docstatus == 1 and may_submit),
		"can_amend": docstatus == 2 and may_edit and not amended_to,
		"amended_to": amended_to,
		"rate_editable": rate_editable(),
		"debit_note": note if note_docstatus is not None else None,
		"debit_note_docstatus": note_docstatus,
		"can_cancel_debit_note": live_note
		and ((note_docstatus == 0 and may_edit) or (note_docstatus == 1 and may_submit)),
		# A cancelled (or never raised) debit note can be raised again for the rejected
		# quantity; grn.generate_debit_note re-checks the authority and the quantity.
		"can_generate_debit_note": docstatus == 1 and rejected and not live_note and may_submit,
	}


# ------------------------------------------------------------------ save / submit


def _apply(pr, data):
	"""Lay the screen's values over the draft. Rows are matched by name; nothing is added."""
	if isinstance(data, str):
		data = json.loads(data or "{}")
	data = data or {}
	from alpinos.purchase.purchase_invoice import rate_editable

	header = data.get("header") or {}
	for fieldname in HEADER_FIELDS:
		if fieldname not in header:
			continue
		value = header.get(fieldname) or None
		if fieldname in ("posting_date", "posting_time"):
			if not value:
				continue
			current = pr.get(fieldname)
			same = (
				str(getdate(current)) == str(getdate(value))
				if fieldname == "posting_date"
				else str(current or "")[:8] == str(value)[:8]
			)
			if same:
				continue
			# ERPNext resets the posting date to now on every save unless this is on.
			pr.set_posting_time = 1
		pr.set(fieldname, value)

	allow_rate = rate_editable()
	rows = {r.get("name"): r for r in (data.get("items") or []) if r.get("name")}
	for row in pr.get("items") or []:
		values = rows.get(row.name)
		if not values:
			continue
		for fieldname in ITEM_FIELDS:
			if fieldname not in values:
				continue
			if fieldname == "rate" and not allow_rate:
				continue
			value = values.get(fieldname)
			row.set(fieldname, flt(value) if fieldname in _NUMERIC else (value or None))
		# Accepted + Rejected IS what was received (BuyingController refuses anything else),
		# so an edited split moves the received quantity with it.
		row.received_qty = flt(row.qty) + flt(row.rejected_qty)
		row.stock_qty = flt(row.qty) * (flt(row.conversion_factor) or 1.0)
		if row.get("batch_no"):
			row.use_serial_batch_fields = 1

	pr.flags.grn_edit_reason = (data.get("reason") or "").strip() or None


@frappe.whitelist()
def save_grn(purchase_receipt, data=None):
	"""Save the Purchase Team's review of a Draft GRN. Each change lands in the change log."""
	pr = _load_grn(purchase_receipt)
	if cint(pr.docstatus) != 0:
		frappe.throw(_("Completed GRN cannot be edited."), title=_("VAL-GRN-07"))
	_assert_edit_role()
	_apply(pr, data)
	pr.flags.ignore_permissions = True
	pr.save()
	return {"name": pr.name, "logged": len(pr.get("custom_grn_change_log") or [])}


@frappe.whitelist()
def submit_grn(purchase_receipt, data=None):
	"""Save what is on screen and final-submit in one request (BR-GRN-06: Admin only).

	One request, so a refused submit -- VAL-GRN-03's missing information, say -- stores
	nothing and the screen keeps what was typed.
	"""
	pr = _load_grn(purchase_receipt)
	if cint(pr.docstatus) != 0:
		frappe.throw(_("This GRN is already submitted."))
	if not _has_role(C.GRN_FINAL_SUBMIT_ROLES):
		frappe.throw(
			_("Only {0} may submit a GRN.").format(", ".join(C.GRN_FINAL_SUBMIT_ROLES)),
			frappe.PermissionError,
		)
	if data:
		_apply(pr, data)
		pr.flags.ignore_permissions = True
		pr.save()
	pr.flags.ignore_permissions = True
	pr.submit()
	return {"name": pr.name, "docstatus": cint(pr.docstatus)}


# ---------------------------------------------------------------- cancel / amend


def _step_inward_back(pr):
	"""A GRN that is no longer live returns its inward to QC Completed (Generate GRN again)."""
	inward_name = pr.get("custom_purchase_inward")
	if not inward_name or not frappe.db.exists(INWARD, inward_name):
		return
	inward = frappe.get_doc(INWARD, inward_name)
	if inward.get("purchase_receipt") != pr.name:
		return
	if inward.inward_status == C.PI_GRN_GENERATED:
		workflow.set_status(inward, C.PI_QC_COMPLETED)


@frappe.whitelist()
def cancel_grn(purchase_receipt, reason=None):
	"""Cancel a GRN: a Draft by the Purchase Team or Admin, a submitted one by the Admin.

	A draft has posted nothing, so it is marked cancelled in place (parent and every child
	row), with a comment saying who and why. A submitted GRN goes through ERPNext's own
	cancel, which reverses its stock and ledger and keeps the consumed-stock guard.
	"""
	from alpinos.purchase import grn as G

	pr = _load_grn(purchase_receipt)
	reason = (reason or "").strip()
	docstatus = cint(pr.docstatus)

	if docstatus == 2:
		frappe.throw(_("{0} is already cancelled.").format(pr.name))

	if docstatus == 1:
		if not _has_role(C.GRN_FINAL_SUBMIT_ROLES):
			frappe.throw(
				_("Only {0} may cancel a submitted GRN.").format(", ".join(C.GRN_FINAL_SUBMIT_ROLES)),
				frappe.PermissionError,
			)
		pr.flags.ignore_permissions = True
		pr.cancel()
	else:
		_assert_edit_role()
		_mark_draft_cancelled(pr)
		G.mark_cancelled(pr)

	if reason or docstatus == 0:
		pr.add_comment(
			"Info",
			_("{0} GRN cancelled by {1}.{2}").format(
				_("Draft") if docstatus == 0 else _("Submitted"),
				frappe.utils.get_fullname(frappe.session.user),
				(" " + _("Reason: {0}").format(reason)) if reason else "",
			),
		)
	_step_inward_back(pr)
	return {"name": pr.name, "docstatus": 2}


def _mark_draft_cancelled(doc):
	"""Cancel a draft in place: it posted nothing, so parent and child rows are just marked."""
	doc.db_set("docstatus", 2, update_modified=True)
	for df in doc.meta.get_table_fields():
		frappe.db.sql(
			f"UPDATE `tab{df.options}` SET docstatus = 2 WHERE parent = %s AND parenttype = %s",
			(doc.name, doc.doctype),
		)


def _grn_of_debit_note(note):
	"""The module GRN a debit note was raised against, from its lines."""
	for row in note.get("items") or []:
		grn = row.get("purchase_receipt")
		if grn and frappe.db.get_value(DOCTYPE, grn, "custom_purchase_inward"):
			return grn
	return None


@frappe.whitelist()
def cancel_debit_note(purchase_receipt=None, debit_note=None, reason=None):
	"""Cancel a GRN's Debit Note: a Draft by the Purchase Team or Admin, a submitted one by
	the Admin -- the same authority as cancelling the GRN itself.

	Frappe offers no Cancel on a draft, and grn.make_debit_note always raises the note as a
	draft, so without this a wrong debit note could only be deleted from the desk. Once
	cancelled, grn.generate_debit_note may raise a fresh one for the rejected quantity.
	"""
	if not debit_note:
		if not purchase_receipt:
			frappe.throw(_("Please choose the GRN or the Debit Note to cancel."))
		debit_note = _load_grn(purchase_receipt).get("custom_debit_note")
	if not debit_note or not frappe.db.exists(DEBIT_NOTE, debit_note):
		frappe.throw(_("This GRN has no Debit Note to cancel."))

	note = frappe.get_doc(DEBIT_NOTE, debit_note)
	note.check_permission("read")
	grn = _grn_of_debit_note(note) if cint(note.is_return) else None
	if not grn:
		frappe.throw(_("{0} is not a Debit Note raised from a GRN.").format(note.name))
	if purchase_receipt and grn != purchase_receipt:
		frappe.throw(_("{0} was not raised against {1}.").format(note.name, purchase_receipt))

	reason = (reason or "").strip()
	docstatus = cint(note.docstatus)
	if docstatus == 2:
		frappe.throw(_("{0} is already cancelled.").format(note.name))
	if docstatus == 1:
		if not _has_role(C.GRN_FINAL_SUBMIT_ROLES):
			frappe.throw(
				_("Only {0} may cancel a submitted Debit Note.").format(", ".join(C.GRN_FINAL_SUBMIT_ROLES)),
				frappe.PermissionError,
			)
		note.flags.ignore_permissions = True
		note.cancel()
	else:
		_assert_edit_role()
		_mark_draft_cancelled(note)

	message = _("{0} Debit Note {1} cancelled by {2}.{3}").format(
		_("Draft") if docstatus == 0 else _("Submitted"),
		note.name,
		frappe.utils.get_fullname(frappe.session.user),
		(" " + _("Reason: {0}").format(reason)) if reason else "",
	)
	note.add_comment("Info", message)
	frappe.get_doc(DOCTYPE, grn).add_comment("Info", message)
	return {"debit_note": note.name, "purchase_receipt": grn, "docstatus": 2}


@frappe.whitelist()
def amend_grn(purchase_receipt):
	"""Raise a new Draft from a cancelled GRN, carrying its values, ready to edit and submit.

	The copy is linked back to the inward and the QC in place of the cancelled one, so the
	rest of the chain (submit, debit note, invoice) follows the amendment.
	"""
	pr = _load_grn(purchase_receipt)
	if cint(pr.docstatus) != 2:
		frappe.throw(_("Only a cancelled GRN can be amended."))
	_assert_edit_role()
	existing = _amendment_of(pr.name)
	if existing:
		frappe.throw(
			_("{0} has already been amended as {1}.").format(pr.name, existing),
			title=_("Already Amended"),
		)
	# One live GRN per inward and QC (BR-GRN-02): a GRN generated again after the cancel
	# already carries these goods.
	live = frappe.db.get_value(
		DOCTYPE,
		{
			"custom_purchase_inward": pr.custom_purchase_inward,
			"custom_purchase_qc": pr.get("custom_purchase_qc"),
			"docstatus": ("<", 2),
			"is_return": 0,
		},
		"name",
	)
	if live:
		frappe.throw(
			_("GRN {0} is already live for this Purchase Inward; amend is not needed.").format(live),
			title=_("BR-GRN-02"),
		)

	new = frappe.copy_doc(pr)
	new.amended_from = pr.name
	new.docstatus = 0
	new.set("custom_grn_status", C.GRN_DRAFT)
	new.set("custom_debit_note", None)
	new.set("custom_final_submitted_by", None)
	new.set("custom_final_submission_datetime", None)
	new.posting_date = getdate()
	new.posting_time = nowtime()
	new.set_posting_time = 0
	# custom_purchase_inward_item is no_copy, and it is the only identity that survives a
	# repeated item code, so it is carried over row by row.
	for old_row, new_row in zip(pr.get("items") or [], new.get("items") or []):
		new_row.custom_purchase_inward_item = old_row.get("custom_purchase_inward_item")
	new.set("custom_grn_change_log", [])
	new.append(
		"custom_grn_change_log",
		{
			"field_label": _("Amended"),
			"old_value": pr.name,
			"new_value": _("new draft"),
			"changed_by": frappe.session.user,
			"changed_on": now_datetime(),
		},
	)
	new.flags.ignore_permissions = True
	new.insert()

	inward = frappe.get_doc(INWARD, pr.custom_purchase_inward)
	from alpinos.purchase.grn import is_main_grn

	if is_main_grn(pr, inward) and inward.get("purchase_receipt") in (pr.name, None, ""):
		inward.db_set({"purchase_receipt": new.name, "grn_status": C.GRN_DRAFT}, update_modified=False)
		if inward.inward_status == C.PI_QC_COMPLETED:
			workflow.set_status(inward, C.PI_GRN_GENERATED)
	qc = pr.get("custom_purchase_qc")
	if qc and frappe.db.get_value(QC, qc, "purchase_receipt") == pr.name:
		frappe.db.set_value(QC, qc, "purchase_receipt", new.name, update_modified=False)

	return {"name": new.name}
