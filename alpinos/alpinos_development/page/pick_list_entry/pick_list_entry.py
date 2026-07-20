import frappe
import json
from frappe.utils import add_days, flt


def _fill_short_pick_remarks(pick_list, reason):
	"""Populate the short-pick reason onto any short row lacking a remark, so the
	qty_flow per-row remark rule is satisfied from the modal choice."""
	if not reason:
		return
	for loc in pick_list.locations or []:
		if flt(loc.qty) < flt(loc.custom_ordered_qty) and not (loc.get("custom_remark") or "").strip():
			loc.custom_remark = reason


def _apply_short_pick_action(pick_list_name, action, reason, future_dispatch_date):
	"""After the closing Pick List is submitted, enact the short-pick modal choice:
	Partial (record future dispatch date) or Forced Close (lock the order)."""
	action = (action or "").strip()
	if not action:
		return
	so = frappe.db.get_value("Pick List", pick_list_name, "custom_sales_order_id")
	if not so:
		return
	if action == "Forced Close":
		from alpinos.forced_close import apply_forced_close_after_pl
		apply_forced_close_after_pl(so, pick_list_name, reason)
	elif action == "Partial":
		from alpinos.partial_dispatch import apply_partial_future_dispatch
		apply_partial_future_dispatch(so, future_dispatch_date, reason)
	frappe.db.commit()


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
				["custom_sku_no", "custom_gross_weight", "shelf_life_in_days", "has_batch_no"],
				as_dict=True,
			)
			or {}
		)
		row["custom_sku_no"] = item_info.get("custom_sku_no") or ""
		if not row.get("custom_weight_per_box"):
			row["custom_weight_per_box"] = item_info.get("custom_gross_weight") or 0
		row["shelf_life_in_days"] = item_info.get("shelf_life_in_days") or 0
		row["has_batch_no"] = item_info.get("has_batch_no") or 0

	# Created By display for the entry page header.
	doc_dict["owner_full_name"] = frappe.utils.get_fullname(doc.owner)

	# Surface any existing (non-cancelled) DN against this pick list so the UI
	# can hide the Create Delivery Note button.
	doc_dict["existing_delivery_note"] = frappe.db.get_value(
		"Delivery Note Item",
		{"against_pick_list": name, "docstatus": ["<", 2]},
		"parent",
	)

	# COMBO table — recomputed from the SO bundle lines (source of truth) so it
	# survives reload of a saved pick list, where rows are already exploded.
	doc_dict["combos"] = []
	if doc.get("custom_sales_order_id"):
		from alpinos.sales_order_api import get_bundle_combos
		try:
			doc_dict["combos"] = get_bundle_combos(doc.custom_sales_order_id)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "Pick List combo recompute failed")

	# Sticker attachments from the linked Sales Order (E-com & MT orders) — shown
	# read-only on the Pick List so the picker can print/reference the artwork.
	doc_dict["custom_sticker_attachments"] = []
	if doc.get("custom_sales_order_id"):
		doc_dict["custom_sticker_attachments"] = frappe.get_all(
			"Sales Order Sticker Attachment",
			filters={"parent": doc.custom_sales_order_id, "parenttype": "Sales Order"},
			fields=["attachment", "file_name", "remarks"],
			order_by="idx",
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
			"options": "Alpino Customer Type",
			"insert_after": "company"
		}).insert()
		frappe.db.commit()

@frappe.whitelist()
def get_batch_details(batch_no, item_code):
	batch = frappe.db.get_value("Batch", {"name": batch_no}, ["manufacturing_date", "expiry_date"], as_dict=1)
	return batch or {}

@frappe.whitelist()
def save_pick_list_keep_draft(name, header, items):
	"""Persist header + per-row edits on an existing draft Pick List WITHOUT
	submitting it. Mirrors save_pick_list_data but skips doc.submit().
	"""
	header = json.loads(header) if isinstance(header, str) else header
	items = json.loads(items) if isinstance(items, str) else items

	doc = frappe.get_doc('Pick List', name)
	doc.check_permission('write')
	if doc.docstatus != 0:
		frappe.throw("Only draft Pick Lists can be saved with this action.")

	frappe.db.set_value('Pick List', name, {k: v for k, v in header.items()}, update_modified=False)

	for item_data in items:
		item_doc = [d for d in doc.locations if d.name == item_data.get('name')]
		if not item_doc:
			continue
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
			'custom_remark': item_data.get('custom_remark') or None,
		}, update_modified=False)

	frappe.db.commit()
	return True


