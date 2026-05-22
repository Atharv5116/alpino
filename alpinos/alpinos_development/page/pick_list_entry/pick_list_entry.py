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
def get_active_users():
	return frappe.get_all("User", filters={"enabled": 1, "user_type": "System User"}, pluck="name")

def create_custom_batch_field():
	if not frappe.db.exists("Custom Field", "Pick List Item-custom_batch_code"):
		frappe.get_doc({
			"doctype": "Custom Field",
			"dt": "Pick List Item",
			"fieldname": "custom_batch_code",
			"fieldtype": "Data",
			"label": "Custom Batch Code",
			"insert_after": "batch_no"
		}).insert()
		frappe.db.commit()

def create_stock_entry_field():
	if not frappe.db.exists("Custom Field", "Stock Entry-custom_customer_type"):
		frappe.get_doc({
			"doctype": "Custom Field",
			"dt": "Stock Entry",
			"fieldname": "custom_customer_type",
			"fieldtype": "Link",
			"label": "Customer Type",
			"options": "Offline Buyer Customer Type",
			"insert_after": "company"
		}).insert()
		frappe.db.commit()

@frappe.whitelist()
def get_batch_details(batch_no, item_code):
	batch = frappe.db.get_value("Batch", {"name": batch_no}, ["manufacturing_date", "expiry_date"], as_dict=1)
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
			item.qty = float(item_data.get('qty') or 0)
			item.custom_box = float(item_data.get('custom_box') or 0)
			item.custom_sample_quantity = float(item_data.get('custom_sample_quantity') or 0)
			
			batch_no_val = item_data.get('custom_batch_code') or item_data.get('batch_no')
			item.custom_batch_code = batch_no_val
			item.batch_no = None
			
			# Forcefully disable batch validations for this Pick List Item
			item.has_batch_no = 0
			item.use_serial_batch_fields = 0
			
			item.custom_mfg_date = item_data.get('custom_mfg_date')
			item.custom_expiry_date = item_data.get('custom_expiry_date')
			
	doc.flags.ignore_mandatory = True
	doc.save()
	return True


@frappe.whitelist()
def get_pick_list_entry_list(
	start=0,
	page_length=20,
	search="",
	status="",
	company=""
):
	start = frappe.utils.cint(start)
	page_length = frappe.utils.cint(page_length)
	
	filters = {}
	if status:
		filters["status"] = status
	if company:
		filters["company"] = company
		
	or_filters = []
	if search:
		or_filters = [
			["name", "like", f"%{search}%"],
			["custom_customer_name", "like", f"%{search}%"]
		]
		
	data = frappe.get_all(
		"Pick List",
		filters=filters,
		or_filters=or_filters,
		fields=["name", "custom_customer_name", "custom_order_date", "company", "status"],
		order_by="creation desc",
		limit_start=start,
		limit_page_length=page_length + 1
	)
	
	has_more = len(data) > page_length
	if has_more:
		data = data[:page_length]
		
	return {
		"data": data,
		"has_more": has_more,
		"start": start,
		"page_length": page_length
	}
