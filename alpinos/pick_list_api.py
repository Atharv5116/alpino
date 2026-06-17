"""Whitelisted helpers for Pick List UI."""

from typing import Optional

import frappe
from frappe.utils import cint, flt, now_datetime


def _format_address_text(address_name: Optional[str]) -> str:
	"""Return a plain-text, comma-separated address for the given Address name.

	Used to seed Delivery Note Dispatch From / Dispatch To fields (Small Text)
	from the standard ERPNext company / shipping address links. Returns "" when
	the address can't be loaded so callers can fall back silently.
	"""
	if not address_name:
		return ""
	try:
		addr = frappe.get_cached_doc("Address", address_name)
	except Exception:
		return ""
	parts = [
		addr.get("address_line1"),
		addr.get("address_line2"),
		addr.get("city"),
		addr.get("state"),
		addr.get("country"),
		addr.get("pincode"),
	]
	return ", ".join(p for p in parts if p)


def resolve_batch_no_for_row(row) -> Optional[str]:
	"""Batch may live on row.batch_no (legacy fields) or inside Serial and Batch Bundle."""
	bn = getattr(row, "batch_no", None)
	if bn:
		return bn
	bundle = getattr(row, "serial_and_batch_bundle", None)
	if not bundle:
		return None
	r = frappe.db.sql(
		"""
		SELECT batch_no FROM `tabSerial and Batch Entry`
		WHERE parent = %s AND IFNULL(batch_no, '') != ''
		LIMIT 1
		""",
		(bundle,),
	)
	return r[0][0] if r else None


def resolve_batch_no_from_args(batch_no=None, serial_and_batch_bundle=None) -> Optional[str]:
	if batch_no:
		return batch_no
	if not serial_and_batch_bundle:
		return None
	r = frappe.db.sql(
		"""
		SELECT batch_no FROM `tabSerial and Batch Entry`
		WHERE parent = %s AND IFNULL(batch_no, '') != ''
		LIMIT 1
		""",
		(serial_and_batch_bundle,),
	)
	return r[0][0] if r else None


@frappe.whitelist()
def get_box_conversion_factor(item_code):
	if not item_code:
		return None
	v = frappe.db.get_value(
		"UOM Conversion Detail",
		{"parent": item_code, "parenttype": "Item", "uom": "Box"},
		"conversion_factor",
	)
	return flt(v) if v else None


SAMPLE_SOURCE_TABLES = {"Marketing Freebies", "Scheme Table", "Additional Units"}

# Display order of source tables on the pick_list_entry page — used to keep
# sticker output in the same sequence the user sees on screen.
SOURCE_TABLE_ORDER = ("Items", "Marketing Freebies", "Scheme Table", "Additional Units")


def _ensure_batch_exists(item_code, batch_name, mfg_date=None, expiry_date=None):
	"""Create the Batch master if it doesn't exist already.

	Returns the batch name (string) on success, or None when:
	  - item_code or batch_name is missing,
	  - the Item is not batched (has_batch_no=0),
	  - the insert raised — error is logged for follow-up.

	Used when persisting custom_batch_code (free text) onto Delivery Note
	Item.batch_no, which is a Link to Batch.
	"""
	if not item_code or not batch_name:
		return None
	if frappe.db.exists("Batch", batch_name):
		return batch_name
	if not frappe.db.get_value("Item", item_code, "has_batch_no"):
		return None
	try:
		batch = frappe.get_doc(
			{
				"doctype": "Batch",
				"batch_id": batch_name,
				"item": item_code,
				"manufacturing_date": mfg_date or None,
				"expiry_date": expiry_date or None,
			}
		)
		batch.flags.ignore_permissions = True
		batch.flags.ignore_mandatory = True
		batch.insert()
		return batch.name
	except Exception:
		frappe.log_error(
			frappe.get_traceback(),
			f"alpinos auto-create Batch failed: {batch_name} / {item_code}",
		)
		return None

# Fixed Dispatch From address for all Delivery Notes (per spec).
DEFAULT_DN_DISPATCH_FROM = (
	"Laxmi incorporation campus 01, valthan punagam, "
	"canal road, ladvi patiya surat. - 394325"
)