@frappe.whitelist()
def save_pick_list_data(name, header, items, short_pick_action=None,
                        short_pick_reason=None, future_dispatch_date=None):
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
			# A short row without a remark inherits the short-pick modal reason.
			remark = item_data.get('custom_remark') or None
			if short_pick_reason and not remark and qty_val < flt(item.custom_ordered_qty):
				remark = short_pick_reason
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
				'custom_remark': remark,
			}, update_modified=False)

	frappe.db.commit()
	
	# Step 3: Reload the doc so it has the freshly written DB values
	doc.reload()
	
	# Step 4: Submit (this will re-run validate hooks — but now doc has correct values from DB)
	doc.flags.ignore_mandatory = True
	doc.submit()

	# Step 5: Enact the short-pick modal choice (Partial / Forced Close).
	_apply_short_pick_action(name, short_pick_action, short_pick_reason, future_dispatch_date)

	return True



@frappe.whitelist()
def get_pick_list_entry_list(
	start=0,
	page_length=20,
	search="",
	status="",
	company="",
	sales_order=""
):
	start = frappe.utils.cint(start)
	page_length = frappe.utils.cint(page_length)

	filters = {}
	if status:
		filters["status"] = status
	if company:
		filters["company"] = company
	if sales_order:
		filters["custom_sales_order_id"] = sales_order

	# A dedicated PL User only sees Pick Lists assigned to them. Warehouse
	# admins/managers (and System Manager) keep full visibility.
	_roles = set(frappe.get_roles())
	_override = {"System Manager", "Administrator", "Warehouse Admin", "Warehouse Manager", "DN Manager"}
	if "PL User" in _roles and not (_roles & _override):
		filters["custom_assigned_to"] = frappe.session.user
		
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
		fields=[
			"name", "custom_customer_name", "custom_order_date", "company",
			"status", "custom_workflow_status", "custom_sales_order_id",
			"custom_po_no", "custom_transporter", "custom_assigned_to",
			"custom_dispatch_date", "custom_total_box",
		],
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

