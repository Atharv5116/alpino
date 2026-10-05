"""Post Dispatch API for the work-queue page.

Queue = created Delivery Notes on a post-delivery-applicable Sales Order whose Post
Dispatch entry isn't Completed yet. Start Post Dispatch gets-or-creates the doc for a
DN, auto-filling transport and GRN SKU rows from the Delivery Note.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

# The customer's own PO number: the e-com / modern-trade field first, then the standard
# ERPNext one the offline orders carry.
_CUSTOMER_PO = "COALESCE(NULLIF(so.custom_po_number, ''), so.po_no)"


@frappe.whitelist()
def get_post_delivery_queue(
	start=0,
	page_length=20,
	search=None,
	status=None,
	customer=None,
	sales_order=None,
	customer_po=None,
	invoice_no=None,
	lr_no=None,
	dispatch_from=None,
	dispatch_to=None,
	channel=None,
):
	"""Delivery Notes pending post-delivery (applicable + not yet Completed)."""
	if not frappe.has_permission("Post Dispatch", "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	start = cint(start)
	page_length = min(max(cint(page_length) or 20, 1), 100)

	conds = ["dn.docstatus < 2", "IFNULL(so.custom_appointment_required, 0) = 1"]
	params = {}

	# Only rows whose post-delivery isn't finished.
	status = (status or "").strip()
	if status:
		conds.append("IFNULL(pd.post_delivery_status, 'Not Started') = %(status)s")
		# The value has to be bound too: without this the filter raised KeyError: status
		# and the Status dropdown on the page did nothing but fail (Changes(HP) #48).
		params["status"] = status
	else:
		conds.append("IFNULL(pd.post_delivery_status, 'Not Started') != 'Completed'")

	if customer:
		conds.append("dn.customer = %(customer)s")
		params["customer"] = customer
	# Changes(HP) #48: one box per field, beside the free-text search.
	sales_order = (sales_order or "").strip()
	if sales_order:
		conds.append("dn.custom_sales_order_id LIKE %(sales_order)s")
		params["sales_order"] = f"%{sales_order}%"
	customer_po = (customer_po or "").strip()
	if customer_po:
		conds.append(f"{_CUSTOMER_PO} LIKE %(customer_po)s")
		params["customer_po"] = f"%{customer_po}%"
	invoice_no = (invoice_no or "").strip()
	if invoice_no:
		conds.append("so.custom_invoice_no LIKE %(invoice_no)s")
		params["invoice_no"] = f"%{invoice_no}%"
	# Changes(HP) #61: the LR / GR number was already fetched for the row but could not be
	# searched on, which is the one number a transporter query actually starts from.
	lr_no = (lr_no or "").strip()
	if lr_no:
		conds.append("dn.custom_lr_gr_no LIKE %(lr_no)s")
		params["lr_no"] = f"%{lr_no}%"
	channel = (channel or "").strip()
	if channel:
		conds.append("so.custom_channel = %(channel)s")
		params["channel"] = channel
	# Dispatch Date is a Datetime on the note, so "to" covers the whole day.
	if dispatch_from:
		conds.append("dn.custom_dispatch_date >= %(dispatch_from)s")
		params["dispatch_from"] = f"{getdate(dispatch_from)} 00:00:00"
	if dispatch_to:
		conds.append("dn.custom_dispatch_date <= %(dispatch_to)s")
		params["dispatch_to"] = f"{getdate(dispatch_to)} 23:59:59"

	search = (search or "").strip()
	if search:
		conds.append(
			"(dn.name LIKE %(like)s OR dn.customer_name LIKE %(like)s"
			" OR dn.custom_sales_order_id LIKE %(like)s OR dn.custom_lr_gr_no LIKE %(like)s)"
		)
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
			so.custom_invoice_no AS invoice_no,
			{_CUSTOMER_PO} AS customer_po_no,
			so.custom_invoice_pdf AS invoice_pdf,
			pd.name AS post_delivery,
			IFNULL(pd.post_delivery_status, 'Not Started') AS post_delivery_status,
			IFNULL(pd.asn_status, 'Pending') AS asn_status,
			IFNULL(pd.grn_status, 'Pending') AS grn_status,
			IFNULL(pd.appointment_status, 'Pending') AS appointment_status
		FROM `tabDelivery Note` dn
		INNER JOIN `tabSales Order` so ON so.name = dn.custom_sales_order_id
		LEFT JOIN `tabPost Dispatch` pd ON pd.delivery_note = dn.name
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
	"""Get-or-create the Post Dispatch doc for a Delivery Note; return its name."""
	if not delivery_note:
		frappe.throw(_("Delivery Note is required."))

	existing = frappe.db.get_value("Post Dispatch", {"delivery_note": delivery_note}, "name")
	if existing:
		return {"name": existing, "created": 0}

	dn = frappe.get_doc("Delivery Note", delivery_note)
	sales_order = dn.get("custom_sales_order_id")
	if not sales_order:
		frappe.throw(_("Delivery Note {0} has no linked Sales Order.").format(delivery_note))

	so = frappe.db.get_value(
		"Sales Order", sales_order,
		[
			"custom_channel", "custom_appointment_required", "custom_grn_available",
			"po_no", "custom_po_number", "custom_invoice_no",
		],
		as_dict=True,
	) or {}

	pd = frappe.new_doc("Post Dispatch")
	pd.sales_order = sales_order
	pd.delivery_note = delivery_note
	pd.customer = dn.customer
	pd.channel = so.get("custom_channel") or ""
	# #29: Customer PO No (offline po_no / e-com custom_po_number), Invoice No from the
	# SO, and Total Invoice Value = this DN's grand total (with GST).
	# The e-com / modern-trade field wins over the standard one, the same order the queue's
	# Customer's Purchase No. column and its filter read them in (Changes(HP) #48).
	pd.customer_po_no = (so.get("custom_po_number") or so.get("po_no") or "")
	pd.invoice_no = (so.get("custom_invoice_no") or "")
	pd.total_invoice_value = flt(dn.get("grand_total") or dn.get("base_grand_total"))
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
