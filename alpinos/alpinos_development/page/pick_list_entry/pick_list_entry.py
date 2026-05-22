import frappe
import json

@frappe.whitelist()
def get_pick_list_data(name):
	doc = frappe.get_doc('Pick List', name)
	doc.check_permission('read')
	
	from alpinos.sales_order_api import get_box_conversion_factor
	doc_dict = doc.as_dict()
	for row in doc_dict.get("locations", []):
		row["custom_conversion_factor"] = get_box_conversion_factor(row.get("item_code")) or 1
		
	return doc_dict

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
			
			item.custom_mfg_date = item_data.get('custom_mfg_date') or None
			item.custom_expiry_date = item_data.get('custom_expiry_date') or None
			
	doc.flags.ignore_mandatory = True
	doc.save(ignore_permissions=True)
	
	# Force update the database directly to bypass any read-only or dirty tracking issues
	for item_data in items:
		item_doc = [d for d in doc.locations if d.name == item_data.get('name')]
		if item_doc:
			item = item_doc[0]
			batch_no_val = item_data.get('custom_batch_code') or item_data.get('batch_no')
			frappe.db.set_value('Pick List Item', item.name, {
				'qty': float(item_data.get('qty') or 0),
				'custom_box': float(item_data.get('custom_box') or 0),
				'custom_sample_quantity': float(item_data.get('custom_sample_quantity') or 0),
				'custom_batch_code': batch_no_val,
				'batch_no': None,
				'custom_mfg_date': item_data.get('custom_mfg_date') or None,
				'custom_expiry_date': item_data.get('custom_expiry_date') or None
			}, update_modified=False)
			
	# Reload to fetch forced updates
	doc.reload()
	
	# Submit
	doc.submit()
	
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

@frappe.whitelist()
def create_and_submit_pick_list(so_name, header, items):
	header = json.loads(header) if isinstance(header, str) else header
	items = json.loads(items) if isinstance(items, str) else items
	
	# Fetch original mapping data to reconstruct the locations
	from alpinos.sales_order_api import get_pick_list_mapping_data
	mapping_data = get_pick_list_mapping_data(so_name)
	
	pick_list = frappe.new_doc("Pick List")
	pick_list.company = mapping_data.company
	pick_list.purpose = mapping_data.purpose
	pick_list.custom_sales_order_id = mapping_data.custom_sales_order_id
	pick_list.custom_customer_name = mapping_data.custom_customer_name
	pick_list.custom_party_code = mapping_data.custom_party_code
	pick_list.custom_order_date = mapping_data.custom_order_date
	pick_list.custom_po_no = mapping_data.custom_po_no
	pick_list.pick_manually = 1
	
	for k, v in header.items():
		pick_list.set(k, v)
		
	# Match mapping rows with UI submitted items
	for mapped_row in mapping_data.locations:
		ui_item = next((i for i in items if i.get("name") == mapped_row.get("name")), None)
		if ui_item:
			qty = float(ui_item.get('qty') or 0)
			pick_list.append("locations", {
				"item_code": mapped_row.get("item_code"),
				"custom_ordered_qty": mapped_row.get("custom_ordered_qty"),
				"qty": qty,
				"custom_box": float(ui_item.get('custom_box') or 0),
				"custom_sample_quantity": float(ui_item.get('custom_sample_quantity') or 0),
				"custom_source_table": mapped_row.get("custom_source_table"),
				"has_batch_no": 0,
				"use_serial_batch_fields": 0,
				"custom_mfg_date": ui_item.get('custom_mfg_date') or None,
				"custom_expiry_date": ui_item.get('custom_expiry_date') or None,
				"batch_no": None
			})
	
	pick_list.flags.ignore_mandatory = True
	pick_list.insert(ignore_permissions=True)
	
	# Force set all fields on the newly created items to ensure direct DB matches UI exactly
	for item in pick_list.locations:
		ui_item = next((i for i in items if i.get("item_code") == item.item_code and i.get("custom_source_table") == item.custom_source_table), None)
		if ui_item:
			batch_no_val = ui_item.get('custom_batch_code') or ui_item.get('batch_no')
			frappe.db.set_value('Pick List Item', item.name, {
				'qty': float(ui_item.get('qty') or 0),
				'custom_box': float(ui_item.get('custom_box') or 0),
				'custom_sample_quantity': float(ui_item.get('custom_sample_quantity') or 0),
				'custom_batch_code': batch_no_val,
				'batch_no': None,
				'custom_mfg_date': ui_item.get('custom_mfg_date') or None,
				'custom_expiry_date': ui_item.get('custom_expiry_date') or None
			}, update_modified=False)
			
	# Reload to fetch forced updates
	pick_list.reload()
	
	# Submit
	pick_list.submit()
	
	return pick_list.name
