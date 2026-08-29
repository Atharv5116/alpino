import json

import frappe
from frappe.utils import cint, formatdate


@frappe.whitelist()
def get_delivery_note_data(name):
	"""Return Delivery Note header + items for the custom page."""
	dn = frappe.get_doc("Delivery Note", name)
	dn.check_permission("read")

	# Pick List name from the first item that carries one
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
			"custom_batch_code": item.get("custom_batch_code") or "",
			"custom_remark": item.get("custom_remark") or "",
			"custom_mfg_date": str(item.get("custom_mfg_date") or ""),
			"custom_expiry_date": str(item.get("custom_expiry_date") or ""),
			"against_pick_list": item.get("against_pick_list") or "",
		})

	return {
		"name": dn.name,
		"docstatus": dn.docstatus,
		"owner": dn.owner,
		"owner_full_name": frappe.utils.get_fullname(dn.owner),
		"posting_date": formatdate(str(dn.posting_date)) if dn.posting_date else "",
		"custom_sales_order_id": dn.get("custom_sales_order_id") or "",
		# Invoice No is set on the Sales Order; show its live value.
		"custom_invoice_no": (
			frappe.db.get_value("Sales Order", dn.get("custom_sales_order_id"), "custom_invoice_no")
			if dn.get("custom_sales_order_id") else ""
		) or "",
		"pick_list_name": pick_list_name,
		"custom_lr_gr_no": dn.get("custom_lr_gr_no") or "",
		"custom_dispatch_from": dn.get("custom_dispatch_from") or "",
		"custom_dn_so_customer_name": dn.get("custom_dn_so_customer_name") or "",
		"custom_transporter_name": dn.get("custom_transporter_name") or "",
		"vehicle_no": dn.get("vehicle_no") or "",
		"custom_dispatch_date": dispatch_date,
		"custom_assigned_to": dn.get("custom_assigned_to") or "",
		"custom_total_boxes": dn.get("custom_total_boxes") or 0,
		"custom_dn_order_gross_weight": dn.get("custom_dn_order_gross_weight") or 0,
		"custom_total_units_dn": dn.get("custom_total_units_dn") or 0,
		"items": items,
		"custom_dispatch_to": dispatch_to_rows,
	}


_EDITABLE_HEADER_FIELDS = {
	"custom_lr_gr_no",
	"custom_dispatch_from",
	"custom_assigned_to",
	# Transporter is seeded from the Pick List but editable in Draft; a change here
	# propagates back to the Pick List (delivery_note_on_update_draft).
	"custom_transporter_name",
	# vehicle_no is synced from the Pick List and read-only, so it's left out here.
}


_DN_QTY_EDIT_ROLES = {"Warehouse Admin", "Warehouse Manager", "System Manager", "PL Manager"}


def _can_edit_dn_qty():
	"""Only authorized roles may change DN item quantities; others re-post it unchanged."""
	return bool(set(frappe.get_roles()) & _DN_QTY_EDIT_ROLES)


def _apply_items_changes(dn, items):
	"""Apply qty edits and row removals from the page to dn.items."""
	if items is None:
		return

	items = json.loads(items) if isinstance(items, str) else items
	by_name = {row.name: row for row in dn.items}
	can_edit_qty = _can_edit_dn_qty()

	to_remove = []
	for entry in items:
		row_name = entry.get("name")
		if not row_name or row_name not in by_name:
			continue
		row = by_name[row_name]
		if entry.get("delete"):
			to_remove.append(row)
			continue
		# Qty edits from users without the role are ignored.
		if can_edit_qty and "qty" in entry and entry.get("qty") not in (None, ""):
			try:
				row.qty = float(entry["qty"])
			except (TypeError, ValueError):
				frappe.throw(f"Invalid quantity for row {row.idx}.")
		if "custom_remark" in entry and entry.get("custom_remark") is not None:
			row.custom_remark = (entry.get("custom_remark") or "").strip() or None

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


