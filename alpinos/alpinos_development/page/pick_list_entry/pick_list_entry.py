import frappe
import json

@frappe.whitelist()
def get_pick_list_data(name):
	doc = frappe.get_doc('Pick List', name)
	doc.check_permission('read')
	return doc.as_dict()

@frappe.whitelist()
def get_active_batches():
	return frappe.get_all("Batch", pluck="name")

@frappe.whitelist()
def get_batch_details(batch_no, item_code):
	batch = frappe.db.get_value("Batch", {"name": batch_no, "item": item_code}, ["manufacturing_date", "expiry_date"], as_dict=1)
	return batch or {}

@frappe.whitelist()
def save_pick_list_data(name, header, items):
	header = json.loads(header) if isinstance(header, str) else header
	items = json.loads(items) if isinstance(items, str) else items
	
	doc = frappe.get_doc('Pick List', name)
	doc.check_permission('write')
	
	for k, v in header.items():
		doc.set(k, v)
		
	for item_data in items:
		item_doc = [d for d in doc.locations if d.name == item_data.get('name')]
		if item_doc:
			item = item_doc[0]
			item.qty = item_data.get('qty')
			item.custom_box = item_data.get('custom_box')
			item.custom_sample_quantity = item_data.get('custom_sample_quantity')
			
			batch_no = item_data.get('batch_no')
			if batch_no:
				item_code = item_data.get('item_code')
				if not frappe.db.exists("Batch", batch_no):
					new_batch = frappe.get_doc({
						"doctype": "Batch",
						"batch_id": batch_no,
						"item": item_code,
						"manufacturing_date": item_data.get('custom_mfg_date'),
						"expiry_date": item_data.get('custom_expiry_date')
					})
					new_batch.insert(ignore_permissions=True)
			
			item.batch_no = batch_no
			item.custom_mfg_date = item_data.get('custom_mfg_date')
			item.custom_expiry_date = item_data.get('custom_expiry_date')
			
	doc.save()
	return True
