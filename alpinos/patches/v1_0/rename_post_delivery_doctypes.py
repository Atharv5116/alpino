"""Rename the Post Delivery doctypes to Post Dispatch. Runs pre_model_sync so the rename
happens before the app's (already renamed) doctype JSONs sync; otherwise migrate would
create fresh empty Post Dispatch * doctypes alongside the old Post Delivery tables."""

import frappe

RENAMES = [
	("Post Delivery", "Post Dispatch"),
	("Post Delivery GRN Item", "Post Dispatch GRN Item"),
]


def execute():
	for old, new in RENAMES:
		if frappe.db.exists("DocType", old) and not frappe.db.exists("DocType", new):
			frappe.rename_doc("DocType", old, new, force=True)
	frappe.db.commit()
