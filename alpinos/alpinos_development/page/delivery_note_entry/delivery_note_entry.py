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
	# vehicle_no (Picklist PO No.) and custom_transporter_name are now
	# synced from Pick List during DN creation and rendered read-only on
	# the entry page — intentionally omitted from this set so the page
	# cannot overwrite them.
}


_DN_QTY_EDIT_ROLES = {"Warehouse Admin", "Warehouse Manager", "System Manager", "PL Manager"}


def _can_edit_dn_qty():
	"""Only authorized roles may change Delivery Note item quantities; everyone
	else re-posts the (read-only) qty unchanged."""
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
		# Qty is read-only unless the user holds an authorized role. Unauthorized
		# edits are silently ignored (the page re-posts the existing qty on submit).
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
	"""Fill MFG / Expiry / Box / Batch on DN items from the best available source.

	Priority for each field, first non-empty wins:
	1. The DN item itself (already populated)
	2. The linked Pick List Item (custom_mfg_date / custom_expiry_date / custom_box
	   / custom_batch_code)
	3. The Batch master pointed to by batch_no — Batch always has
	   manufacturing_date + expiry_date

	The DN custom_mfg_date / custom_expiry_date fields are reqd=1 read_only=1, so
	without this no DN can submit if either the Pick List didn't enter dates or
	the DN was created before pick_list_api started copying them.
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

		# Batch first — Pick List's custom_batch_code is the source of truth.
		# The free-text code always lands in custom_batch_code; batch_no (a Link
		# to Batch) is only set when a real Batch master exists or can be created
		# (batch-tracked items) — a bare string there fails DN submit.
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
):
	start = cint(start)
	page_length = cint(page_length)

	filters = {}
	if status:
		filters["status"] = status
	if company:
		filters["company"] = company

	# A dedicated DN User only sees Delivery Notes assigned to them. Warehouse
	# admins/managers (and System Manager) keep full visibility.
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
