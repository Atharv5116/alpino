import frappe
from frappe.utils import formatdate


@frappe.whitelist()
def get_delivery_note_data(name):
	"""Return Delivery Note header + items for the custom page."""
	dn = frappe.get_doc("Delivery Note", name)
	dn.check_permission("read")

	# Get Pick List name from the first item that has one
	pick_list_name = ""
	for item in dn.items:
		if item.get("against_pick_list"):
			pick_list_name = item.against_pick_list
			break

	dispatch_date = ""
	if dn.custom_dispatch_date:
		try:
			dispatch_date = formatdate(str(dn.custom_dispatch_date)[:10])
		except Exception:
			dispatch_date = str(dn.custom_dispatch_date)

	items = []
	for item in dn.items:
		items.append({
			"item_code": item.item_code,
			"item_name": item.item_name,
			"qty": item.qty,
			"custom_box": item.get("custom_box") or 0,
			"batch_no": item.get("batch_no") or "",
			"custom_mfg_date": str(item.get("custom_mfg_date") or ""),
			"custom_expiry_date": str(item.get("custom_expiry_date") or ""),
		})

	return {
		"name": dn.name,
		"posting_date": formatdate(str(dn.posting_date)) if dn.posting_date else "",
		"custom_sales_order_id": dn.get("custom_sales_order_id") or "",
		"pick_list_name": pick_list_name,
		"custom_lr_gr_no": dn.get("custom_lr_gr_no") or "",
		"custom_dn_so_customer_name": dn.get("custom_dn_so_customer_name") or "",
		"custom_transporter_name": dn.get("custom_transporter_name") or "",
		"vehicle_no": dn.get("vehicle_no") or "",
		"custom_dispatch_date": dispatch_date,
		"custom_total_boxes": dn.get("custom_total_boxes") or 0,
		"custom_dn_order_gross_weight": dn.get("custom_dn_order_gross_weight") or 0,
		"custom_total_units_dn": dn.get("custom_total_units_dn") or 0,
		"items": items,
	}
