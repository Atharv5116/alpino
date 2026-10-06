"""Dispatch rules on the EXISTING Delivery Note (FRD Phase 11) + Dispatch Tracking (11.3).

Dispatch is the existing Delivery Note and its screens (delivery_note_entry / _list); this
module adds rules only, registered by Groundwork as Delivery Note "validate":

    VAL-DSP-02 / 11.4.1  a batch whose Batch.custom_fg_status is set and is not FG-Cleared
                         -> "Cannot dispatch unapproved stock."
    11.4.1               a batch-tracked FG item may not ship out of the FG Hold or Rejected
                         warehouse (Production Settings).

It returns at once when Batch has no custom_fg_status field (Filling not installed yet), for
returns, and for rows without a batch -- no other Delivery Note behaviour changes.

# default pending BA confirmation: a batch with a BLANK fg status (stock that existed before
# Final QC was introduced, or a batch not made by Filling) is not blocked, so existing
# dispatch keeps working; only FG-Hold / QC-Rejected (or any other non-cleared value) is.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

from alpinos.production import inventory_common as IC

DN = "Delivery Note"
DN_ITEM = "Delivery Note Item"


def _row_batches(row):
	batches = []
	if row.get("batch_no"):
		batches.append(row.batch_no)
	bundle = row.get("serial_and_batch_bundle")
	if bundle:
		try:
			batches.extend(b for b in frappe.get_all(
				"Serial and Batch Entry", filters={"parent": bundle}, pluck="batch_no") if b)
		except Exception:
			pass
	return list(dict.fromkeys(batches))


def validate_delivery_note(doc, method=None):
	if not IC.batch_fg_tracked():
		return
	if cint(doc.get("is_return")):
		return
	rows = [(r, _row_batches(r)) for r in (doc.get("items") or [])]
	rows = [(r, b) for r, b in rows if b]
	if not rows:
		return
	status = IC.fg_status_map([b for _r, bs in rows for b in bs])
	blocked_wh = {w for w in (IC.setting("fg_hold_warehouse"), IC.setting("rejected_warehouse")) if w}
	info = IC.item_meta([r.item_code for r, _b in rows])
	for row, batches in rows:
		for batch in batches:
			fg_status = (status.get(batch) or frappe._dict()).get("fg_status") or ""
			if fg_status and fg_status != IC.FG_CLEARED:
				frappe.throw(
					_("Row {0}: batch {1} of {2} is {3}. {4}").format(
						row.idx, batch, row.item_code, fg_status, _(IC.MSG_UNAPPROVED)),
					title=_("Unapproved Stock"))
		meta = info.get(row.item_code) or frappe._dict()
		if (row.get("warehouse") in blocked_wh and meta.get("has_batch_no")
				and meta.get("material_type") == "FG"):
			frappe.throw(
				_("Row {0}: {1} cannot be dispatched from {2} (FG Hold / Rejected stock). {3}").format(
					row.idx, row.item_code, row.warehouse, _(IC.MSG_UNAPPROVED)),
				title=_("Unapproved Stock"))


# ======================================================== Dispatch Tracking (11.3)

def _assert_read():
	IC.assert_roles(IC.DISPATCH_READ_ROLES, _("open Dispatch Tracking"))


@frappe.whitelist()
def get_dispatch_list(search=None, customer=None, status=None, date_from=None, date_to=None,
                      batch=None, item=None, start=0, page_length=50):
	"""Dispatch ID, Date, Customer, Vehicle No, Total Qty, Status. Uses frappe.get_list so
	the existing Delivery Note permission hooks (channel / assignment) still apply."""
	_assert_read()
	start = max(cint(start), 0)
	page_length = min(max(cint(page_length) or 50, 1), 500)
	meta = frappe.get_meta(DN)
	filters = {}
	if customer:
		filters["customer"] = customer
	if status:
		if status in ("Draft", "Submitted", "Cancelled"):
			filters["docstatus"] = {"Draft": 0, "Submitted": 1, "Cancelled": 2}[status]
		else:
			filters["status"] = status
	if date_from and date_to:
		filters["posting_date"] = ("between", [date_from, date_to])
	elif date_from:
		filters["posting_date"] = (">=", date_from)
	elif date_to:
		filters["posting_date"] = ("<=", date_to)
	if batch or item:
		item_filters = {"parenttype": DN}
		if item:
			item_filters["item_code"] = item
		parents = set()
		if batch:
			parents.update(frappe.get_all(DN_ITEM, filters=dict(item_filters, batch_no=batch),
			                              pluck="parent", distinct=True))
			if frappe.get_meta(DN_ITEM).has_field("custom_batch_code"):
				parents.update(frappe.get_all(DN_ITEM, filters=dict(item_filters, custom_batch_code=batch),
				                              pluck="parent", distinct=True))
		else:
			parents.update(frappe.get_all(DN_ITEM, filters=item_filters, pluck="parent", distinct=True))
		if not parents:
			return {"rows": [], "has_more": 0, "start": start, "page_length": page_length}
		filters["name"] = ("in", list(parents))
	fields = ["name", "posting_date", "customer", "customer_name", "total_qty", "status",
	          "docstatus"]
	for f in ("vehicle_no", "workflow_state", "custom_dispatch_date", "custom_lr_gr_no",
	          "custom_transporter_name"):
		if meta.has_field(f):
			fields.append(f)
	or_filters = None
	if search:
		or_filters = {"name": ("like", f"%{search}%"), "customer_name": ("like", f"%{search}%")}
		if meta.has_field("vehicle_no"):
			or_filters["vehicle_no"] = ("like", f"%{search}%")
	rows = frappe.get_list(DN, filters=filters, or_filters=or_filters, fields=fields,
	                       order_by="posting_date desc, name desc", start=start,
	                       page_length=page_length + 1)
	more = len(rows) > page_length
	return {"rows": rows[:page_length], "has_more": int(more), "start": start,
	        "page_length": page_length}


@frappe.whitelist()
def get_dispatch_detail(name):
	"""The exact batch codes on one dispatch (recall traceability)."""
	_assert_read()
	if not frappe.has_permission(DN, "read", name):
		frappe.throw(_("You do not have access to {0}.").format(name), frappe.PermissionError,
		             title=_("Not Permitted"))
	dn = frappe.get_doc(DN, name)
	out_rows = []
	all_batches = []
	for r in dn.items:
		batches = _row_batches(r)
		all_batches.extend(batches)
		out_rows.append({"idx": r.idx, "item_code": r.item_code, "item_name": r.item_name,
		                 "qty": flt(r.qty), "uom": r.uom, "warehouse": r.warehouse,
		                 "batches": batches, "batch_code": r.get("custom_batch_code") or "",
		                 "expiry_date": r.get("custom_expiry_date")})
	status = IC.fg_status_map(all_batches)
	for row in out_rows:
		row["batch_info"] = [{"batch_no": b, "fg_status": (status.get(b) or {}).get("fg_status") or "",
		                      "sub_order": (status.get(b) or {}).get("sub_order") or "",
		                      "parent": (status.get(b) or {}).get("parent") or "",
		                      "mfg_date": (status.get(b) or {}).get("mfg"),
		                      "expiry_date": (status.get(b) or {}).get("expiry")}
		                     for b in row["batches"]]
	return {"name": dn.name, "posting_date": dn.posting_date, "customer": dn.customer,
	        "customer_name": dn.customer_name, "vehicle_no": dn.get("vehicle_no") or "",
	        "status": dn.status, "docstatus": dn.docstatus, "total_qty": dn.total_qty,
	        "transporter": dn.get("custom_transporter_name") or "",
	        "lr_no": dn.get("custom_lr_gr_no") or "", "items": out_rows}
