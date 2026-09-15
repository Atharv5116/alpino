"""Purchase Invoice & Payment — BRD 6.

TWO CREATION PATHS, ONE DOCUMENT (BRD 6.0)
------------------------------------------
    Normal   PO -> Inward -> QC -> GRN -> Admin final submit -> Purchase Invoice
    Direct   approved PO with the Direct flag -> Purchase Invoice, skipping all three

Both land on the same Purchase Invoice; `custom_invoice_type` records which path it took,
and a Direct invoice simply carries no GRN or Inward link, exactly as BRD 6.1 says ("For
a Direct Purchase Invoice, Purchase Inward ID and GRN ID shall not be available because
those transactions are intentionally skipped"). Each path is mapped by ERPNext's own
`make_purchase_invoice` so item mapping, tax handling and the GL posting stay standard;
this module adds the links, the logistics bill and the payment history on top.

WHY THE STATUS IS DERIVED, NEVER SET
------------------------------------
BRD 6.2's statuses describe payments made in TALLY and recorded here, which is a
different fact from `outstanding_amount` on the ledger. `recompute_payment_state` is the
only writer, and it derives everything -- both pending amounts and the status -- from the
payment rows. Nothing else may set the status, so "Completed" cannot be reached except by
BR-UNF-06's actual condition: both pending amounts at zero.

WHY PAYMENTS ARE A CHILD TABLE
------------------------------
BR-UNF-05 is explicit that Accounts pays in instalments, and BR-UNF-04 wants supplier and
logistics tracked separately in the same document. A row per payment carrying its type
gives both by summation; a pair of "paid" totals would give neither an audit trail nor a
way to answer "what has been paid to the transporter".
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, now_datetime

from alpinos.purchase import constants as C
from alpinos.purchase.purchase_invoice_fields import (
	PURCHASE_OWNED_FIELDS,
	STATUS_FIELD,
	TYPE_FIELD,
)

PI = "Purchase Invoice"
GRN = "Purchase Receipt"
PO = "Purchase Order"
INWARD = "Purchase Inward"

#: Rounding guard. Currency is stored to 2dp, so two amounts within half a paisa are the
#: same amount -- comparing them with == would leave an invoice a rounding error short of
#: Completed forever.
_EPSILON = 0.005


# ------------------------------------------------------------------- helpers


def _is_direct(doc):
	return (doc.get(TYPE_FIELD) or C.UNF_TYPE_NORMAL) == C.UNF_TYPE_DIRECT


def is_module_invoice(doc):
	"""True for an invoice this module raised: one linked to a GRN / inward, or a Direct one.

	The doc_events are registered for EVERY Purchase Invoice on the site, and Invoice Type
	defaults to Normal on all of them, so the type alone cannot tell. Without this guard a
	GRN's debit note (a return) and any ordinary invoice keyed in by Accounts were held to
	BRD 6's submit rules -- the debit note could not be submitted without a "physical
	supplier invoice copy".
	"""
	if cint(doc.get("is_return")):
		return False
	return bool(doc.get("custom_grn") or doc.get("custom_purchase_inward") or _is_direct(doc))


def _has_role(roles):
	return bool(set(frappe.get_roles()) & set(roles))


def rate_editable():
	"""Whether this user may type a Unit Price that differs from the PO / GRN (BRD 6.2.2).

	ERPNext's Buying Settings "Maintain Same Rate" with action Stop refuses any invoice rate
	that differs from its Purchase Order / Purchase Receipt ("Rate must be same as ...")
	unless the user holds the override role. Offering an editable price that the save then
	refuses reads as a bug, so the screen asks this first.
	"""
	settings = frappe.get_cached_doc("Buying Settings")
	if not cint(settings.get("maintain_same_rate")):
		return True
	if (settings.get("maintain_same_rate_action") or "Stop") != "Stop":
		return True
	override = settings.get("role_to_override_stop_action")
	return bool(override and override in frappe.get_roles())


def _payable_supplier(doc):
	"""What the supplier is owed: the invoice total, exclusive of any freight bill."""
	return flt(doc.get("rounded_total") or doc.get("grand_total"))


def _payable_logistics(doc):
	if not cint(doc.get("custom_include_logistics")):
		return 0.0
	return flt(doc.get("custom_freight_amount"))


def _paid(doc, payment_type):
	return sum(
		flt(row.payment_amount)
		for row in (doc.get("custom_payment_references") or [])
		if (row.payment_type or "") == payment_type
	)


def _payment_terms_template(doc):
	"""The template the due date is derived from: the invoice's own, else the supplier's.

	get_payment_terms_template also falls back to the Supplier Group, the same lookup
	ERPNext uses for the standard due date.
	"""
	if doc.get("payment_terms_template"):
		return doc.payment_terms_template
	if not doc.get("supplier"):
		return None
	from erpnext.accounts.party import get_payment_terms_template

	return get_payment_terms_template(doc.supplier, "Supplier", doc.get("company"))


def terms_due_date(doc):
	"""Invoice Date + Payment Terms, or None when there are no terms to apply.

	The LAST instalment's date is the one returned: that is when the whole bill is due.
	"""
	template = _payment_terms_template(doc)
	if not (template and doc.get("bill_date")):
		return None
	from erpnext.controllers.accounts_controller import get_due_date

	dates = []
	for term in frappe.get_all(
		"Payment Terms Template Detail",
		filters={"parent": template, "parenttype": "Payment Terms Template"},
		fields=["due_date_based_on", "credit_days", "credit_months"],
		order_by="idx asc",
	):
		due = get_due_date(term, bill_date=doc.bill_date)
		if due:
			dates.append(getdate(due))
	return max(dates) if dates else None


def _derive_payment_due_date(doc):
	"""BRD 6.2.1: Invoice Date + Payment Terms on a Normal invoice.

	Recomputed on every draft save, so a corrected Invoice Date moves the due date with it.
	A supplier with no payment terms leaves the date to the Purchase Team, and a Direct
	invoice is always typed by hand (BRD 6.2.1 Direct flow). This used to throw the
	supplier's terms away and fill nothing at all.
	"""
	# validate() never runs for an after-submit save, so a submitted due date is not moved
	# here; BR-UNF-03 freezes it in before_update_after_submit.
	if _is_direct(doc):
		return
	due = terms_due_date(doc)
	if due:
		doc.custom_payment_due_date = due


# --------------------------------------------------------------- BRD 6.3 / 6.4


def _validate_submit_requirements(doc):
	"""VAL-UNF-01 / 02 / 03 — what the Purchase Team must supply before submitting."""
	if not (doc.get("bill_no") or "").strip():
		frappe.throw(_("Please enter the Supplier Invoice Number."), title=_("VAL-UNF-01"))

	# BRD 6.2.1 marks both dates mandatory. Neither had a check, so an invoice could reach
	# Accounts with no invoice date and no date to pay by.
	if not doc.get("bill_date"):
		frappe.throw(_("Please enter the Supplier Invoice Date."), title=_("Missing Invoice Date"))

	if not (doc.get("custom_invoice_attachment") or "").strip():
		frappe.throw(
			_("Please upload the physical supplier invoice copy."), title=_("VAL-UNF-02")
		)

	if not doc.get("custom_payment_due_date"):
		frappe.throw(
			_("Please enter the Payment Due Date.")
			if _is_direct(doc)
			else _(
				"Please enter the Payment Due Date. It fills in automatically when the "
				"supplier has Payment Terms."
			),
			title=_("Missing Payment Due Date"),
		)

	if cint(doc.get("custom_include_logistics")):
		# BRD 6.2.3 marks all four mandatory once the box is ticked; Transport Invoice No.
		# and the attachment were not checked.
		if (
			not doc.get("custom_logistics_vendor")
			or not (doc.get("custom_transport_invoice_no") or "").strip()
			or flt(doc.get("custom_freight_amount")) <= 0
			or not (doc.get("custom_transport_attachment") or "").strip()
		):
			frappe.throw(
				_("Please complete all mandatory Logistics details."), title=_("VAL-UNF-03")
			)


def _validate_payment_rows(doc):
	"""VAL-UNF-04 / 05 / 06 / 07 — each payment Accounts records.

	06 and 07 are checked against the payable less the OTHER rows of the same type, not
	less the stored pending amount: the stored figure is a derived cache, and validating a
	row against a number this same save is about to recompute is circular.
	"""
	rows = doc.get("custom_payment_references") or []
	if not rows:
		return

	payable = {
		C.UNF_PAYMENT_SUPPLIER: _payable_supplier(doc),
		C.UNF_PAYMENT_LOGISTICS: _payable_logistics(doc),
	}
	running = {C.UNF_PAYMENT_SUPPLIER: 0.0, C.UNF_PAYMENT_LOGISTICS: 0.0}

	for row in rows:
		amount = flt(row.payment_amount)
		if amount <= 0:
			frappe.throw(
				_("Row {0}: Payment Amount must be greater than zero.").format(row.idx),
				title=_("VAL-UNF-04"),
			)

		if (row.payment_mode or "") in C.UNF_MODES_REQUIRING_REFERENCE and not (
			row.reference_number or ""
		).strip():
			frappe.throw(
				_("Row {0}: Tally Reference/UTR is mandatory for bank transactions.").format(row.idx),
				title=_("VAL-UNF-05"),
			)

		ptype = row.payment_type or C.UNF_PAYMENT_SUPPLIER
		running[ptype] = running.get(ptype, 0.0) + amount

		if ptype == C.UNF_PAYMENT_LOGISTICS and not cint(doc.get("custom_include_logistics")):
			frappe.throw(
				_("Row {0}: there is no logistics bill on this invoice to pay against.").format(
					row.idx
				),
				title=_("VAL-UNF-07"),
			)

		if running[ptype] > payable.get(ptype, 0.0) + _EPSILON:
			if ptype == C.UNF_PAYMENT_SUPPLIER:
				frappe.throw(
					_(
						"Payment amount cannot exceed the pending supplier bill. "
						"Billed {0}, already recorded {1}, this row {2}."
					).format(
						frappe.format_value(payable[ptype], {"fieldtype": "Currency"}),
						frappe.format_value(running[ptype] - amount, {"fieldtype": "Currency"}),
						frappe.format_value(amount, {"fieldtype": "Currency"}),
					),
					title=_("VAL-UNF-06"),
				)
			frappe.throw(
				_(
					"Payment amount cannot exceed the pending freight bill. "
					"Billed {0}, already recorded {1}, this row {2}."
				).format(
					frappe.format_value(payable[ptype], {"fieldtype": "Currency"}),
					frappe.format_value(running[ptype] - amount, {"fieldtype": "Currency"}),
					frappe.format_value(amount, {"fieldtype": "Currency"}),
				),
				title=_("VAL-UNF-07"),
			)


def recompute_payment_state(doc):
	"""BR-UNF-04 and BR-UNF-06 — the two pending amounts and the status they imply.

	The single writer of the status. Completed is reached only when BOTH pending amounts
	are zero, which is BR-UNF-06 stated as code rather than trusted to a caller.
	"""
	supplier_paid = _paid(doc, C.UNF_PAYMENT_SUPPLIER)
	logistics_paid = _paid(doc, C.UNF_PAYMENT_LOGISTICS)

	supplier_pending = max(_payable_supplier(doc) - supplier_paid, 0.0)
	logistics_pending = max(_payable_logistics(doc) - logistics_paid, 0.0)

	doc.custom_supplier_pending_amount = supplier_pending
	doc.custom_logistics_pending_amount = logistics_pending
	doc.custom_total_paid_amount = supplier_paid + logistics_paid

	if cint(doc.docstatus) == 2:
		doc.set(STATUS_FIELD, C.UNF_CANCELLED)
		return
	if cint(doc.docstatus) == 0:
		doc.set(STATUS_FIELD, C.UNF_DRAFT)
		return

	settled = supplier_pending <= _EPSILON and logistics_pending <= _EPSILON
	if settled:
		doc.set(STATUS_FIELD, C.UNF_COMPLETED)
	elif (supplier_paid + logistics_paid) > _EPSILON:
		doc.set(STATUS_FIELD, C.UNF_PARTIALLY_PAID)
	else:
		doc.set(STATUS_FIELD, C.UNF_PENDING_PAYMENT)


def _assert_purchase_sections_unchanged(doc):
	"""BR-UNF-03 — the Purchase Team's sections freeze once the invoice is submitted.

	Accounts works on the same document afterwards, so the lock has to be per-field
	rather than per-document: the payment table stays open while everything the Purchase
	Team owns stops moving. read_only is a client-side hint only, so this is the guard
	that actually holds against a REST write.
	"""
	before = doc.get_doc_before_save()
	if not before or cint(doc.docstatus) != 1:
		return

	changed = [
		f
		for f in PURCHASE_OWNED_FIELDS
		if (doc.get(f) or None) != (before.get(f) or None)
	]
	if not changed:
		return

	labels = ", ".join(doc.meta.get_label(f) for f in changed)
	frappe.throw(
		_(
			"{0} cannot be changed after the invoice has been submitted (BR-UNF-03). "
			"Cancel and amend the invoice if the supplier bill itself was wrong."
		).format(frappe.bold(labels)),
		frappe.PermissionError,
		title=_("Submitted Invoice Is Locked"),
	)


#: The values a recorded payment is made of. Compared as text, so 500 and 500.0 match.
_PAYMENT_ROW_FIELDS = (
	"payment_type",
	"payment_amount",
	"payment_date",
	"payment_mode",
	"reference_number",
	"payment_attachment",
	"remarks",
)


def _row_value(row, field):
	value = row.get(field)
	if field == "payment_amount":
		return flt(value)
	return str(value) if value not in (None, "") else ""


def _guard_payment_rows(doc):
	"""Only Accounts records payments, and a recorded payment stays as it was recorded.

	BRD 6.2.4 is the Accounts Team's section, and the payment history is an audit trail
	(BRD 6.5 "Append new payment reference block to history"). Two holes made it neither:
	add_payment checked only write permission, which the Purchase Team holds on a submitted
	invoice, and any row could be edited or deleted after the fact. An Admin may still
	correct a row keyed in wrongly.

	Also stamps Recorded By / On. They were set in the child controller's before_insert,
	which Frappe never runs for a child row, so both stayed blank.
	"""
	before = doc.get_doc_before_save()
	old = {r.name: r for r in ((before.get("custom_payment_references") or []) if before else [])}
	is_admin = _has_role(C.ADMIN_ROLES)
	kept = set()

	for row in doc.get("custom_payment_references") or []:
		if row.name and row.name in old:
			kept.add(row.name)
			previous = old[row.name]
			if not is_admin and any(
				_row_value(row, f) != _row_value(previous, f) for f in _PAYMENT_ROW_FIELDS
			):
				frappe.throw(
					_("Row {0}: a recorded payment cannot be changed.").format(row.idx),
					frappe.PermissionError,
					title=_("Payment Locked"),
				)
			continue
		if not _has_role(C.UNF_PAYMENT_ROLES):
			frappe.throw(
				_("Only the Accounts Team can record a payment."),
				frappe.PermissionError,
				title=_("Not Permitted"),
			)
		if not row.get("recorded_by"):
			row.recorded_by = frappe.session.user
		if not row.get("recorded_on"):
			row.recorded_on = now_datetime()

	if not is_admin and set(old) - kept:
		frappe.throw(
			_("A recorded payment cannot be removed."),
			frappe.PermissionError,
			title=_("Payment Locked"),
		)


def _sync_inward(doc, detached=False):
	"""Roll the invoice's state onto its Purchase Inward (BRD 6.2.1 workflow).

	    invoice created             -> inward Payment Pending, linked to the invoice
	    invoice Completed           -> inward Completed
	    invoice cancelled / deleted -> inward back to GRN Generated, link cleared

	None of it happened before: create_from_grn never linked the inward, and nothing ever
	moved its status past GRN Generated.
	"""
	name = doc.get("custom_purchase_inward")
	if not name or not frappe.db.exists(INWARD, name):
		return
	from alpinos.purchase import workflow

	inward = frappe.get_doc(INWARD, name)
	if cint(inward.docstatus) != 1:
		return
	chain = (C.PI_GRN_GENERATED, C.PI_PAYMENT_PENDING, C.PI_COMPLETED)

	if detached:
		if inward.get("purchase_invoice") == doc.name:
			inward.db_set("purchase_invoice", None, update_modified=False)
		if inward.inward_status in (C.PI_PAYMENT_PENDING, C.PI_COMPLETED):
			workflow.set_status(inward, C.PI_GRN_GENERATED)
		return

	if inward.get("purchase_invoice") != doc.name:
		inward.db_set("purchase_invoice", doc.name, update_modified=False)
	target = (
		C.PI_COMPLETED
		if cint(doc.docstatus) == 1 and doc.get(STATUS_FIELD) == C.UNF_COMPLETED
		else C.PI_PAYMENT_PENDING
	)
	if inward.inward_status in chain:
		workflow.set_status(inward, target)


# ------------------------------------------------------------------ doc hooks


def validate(doc, method=None):
	if not is_module_invoice(doc):
		return
	if not doc.get(TYPE_FIELD):
		doc.set(TYPE_FIELD, C.UNF_TYPE_NORMAL)
	# BRD 6.2.1: Accounts records payments against the SUBMITTED invoice. add_payment already
	# refused a draft, but the desk form let anyone type payment rows into one, where no role
	# check runs and they would arrive at Accounts as already paid.
	if cint(doc.docstatus) == 0 and doc.get("custom_payment_references"):
		frappe.throw(
			_("Payments can only be recorded after the invoice is submitted."),
			title=_("Not Submitted"),
		)
	_derive_payment_due_date(doc)
	_validate_payment_rows(doc)
	recompute_payment_state(doc)


def after_insert(doc, method=None):
	if is_module_invoice(doc):
		_sync_inward(doc)


def before_submit(doc, method=None):
	if not is_module_invoice(doc):
		return
	_validate_submit_requirements(doc)
	# Submitting is the hand-off to Accounts (BRD 6.2.1 "Fill Details & Click Submit ->
	# Pending Payment"), so the status is derived at docstatus 1 rather than left at Draft.
	doc.docstatus = 1
	recompute_payment_state(doc)


def before_update_after_submit(doc, method=None):
	if not is_module_invoice(doc):
		return
	_assert_purchase_sections_unchanged(doc)
	_guard_payment_rows(doc)
	_validate_payment_rows(doc)
	recompute_payment_state(doc)


def on_update_after_submit(doc, method=None):
	if is_module_invoice(doc):
		_sync_inward(doc)


def on_cancel(doc, method=None):
	if not is_module_invoice(doc):
		return
	# on_cancel runs after the row is written, so a plain assignment never reached the
	# database and a cancelled invoice kept reading Pending Payment in every list.
	doc.db_set(STATUS_FIELD, C.UNF_CANCELLED, update_modified=False)
	_sync_inward(doc, detached=True)
	# The inward's purchase_invoice link would otherwise block the cancel for good
	# ("Cannot delete or cancel because Purchase Invoice ... is linked with Purchase
	# Inward"). PurchaseInvoice.on_cancel ASSIGNS ignore_linked_doctypes, so appending in
	# this doc_event -- which runs after it and before the back-link check -- is the only
	# place that survives. The same pattern the GRN cancel uses in hooks_glue.
	doc.ignore_linked_doctypes = tuple(doc.get("ignore_linked_doctypes") or ()) + (INWARD,)


def on_trash(doc, method=None):
	"""A deleted draft releases its inward; the link would otherwise block the delete."""
	if is_module_invoice(doc):
		_sync_inward(doc, detached=True)


# ------------------------------------------------------------- creation paths


def _link_chain(invoice, inward=None, grn=None, invoice_type=C.UNF_TYPE_NORMAL):
	invoice.set(TYPE_FIELD, invoice_type)
	invoice.custom_purchase_inward = inward
	invoice.custom_grn = grn


@frappe.whitelist()
def create_from_grn(purchase_receipt):
	"""BR-UNF-01 / BR-UNF-02 — one invoice, from one finally submitted GRN."""
	from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_invoice

	grn = frappe.get_doc(GRN, purchase_receipt)
	grn.check_permission("read")

	if cint(grn.docstatus) != 1:
		frappe.throw(
			_("Purchase Invoice can be created only after the GRN is finally submitted."),
			title=_("BR-UNF-01"),
		)

	existing = frappe.get_all(
		PI,
		filters={"custom_grn": grn.name, "docstatus": ("<", 2)},
		pluck="name",
		limit=1,
	)
	if existing:
		frappe.throw(
			_("Purchase Invoice {0} already exists against this GRN.").format(
				frappe.utils.get_link_to_form(PI, existing[0])
			),
			title=_("BR-UNF-02"),
		)

	invoice = make_purchase_invoice(grn.name)
	_link_chain(
		invoice,
		inward=grn.get("custom_purchase_inward"),
		grn=grn.name,
		invoice_type=C.UNF_TYPE_NORMAL,
	)
	bill_approved_quantity(invoice)
	invoice.flags.ignore_permissions = True
	invoice.insert(ignore_permissions=True)
	return invoice


def bill_approved_quantity(invoice):
	"""BRD 6.2.2: a Normal invoice bills the GRN's APPROVED quantity, never the rejected part.

	ERPNext's Buying Settings "Bill for Rejected Quantity in Purchase Invoice" maps the GRN's
	RECEIVED quantity instead, so a 400 approved / 100 rejected receipt was invoiced for all
	500 -- more than the GRN put into Stock Received But Not Billed, which carries only the
	approved value. Held here, on the module's own creation path, so the rule does not
	depend on that site-wide setting staying off.

	Returns True when a line changed. The payment schedule is cleared so ERPNext rebuilds it
	against the corrected total on the next save; a stale one fails "Total Payment Amount in
	Payment Schedule must be equal to Grand Total".
	"""
	details = [row.pr_detail for row in invoice.get("items") or [] if row.get("pr_detail")]
	if not details:
		return False
	approved = dict(
		frappe.get_all(
			"Purchase Receipt Item",
			filters={"name": ["in", details]},
			fields=["name", "qty"],
			as_list=True,
		)
	)
	changed = False
	for row in invoice.get("items") or []:
		if row.get("pr_detail") not in approved:
			continue
		limit = flt(approved[row.pr_detail])
		if flt(row.qty) > limit or flt(row.get("rejected_qty")):
			row.qty = min(flt(row.qty), limit)
			row.rejected_qty = 0
			row.received_qty = row.qty
			row.stock_qty = flt(row.qty) * (flt(row.conversion_factor) or 1.0)
			changed = True
	if changed:
		invoice.run_method("calculate_taxes_and_totals")
		invoice.set("payment_schedule", [])
	return changed


def direct_invoices_for(purchase_orders):
	"""{purchase_order: its live Direct Purchase Invoice} for the given orders.

	The single definition of "this order is already invoiced", shared by the guard below,
	the Purchase Order form and the Purchase Order list, so the three cannot disagree about
	whether Create Invoice should still be offered.
	"""
	names = [n for n in (purchase_orders or []) if n]
	if not names or not frappe.get_meta(PI).has_field(TYPE_FIELD):
		return {}
	rows = frappe.db.sql(
		"""
		SELECT pii.purchase_order, pi.name
		FROM `tabPurchase Invoice Item` pii
		JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
		WHERE pii.purchase_order IN %(names)s
		  AND pi.docstatus < 2
		  AND pi.custom_invoice_type = %(direct)s
		ORDER BY pi.creation ASC
		""",
		{"names": tuple(names), "direct": C.UNF_TYPE_DIRECT},
		as_dict=True,
	)
	out = {}
	for r in rows:
		out.setdefault(r.purchase_order, r.name)
	return out


@frappe.whitelist()
def create_direct_from_po(purchase_order):
	"""BRD 6.0 path 2 — straight from an approved PO, skipping Inward, QC and GRN.

	Refused unless the PO actually carries the Direct flag: the skip is a decision taken
	when the order was raised, not one the invoice screen may make later.
	"""
	from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_invoice

	order = frappe.get_doc(PO, purchase_order)
	order.check_permission("read")

	if cint(order.docstatus) != 1:
		frappe.throw(
			_("Only an Approved Purchase Order can be invoiced."), title=_("BRD 6.0")
		)
	if not cint(order.get("custom_direct_purchase_invoice")):
		frappe.throw(
			_(
				"Purchase Order {0} is not marked Direct Purchase Invoice. Receive it "
				"through Purchase Inward, QC and GRN instead."
			).format(order.name),
			title=_("BRD 6.0"),
		)

	# BR-PO-25: one order, one Direct invoice. Without this a second click on Create
	# Invoice -- or the list and the form both open at once -- raised a second invoice for
	# the same goods.
	existing = direct_invoices_for([order.name]).get(order.name)
	if existing:
		frappe.throw(
			_("Purchase Invoice {0} already exists against this Purchase Order.").format(
				frappe.utils.get_link_to_form(PI, existing)
			),
			title=_("Already Invoiced"),
		)

	invoice = make_purchase_invoice(order.name)
	_link_chain(invoice, inward=None, grn=None, invoice_type=C.UNF_TYPE_DIRECT)
	invoice.flags.ignore_permissions = True
	invoice.insert(ignore_permissions=True)
	return invoice


@frappe.whitelist()
def create_purchase_invoice(purchase_inward):
	"""The Purchase Inward workflow's `create_purchase_invoice` action (BRD 6.2.1).

	Resolves the inward's GRN and delegates, so the transition and the button on the GRN
	cannot produce differently linked invoices.
	"""
	inward = frappe.get_doc(INWARD, purchase_inward)
	inward.check_permission("read")

	if not inward.get("purchase_receipt"):
		frappe.throw(
			_("No GRN has been generated for {0} yet.").format(inward.name),
			title=_("BR-UNF-01"),
		)

	# after_insert links the inward and moves it to Payment Pending.
	invoice = create_from_grn(inward.purchase_receipt)
	return {"purchase_invoice": invoice.name, "invoice_status": invoice.get(STATUS_FIELD)}


# ------------------------------------------------------------------- payments


@frappe.whitelist()
def add_payment(
	purchase_invoice,
	payment_type,
	payment_amount,
	payment_date,
	payment_mode,
	reference_number=None,
	payment_attachment=None,
	remarks=None,
):
	"""BRD 6.2.1 "Click Add Payment & Submit" — append one payment and re-derive the state.

	The whole VAL-UNF-04..07 set runs through the document's own validate, so a payment
	added here and one added by editing the table are checked identically.
	"""
	invoice = frappe.get_doc(PI, purchase_invoice)
	invoice.check_permission("write")
	if not _has_role(C.UNF_PAYMENT_ROLES):
		frappe.throw(
			_("Only the Accounts Team can record a payment."),
			frappe.PermissionError,
			title=_("Not Permitted"),
		)

	if cint(invoice.docstatus) != 1:
		frappe.throw(
			_("Payments can only be recorded against a submitted invoice."),
			title=_("Not Submitted"),
		)
	if invoice.get(STATUS_FIELD) == C.UNF_CANCELLED:
		frappe.throw(_("This invoice has been cancelled."), title=_("Cancelled"))

	invoice.append(
		"custom_payment_references",
		{
			"payment_type": payment_type,
			"payment_amount": flt(payment_amount),
			"payment_date": payment_date,
			"payment_mode": payment_mode,
			"reference_number": reference_number,
			"payment_attachment": payment_attachment,
			"remarks": remarks,
			"payment_status": "Done",
		},
	)
	invoice.save()
	invoice.reload()
	return {
		"status": invoice.get(STATUS_FIELD),
		"supplier_pending": flt(invoice.get("custom_supplier_pending_amount")),
		"logistics_pending": flt(invoice.get("custom_logistics_pending_amount")),
		"total_paid": flt(invoice.get("custom_total_paid_amount")),
	}


def invoice_status(invoice):
	"""The status to show. docstatus wins, so a cancelled or draft invoice never reads
	as whatever an older build left in the status field."""
	docstatus = cint(invoice.get("docstatus"))
	if docstatus == 2:
		return C.UNF_CANCELLED
	if docstatus == 0:
		return C.UNF_DRAFT
	return invoice.get(STATUS_FIELD) or C.UNF_PENDING_PAYMENT


@frappe.whitelist()
def get_invoice_context(purchase_invoice):
	"""What the screen needs to draw its buttons and sections, decided on the server."""
	invoice = frappe.get_doc(PI, purchase_invoice)
	invoice.check_permission("read")
	roles = set(frappe.get_roles())
	status = invoice_status(invoice)
	docstatus = cint(invoice.docstatus)
	may_create = bool(roles.intersection(C.UNF_CREATE_ROLES))
	orders = []
	for row in invoice.get("items") or []:
		if row.purchase_order and row.purchase_order not in orders:
			orders.append(row.purchase_order)
	return {
		"name": invoice.name,
		"status": status,
		"invoice_type": invoice.get(TYPE_FIELD) or C.UNF_TYPE_NORMAL,
		"docstatus": docstatus,
		"purchase_orders": orders,
		"supplier_payable": _payable_supplier(invoice),
		"logistics_payable": _payable_logistics(invoice),
		"supplier_pending": flt(invoice.get("custom_supplier_pending_amount")),
		"logistics_pending": flt(invoice.get("custom_logistics_pending_amount")),
		"total_paid": flt(invoice.get("custom_total_paid_amount")),
		# A Normal invoice whose supplier has Payment Terms gets its due date computed on
		# save, so the screen shows it read-only rather than inviting an edit that is lost.
		"due_date_auto": not _is_direct(invoice) and bool(_payment_terms_template(invoice)),
		"rate_editable": rate_editable(),
		"payment_types": [C.UNF_PAYMENT_SUPPLIER]
		+ ([C.UNF_PAYMENT_LOGISTICS] if cint(invoice.get("custom_include_logistics")) else []),
		"payment_modes": list(C.UNF_PAYMENT_MODES),
		"can_edit": docstatus == 0
		and may_create
		and bool(frappe.has_permission(PI, "write", doc=invoice)),
		"can_submit": docstatus == 0
		and may_create
		and bool(frappe.has_permission(PI, "submit", doc=invoice)),
		"can_add_payment": docstatus == 1
		and status in (C.UNF_PENDING_PAYMENT, C.UNF_PARTIALLY_PAID)
		and bool(roles.intersection(C.UNF_PAYMENT_ROLES))
		and bool(frappe.has_permission(PI, "write", doc=invoice)),
	}


# ------------------------------------------------------------ entry page saves

#: What the Purchase Team fills on the entry page (BRD 6.2.1 / 6.2.3). Everything else on
#: the invoice is fetched from the GRN or PO and is not the screen's to change.
DRAFT_FIELDS = (
	"bill_no",
	"bill_date",
	"custom_payment_due_date",
	"custom_invoice_attachment",
	"custom_invoice_remarks",
	"custom_include_logistics",
	"custom_logistics_vendor",
	"custom_transport_invoice_no",
	"custom_freight_amount",
	"custom_transport_attachment",
)


def _date_str(value):
	return str(getdate(value)) if value else ""


def _align_erpnext_schedule(invoice):
	"""Keep ERPNext's own due date and payment schedule in step with the dates typed here.

	ERPNext builds `due_date` and the payment schedule when the invoice is created, from
	the posting date. Its validate then refuses a due date later than the supplier's terms
	allow from the SUPPLIER invoice date ("Due / Reference Date cannot be after ..."), so an
	invoice dated before the day it was keyed in could not be saved at all. The desk form
	avoids this by recalculating in the browser when the date changes; this screen saves on
	the server, so the schedule is cleared here and ERPNext rebuilds it from the new dates.
	"""
	if not invoice.get("bill_date"):
		return
	bill = getdate(invoice.bill_date)
	if _payment_terms_template(invoice):
		due = terms_due_date(invoice)
	else:
		due = invoice.get("custom_payment_due_date")
	invoice.due_date = max(getdate(due), bill) if due else bill
	invoice.set("payment_schedule", [])


def _apply_draft_values(invoice, data):
	if isinstance(data, str):
		data = json.loads(data or "{}")
	data = data or {}
	dates_before = (_date_str(invoice.get("bill_date")), _date_str(invoice.get("custom_payment_due_date")))
	for field in DRAFT_FIELDS:
		if field in data:
			invoice.set(field, data.get(field) or None)
	if dates_before != (_date_str(invoice.get("bill_date")), _date_str(invoice.get("custom_payment_due_date"))):
		_align_erpnext_schedule(invoice)
	if not cint(invoice.get("custom_include_logistics")):
		for field in (
			"custom_logistics_vendor",
			"custom_transport_invoice_no",
			"custom_freight_amount",
			"custom_transport_attachment",
		):
			invoice.set(field, None)

	# BRD 6.2.2 Unit Price is the one item value the Purchase Team types; the quantity is
	# the GRN's approved quantity and stays as fetched. Rows are matched by name, so a
	# stale or foreign row name changes nothing. Under Maintain Same Rate the price is the
	# PO's, so nothing sent for it is applied.
	if not rate_editable():
		return
	rates = {r.get("name"): r.get("rate") for r in (data.get("items") or []) if r.get("name")}
	for row in invoice.get("items") or []:
		if row.name in rates and rates[row.name] is not None:
			row.rate = flt(rates[row.name])


def _load_draft_for_edit(purchase_invoice):
	invoice = frappe.get_doc(PI, purchase_invoice)
	invoice.check_permission("write")
	if not is_module_invoice(invoice):
		frappe.throw(_("{0} was not raised by the Purchase Inward module.").format(invoice.name))
	if cint(invoice.docstatus) != 0:
		frappe.throw(
			_("Invoice {0} is already submitted; its supplier bill can no longer be edited.").format(
				invoice.name
			),
			title=_("Submitted Invoice Is Locked"),
		)
	if not _has_role(C.UNF_CREATE_ROLES):
		frappe.throw(
			_("Only the Purchase Team can edit the supplier bill."),
			frappe.PermissionError,
			title=_("Not Permitted"),
		)
	return invoice


@frappe.whitelist()
def save_invoice(purchase_invoice, data=None):
	"""BRD 6.5 "Save Draft": store the Purchase Team's entries without moving the workflow."""
	invoice = _load_draft_for_edit(purchase_invoice)
	_apply_draft_values(invoice, data)
	invoice.save()
	return {"name": invoice.name, "status": invoice_status(invoice)}


@frappe.whitelist()
def submit_invoice(purchase_invoice, data=None):
	"""BRD 6.5 "Submit Invoice": save what is on screen, then lock it and hand it to Accounts.

	One request, so a refused submit (VAL-UNF-01..03) rolls back the save as well and the
	screen is never left half-saved behind an error.
	"""
	invoice = _load_draft_for_edit(purchase_invoice)
	invoice.check_permission("submit")
	if data:
		_apply_draft_values(invoice, data)
		invoice.save()
	invoice.submit()
	return {"name": invoice.name, "status": invoice_status(invoice)}
