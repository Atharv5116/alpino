import frappe

def create_pick_list_list_page():
	if not frappe.db.exists("Page", "pick_list_list"):
		doc = frappe.get_doc({
			"doctype": "Page",
			"page_name": "pick_list_list",
			"title": "Pick List List",
			"module": "Alpinos Development",
			"standard": "Yes"
		})
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		print("CREATED")
	else:
		print("EXISTS")
