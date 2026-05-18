import frappe

def execute():
	"""Enable guest file uploads in System Settings so web forms can accept attachments from guests."""
	frappe.reload_doc("core", "doctype", "system_settings")
	
	system_settings = frappe.get_doc("System Settings")
	system_settings.allow_guests_to_upload_files = 1
	system_settings.save(ignore_permissions=True)
	frappe.db.commit()
