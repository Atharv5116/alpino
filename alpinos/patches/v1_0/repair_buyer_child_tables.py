"""Repair Buyer * tables after the Offline Buyer rename.

On UAT the migrate that performed the rename aborted partway (the Job
Application web-form crash fixed in f68ad45), leaving Buyer child tables
without their standard child columns — loading any Buyer Master then dies
with "Unknown column 'parent' in 'WHERE'". Re-running the schema sync per
doctype adds the missing standard columns. Idempotent and harmless on
healthy sites."""

import frappe

DOCTYPES = ("Buyer Master", "Buyer Items", "Buyer Item", "Buyer Margin", "Buyer Address")


def execute():
	for dt in DOCTYPES:
		if not frappe.db.exists("DocType", dt):
			continue
		try:
			frappe.db.updatedb(dt)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"buyer table repair failed: {dt}")
	frappe.db.commit()
