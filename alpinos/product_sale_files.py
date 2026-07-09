"""Alpino Product Sale screenshots are public files.

Payment screenshots must be viewable without a Frappe session (shared links,
WhatsApp, accountant reviews), so every file attached to Alpino Product Sale
is flipped to public right after upload. Flipping happens in after_insert —
File writes its content to disk inside the controller's before_insert, so the
supported way to relocate it is a save with is_private changed, which routes
through File.handle_is_private_changed (moves the file, rewrites file_url)."""

import frappe

TARGET_DOCTYPE = "Alpino Product Sale"
DEFAULT_FIELD = "payment_screenshot"


def _publish_file(file_doc):
	"""Make one File public and keep the referencing attach field in sync.
	Returns True when the file was flipped."""
	if not file_doc.is_private:
		return False
	old_url = file_doc.file_url
	file_doc.is_private = 0
	file_doc.save(ignore_permissions=True)

	# file_url changed (/private/files/... -> /files/...): update the attach
	# field on the sale record if it still points at the old URL.
	if file_doc.attached_to_name and frappe.db.exists(TARGET_DOCTYPE, file_doc.attached_to_name):
		field = file_doc.attached_to_field or DEFAULT_FIELD
		current = frappe.db.get_value(TARGET_DOCTYPE, file_doc.attached_to_name, field)
		if current == old_url:
			frappe.db.set_value(
				TARGET_DOCTYPE,
				file_doc.attached_to_name,
				field,
				file_doc.file_url,
				update_modified=False,
			)
	return True


def make_product_sale_file_public(doc, method=None):
	"""File after_insert hook: uploads attached to Alpino Product Sale become
	public immediately, so the URL handed back to the uploader is already the
	public one."""
	if doc.get("attached_to_doctype") != TARGET_DOCTYPE or doc.get("is_folder"):
		return
	try:
		_publish_file(doc)
	except Exception:
		# Never block the upload over a relocation problem; log for follow-up.
		frappe.log_error(frappe.get_traceback(), "product sale screenshot publish failed")


def publish_existing_files():
	"""Idempotent backfill: flip every private file already attached to
	Alpino Product Sale. Used by the migration patch; safe to re-run."""
	names = frappe.get_all(
		"File",
		filters={"attached_to_doctype": TARGET_DOCTYPE, "is_private": 1, "is_folder": 0},
		pluck="name",
	)
	done = failed = 0
	for name in names:
		try:
			if _publish_file(frappe.get_doc("File", name)):
				done += 1
		except Exception:
			failed += 1
			frappe.log_error(
				frappe.get_traceback(), f"product sale screenshot backfill failed: {name}"
			)
	if done or failed:
		print(f"Alpino Product Sale screenshots: {done} made public, {failed} failed (see Error Log)")
	return {"published": done, "failed": failed}
