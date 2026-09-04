"""doc_event adapters for the Purchase Inward module.

Frappe hands doc_events a (doc, method) pair, while the module's own entry points
take plain names and are meant to be callable from the console and from tests. The
thin wrappers here are the only place that impedance mismatch lives.

Every wrapper is a no-op for documents outside this module, so registering them
site-wide cannot disturb ordinary alpinos stock or buying traffic.
"""

import frappe
from frappe.utils import cint


def purchase_receipt_on_submit(doc, method=None):
	"""Post the QC stock movements that had to wait for the GRN.

	QC draws its sample and control-sample quantities before any stock exists —
	the BRD parks the GRN in Draft until an Admin finally submits it (BR-QC-17 /
	BR-QC-20), so at QC-submit time the receiving warehouse is still empty and the
	transfers are deferred rather than blocking the inspection. Submitting the GRN
	is the first moment they can succeed. It is also the moment the GRN's own status and
	the BRD 5.2.1 final-submission trail are stamped.
	"""
	# A Purchase Return copies custom_purchase_inward / custom_purchase_qc off the GRN it
	# returns against (make_purchase_return does not treat them as no_copy), so without
	# this every wrapper here would also fire for the return document -- re-pointing the
	# QC at the return, or unwinding the QC's sample transfers when a return is cancelled
	# and silently moving sample stock out of the lab back into Stores.
	if cint(doc.get("is_return")):
		return

	from alpinos.purchase import grn

	# BR-GRN-06: C.GRN_COMPLETED was assigned nowhere, so a final-submitted receipt kept
	# custom_grn_status = "Draft" — the field is in_list_view + in_standard_filter, so the
	# Purchase Receipt list showed every completed GRN as Draft and filtering "Completed"
	# returned nothing. Stamped before the early return below, because a GRN raised without
	# a Purchase QC still has a status to move.
	grn.mark_submitted(doc)

	qc = doc.get("custom_purchase_qc")
	if qc:
		_post_deferred_sample_stock(doc, qc)

	if not doc.get("custom_purchase_inward"):
		# An ordinary alpinos stock receipt is none of this module's business.
		return

	# BRD 5 puts the Debit Note at this same moment: "Once submitted ... If the QC
	# Rejected Quantity is greater than zero, the system shall generate the applicable
	# Debit Note against the GRN" (BR-GRN-09 / BR-QC-21 / VAL-QC-17). Deliberately NOT
	# inside the QC branch: the two are independent.
	from alpinos.purchase.grn import make_debit_note

	try:
		make_debit_note(doc)
	except Exception:
		# A debit note is an Accounts artefact; failing to draft one must not roll back a
		# goods receipt that already moved stock. make_debit_note is idempotent, so
		# grn.generate_debit_note re-runs it once the cause is fixed.
		frappe.log_error(
			title="Purchase Inward: debit note generation failed",
			message=frappe.get_traceback(),
		)
		frappe.msgprint(
			frappe._(
				"The GRN is submitted, but the Debit Note for the rejected quantity could "
				"not be generated. It can be raised again once the cause is fixed."
			),
			indicator="orange",
		)


def _post_deferred_sample_stock(doc, qc):
	"""Post the QC sample transfers that had to wait for the GRN to exist."""
	from alpinos.alpinos_development.doctype.purchase_qc.purchase_qc import (
		post_pending_stock_entries,
	)

	# An amended GRN is a NEW receipt (GRN-x-1) while the QC and the inward still name
	# the cancelled one, and purchase_qc._receipt_batch only reads a batch off a
	# *submitted* receipt — without re-pointing them, every batch-tracked sample stayed
	# deferred forever after the BRD 5.3 cancel + amend. Written with db writes because
	# purchase_receipt is engine-owned (PurchaseInward._guard_engine_owned_fields).
	if frappe.db.get_value("Purchase QC", qc, "purchase_receipt") != doc.name:
		frappe.db.set_value("Purchase QC", qc, "purchase_receipt", doc.name, update_modified=False)
	inward = doc.get("custom_purchase_inward")
	if inward and frappe.db.get_value("Purchase Inward", inward, "purchase_receipt") != doc.name:
		frappe.db.set_value(
			"Purchase Inward", inward, "purchase_receipt", doc.name, update_modified=False
		)

	try:
		post_pending_stock_entries(qc)
	except Exception:
		# A failed sample transfer must not roll back a legitimate goods receipt;
		# the QC row keeps its blank stock_entry and post_pending_stock_entries is
		# safe to re-run from the QC form.
		frappe.log_error(
			title="Purchase QC: deferred stock entries failed",
			message=frappe.get_traceback(),
		)