@frappe.whitelist()
def generate_pick_list_stickers(pick_list):
	"""Return a PDF stream of pick-list stickers — one per box per row.

	Sticker layout fields (per sticker dict): see templates/print/pick_list_stickers.html.
	Rows whose custom_source_table is in SAMPLE_SOURCE_TABLES are marked
	is_sample=1 so the template overlays a SAMPLE watermark + flag.
	Box index is 1..N within the SKU; total_box is N (per-row, per spec answer).
	Dispatch area is left blank until that source is confirmed.
	"""
	doc = frappe.get_doc("Pick List", pick_list)
	doc.check_permission("read")

	party_name = doc.get("custom_customer_name") or ""
	po_no = doc.get("custom_po_no") or ""
	# Gate now lives on the PL header (one value for the whole pick), so we
	# read it once outside the row loop and apply it to every sticker.
	gate = doc.get("custom_gate") or ""

	# Match the page's section order (Items > Marketing Freebies > Scheme >
	# Additional Units), then preserve the existing row sequence within each
	# section. Stickers come out in the same order the user sees on screen.
	def _row_sort_key(row):
		src = row.get("custom_source_table") or "Items"
		try:
			src_idx = SOURCE_TABLE_ORDER.index(src)
		except ValueError:
			src_idx = len(SOURCE_TABLE_ORDER)
		return (src_idx, row.idx or 0)

	sorted_rows = sorted(doc.locations or [], key=_row_sort_key)
	stickers = []
	for row in sorted_rows:
		source_table = row.get("custom_source_table") or "Items"
		is_sample = source_table in SAMPLE_SOURCE_TABLES
		# Items rows: use custom_box. Sample-table rows: use custom_sample_box,
		# falling back to 1 sticker per row when the count is zero so the
		# freebie/scheme/additional-unit gets at least one printed label.
		if is_sample:
			total_box = int(flt(row.get("custom_sample_box") or 0)) or 1
		else:
			total_box = int(flt(row.get("custom_box") or 0))
			if total_box <= 0:
				continue
		sku_no = ""
		if row.item_code:
			sku_no = frappe.db.get_value("Item", row.item_code, "custom_sku_no") or ""
		batch_no = row.get("batch_no") or row.get("custom_batch_code") or ""
		for box_idx in range(1, total_box + 1):
			stickers.append({
				"sku_no": sku_no,
				"sku_name": row.item_code or "",
				"batch_no": batch_no,
				"box_index": box_idx,
				"total_box": total_box,
				"party_name": party_name,
				"po_no": po_no,
				"dispatch_area": gate,
				"is_sample": is_sample,
			})

	html = frappe.render_template(
		"alpinos/templates/print/pick_list_stickers.html",
		{"stickers": stickers, "pick_list": doc.name},
	)
	from frappe.utils.pdf import get_pdf
	# 100mm x 75mm landscape, zero margins so the @page CSS is honoured exactly.
	# Smart-shrinking left ON (default) — disabling it was pushing overflow
	# content onto a second page when the content barely exceeded 75mm.
	pdf_options = {
		"page-width": "100mm",
		"page-height": "75mm",
		"orientation": "Landscape",
		"margin-top": "0mm",
		"margin-bottom": "0mm",
		"margin-left": "0mm",
		"margin-right": "0mm",
	}
	pdf = get_pdf(html, options=pdf_options)

	frappe.local.response.filename = "stickers-{0}.pdf".format(pick_list)
	frappe.local.response.filecontent = pdf
	frappe.local.response.type = "download"


@frappe.whitelist()
def update_pick_list_assignment(pick_list, assigned_to):
	"""Lightweight assignment update — works on any docstatus.

	Used by the pick_list_entry page's on-change handler so the value sticks
	immediately without going through the full save/submit flow. The field
	is allow_on_submit=1, so this is safe even for docstatus=1 docs.
	"""
	if not pick_list:
		frappe.throw("Pick List name is required.")
	if not frappe.db.exists("Pick List", pick_list):
		frappe.throw(f"Pick List {pick_list} not found.")
	frappe.has_permission("Pick List", "write", doc=pick_list, throw=True)
	value = (assigned_to or "").strip() or None
	frappe.db.set_value("Pick List", pick_list, "custom_assigned_to", value)
	frappe.db.commit()
	return value


