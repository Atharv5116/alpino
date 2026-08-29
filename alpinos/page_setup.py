"""Setup custom pages for alpinos app."""

import frappe
import json
import os


def create_screening_page():
	"""Delete any existing Screening page and recreate it from the JSON file."""

	page_name = "screening"

	if frappe.db.exists("Page", page_name):
		try:
			frappe.delete_doc("Page", page_name, force=1, ignore_permissions=True)
			frappe.db.commit()
			print(f"✅ Deleted existing Page: {page_name}")
		except Exception as e:
			print(f"⚠️  Could not delete existing page: {str(e)}")
			frappe.db.rollback()
	
	try:
		app_path = frappe.get_app_path("alpinos")
		json_path = os.path.join(app_path, "alpinos_development", "page", page_name, f"{page_name}.json")

		if os.path.exists(json_path):
			with open(json_path, 'r') as f:
				page_data = json.load(f)

			# Drop name/timestamps so the page is created fresh.
			page_data.pop('name', None)
			page_data.pop('creation', None)
			page_data.pop('modified', None)
			page_data.pop('modified_by', None)
			page_data.pop('owner', None)

			page = frappe.get_doc(page_data)
			page.insert(ignore_permissions=True)
			frappe.db.commit()
			frappe.clear_cache()
			print(f"✅ Created Page: {page_name} from JSON file")
		else:
			# Fallback: create page directly
			page = frappe.get_doc({
				"doctype": "Page",
				"page_name": page_name,
				"title": "Screening",
				"icon": "fa fa-filter",
				"module": "Alpinos Development",
				"standard": "Yes",
				"system_page": 0,
			})
			page.insert(ignore_permissions=True)
			frappe.db.commit()
			frappe.clear_cache()
			print(f"✅ Created Page: {page_name}")
	except Exception as e:
		print(f"⚠️  Could not create page {page_name}: {str(e)}")
		frappe.log_error(f"Error creating screening page: {str(e)}")
		frappe.db.rollback()