def purchase_receipt_before_cancel(doc, method=None):
	"""BRD 5.3 — put the samples back before ERPNext reverses the receipt.

	Submitting the GRN posts the QC's sample / control-sample Material Transfers out of
	the receiving warehouse, so cancelling it afterwards died with NegativeStockError
	("5.0 units of Item X needed in Warehouse Stores - AHF ... for Stock Entry
	MAT-STE-...") while the QC refused to go first ("Cancel GRN ... before cancelling
	this Purchase QC") — a deadlock whose only escape was cancelling the Stock Entry by
	hand in Stock. Cancellation is reverse-chronological, so the samples come back
	before the receipt does. The QC rows are left with a blank stock_entry, which is
	exactly the state post_pending_stock_entries re-posts from when the GRN is amended
	and submitted again. No QC permission check on purpose: the right to cancel the GRN
	is the gate, and a QC-write check here would only re-create the deadlock.
	"""
	# A Purchase Return copies custom_purchase_inward / custom_purchase_qc off the GRN it
	# returns against (make_purchase_return does not treat them as no_copy), so without
	# this every wrapper here would also fire for the return document -- re-pointing the
	# QC at the return, or unwinding the QC's sample transfers when a return is cancelled
	# and silently moving sample stock out of the lab back into Stores.
	if cint(doc.get("is_return")):
		return

	qc = doc.get("custom_purchase_qc")
	if not qc or not frappe.db.exists("Purchase QC", qc):
		return
	from alpinos.alpinos_development.doctype.purchase_qc.purchase_qc import (
		reverse_pending_stock_entries,
	)

	reverse_pending_stock_entries(qc)


def purchase_receipt_on_cancel(doc, method=None):
	"""Flip the GRN status to Cancelled (BR-GRN-07).

	Without this a cancelled receipt — and the parent Purchase Inward it rolls onto — keep
	reading "Completed", so the Purchase Receipt list and every GRN Status filter lie.
	"""
	# A Purchase Return copies custom_purchase_inward / custom_purchase_qc off the GRN it
	# returns against (make_purchase_return does not treat them as no_copy), so without
	# this every wrapper here would also fire for the return document -- re-pointing the
	# QC at the return, or unwinding the QC's sample transfers when a return is cancelled
	# and silently moving sample stock out of the lab back into Stores.
	if cint(doc.get("is_return")):
		return

	if not doc.get("custom_purchase_inward"):
		return

	from alpinos.purchase import grn

	grn.mark_cancelled(doc)

	# BRD 5.3 orders the cancel GRN -> QC -> inward, so the GRN must not be blocked by
	# the very documents that are cancelled after it. PurchaseReceipt.on_cancel ASSIGNS
	# ignore_linked_doctypes, so appending here (doc_events compose after the controller
	# method, still before check_no_back_links_exist) is the only window that survives.
	# Every other back-link -- a Purchase Invoice, a Stock Entry consuming the received
	# stock -- keeps blocking the cancel, which is VAL-GRN-11.
	doc.ignore_linked_doctypes = tuple(doc.get("ignore_linked_doctypes") or ()) + (
		"Purchase Inward",
		"Purchase QC",
	)
