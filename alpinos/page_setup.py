"""Setup custom pages for alpinos app."""

import frappe


def create_screening_page():
	"""Bring the Screening page in line with its JSON file.

	This used to delete the page and insert it again from the JSON. Frappe v16 refuses to
	insert a standard Page outside developer mode, so the delete went through, the insert
	did not, and the page was gone. Re-importing the file updates it in place on v15 and
	v16 alike and never leaves the site without the page.
	"""
	try:
		frappe.reload_doc("alpinos_development", "page", "screening", force=True)
		frappe.clear_cache()
		print("✅ Screening page synced from its JSON file")
	except Exception as e:
		print(f"⚠️  Could not sync page screening: {str(e)}")
		frappe.log_error(f"Error syncing screening page: {str(e)}")