def _backfill_item_dates_from_pick_list(dn):
	"""Fill MFG/Expiry/Box/Batch on DN items from the DN row, else the Pick List Item, else the Batch master.

	Those DN date fields are reqd + read-only, so without this a DN can't submit
	when the Pick List left dates blank or predates them being copied.
	"""
	pl_row_names = [it.get("pick_list_item") for it in dn.items if it.get("pick_list_item")]
	pl_data = {}
	if pl_row_names:
		for r in frappe.get_all(
			"Pick List Item",
			filters={"name": ["in", pl_row_names]},
			fields=["name", "custom_mfg_date", "custom_expiry_date", "custom_box", "custom_batch_code"],
		):
			pl_data[r["name"]] = r

	changed = False

	def _fill(item, attr, value):
		nonlocal changed
		if value and not item.get(attr):
			item.set(attr, value)
			changed = True

	from alpinos.pick_list_api import _ensure_batch_exists

	for item in dn.items:
		pl = pl_data.get(item.get("pick_list_item")) or {}

		# Batch first: the free-text code lands in custom_batch_code; batch_no (a
		# Link to Batch) is set only when a real Batch exists, since a bare string
		# there fails DN submit.
		_fill(item, "custom_batch_code", pl.get("custom_batch_code"))
		if not item.get("batch_no") and item.get("custom_batch_code"):
			bn = _ensure_batch_exists(
				item.get("item_code"),
				item.custom_batch_code,
				pl.get("custom_mfg_date"),
				pl.get("custom_expiry_date"),
			)
			_fill(item, "batch_no", bn)
		_fill(item, "custom_box", pl.get("custom_box"))
		_fill(item, "custom_mfg_date", pl.get("custom_mfg_date"))
		_fill(item, "custom_expiry_date", pl.get("custom_expiry_date"))

		# Final fallback: read manufacturing / expiry from the Batch master.
		if item.get("batch_no") and (
			not item.get("custom_mfg_date") or not item.get("custom_expiry_date")
		):
			b = frappe.db.get_value(
				"Batch",
				item.batch_no,
				["manufacturing_date", "expiry_date"],
				as_dict=True,
			) or {}
			_fill(item, "custom_mfg_date", b.get("manufacturing_date"))
			_fill(item, "custom_expiry_date", b.get("expiry_date"))

	return changed


@frappe.whitelist()
def submit_delivery_note(name, header=None, items=None, dispatch_to=None):
	"""Save then submit the Delivery Note."""
	if header is not None:
		save_delivery_note_data(name, header, items, dispatch_to)

	dn = frappe.get_doc("Delivery Note", name)
	dn.check_permission("submit")
	if dn.docstatus == 0:
		if _backfill_item_dates_from_pick_list(dn):
			dn.flags.ignore_mandatory = True
			dn.save(ignore_permissions=True)
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
	sales_order="",
):
	if not frappe.has_permission("Delivery Note", "read"):
		frappe.throw(frappe._("You are not permitted to view Delivery Notes."), frappe.PermissionError)
	start = cint(start)
	page_length = cint(page_length)

	filters = {}
	if status:
		filters["status"] = status
	if company:
		filters["company"] = company
	if sales_order:
		filters["custom_sales_order_id"] = sales_order

	# A dedicated DN User only sees DNs assigned to them; admins/managers see all.
	_roles = set(frappe.get_roles())
	_override = {"System Manager", "Administrator", "Warehouse Admin", "Warehouse Manager", "PL Manager"}
	if "DN User" in _roles and not (_roles & _override):
		filters["custom_assigned_to"] = frappe.session.user

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
			"custom_sales_order_id",
			"custom_transporter_name",
			"custom_lr_gr_no",
			"custom_invoice_no",
			"custom_assigned_to",
			"custom_total_boxes",
		],
		order_by="creation desc",
		limit_start=start,
		limit_page_length=page_length + 1,
	)

	has_more = len(rows) > page_length
	if has_more:
		rows = rows[:page_length]

	# Invoice No lives on the Sales Order (set after the DN is made); the DN's own
	# copy is usually empty, so show the SO's live value.
	so_ids = list({r.custom_sales_order_id for r in rows if r.get("custom_sales_order_id")})
	inv_by_so = {}
	if so_ids:
		for so in frappe.get_all(
			"Sales Order", filters={"name": ["in", so_ids]}, fields=["name", "custom_invoice_no"]
		):
			inv_by_so[so.name] = so.custom_invoice_no or ""

	for r in rows:
		r["custom_invoice_no"] = inv_by_so.get(r.get("custom_sales_order_id"), "")
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