@frappe.whitelist()
def remove_pick_list_row_with_reason(pick_list, row_name, reason):
	"""Remove a draft Pick List Item row with an audit entry in custom_removed_items.

	Used by the pick_list_entry custom page. Returns True on success; throws on
	invalid input.
	"""
	if not reason or not str(reason).strip():
		frappe.throw("A reason is required to remove a row.")

	doc = frappe.get_doc("Pick List", pick_list)
	doc.check_permission("write")
	if doc.docstatus != 0:
		frappe.throw("Cannot remove rows from a submitted or cancelled Pick List.")

	row = next((r for r in doc.locations if r.name == row_name), None)
	if not row:
		frappe.throw(f"Row {row_name} not found on Pick List {pick_list}.")

	doc.append(
		"custom_removed_items",
		{
			"item_code": row.item_code,
			"item_name": row.item_name,
			"removed_qty": flt(row.qty),
			"removed_box": flt(row.custom_box),
			"batch_no": row.batch_no or row.get("custom_batch_code"),
			"reason": reason,
			"removed_by": frappe.session.user,
			"removed_on": now_datetime(),
		},
	)
	doc.locations = [r for r in doc.locations if r.name != row_name]
	doc.flags.ignore_mandatory = True
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return True


@frappe.whitelist()
def split_pick_list_row(pick_list, row_name, split_box):
	"""Split a draft Pick List row by box count.

	Clones the source row with `custom_box = split_box` and the matching
	`qty = split_box * factor`, decrements the original's box and qty, clears
	batch/MFG/expiry on the new row so a different batch can be assigned.
	Throws if the item has no UOM 'Box' configured — we don't silently fall
	back to a 1:1 factor.
	"""
	split_box = cint(split_box)
	doc = frappe.get_doc("Pick List", pick_list)
	doc.check_permission("write")
	if doc.docstatus != 0:
		frappe.throw("Cannot split rows on a submitted or cancelled Pick List.")

	row = next((r for r in doc.locations if r.name == row_name), None)
	if not row:
		frappe.throw(f"Row {row_name} not found on Pick List {pick_list}.")

	current_box = cint(row.custom_box)
	if split_box <= 0 or split_box >= current_box:
		frappe.throw(
			f"Split box must be between 1 and {current_box - 1} (row has {current_box} boxes)."
		)

	factor = flt(get_box_conversion_factor(row.item_code))
	if not factor:
		frappe.throw(
			f"Define UOM 'Box' on Item {row.item_code} before splitting."
		)

	new_qty = flt(split_box * factor, 2)
	doc.append(
		"locations",
		{
			"item_code": row.item_code,
			"item_name": row.item_name,
			"custom_ordered_qty": row.custom_ordered_qty,
			"qty": new_qty,
			"stock_qty": new_qty,
			"picked_qty": new_qty,
			"conversion_factor": row.conversion_factor or 1,
			"warehouse": row.warehouse,
			"sales_order": row.sales_order,
			"sales_order_item": row.sales_order_item,
			"custom_box": split_box,
			"custom_sample_quantity": 0,
			"custom_sample_box": 0,
			"custom_weight_per_box": row.custom_weight_per_box,
			"custom_source_table": row.custom_source_table,
			"custom_remark": (row.custom_remark or "") + " [split]",
			"has_batch_no": 0,
			"use_serial_batch_fields": 0,
		},
	)

	remaining_box = current_box - split_box
	remaining_qty = flt(remaining_box * factor, 2)
	row.custom_box = remaining_box
	row.qty = remaining_qty
	row.stock_qty = remaining_qty
	row.picked_qty = remaining_qty

	doc.flags.ignore_mandatory = True
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return True


@frappe.whitelist()
def resolve_batch_dates_for_row(batch_no=None, serial_and_batch_bundle=None):
	"""Return resolved batch + manufacturing / expiry for a Pick List Item row."""
	bn = resolve_batch_no_from_args(batch_no=batch_no, serial_and_batch_bundle=serial_and_batch_bundle)
	if not bn:
		return {"batch_no": None, "manufacturing_date": None, "expiry_date": None}
	d = (
		frappe.db.get_value(
			"Batch",
			bn,
			["manufacturing_date", "expiry_date"],
			as_dict=True,
		)
		or {}
	)
	return {
		"batch_no": bn,
		"manufacturing_date": d.get("manufacturing_date"),
		"expiry_date": d.get("expiry_date"),
	}


@frappe.whitelist()
def bulk_edit_transporter(pick_lists, transporter):
	import json
	if isinstance(pick_lists, str):
		pick_lists = json.loads(pick_lists)

	if not pick_lists or not isinstance(pick_lists, list):
		frappe.throw("No Pick Lists selected or invalid input format.")

	for pl in pick_lists:
		frappe.db.set_value("Pick List", pl, "custom_transporter", transporter)

	frappe.db.commit()
	return {"status": "success"}


