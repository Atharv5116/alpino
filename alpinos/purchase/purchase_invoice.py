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

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, now_datetime

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


def _derive_payment_due_date(doc):
	"""Invoice Date + the supplier's credit days (BRD 6.1.1 "Invoice Date + Payment Terms").

	Only ever fills a blank. On a Direct invoice the BRD has the Purchase Team type the
	date by hand (6.1.2), and on a normal one an explicit date beats a derived one.
	"""
	if doc.get("custom_payment_due_date") or not doc.get("bill_date"):
		return
	credit_days = None
	if doc.get("payment_terms_template"):
		rows = frappe.get_all(
			"Payment Terms Template Detail",
			filters={"parent": doc.payment_terms_template},
			fields=["credit_days"],
			order_by="idx asc",
			limit=1,
		)
		credit_days = rows[0].credit_days if rows else None
	if credit_days is None and doc.get("supplier"):
		credit_days = frappe.db.get_value("Supplier", doc.supplier, "payment_terms")
		credit_days = None  # a Supplier's payment_terms is a template name, not a number
	if credit_days is None:
		return
	doc.custom_payment_due_date = add_days(getdate(doc.bill_date), cint(credit_days))


# --------------------------------------------------------------- BRD 6.3 / 6.4


def _validate_submit_requirements(doc):
	"""VAL-UNF-01 / 02 / 03 — what the Purchase Team must supply before submitting."""
	if not (doc.get("bill_no") or "").strip():
		frappe.throw(_("Please enter the Supplier Invoice Number."), title=_("VAL-UNF-01"))

	if not (doc.get("custom_invoice_attachment") or "").strip():
		frappe.throw(
			_("Please upload the physical supplier invoice copy."), title=_("VAL-UNF-02")
		)

	if cint(doc.get("custom_include_logistics")):
		if not doc.get("custom_logistics_vendor") or flt(doc.get("custom_freight_amount")) <= 0:
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


# ------------------------------------------------------------------ doc hooks


def validate(doc, method=None):
	if not doc.get(TYPE_FIELD):
		doc.set(TYPE_FIELD, C.UNF_TYPE_NORMAL)
	_derive_payment_due_date(doc)
	_validate_payment_rows(doc)
	recompute_payment_state(doc)


def before_submit(doc, method=None):
	_validate_submit_requirements(doc)
	# Submitting is the hand-off to Accounts (BRD 6.2.1 "Fill Details & Click Submit ->
	# Pending Payment"), so the status is derived at docstatus 1 rather than left at Draft.
	doc.docstatus = 1
	recompute_payment_state(doc)


def before_update_after_submit(doc, method=None):
	_assert_purchase_sections_unchanged(doc)
	_validate_payment_rows(doc)
	recompute_payment_state(doc)


def on_cancel(doc, method=None):
	doc.set(STATUS_FIELD, C.UNF_CANCELLED)


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
	invoice.flags.ignore_permissions = True
	invoice.insert(ignore_permissions=True)
	return invoice


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

	invoice = create_from_grn(inward.purchase_receipt)
	inward.db_set("purchase_invoice", invoice.name, update_modified=False)
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


@frappe.whitelist()
def get_invoice_context(purchase_invoice):
	"""What the screen needs to draw its buttons, decided on the server."""
	invoice = frappe.get_doc(PI, purchase_invoice)
	invoice.check_permission("read")
	roles = set(frappe.get_roles())
	status = invoice.get(STATUS_FIELD) or C.UNF_DRAFT
	return {
		"name": invoice.name,
		"status": status,
		"invoice_type": invoice.get(TYPE_FIELD),
		"docstatus": cint(invoice.docstatus),
		"supplier_pending": flt(invoice.get("custom_supplier_pending_amount")),
		"logistics_pending": flt(invoice.get("custom_logistics_pending_amount")),
		"total_paid": flt(invoice.get("custom_total_paid_amount")),
		"can_edit": cint(invoice.docstatus) == 0
		and bool(roles.intersection(C.UNF_CREATE_ROLES)),
		"can_add_payment": cint(invoice.docstatus) == 1
		and status in (C.UNF_PENDING_PAYMENT, C.UNF_PARTIALLY_PAID)
		and bool(roles.intersection(C.UNF_PAYMENT_ROLES)),
	}
