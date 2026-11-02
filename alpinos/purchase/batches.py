"""Batch documents for batch-tracked items received through the purchase chain.

A batch-tracked item (Item > Has Batch No) can only be received into a Batch that exists:
Purchase Receipt Item.batch_no is a Link, and without "Automatically Create New Batch" ERPNext
makes none. Purchase QC used to be the only place a Batch was made, and only for an Internal
Batch Code (RM / PM). A finished-goods line carries the supplier batch Store typed on the
inward instead, so its GRN had nothing to link and its final submit was refused
(VAL-GRN-03: "Batch Number" missing).

ensure_batch() is the one place a Batch is made for a code, used by QC, by GRN generation, by
a Draft GRN on save, and by a batch typed on the GRN screen.
"""

import re

import frappe
from frappe.utils import cint


def clean(value):
	"""Batch codes go on stickers and into the stock ledger — keep them tame."""
	value = re.sub(r"[^A-Za-z0-9_\-/]+", "-", (value or "").strip())
	return re.sub(r"-{2,}", "-", value).strip("-")


def ensure_batch(item_code, code, supplier=None, manufacturing_date=None, expiry_date=None,
		reference_doctype=None, reference_name=None):
	"""The Batch id for `code` on a batch-tracked item, creating the Batch when it is missing.

	A Batch belongs to exactly one Item, while a code (an invoice-based Internal Batch Code, a
	supplier batch) can be shared by several items of one inward, so a code already held by
	another item is made per item ("<code>-<item>") and that id is returned: the document has
	to name the batch the ledger holds.

	None when the item is not batch tracked, there is no code, or the item needs an expiry
	date that cannot be worked out (Batch.set_expiry_date would throw) - the GRN then names the
	missing batch instead of failing somewhere else.
	"""
	code = clean(code)
	if not (item_code and code):
		return None
	has_batch, has_expiry, shelf_life = frappe.get_cached_value(
		"Item", item_code, ["has_batch_no", "has_expiry_date", "shelf_life_in_days"]
	) or (0, 0, 0)
	if not cint(has_batch):
		return None
	for batch_id in (code, clean(code + "-" + item_code)):
		owner = frappe.db.get_value("Batch", batch_id, "item")
		if owner == item_code:
			return batch_id
		if owner:
			continue
		if cint(has_expiry) and not expiry_date and not (cint(shelf_life) and manufacturing_date):
			return None
		batch = frappe.new_doc("Batch")
		batch.batch_id = batch_id
		batch.item = item_code
		batch.supplier = supplier
		batch.manufacturing_date = manufacturing_date
		batch.expiry_date = expiry_date
		batch.reference_doctype = reference_doctype
		batch.reference_name = reference_name
		batch.flags.ignore_permissions = True
		batch.insert()
		return batch.name
	return None


def inward_line_dates(inward_item):
	"""(manufacturing date, expiry date) Store recorded on a Purchase Inward line."""
	if not inward_item:
		return None, None
	row = frappe.db.get_value(
		"Purchase Inward Item", inward_item, ["manufacturing_date", "expiry_date"], as_dict=True
	)
	return (row.manufacturing_date, row.expiry_date) if row else (None, None)


def grn_row_batch(pr, row, code):
	"""The Batch for a GRN row's code (typed on the GRN screen or carried from the inward)."""
	mfg, exp = inward_line_dates(row.get("custom_purchase_inward_item"))
	return ensure_batch(
		row.item_code, code, supplier=pr.get("supplier"), manufacturing_date=mfg, expiry_date=exp,
		reference_doctype="Purchase Inward" if pr.get("custom_purchase_inward") else None,
		reference_name=pr.get("custom_purchase_inward"),
	)


def fill_grn_batches(doc, method=None):
	"""Purchase Receipt before_validate: a module GRN row of a batch-tracked item with no Batch
	links the batch its code names (the Internal Batch Code, else the supplier batch from the
	inward), made when missing - so a Draft GRN generated before batches were made for
	finished goods submits on its next save instead of naming a Batch Number nobody can pick.
	"""
	if not doc.get("custom_purchase_inward") or doc.get("is_return"):
		return
	for row in doc.get("items") or []:
		if row.get("batch_no") or not row.get("item_code"):
			continue
		if not cint(frappe.get_cached_value("Item", row.item_code, "has_batch_no")):
			continue
		code = row.get("custom_internal_batch_no")
		if not code and row.get("custom_purchase_inward_item"):
			code = frappe.db.get_value("Purchase Inward Item", row.custom_purchase_inward_item, "batch_no")
		batch = grn_row_batch(doc, row, code) if code else None
		if batch:
			row.batch_no = batch
			row.use_serial_batch_fields = 1