@frappe.whitelist()
def bulk_edit_pick_lists(pick_lists, fieldname, value):
	import json
	if isinstance(pick_lists, str):
		pick_lists = json.loads(pick_lists)

	if not pick_lists or not isinstance(pick_lists, list):
		frappe.throw("No Pick Lists selected or invalid input format.")

	if fieldname not in ["custom_transporter", "custom_qc_attended_by"]:
		frappe.throw("Unauthorized field modification.")

	for pl in pick_lists:
		frappe.db.set_value("Pick List", pl, fieldname, value)

	frappe.db.commit()
	return {"status": "success"}


@frappe.whitelist()
def create_delivery_note_from_pick_list(pick_list_name):
	from erpnext.stock.doctype.pick_list.pick_list import create_delivery_note
	import json

	# Load Pick List to get its custom fields
	pick_list = frappe.get_doc("Pick List", pick_list_name)

	# Ensure Pick List is submitted
	if pick_list.docstatus != 1:
		frappe.throw("Pick List must be submitted to create a Delivery Note.")

	# Ensure every referenced Sales Order is submitted — ERPNext's SO→DN mapper
	# silently throws a cryptic "Cannot map because following condition fails:
	# docstatus=1" otherwise.
	unsubmitted_sos = []
	seen = set()
	for loc in pick_list.locations or []:
		so = loc.sales_order
		if not so or so in seen:
			continue
		seen.add(so)
		ds = frappe.db.get_value("Sales Order", so, "docstatus")
		if ds != 1:
			unsubmitted_sos.append((so, ds))
	if unsubmitted_sos:
		details = ", ".join(
			f"{so} (docstatus={ds if ds is not None else 'missing'})"
			for so, ds in unsubmitted_sos
		)
		frappe.throw(
			"Cannot create Delivery Note — the following Sales Orders are not "
			f"submitted: {details}. Submit or amend the Sales Order(s) first."
		)

	# If a DN already exists against this pick list (previous attempt), return it
	# instead of trying to create a duplicate — frontend can navigate to the real doc.
	existing_dn = frappe.db.get_value(
		"Delivery Note Item",
		{"against_pick_list": pick_list_name, "docstatus": ["<", 2]},
		"parent",
	)
	if existing_dn:
		return existing_dn

	# Bundle components are packed by ERPNext's native make_packing_list, which copies
	# the batch/warehouse onto each packed item via update_packed_item_with_pick_list_info
	# — but it reads the STANDARD batch_no field on the Pick List Item. The custom flow
	# stores the picker's batch in custom_batch_code (free text) and leaves batch_no blank,
	# so resolve it to a real Batch and stamp batch_no on the bundle-component rows first.
	# (Native picks the single largest-qty batch per component; a component split across
	# several batches keeps only the dominant one in the packed item.)
	for loc in pick_list.locations or []:
		if loc.get("product_bundle_item") and not loc.get("batch_no") and loc.get("custom_batch_code"):
			bn = _ensure_batch_exists(
				loc.item_code,
				loc.custom_batch_code,
				loc.get("custom_mfg_date"),
				loc.get("custom_expiry_date"),
			)
			if bn:
				frappe.db.set_value("Pick List Item", loc.name, "batch_no", bn, update_modified=False)
				loc.batch_no = bn

	# Suppress the default ERPNext msgprint during DN creation
	_original_msgprint = frappe.msgprint
	def _silent_msgprint(*args, **kwargs):
		if "raise_exception" in kwargs and kwargs["raise_exception"]:
			raise_exception = kwargs["raise_exception"]
			if isinstance(raise_exception, type) and issubclass(raise_exception, Exception):
				raise raise_exception(args[0] if args else "Validation Error")
			else:
				raise frappe.ValidationError(args[0] if args else "Validation Error")
	frappe.msgprint = _silent_msgprint

	# Monkeypatch frappe.get_doc to handle custom SO child tables mapping
	_original_get_doc = frappe.get_doc
	def _custom_get_doc(*args, **kwargs):
		doctype = None
		name = None
		if args:
			if isinstance(args[0], str):
				doctype = args[0]
				if len(args) > 1:
					name = args[1]
			elif isinstance(args[0], dict):
				doctype = args[0].get("doctype")
				name = args[0].get("name")
		
		if not doctype and kwargs:
			doctype = kwargs.get("doctype")
			name = kwargs.get("name")

		if doctype == "Sales Order Item" and name:
			if not frappe.db.exists("Sales Order Item", name):
				for custom_doctype in [
					"Sales Order Marketing Freebie",
					"Sales Order Scheme Item",
					"Sales Order Additional Units Item"
				]:
					if frappe.db.exists(custom_doctype, name):
						custom_doc = _original_get_doc(custom_doctype, name)
						# Masquerade custom table doc as a Sales Order Item
						custom_doc.doctype = "Sales Order Item"
						
						# Fetch missing item fields from Item master
						item_details = frappe.db.get_value(
							"Item",
							custom_doc.item_code,
							["item_group", "item_name", "brand", "description", "stock_uom"],
							as_dict=True,
						) or {}
						for key, val in item_details.items():
							if not getattr(custom_doc, key, None):
								setattr(custom_doc, key, val)

						if not getattr(custom_doc, "uom", None):
							custom_doc.uom = custom_doc.stock_uom or "Nos"
						if not getattr(custom_doc, "conversion_factor", None):
							custom_doc.conversion_factor = 1.0
						if not getattr(custom_doc, "stock_uom", None):
							custom_doc.stock_uom = custom_doc.uom
						if not getattr(custom_doc, "rate", None):
							custom_doc.rate = 0.0
						if not getattr(custom_doc, "delivered_qty", None):
							custom_doc.delivered_qty = 0.0
						if not getattr(custom_doc, "delivered_by_supplier", None):
							custom_doc.delivered_by_supplier = 0
						return custom_doc
				return None
		return _original_get_doc(*args, **kwargs)

	# Monkeypatch frappe.get_all to fetch details for masqueraded Sales Order Items from custom tables
	_original_get_all = frappe.get_all
	def _custom_get_all(*args, **kwargs):
		doctype = args[0] if args else kwargs.get("doctype")
		filters = kwargs.get("filters")
		if doctype == "Sales Order Item" and filters and "name" in filters:
			name_filter = filters["name"]
			names_to_query = []
			if isinstance(name_filter, (list, tuple)):
				if len(name_filter) == 2 and name_filter[0] == "in" and isinstance(name_filter[1], (list, tuple)):
					names_to_query = list(name_filter[1])
				elif len(name_filter) == 2 and isinstance(name_filter[1], str):
					names_to_query = [name_filter[1]]
			elif isinstance(name_filter, str):
				names_to_query = [name_filter]

			results = _original_get_all(*args, **kwargs)
			found_names = {r.name if hasattr(r, "name") else r.get("name") for r in results}
			missing_names = [n for n in names_to_query if n not in found_names]

			if missing_names:
				fields = kwargs.get("fields") or ["name"]
				fields_list = fields if isinstance(fields, list) else [fields]
				custom_results = []
				for custom_doctype in [
					"Sales Order Marketing Freebie",
					"Sales Order Scheme Item",
					"Sales Order Additional Units Item"
				]:
					missing_in_custom = [n for n in missing_names if frappe.db.exists(custom_doctype, n)]
					if missing_in_custom:
						valid_fields = [f.fieldname for f in frappe.get_meta(custom_doctype).fields] + ["name", "parent"]
						query_fields = [f for f in fields_list if f in valid_fields]
						custom_records = _original_get_all(
							custom_doctype,
							filters={"name": ("in", missing_in_custom)},
							fields=query_fields
						)
						for r in custom_records:
							for f in fields_list:
								if f not in r:
									r[f] = 1.0 if f == "conversion_factor" else (0.0 if f in ["rate", "qty", "delivered_qty"] else None)
						custom_results.extend(custom_records)
				results.extend(custom_results)
			return results
		return _original_get_all(*args, **kwargs)

	frappe.get_doc = _custom_get_doc
	frappe.get_all = _custom_get_all

	# Patch create_dn_with_so / create_dn_wo_so to drop zero-qty rows
	# (items already fully delivered or never picked) before save, otherwise
	# erpnext's validate_qty_is_not_zero blows up the whole DN creation.
	from erpnext.stock.doctype.pick_list import pick_list as _pl_module
	_orig_create_dn_with_so = _pl_module.create_dn_with_so
	_orig_create_dn_wo_so = _pl_module.create_dn_wo_so

	def _patched_create_dn_with_so(sales_dict, pl):
		delivery_note = None
		for customer in sales_dict:
			delivery_note = _pl_module.create_dn_from_so(pl, sales_dict[customer], None)
			if not delivery_note:
				continue
			delivery_note.items = [it for it in delivery_note.items if flt(it.qty) > 0]
			if not delivery_note.items:
				delivery_note = None
				continue
			delivery_note.flags.ignore_mandatory = True
			delivery_note.save()
		return delivery_note

	def _patched_create_dn_wo_so(pl, delivery_note=None):
		dn_local = _orig_create_dn_wo_so(pl, delivery_note)
		if dn_local:
			dn_local.items = [it for it in dn_local.items if flt(it.qty) > 0]
		return dn_local

	_pl_module.create_dn_with_so = _patched_create_dn_with_so
	_pl_module.create_dn_wo_so = _patched_create_dn_wo_so

	try:
		# Call standard erpnext mapper to create Delivery Note
		dn = create_delivery_note(pick_list_name)

		if not dn:
			frappe.throw(
				"Could not create Delivery Note: no remaining quantity to deliver "
				"for this Pick List (all items appear to be already delivered)."
			)

		if isinstance(dn, str):
			dn = frappe.get_doc("Delivery Note", dn)

		# Map custom fields from Pick List to Delivery Note
		dn.custom_sales_order_id = pick_list.custom_sales_order_id
		dn.custom_dn_so_customer_name = pick_list.custom_customer_name
		dn.custom_dispatch_date = pick_list.custom_order_date or frappe.utils.now_datetime()
		dn.custom_delivery_date = pick_list.custom_order_date or frappe.utils.now_datetime()

		# Transporter — copy verbatim from Pick List (custom_transporter_name is
		# now a Data field; no Select-option matching needed).
		dn.custom_transporter_name = pick_list.custom_transporter or ""
		# Picklist PO No. lives in vehicle_no (re-labelled via Property Setter).
		dn.vehicle_no = pick_list.custom_po_no or ""

		# Copy custom_mfg_date / custom_expiry_date / custom_box from the matching
		# Pick List Item rows — ERPNext's standard mapper drops these custom fields
		# and Delivery Note Item declares them as reqd=1, blocking submit.
		pl_rows_by_name = {row.name: row for row in (pick_list.locations or [])}
		for dn_item in dn.items:
			pl_row = pl_rows_by_name.get(dn_item.get("pick_list_item"))
			if not pl_row:
				continue
			if not dn_item.get("custom_mfg_date") and pl_row.get("custom_mfg_date"):
				dn_item.custom_mfg_date = pl_row.custom_mfg_date
			if not dn_item.get("custom_expiry_date") and pl_row.get("custom_expiry_date"):
				dn_item.custom_expiry_date = pl_row.custom_expiry_date
			if not dn_item.get("custom_box") and pl_row.get("custom_box"):
				dn_item.custom_box = pl_row.custom_box
			# Mirror the picker's free-text batch code onto DN Item unconditionally
			# so it survives even when the Item isn't batched or Batch insert fails.
			if pl_row.get("custom_batch_code") and not dn_item.get("custom_batch_code"):
				dn_item.custom_batch_code = pl_row.custom_batch_code
			# Standard batch_no link: only set when the Item is batched and the
			# Batch can be auto-created (or already exists).
			if not dn_item.get("batch_no") and pl_row.get("custom_batch_code"):
				bn = _ensure_batch_exists(
					dn_item.item_code,
					pl_row.custom_batch_code,
					pl_row.get("custom_mfg_date"),
					pl_row.get("custom_expiry_date"),
				)
				if bn:
					dn_item.batch_no = bn

		# Dispatch From: fixed company address (per spec). Override blanks.
		if not dn.get("custom_dispatch_from"):
			dn.custom_dispatch_from = DEFAULT_DN_DISPATCH_FROM

		if not (dn.get("custom_dispatch_to") or []):
			dispatch_to = _format_address_text(dn.get("shipping_address_name"))
			if dispatch_to:
				dn.append("custom_dispatch_to", {"dispatch_to_address": dispatch_to})

		# Save updated Delivery Note bypassing validations for Draft
		dn.flags.ignore_mandatory = True
		dn.save(ignore_permissions=True)
		frappe.db.commit()
	finally:
		# Restore original msgprint, get_doc, and get_all
		frappe.msgprint = _original_msgprint
		frappe.get_doc = _original_get_doc
		frappe.get_all = _original_get_all
		_pl_module.create_dn_with_so = _orig_create_dn_with_so
		_pl_module.create_dn_wo_so = _orig_create_dn_wo_so

	return dn.name

