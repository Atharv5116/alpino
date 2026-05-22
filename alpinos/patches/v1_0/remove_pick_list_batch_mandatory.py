import frappe

def execute():
	# Delete the property setter that made batch_no mandatory
	frappe.db.delete("Property Setter", {
		"doc_type": "Pick List Item",
		"field_name": "batch_no",
		"property": "reqd"
	})
	frappe.clear_cache(doctype="Pick List Item")