def _build_pick_list_from_mapping(so_name, header, items, removed_rows=None, remaining_only=0):
	"""Shared core: insert a Pick List in draft state from SO mapping data + UI edits.

	Items may include client-side split rows (marked is_client_extra=1) that
	don't exist in the SO mapping — those get appended as fresh locations
	cloned from their `source_row` mapping. removed_rows is a list of audit
	entries written to custom_removed_items.

	remaining_only=1 (partial "Create PL for Remaining Qty"): the mapping is
	refetched with the SAME remaining-qty reduction the UI rendered, so each
	row's custom_ordered_qty snapshots the remaining qty (not the full SO qty).
	Without this, a full-remaining pick reads as short vs the full ordered qty
	and qty_flow wrongly demands a short-pick remark.

	Returns the inserted doc (still docstatus=0). Caller decides whether to submit.
	"""
	header = json.loads(header) if isinstance(header, str) else header
	items = json.loads(items) if isinstance(items, str) else items
	removed_rows = json.loads(removed_rows) if isinstance(removed_rows, str) else (removed_rows or [])

	from alpinos.sales_order_api import get_pick_list_mapping_data
	mapping_data = get_pick_list_mapping_data(so_name, remaining_only=frappe.utils.cint(remaining_only))
	mapping_by_name = {row.get("name"): row for row in (mapping_data.locations or [])}

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

	# Index UI items by original mapping name so we know which mapping rows
	# survived (not removed) and which need their qty/box edits applied.
	ui_by_name = {i.get("name"): i for i in items if not i.get("is_client_extra")}

	for mapped_row in mapping_data.locations:
		ui_item = ui_by_name.get(mapped_row.get("name"))
		if not ui_item:
			# Row was removed client-side; skip.
			continue
		qty = float(ui_item.get('qty') or 0)
		pick_list.append("locations", {
			"sales_order": so_name,
			"sales_order_item": mapped_row.get("sales_order_item") or mapped_row.get("name"),
			"product_bundle_item": mapped_row.get("product_bundle_item") or None,
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
			"custom_bundle_parent": mapped_row.get("custom_bundle_parent") or None,
			"has_batch_no": 0,
			"use_serial_batch_fields": 0,
			"custom_mfg_date": ui_item.get('custom_mfg_date') or None,
			"custom_expiry_date": ui_item.get('custom_expiry_date') or None,
			"custom_batch_code": ui_item.get('custom_batch_code') or None,
			"batch_no": None,
			"custom_remark": ui_item.get('custom_remark') or None,
		})

	# Client-side split rows: clone from the source mapping row when known so
	# they inherit warehouse / source_table / ordered_qty correctly.
	for extra in (i for i in items if i.get("is_client_extra")):
		source = mapping_by_name.get(extra.get("source_row")) or {}
		qty = float(extra.get('qty') or 0)
		pick_list.append("locations", {
			"sales_order": so_name,
			"sales_order_item": source.get("sales_order_item") or source.get("name") or extra.get("source_row"),
			"product_bundle_item": source.get("product_bundle_item") or None,
			"item_code": extra.get("item_code") or source.get("item_code"),
			"custom_ordered_qty": source.get("custom_ordered_qty"),
			"qty": qty,
			"stock_qty": qty,
			"picked_qty": qty,
			"conversion_factor": 1,
			"warehouse": source.get("warehouse"),
			"custom_box": float(extra.get('custom_box') or 0),
			"custom_sample_quantity": 0,
			"custom_source_table": extra.get("custom_source_table") or source.get("custom_source_table"),
			"custom_bundle_parent": source.get("custom_bundle_parent") or None,
			"has_batch_no": 0,
			"use_serial_batch_fields": 0,
			"custom_mfg_date": extra.get('custom_mfg_date') or None,
			"custom_expiry_date": extra.get('custom_expiry_date') or None,
			"custom_batch_code": extra.get('custom_batch_code') or None,
			"batch_no": None,
			"custom_remark": extra.get('custom_remark') or None,
		})

	# Client-side removals: write the audit child rows on the new doc.
	for removed in removed_rows:
		if not removed.get("reason"):
			continue
		pick_list.append("custom_removed_items", {
			"item_code": removed.get("item_code"),
			"item_name": removed.get("item_name"),
			"removed_qty": float(removed.get("removed_qty") or 0),
			"removed_box": float(removed.get("removed_box") or 0),
			"batch_no": removed.get("batch_no") or None,
			"reason": removed.get("reason"),
			"removed_by": frappe.session.user,
			"removed_on": frappe.utils.now_datetime(),
		})

	pick_list.flags.ignore_mandatory = True
	pick_list.insert(ignore_permissions=True)

	# Force-set qty/box/dates on every location row so direct DB matches the UI
	# (mapping items go through ORM; client extras likewise need precision).
	for item in pick_list.locations:
		ui_item = (
			ui_by_name.get(item.sales_order_item)
			or next(
				(
					i for i in items
					if i.get("is_client_extra")
					and (i.get("source_row") == item.sales_order_item)
					and float(i.get('custom_box') or 0) == float(item.custom_box or 0)
					and float(i.get('qty') or 0) == float(item.qty or 0)
				),
				None,
			)
		)
		if not ui_item:
			continue
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

	pick_list.reload()
	return pick_list


@frappe.whitelist()
def create_pick_list_as_draft(so_name, header, items, removed_rows=None, remaining_only=0):
	"""Persist a Pick List as draft (docstatus=0) and return its name.

	Used by the entry page when the user wants to split/remove rows on a
	new PL — those actions need a persisted doc to operate on. After draft
	creation, the page navigates to the new doc and the row-action buttons
	become available.
	"""
	pick_list = _build_pick_list_from_mapping(so_name, header, items, removed_rows, remaining_only)
	frappe.db.commit()
	return pick_list.name


@frappe.whitelist()
def create_and_submit_pick_list(so_name, header, items, removed_rows=None,
                                short_pick_action=None, short_pick_reason=None,
                                future_dispatch_date=None, remaining_only=0):
	pick_list = _build_pick_list_from_mapping(so_name, header, items, removed_rows, remaining_only)
	_fill_short_pick_remarks(pick_list, short_pick_reason)
	pick_list.submit()
	_apply_short_pick_action(pick_list.name, short_pick_action, short_pick_reason, future_dispatch_date)
	return pick_list.name
