import frappe


def execute():
	frappe.reload_doc(
		"alpinos_development", "doctype", "alpinos_removed_pick_list_item"
	)
