"""Enable guest file uploads for web forms."""

import frappe


def enable_guest_file_uploads():
	try:
		system_settings = frappe.get_single("System Settings")
		if not system_settings.allow_guests_to_upload_files:
			system_settings.allow_guests_to_upload_files = 1
			system_settings.save(ignore_permissions=True)
			frappe.db.commit()
			print("✅ Enabled 'Allow Guests to Upload Files' system setting")
		else:
			print("ℹ️  'Allow Guests to Upload Files' is already enabled")
	except Exception as e:
		frappe.log_error(
			f"Failed to enable guest file uploads: {str(e)}\nTraceback: {frappe.get_traceback()}",
			"System Settings Setup Error"
		)
		print(f"⚠️  Warning: Could not enable guest file uploads: {str(e)}")


def execute():
	enable_guest_file_uploads()

