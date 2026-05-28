import json

import frappe


@frappe.whitelist()
def get_delivery_note_data(name):
	doc = frappe.get_doc("Delivery Note", name)
	doc.check_permission("read")

	d = doc.as_dict()

	# Surface SO No. and Pick List No. from the item rows so the page can
	# show them as header-level read-only fields.
	sales_orders = sorted({i.against_sales_order for i in doc.items if i.against_sales_order})
	pick_lists = sorted({i.against_pick_list for i in doc.items if i.against_pick_list})
	d["sales_order_no"] = ", ".join(sales_orders)
	d["pick_list_no"] = ", ".join(pick_lists)

	return d


@frappe.whitelist()
def save_delivery_note_data(name, header, items):
	header = json.loads(header) if isinstance(header, str) else header
	items = json.loads(items) if isinstance(items, str) else items

	doc = frappe.get_doc("Delivery Note", name)
	doc.check_permission("write")

	if doc.docstatus != 0:
		frappe.throw("Submitted Delivery Note cannot be edited.")

	# Only logistics fields are editable from this page; everything else stays
	# as set by create_delivery_note_from_pick_list.
	header_fields = {
		"lr_no",
		"lr_date",
		"vehicle_no",
		"driver_name",
		"transporter",
	}
	for k, v in header.items():
		if k in header_fields:
			doc.set(k, v or None)

	doc.flags.ignore_mandatory = True
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return True


@frappe.whitelist()
def submit_delivery_note(name, header=None, items=None):
	if header is not None or items is not None:
		save_delivery_note_data(name, header or "{}", items or "[]")

	doc = frappe.get_doc("Delivery Note", name)
	doc.check_permission("submit")
	if doc.docstatus == 0:
		doc.submit()
		frappe.db.commit()
	return doc.name
