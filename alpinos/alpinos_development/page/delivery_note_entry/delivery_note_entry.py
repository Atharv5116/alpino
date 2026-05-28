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

	dispatch_to_rows = []
	for row in (dn.get("custom_dispatch_to") or []):
		dispatch_to_rows.append({
			"name": row.name,
			"dispatch_to_address": row.get("dispatch_to_address") or "",
		})

	items = []
	for item in dn.items:
		items.append({
			"name": item.name,
			"item_code": item.item_code,
			"item_name": item.item_name,
			"qty": item.qty,
			"custom_box": item.get("custom_box") or 0,
			"batch_no": item.get("batch_no") or "",
			"custom_mfg_date": str(item.get("custom_mfg_date") or ""),
			"custom_expiry_date": str(item.get("custom_expiry_date") or ""),
			"against_pick_list": item.get("against_pick_list") or "",
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
		"custom_dispatch_to": dispatch_to_rows,
	}


_EDITABLE_HEADER_FIELDS = {
	"custom_lr_gr_no",
	"custom_dispatch_from",
	"vehicle_no",
	"custom_transporter_name",
}


def _apply_items_changes(dn, items):
	"""Apply qty edits and row removals from the page to dn.items."""
	if items is None:
		return

	items = json.loads(items) if isinstance(items, str) else items
	by_name = {row.name: row for row in dn.items}

	to_remove = []
	for entry in items:
		row_name = entry.get("name")
		if not row_name or row_name not in by_name:
			continue
		row = by_name[row_name]
		if entry.get("delete"):
			to_remove.append(row)
			continue
		if "qty" in entry and entry.get("qty") not in (None, ""):
			try:
				row.qty = float(entry["qty"])
			except (TypeError, ValueError):
				frappe.throw(f"Invalid quantity for row {row.idx}.")

	for row in to_remove:
		dn.remove(row)


def _apply_dispatch_to_changes(dn, dispatch_to):
	"""Replace the Dispatch To child rows with the provided list."""
	if dispatch_to is None:
		return
	dispatch_to = json.loads(dispatch_to) if isinstance(dispatch_to, str) else dispatch_to

	dn.set("custom_dispatch_to", [])
	for entry in dispatch_to:
		text = (entry or {}).get("dispatch_to_address")
		if isinstance(text, str):
			text = text.strip()
		if not text:
			continue
		dn.append("custom_dispatch_to", {"dispatch_to_address": text})


@frappe.whitelist()
def save_delivery_note_data(name, header, items=None, dispatch_to=None):
	"""Save editable header fields, item edits and Dispatch To rows on a Draft DN."""
	header = json.loads(header) if isinstance(header, str) else header

	dn = frappe.get_doc("Delivery Note", name)
	dn.check_permission("write")

	if dn.docstatus != 0:
		frappe.throw("Submitted Delivery Note cannot be edited.")

	for k, v in header.items():
		if k in _EDITABLE_HEADER_FIELDS:
			dn.set(k, v if v not in ("", None) else None)

	_apply_items_changes(dn, items)
	_apply_dispatch_to_changes(dn, dispatch_to)

	dn.flags.ignore_mandatory = True
	dn.save(ignore_permissions=True)
	frappe.db.commit()
	return True


@frappe.whitelist()
def submit_delivery_note(name, header=None, items=None, dispatch_to=None):
	"""Save then submit the Delivery Note."""
	if header is not None:
		save_delivery_note_data(name, header, items, dispatch_to)

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
