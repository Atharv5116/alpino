"""Build a Google Drive link to a Sales Order's PO file.

The PO documents live in Drive under:  <root>/<Channel>/<Customer>/<prefix + Customer>/
and the file itself is named after the PO No (custom_po_no_for_pdf). Given a Sales
Order, we walk that path with the invoice-sync service account, find the file, and
store a clickable Drive link on custom_po_drive_url.

Config (Invoice Sync Settings): service_account_json (reused), po_drive_root_folder_id,
po_folder_prefix. If the file isn't there yet, we link to the deepest folder that DOES
exist so the link still opens the right place in Drive (to upload into).
"""

import frappe
from frappe import _
from frappe.utils import flt  # noqa: F401  (kept for parity; harmless)

# Reuse the Drive plumbing already built for invoice sync.
from alpinos.invoice_sync import _settings, _drive_service, _folder_id, _child_folder, _find_file


def _drive_file_url(file_id):
	return f"https://drive.google.com/file/d/{file_id}/view"


def _drive_folder_url(folder_id):
	return f"https://drive.google.com/drive/folders/{folder_id}"


def _resolve_po_drive_url(channel, customer, po_no):
	"""Return a Drive URL for the PO file, or the deepest existing folder as a fallback.

	Returns (url, note). Raises only when Drive isn't configured or the top-level
	Channel folder is missing (so the caller can surface a helpful message)."""
	s = _settings()
	root = _folder_id(s.get("po_drive_root_folder_id") or s.get("drive_root_folder_id") or "")
	if not (s.get("service_account_json") and root):
		frappe.throw(_("Set the Service Account JSON and PO Drive Root Folder ID in Invoice Sync Settings first."))
	if not channel:
		frappe.throw(_("This Sales Order has no Channel set."))
	if not customer:
		frappe.throw(_("This Sales Order has no Customer name."))

	drive = _drive_service(s)
	prefix = s.get("po_folder_prefix")
	if prefix is None:
		prefix = "PO "

	# Walk root -> Channel -> Customer -> "<prefix>Customer", remembering the deepest
	# folder that exists so we can fall back to it if a deeper level is missing.
	deepest_id, deepest_label = root, "root"
	steps = [
		(channel, f"Channel '{channel}'"),
		(customer, f"Customer '{customer}'"),
		(f"{prefix}{customer}", f"'{prefix}{customer}'"),
	]
	parent = root
	for i, (name, label) in enumerate(steps):
		folder = _child_folder(drive, parent, name)
		if not folder:
			if i == 0:
				frappe.throw(_("Drive folder for {0} not found under the PO root.").format(label))
			# Deeper level missing -> link to the deepest folder we did reach.
			return _drive_folder_url(deepest_id), _("Folder {0} not found; linked to the {1} folder instead.").format(label, deepest_label)
		parent = deepest_id = folder
		deepest_label = label

	# We're in the "<prefix>Customer" folder — look for the file named after the PO No.
	ext = (s.get("pdf_extension") or ".pdf").strip()
	file_id = _find_file(drive, parent, (po_no or "").strip(), ext) if po_no else None
	if file_id:
		return _drive_file_url(file_id), ""
	return _drive_folder_url(parent), _("PO file '{0}' not found; linked to its folder so you can open/upload it.").format(po_no or "")


@frappe.whitelist()
def build_po_drive_url(sales_order, po_no_for_pdf=None):
	"""Resolve and store the PO Drive link on a Sales Order. Returns {url, note}."""
	doc = frappe.get_doc("Sales Order", sales_order)
	doc.check_permission("write")
	po_no = (po_no_for_pdf or doc.get("custom_po_no_for_pdf") or "").strip()
	url, note = _resolve_po_drive_url(doc.get("custom_channel"), doc.get("customer_name"), po_no)
	# db_set: works on submitted orders (field is allow_on_submit) without re-validating.
	if po_no and po_no != (doc.get("custom_po_no_for_pdf") or ""):
		doc.db_set("custom_po_no_for_pdf", po_no, update_modified=False)
	doc.db_set("custom_po_drive_url", url, update_modified=False)
	frappe.db.commit()
	return {"url": url, "note": note}


def maybe_build_po_drive_url(sales_order):
	"""Best-effort build after an entry-page save — never breaks the save; the user can
	always use the 'Fetch PO Drive Link' button and get the real error."""
	try:
		if frappe.db.get_value("Sales Order", sales_order, "custom_po_no_for_pdf"):
			build_po_drive_url(sales_order)
	except Exception:
		frappe.clear_last_message()
		frappe.log_error(frappe.get_traceback(), f"PO Drive link auto-build failed: {sales_order}")
