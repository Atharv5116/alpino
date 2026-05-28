import json

import frappe
from frappe.utils import cint, formatdate


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
		"docstatus": dn.docstatus,
		"posting_date": formatdate(str(dn.posting_date)) if dn.posting_date else "",
		"custom_sales_order_id": dn.get("custom_sales_order_id") or "",
		"pick_list_name": pick_list_name,
		"custom_lr_gr_no": dn.get("custom_lr_gr_no") or "",
		"custom_dispatch_from": dn.get("custom_dispatch_from") or "",
		"custom_dn_so_customer_name": dn.get("custom_dn_so_customer_name") or "",
		"custom_transporter_name": dn.get("custom_transporter_name") or "",
		"vehicle_no": dn.get("vehicle_no") or "",
		"custom_dispatch_date": dispatch_date,
		"custom_total_boxes": dn.get("custom_total_boxes") or 0,
		"custom_dn_order_gross_weight": dn.get("custom_dn_order_gross_weight") or 0,
		"custom_total_units_dn": dn.get("custom_total_units_dn") or 0,
		"items": items,
	}


_EDITABLE_HEADER_FIELDS = {
	"custom_lr_gr_no",
	"custom_dispatch_from",
	"vehicle_no",
	"custom_transporter_name",
}


@frappe.whitelist()
def save_delivery_note_data(name, header):
	"""Save editable header fields on a Draft Delivery Note."""
	header = json.loads(header) if isinstance(header, str) else header

	dn = frappe.get_doc("Delivery Note", name)
	dn.check_permission("write")

	if dn.docstatus != 0:
		frappe.throw("Submitted Delivery Note cannot be edited.")

	for k, v in header.items():
		if k in _EDITABLE_HEADER_FIELDS:
			dn.set(k, v if v not in ("", None) else None)

	dn.flags.ignore_mandatory = True
	dn.save(ignore_permissions=True)
	frappe.db.commit()
	return True


@frappe.whitelist()
def submit_delivery_note(name, header=None):
	"""Save then submit the Delivery Note."""
	if header is not None:
		save_delivery_note_data(name, header)

	dn = frappe.get_doc("Delivery Note", name)
	dn.check_permission("submit")
	if dn.docstatus == 0:
		dn.submit()
		frappe.db.commit()
	return dn.name


@frappe.whitelist()
def get_delivery_note_list(
	start=0,
	page_length=20,
	search="",
	status="",
	company="",
):
	start = cint(start)
	page_length = cint(page_length)

	filters = {}
	if status:
		filters["status"] = status
	if company:
		filters["company"] = company

	or_filters = []
	if search:
		or_filters = [
			["name", "like", f"%{search}%"],
			["custom_dn_so_customer_name", "like", f"%{search}%"],
			["customer_name", "like", f"%{search}%"],
		]

	rows = frappe.get_all(
		"Delivery Note",
		filters=filters,
		or_filters=or_filters,
		fields=[
			"name",
			"customer_name",
			"custom_dn_so_customer_name",
			"posting_date",
			"custom_dispatch_date",
			"company",
			"status",
			"docstatus",
		],
		order_by="creation desc",
		limit_start=start,
		limit_page_length=page_length + 1,
	)

	has_more = len(rows) > page_length
	if has_more:
		rows = rows[:page_length]

	for r in rows:
		if r.get("custom_dispatch_date"):
			try:
				r["custom_dispatch_date"] = formatdate(str(r["custom_dispatch_date"])[:10])
			except Exception:
				pass
		if r.get("posting_date"):
			try:
				r["posting_date"] = formatdate(str(r["posting_date"]))
			except Exception:
				pass

	return {
		"data": rows,
		"has_more": has_more,
		"start": start,
		"page_length": page_length,
	}
