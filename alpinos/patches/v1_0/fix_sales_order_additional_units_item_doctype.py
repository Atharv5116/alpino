"""Ensure Sales Order Additional Units Item is a standard app DocType under Alpinos Development.

Sites can end up with module=Core or custom=1 if metadata was created incorrectly, which
breaks controller import (frappe.core.doctype...).
"""

import frappe


def execute():
	if not frappe.db.exists("DocType", "Sales Order Additional Units Item"):
		return

	row = frappe.db.get_value(
		"DocType",
		"Sales Order Additional Units Item",
		["module", "custom"],
		as_dict=True,
	)
	if not row:
		return

	changed = False
	if row.get("custom"):
		frappe.db.set_value("DocType", "Sales Order Additional Units Item", "custom", 0)
		changed = True
	if (row.get("module") or "").strip() != "Alpinos Development":
		frappe.db.set_value(
			"DocType",
			"Sales Order Additional Units Item",
			"module",
			"Alpinos Development",
		)
		changed = True

	if changed:
		frappe.db.commit()
		frappe.clear_cache(doctype="DocType")
