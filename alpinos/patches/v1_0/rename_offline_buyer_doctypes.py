"""Rename the Offline Buyer doctypes to plain Buyer — they are the general
buyer masters now (channel-agnostic). Runs pre_model_sync so the rename happens
before the app's (already renamed) doctype JSONs sync; otherwise migrate would
create fresh empty Buyer * doctypes alongside the old tables."""

import frappe

RENAMES = [
	("Offline Buyer Master", "Buyer Master"),
	("Offline Buyer Items", "Buyer Items"),
	("Offline Buyer Item", "Buyer Item"),
	("Offline Buyer Margin", "Buyer Margin"),
	("Offline Buyer Address", "Buyer Address"),
]


def execute():
	for old, new in RENAMES:
		if frappe.db.exists("DocType", old) and not frappe.db.exists("DocType", new):
			frappe.rename_doc("DocType", old, new, force=True)
	frappe.db.commit()
