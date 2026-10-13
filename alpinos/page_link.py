"""Frappe 15's link check, for link fields on the alpinos pages and dialogs under Frappe 16.

Frappe 16 checks a link value through the field's search (its query and filters, which hide
disabled records), where Frappe 15 only checked that the record exists and the user may pick it.
The alpinos pages open saved documents into such fields, so a value that has since left the
query's selection (an FG batch no longer on hold, a completed Sub PO, a disabled user) was
cleared. alpinos_page_controls.js sends page and dialog links here instead: the record exists,
the user may select or read it, and the fields the control fetches. This is Frappe 15's
frappe.client.validate_link, which Frappe 16 removed.
"""

import frappe
from frappe import _


@frappe.whitelist()
def validate_link(doctype: str, docname: str, fields: str | list | None = None):
	if doctype != "DocType":
		parent_doctype = None
		if frappe.get_meta(doctype).istable:  # links to child rows
			parent_doctype = frappe.db.get_value(doctype, docname, "parenttype")
		if not (
			frappe.has_permission(doctype, "select", parent_doctype=parent_doctype)
			or frappe.has_permission(doctype, "read", parent_doctype=parent_doctype)
		):
			frappe.throw(
				_("You do not have Read or Select Permissions for {}").format(frappe.bold(doctype)),
				frappe.PermissionError,
			)

	values = frappe._dict(name=frappe.db.get_value(doctype, docname, cache=True))
	fields = frappe.parse_json(fields)
	if not values.name or not fields:
		return values

	from frappe.client import get_value

	try:
		values.update(get_value(doctype, fields, docname))
	except frappe.PermissionError:
		frappe.clear_last_message()
		frappe.msgprint(
			_("You need {0} permission to fetch values from {1} {2}").format(
				frappe.bold(_("Read")), frappe.bold(doctype), frappe.bold(docname)
			),
			title=_("Cannot Fetch Values"),
			indicator="orange",
		)
	return values
