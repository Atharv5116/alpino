"""Server-side hooks for Stock Entry."""

import frappe


def set_entry_by(doc, method=None):
	"""Auto-populate Entry By with the currently logged-in user on new records."""
	if not doc.get("custom_entry_by"):
		doc.custom_entry_by = frappe.session.user


def apply_batch_codes(doc, method=None):
	"""Batch Code on a Stock Entry row (Changes(HP) #82).

	A receipt creates the Batch master for a batch-tracked item when the code is new and links
	it; other entries link a batch that already exists. For an item that is not batch-tracked
	the code stays text only, as on the Pick List and Delivery Note (ERPNext refuses a Batch
	for such an item). A Batch No chosen directly is copied into Batch Code.
	"""
	from alpinos.pick_list_api import _ensure_batch_exists

	receipt = doc.purpose == "Material Receipt"
	for row in doc.get("items") or []:
		code = (row.get("custom_batch_code") or "").strip()
		if not code:
			if row.get("batch_no"):
				row.custom_batch_code = row.batch_no
			continue
		row.custom_batch_code = code
		if row.get("batch_no") == code or not row.get("item_code"):
			continue
		if receipt:
			batch = _ensure_batch_exists(row.item_code, code, row.get("custom_mfg_date"), row.get("custom_exp_date"))
		else:
			batch = code if frappe.db.exists("Batch", {"name": code, "item": row.item_code}) else None
		if batch:
			row.batch_no = batch
			row.use_serial_batch_fields = 1
