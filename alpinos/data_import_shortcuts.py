"""One-click Data Import shortcuts.

Three thin desk pages (/app/stock-entry-import, /app/stock-reconciliation-import,
/app/sales-order-import) that create — or reuse — a pre-filled Data Import and
redirect straight to the native Data Import form at the upload step. Column
mapping, preview, status and error logs are the standard Data Import features;
nothing is reimplemented.
"""

import frappe

ALLOWED_DOCTYPES = ("Stock Entry", "Stock Reconciliation", "Sales Order")


def ensure_allow_import():
	"""after_migrate hook: every doctype behind an import shortcut page must
	have Allow Import on, else Data Import refuses it (Stock Reconciliation
	ships without it). Property setter, so it survives frappe/erpnext updates."""
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	changed = False
	for dt in ALLOWED_DOCTYPES:
		if not frappe.get_meta(dt).allow_import:
			make_property_setter(dt, None, "allow_import", 1, "Check", for_doctype=True)
			changed = True

	# Submit After Import is set_only_once in core — frozen the moment a Data
	# Import is saved. The shortcut pages pre-create the document, so the user
	# could never toggle it. Lift the lock; the importer reads the value at
	# import time, so editing it on a pending import is safe.
	if frappe.get_meta("Data Import").get_field("submit_after_import").set_only_once:
		make_property_setter("Data Import", "submit_after_import", "set_only_once", 0, "Check")
		changed = True

	if changed:
		frappe.clear_cache()


@frappe.whitelist()
def get_or_create_data_import(reference_doctype):
	"""Return the name of a pre-filled, saved Data Import for the doctype.

	Reuses the current user's own pending import for the same doctype when it
	has no file attached yet, so revisiting the shortcut page doesn't litter
	Data Import records."""
	if reference_doctype not in ALLOWED_DOCTYPES:
		frappe.throw(frappe._("No import shortcut is defined for {0}.").format(reference_doctype))
	if not frappe.has_permission("Data Import", "create"):
		frappe.throw(frappe._("Not permitted to create Data Import."), frappe.PermissionError)
	if not frappe.has_permission(reference_doctype, "create"):
		frappe.throw(
			frappe._("Not permitted to create {0}.").format(reference_doctype),
			frappe.PermissionError,
		)

	existing = frappe.get_all(
		"Data Import",
		filters=[
			["reference_doctype", "=", reference_doctype],
			["status", "=", "Pending"],
			["import_file", "is", "not set"],
			["google_sheets_url", "is", "not set"],
			["owner", "=", frappe.session.user],
			["docstatus", "=", 0],
		],
		pluck="name",
		limit=1,
	)
	if existing:
		return existing[0]

	doc = frappe.new_doc("Data Import")
	doc.reference_doctype = reference_doctype
	doc.import_type = "Insert New Records"
	doc.insert()
	return doc.name
