import frappe
import json
from frappe.utils import add_days


def _compute_expiry_from_shelf_life(item_code, mfg_date):
	if not item_code or not mfg_date:
		return None
	shelf = frappe.db.get_value("Item", item_code, "shelf_life_in_days")
	if not shelf or int(shelf) <= 0:
		return None
	return add_days(mfg_date, int(shelf))

@frappe.whitelist()
def get_pick_list_data(name):
	doc = frappe.get_doc('Pick List', name)
	doc.check_permission('read')

	from alpinos.sales_order_api import get_box_conversion_factor
	doc_dict = doc.as_dict()
	for row in doc_dict.get("locations", []):
		row["custom_conversion_factor"] = get_box_conversion_factor(row.get("item_code")) or 1
		item_info = (
			frappe.db.get_value(
				"Item",
				row.get("item_code"),
				["custom_sku_no", "custom_gross_weight", "shelf_life_in_days"],
				as_dict=True,
			)
			or {}
		)
		row["custom_sku_no"] = item_info.get("custom_sku_no") or ""
		if not row.get("custom_weight_per_box"):
			row["custom_weight_per_box"] = item_info.get("custom_gross_weight") or 0
		row["shelf_life_in_days"] = item_info.get("shelf_life_in_days") or 0

	# Surface any existing (non-cancelled) DN against this pick list so the UI
	# can hide the Create Delivery Note button.
	doc_dict["existing_delivery_note"] = frappe.db.get_value(
		"Delivery Note Item",
		{"against_pick_list": name, "docstatus": ["<", 2]},
		"parent",
	)

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
	
	# Step 1: Write header directly to the Pick List document in DB
	frappe.db.set_value('Pick List', name, {
		k: v for k, v in header.items()
	}, update_modified=False)
	
	# Step 2: Write all item row values directly to DB (bypass ORM/hooks re-calculation)
	for item_data in items:
		item_doc = [d for d in doc.locations if d.name == item_data.get('name')]
		if item_doc:
			item = item_doc[0]
			batch_no_val = item_data.get('custom_batch_code') or item_data.get('batch_no')
			qty_val = float(item_data.get('qty') or 0)
			mfg = item_data.get('custom_mfg_date') or None
			exp = item_data.get('custom_expiry_date') or None
			if mfg and not exp:
				exp = _compute_expiry_from_shelf_life(item.item_code, mfg)
			frappe.db.set_value('Pick List Item', item.name, {
				'qty': qty_val,
				'stock_qty': qty_val,
				'picked_qty': qty_val,
				'conversion_factor': 1,
				'custom_box': float(item_data.get('custom_box') or 0),
				'custom_sample_quantity': 0,
				'custom_batch_code': batch_no_val,
				'batch_no': None,
				'custom_mfg_date': mfg,
				'custom_expiry_date': exp,
				'custom_remark': item_data.get('custom_remark') or None
			}, update_modified=False)
	
	frappe.db.commit()
	
	# Step 3: Reload the doc so it has the freshly written DB values
	doc.reload()
	
	# Step 4: Submit (this will re-run validate hooks — but now doc has correct values from DB)
	doc.flags.ignore_mandatory = True
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
				"sales_order": so_name,
				"sales_order_item": mapped_row.get("name"), # Stable name from SO child row
				"item_code": mapped_row.get("item_code"),
				"custom_ordered_qty": mapped_row.get("custom_ordered_qty"),
				"qty": qty,
				"stock_qty": qty,
				"picked_qty": qty,
				"conversion_factor": 1,
				"warehouse": mapped_row.get("warehouse"),
				"custom_box": float(ui_item.get('custom_box') or 0),
				"custom_sample_quantity": 0,
				"custom_source_table": mapped_row.get("custom_source_table"),
				"has_batch_no": 0,
				"use_serial_batch_fields": 0,
				"custom_mfg_date": ui_item.get('custom_mfg_date') or None,
				"custom_expiry_date": ui_item.get('custom_expiry_date') or None,
				"batch_no": None,
				"custom_remark": ui_item.get('custom_remark') or None
			})
	
	pick_list.flags.ignore_mandatory = True
	pick_list.insert(ignore_permissions=True)
	
	# Force set all fields on the newly created items to ensure direct DB matches UI exactly
	for item in pick_list.locations:
		ui_item = next((i for i in items if i.get("name") == item.sales_order_item), None)
		if ui_item:
			batch_no_val = ui_item.get('custom_batch_code') or ui_item.get('batch_no')
			qty_val = float(ui_item.get('qty') or 0)
			mfg = ui_item.get('custom_mfg_date') or None
			exp = ui_item.get('custom_expiry_date') or None
			if mfg and not exp:
				exp = _compute_expiry_from_shelf_life(item.item_code, mfg)
			frappe.db.set_value('Pick List Item', item.name, {
				'qty': qty_val,
				'stock_qty': qty_val,
				'picked_qty': qty_val,
				'conversion_factor': 1,
				'custom_box': float(ui_item.get('custom_box') or 0),
				'custom_sample_quantity': 0,
				'custom_batch_code': batch_no_val,
				'batch_no': None,
				'custom_mfg_date': mfg,
				'custom_expiry_date': exp,
				'custom_remark': ui_item.get('custom_remark') or None
			}, update_modified=False)
			
	# Reload to fetch forced updates
	pick_list.reload()
	
	# Submit
	pick_list.submit()
	
	return pick_list.name
