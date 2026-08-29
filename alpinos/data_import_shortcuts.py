"""One-click desk pages that pre-fill a native Data Import and jump to its upload step."""

import frappe

ALLOWED_DOCTYPES = ("Stock Entry", "Stock Reconciliation", "Sales Order")


def ensure_allow_import():
	"""after_migrate: turn on Allow Import for the shortcut doctypes (Stock Reconciliation ships without it)."""
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	changed = False
	for dt in ALLOWED_DOCTYPES:
		if not frappe.get_meta(dt).allow_import:
			make_property_setter(dt, None, "allow_import", 1, "Check", for_doctype=True)
			changed = True

	# submit_after_import is set_only_once in core; the shortcut pre-creates the doc, so unlock it.
	if frappe.get_meta("Data Import").get_field("submit_after_import").set_only_once:
		make_property_setter("Data Import", "submit_after_import", "set_only_once", 0, "Check")
		changed = True

	if changed:
		frappe.clear_cache()


@frappe.whitelist()
def get_or_create_data_import(reference_doctype):
	"""Return a pre-filled Data Import for the doctype, reusing the user's own pending file-less one."""
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
