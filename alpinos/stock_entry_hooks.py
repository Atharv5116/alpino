"""Server-side hooks for Stock Entry."""

import frappe


def set_entry_by(doc, method=None):
	"""Auto-populate Entry By with the currently logged-in user on new records."""
	if not doc.get("custom_entry_by"):
		doc.custom_entry_by = frappe.session.user
