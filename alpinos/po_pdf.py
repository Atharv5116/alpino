"""Fetch customer PO PDFs from the configured server folder onto Sales Orders."""

import os

import frappe
from frappe import _


def _resolve_pdf_path(po_no):
	folder = (frappe.db.get_single_value("Alpino General Settings", "po_pdf_folder") or "").strip()
	if not folder:
		frappe.throw(_("Set the PO PDF Folder in Alpino General Settings first."))
	if not os.path.isdir(folder):
		frappe.throw(_("PO PDF Folder does not exist on the server: {0}").format(folder))

	# file name only, never a path (blocks traversal)
	safe = os.path.basename((po_no or "").strip())
	if not safe:
		frappe.throw(_("Set 'PO No for PDF' first."))

	names = [safe] if safe.lower().endswith(".pdf") else [safe + ".pdf", safe + ".PDF"]
	for name in names:
		path = os.path.join(folder, name)
		if os.path.isfile(path):
			return path, os.path.basename(path)
	frappe.throw(
		_("No PDF named {0} found in the PO PDF folder.").format(
			frappe.bold(safe if safe.lower().endswith(".pdf") else safe + ".pdf")
		)
	)


@frappe.whitelist()
def fetch_po_pdf(sales_order, po_no_for_pdf=None):
	"""Fetch the PO PDF for a Sales Order and attach it, replacing any previous one."""
	doc = frappe.get_doc("Sales Order", sales_order)
	doc.check_permission("write")

	po_no = (po_no_for_pdf or doc.get("custom_po_no_for_pdf") or "").strip()
	path, file_name = _resolve_pdf_path(po_no)

	with open(path, "rb") as f:
		content = f.read()

	# drop the previous attachment before re-attaching
	if doc.get("custom_po_pdf"):
		old = frappe.db.get_value(
			"File",
			{
				"file_url": doc.custom_po_pdf,
				"attached_to_doctype": "Sales Order",
				"attached_to_name": doc.name,
			},
			"name",
		)
		if old:
			frappe.delete_doc("File", old, force=True, ignore_permissions=True)

	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": file_name,
			"attached_to_doctype": "Sales Order",
			"attached_to_name": doc.name,
			"attached_to_field": "custom_po_pdf",
			"is_private": 1,
			"content": content,
		}
	).insert(ignore_permissions=True)

	# db_set works on submitted orders (allow_on_submit) and skips the SO validate chain
	doc.db_set("custom_po_no_for_pdf", po_no, update_modified=False)
	doc.db_set("custom_po_pdf", file_doc.file_url, update_modified=False)
	frappe.db.commit()
	return {"file_url": file_doc.file_url, "file_name": file_doc.file_name}


def maybe_fetch_po_pdf(sales_order):
	"""Best-effort fetch after an entry-page save; never breaks the save."""
	try:
		if frappe.db.get_value("Sales Order", sales_order, "custom_po_no_for_pdf"):
			fetch_po_pdf(sales_order)
	except Exception:
		frappe.clear_last_message()
		frappe.log_error(frappe.get_traceback(), f"PO PDF auto-fetch failed: {sales_order}")
