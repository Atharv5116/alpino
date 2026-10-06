"""Audit trail helper (FRD 5.6): a readable Info comment on the document for every
significant production action -- who, when, what and why."""

import frappe
from frappe.utils import format_datetime, now_datetime


def log_event(doctype, name, action, details="", reason=""):
	"""Adds "[ACTION] by <user> at <time>: details (reason)" as an Info comment on the
	document. Never raises; returns the Comment name or None."""
	try:
		if not (doctype and name):
			return None
		user = frappe.session.user if frappe.session else "Administrator"
		full_name = frappe.utils.get_fullname(user) or user
		at = format_datetime(now_datetime(), "dd-MM-yyyy HH:mm:ss")
		text = f"[{str(action or '').upper()}] by {full_name} at {at}"
		if details:
			text += f": {details}"
		if reason:
			text += f" ({reason})"
		comment = frappe.get_doc({
			"doctype": "Comment",
			"comment_type": "Info",
			"reference_doctype": doctype,
			"reference_name": name,
			"comment_email": user,
			"comment_by": full_name,
			"content": frappe.utils.escape_html(text),
		})
		comment.insert(ignore_permissions=True)
		return comment.name
	except Exception:
		frappe.log_error(frappe.get_traceback(), "audit.log_event")
		return None
