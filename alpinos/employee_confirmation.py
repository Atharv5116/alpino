"""Detect employee confirmation (employment type leaving "Probation") and allocate leaves.

Wired as Employee `on_update` in hooks.py. When an employee's employment_type changes
FROM "Probation" to anything else, we allocate the confirmation leaves (Casual/Bereavement/
Restricted) via alpinos.confirmation_leave_allocation.allocate_confirmation_leaves.

Failures are caught and logged so they never block HR's save of the Employee; the
allocation itself is idempotent (guard flag + per-period existence check).
"""

import frappe

from alpinos.confirmation_leave_allocation import allocate_confirmation_leaves

PROBATION = "Probation"


def on_employee_update(doc, method=None):
	# Already allocated once -> nothing to do.
	if doc.get("custom_confirmation_leaves_allocated"):
		return

	before = doc.get_doc_before_save()
	if not before:
		return

	was_probation = (before.get("employment_type") or "") == PROBATION
	now_confirmed = (doc.get("employment_type") or "") != PROBATION

	if not (was_probation and now_confirmed):
		return

	try:
		allocate_confirmation_leaves(doc)
	except Exception:
		frappe.log_error(
			f"Confirmation leave allocation failed for {doc.name}\n{frappe.get_traceback()}",
			"Employee Confirmation",
		)
