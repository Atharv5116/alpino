"""
Post Delivery — API for the work-queue page.

Queue = created Delivery Notes whose Sales Order is post-delivery-applicable
(SO.custom_appointment_required) and whose Post Delivery entry isn't Completed yet.
"Start Post Delivery" gets-or-creates the Post Delivery doc for a DN, auto-filling
transport + GRN SKU rows from the Delivery Note.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt


@frappe.whitelist()
def get_post_delivery_queue(start=0, page_length=20, search=None, status=None, customer=None):
	"""Delivery Notes pending post-delivery (applicable + not yet Completed)."""
	if not frappe.has_permission("Post Delivery", "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	start = cint(start)
	page_length = min(max(cint(page_length) or 20, 1), 100)

	conds = ["dn.docstatus < 2", "IFNULL(so.custom_appointment_required, 0) = 1"]
	params = {}

	# Only rows whose post-delivery isn't finished.
	status = (status or "").strip()
	if status:
		conds.append("IFNULL(pd.post_delivery_status, 'Not Started') = %(status)s")
	else:
		conds.append("IFNULL(pd.post_delivery_status, 'Not Started') != 'Completed'")

	if customer:
		conds.append("dn.customer = %(customer)s")
		params["customer"] = customer
	search = (search or "").strip()
	if search:
		conds.append("(dn.name LIKE %(like)s OR dn.customer_name LIKE %(like)s OR dn.custom_sales_order_id LIKE %(like)s)")
		params["like"] = f"%{search}%"

	where = " AND ".join(conds)
	params.update({"start": start, "page_length": page_length + 1})

	rows = frappe.db.sql(
		f"""
		SELECT
			dn.name AS delivery_note,
			dn.custom_sales_order_id AS sales_order,
			dn.customer, dn.customer_name,
			dn.docstatus,
			dn.custom_dispatch_date AS dispatch_date,
			dn.custom_transporter_name AS transporter,
			dn.custom_lr_gr_no AS lr_awb_no,
			so.custom_channel AS channel,
			so.custom_grn_available AS grn_available,
			pd.name AS post_delivery,
			IFNULL(pd.post_delivery_status, 'Not Started') AS post_delivery_status,
			IFNULL(pd.asn_status, 'Pending') AS asn_status,
			IFNULL(pd.grn_status, 'Pending') AS grn_status,
			IFNULL(pd.appointment_status, 'Pending') AS appointment_status
		FROM `tabDelivery Note` dn
		INNER JOIN `tabSales Order` so ON so.name = dn.custom_sales_order_id
		LEFT JOIN `tabPost Delivery` pd ON pd.delivery_note = dn.name
		WHERE {where}
		ORDER BY dn.modified DESC
		LIMIT %(page_length)s OFFSET %(start)s
		""",
		params,
		as_dict=True,
	)

	has_more = len(rows) > page_length
	rows = rows[:page_length]
	return {"data": rows, "has_more": int(has_more), "start": start, "page_length": page_length}


@frappe.whitelist()
def start_post_delivery(delivery_note):
	"""Get-or-create the Post Delivery doc for a Delivery Note; return its name."""
	if not delivery_note:
		frappe.throw(_("Delivery Note is required."))

	existing = frappe.db.get_value("Post Delivery", {"delivery_note": delivery_note}, "name")
	if existing:
		return {"name": existing, "created": 0}

	dn = frappe.get_doc("Delivery Note", delivery_note)
	sales_order = dn.get("custom_sales_order_id")
	if not sales_order:
		frappe.throw(_("Delivery Note {0} has no linked Sales Order.").format(delivery_note))

	so = frappe.db.get_value(
		"Sales Order", sales_order,
		["custom_channel", "custom_appointment_required", "custom_grn_available"],
		as_dict=True,
	) or {}

	pd = frappe.new_doc("Post Delivery")
	pd.sales_order = sales_order
	pd.delivery_note = delivery_note
	pd.customer = dn.customer
	pd.channel = so.get("custom_channel") or ""
	pd.appointment_required = cint(so.get("custom_appointment_required"))
	pd.grn_available = cint(so.get("custom_grn_available"))
	# Transport (from DN)
	pd.transporter = dn.get("custom_transporter_name") or ""
	pd.lr_awb_no = dn.get("custom_lr_gr_no") or ""
	pd.dispatch_date = dn.get("custom_dispatch_date") or dn.get("posting_date")
	pd.dispatch_time = dn.get("posting_time")
	pd.dispatched_qty = flt(sum(flt(r.qty) for r in (dn.items or [])))
	# GRN SKU rows seeded from this DN's line items.
	for r in dn.items or []:
		pd.append("grn_items", {
			"item_code": r.item_code,
			"item_name": r.get("item_name") or "",
			"dispatched_qty": flt(r.qty),
		})
	pd.insert()
	frappe.db.commit()
	return {"name": pd.name, "created": 1}
