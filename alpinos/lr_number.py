"""Changes(HP) #52: the LR No. accepts a typed number and a scanned one alike.

    "In the Delivery Note, the LR No. field should support both:
     - Manually entered text/number (LR number)
     - Scanned LR number from a barcode/QR scanner"

A barcode scanner is a keyboard. It types the characters and then sends a terminator --
usually Enter, sometimes Tab, often a carriage return as well -- and some models prefix the
payload with a control character. Nothing has to be "integrated"; what has to happen is
that the value which lands in the field is the number and not the number plus whatever the
scanner wrapped around it.

Normalising on the server rather than only in the field matters because the LR number
arrives by three routes: typed on the Delivery Note entry page, set through the bulk LR
update, and imported from the LR Excel. A scanned value pasted into that spreadsheet would
otherwise be stored with its terminator intact and never match a search again.
"""

import re

import frappe

#: Control characters a scanner may wrap around the payload, plus the zero-width ones that
#: survive a copy-paste through a spreadsheet.
_CONTROL = re.compile(r"[\x00-\x1f\x7f​-‏  ﻿]")
_SPACES = re.compile(r"\s+")


def normalise_lr(value):
	"""The LR number as a human would read it, free of scanner debris.

	Inner whitespace is collapsed rather than removed: some transporters genuinely issue
	numbers with a space in them, and deleting it would change the number.
	"""
	if value is None:
		return None
	text = _CONTROL.sub("", str(value))
	text = _SPACES.sub(" ", text).strip()
	return text or None


def normalise_delivery_note_lr(doc, method=None):
	"""Delivery Note validate hook: whatever route the number arrived by, store it clean."""
	if doc.get("custom_lr_gr_no") is None:
		return
	cleaned = normalise_lr(doc.custom_lr_gr_no)
	if cleaned != doc.custom_lr_gr_no:
		doc.custom_lr_gr_no = cleaned


@frappe.whitelist()
def clean_existing_lr_numbers(apply=0, limit=500):
	"""Report, and optionally repair, LR numbers already stored with scanner debris.

	  bench --site SITE execute alpinos.lr_number.clean_existing_lr_numbers
	  bench --site SITE execute alpinos.lr_number.clean_existing_lr_numbers --kwargs "{'apply':1}"
	"""
	apply = int(apply)
	rows = frappe.db.sql(
		"""
		SELECT name, custom_lr_gr_no FROM `tabDelivery Note`
		WHERE IFNULL(custom_lr_gr_no, '') <> '' AND docstatus < 2
		LIMIT %(limit)s
		""",
		{"limit": int(limit)}, as_dict=True,
	)
	dirty = []
	for r in rows:
		cleaned = normalise_lr(r.custom_lr_gr_no)
		if cleaned != r.custom_lr_gr_no:
			dirty.append({"delivery_note": r.name, "stored": r.custom_lr_gr_no, "clean": cleaned})

	if apply:
		for d in dirty:
			frappe.db.set_value(
				"Delivery Note", d["delivery_note"], "custom_lr_gr_no", d["clean"],
				update_modified=False,
			)
		frappe.db.commit()

	return {
		"mode": "APPLY" if apply else "DRY-RUN",
		"scanned": len(rows),
		"needing_repair": len(dirty),
		"sample": dirty[:15],
	}