# Bulk LR No. update (Warehouse Admin / Manager)
_LR_BULK_ROLES = {"Warehouse Admin", "Warehouse Manager", "System Manager"}


def _require_lr_roles():
	if not (set(frappe.get_roles()) & _LR_BULK_ROLES):
		frappe.throw(frappe._("Only Warehouse Admin / Manager can bulk-update LR No."))


def _so_po_invoice(so_id):
	"""(Customer PO, Invoice No) for a Sales Order — PO prefers the e-com PO number."""
	if not so_id:
		return "", ""
	r = frappe.db.get_value(
		"Sales Order", so_id, ["po_no", "custom_po_number", "custom_invoice_no"], as_dict=True
	) or {}
	return (r.get("custom_po_number") or r.get("po_no") or ""), (r.get("custom_invoice_no") or "")


@frappe.whitelist()
def download_lr_excel():
	"""Excel of DRAFT Delivery Notes dispatching TODAY, for bulk LR No. entry. Exactly four
	columns: Sales Order ID, Customer PO / PO Number, Invoice No., LR No. (blank for input)."""
	_require_lr_roles()
	from frappe.utils.xlsxutils import make_xlsx

	today = frappe.utils.today()
	# custom_dispatch_date is a Datetime, so match a full-day range, not "= today".
	dns = frappe.get_all(
		"Delivery Note",
		filters={
			"docstatus": 0,
			"custom_dispatch_date": ["between", [f"{today} 00:00:00", f"{today} 23:59:59"]],
		},
		fields=["name", "custom_sales_order_id"],
		order_by="name",
	)
	rows = [["Sales Order ID", "Customer PO / PO Number", "Invoice No.", "LR No."]]
	for dn in dns:
		po, inv = _so_po_invoice(dn.get("custom_sales_order_id"))
		rows.append([dn.get("custom_sales_order_id") or "", po, inv, ""])

	xlsx = make_xlsx(rows, "LR Update")
	frappe.response["filename"] = f"LR_Update_{today}.xlsx"
	frappe.response["filecontent"] = xlsx.getvalue()
	frappe.response["type"] = "binary"


@frappe.whitelist()
def upload_lr_excel(file_url):
	"""Read a filled LR Excel, set LR No. on the matching draft DN by Sales Order ID, then submit it. Returns a summary and per-row failures."""
	_require_lr_roles()
	import io

	try:
		import openpyxl
	except Exception:
		frappe.throw(frappe._("openpyxl is required to read the uploaded Excel."))

	from frappe.utils.file_manager import get_file

	content = get_file(file_url)[1]
	wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
	ws = wb.active

	updated, failed = 0, []
	for idx, r in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
		so_id = (str(r[0]).strip() if r and len(r) > 0 and r[0] not in (None, "") else "")
		lr = (str(r[3]).strip() if r and len(r) > 3 and r[3] not in (None, "") else "")
		if not so_id:
			continue
		if not lr:
			failed.append({"row": idx, "sales_order": so_id, "reason": "LR No. is blank"})
			continue
		dns = frappe.get_all(
			"Delivery Note", filters={"docstatus": 0, "custom_sales_order_id": so_id}, pluck="name"
		)
		if not dns:
			failed.append({"row": idx, "sales_order": so_id, "reason": "No draft Delivery Note found"})
			continue
		if len(dns) > 1:
			failed.append({"row": idx, "sales_order": so_id, "reason": "Multiple draft Delivery Notes — update individually"})
			continue
		try:
			dn = frappe.get_doc("Delivery Note", dns[0])
			dn.custom_lr_gr_no = lr
			dn.flags.ignore_permissions = True
			dn.submit()  # runs validate (LR mandatory now satisfied) + on_submit
			frappe.db.commit()
			updated += 1
		except Exception as e:
			frappe.db.rollback()
			failed.append({"row": idx, "sales_order": so_id, "reason": str(e)[:200]})

	return {
		"updated": updated,
		"failed": failed,
		"message": frappe._("{0} Delivery Notes updated and submitted successfully. {1} rows failed.").format(
			updated, len(failed)
		),
	}
