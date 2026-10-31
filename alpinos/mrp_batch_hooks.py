"""Where each stock document picks its Batch / MRP (see alpinos.mrp_batch).

    Stock Entry   a receipt makes the lot from the Batch Code and MRP typed on the row; an
                  issue or transfer with no lot takes lots by itself (batch typed, then
                  oldest unassigned stock, then earliest expiry), and a transfer lands in
                  the same lot it left.
    Pick List     at submit, a row with no lot takes lots by itself, the Sales Order line's
                  MRP first, and is split across lots when one does not cover it.
    Delivery Note follows its Pick List row; a row raised without one falls back to a
                  single lot, or to stock with no lot.

Nothing here runs until the MRP Batch dimension exists, and no row whose lot a person chose
is ever changed.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

from alpinos import mrp_batch as MB


def _lot_fields(lot):
	return MB.lot_details([lot]).get(lot) if lot else None


# What a row says about its goods, apart from the lot: when a row is split across lots each
# part starts again from what was typed, then takes its own lot's batch and dates.
_TEXT_FIELDS = ("custom_batch_code", "custom_mfg_date", "custom_exp_date", "custom_expiry_date", "custom_mrp", "custom_lot_mrp")


def _typed_text(row):
	return {f: row.get(f) for f in _TEXT_FIELDS if row.meta.has_field(f)}


def _box_factor(item_code):
	try:
		from alpinos.sales_order_api import get_box_conversion_factor

		return flt(get_box_conversion_factor(item_code))
	except Exception:
		return 0.0


def _assert_lot_item(row, lot, label):
	details = _lot_fields(lot)
	if not details:
		frappe.throw(_("Row {0}: Batch / MRP {1} does not exist.").format(row.idx, lot))
	if details.item_code != row.item_code:
		frappe.throw(
			_("Row {0}: Batch / MRP {1} belongs to {2}, not {3}.").format(
				row.idx, frappe.bold(details.title or lot), details.item_code, row.item_code
			),
			title=label,
		)
	return details


# ------------------------------------------------------------ Stock Entry


def stock_entry_before_validate(doc, method=None):
	if not MB.enabled() or cint(doc.docstatus) == 2:
		return
	_material_return_rows_prefer_issued_lot(doc)
	for row in list(doc.get("items") or []):
		if not row.item_code or not flt(row.get("qty")):
			continue
		if row.get("s_warehouse"):
			_stock_entry_outward(doc, row)
		elif row.get("t_warehouse"):
			_stock_entry_receipt(doc, row)


def _material_return_rows_prefer_issued_lot(doc):
	"""A production Material Return row goes back as the lot its Material Issue row moved into
	WIP, while WIP still holds that much of it. Production consumes WIP stock by earliest
	expiry, so the issued lot may be used up already; then the row is allocated like any
	other, preferring that lot's batch and MRP."""
	if not frappe.get_meta("Stock Entry Detail").has_field("custom_mi_detail"):
		return
	for row in doc.get("items") or []:
		if row.get(MB.FIELD) or not row.get("custom_mi_detail") or not row.get("s_warehouse"):
			continue
		issued = frappe.db.get_value(
			"Stock Entry Detail", row.custom_mi_detail, [MB.TO_FIELD, MB.FIELD, "t_warehouse"], as_dict=True
		)
		lot = issued and (issued.get(MB.TO_FIELD) or issued.get(MB.FIELD))
		if not lot or issued.t_warehouse != row.s_warehouse:
			continue
		stock_qty = flt(row.get("transfer_qty")) or flt(row.qty) * (flt(row.get("conversion_factor")) or 1.0)
		free = {d.lot: flt(d.qty) for d in MB.available(row.item_code, row.s_warehouse, respect_holds=False)[0]}
		if flt(free.get(lot)) + 1e-6 >= stock_qty:
			row.set(MB.FIELD, lot)
		else:
			details = _lot_fields(lot) or frappe._dict()
			if row.meta.has_field("custom_batch_code") and not row.get("custom_batch_code"):
				row.custom_batch_code = details.batch_no
			if row.meta.has_field("custom_mrp") and not flt(row.get("custom_mrp")):
				row.custom_mrp = details.mrp


def _stock_entry_receipt(doc, row):
	lot = row.get(MB.TO_FIELD) or row.get(MB.FIELD)
	if not lot:
		lot = MB.get_or_create(
			row.item_code,
			row.get("custom_batch_code"),
			row.get("custom_mrp"),
			row.get("custom_mfg_date"),
			row.get("custom_exp_date"),
			source="Production" if doc.get("purpose") == "Manufacture" else "Stock Entry",
			reference_doctype="Stock Entry",
			reference_name=doc.name if not doc.is_new() else None,
		)
	if not lot:
		return
	details = _assert_lot_item(row, lot, _("Stock Entry"))
	# ERPNext reads the TARGET field for the receiving side of a Stock Entry row.
	row.set(MB.FIELD, lot)
	row.set(MB.TO_FIELD, lot)
	_fill_stock_entry_text(row, details)


def _fill_stock_entry_text(row, details, overwrite=False):
	"""The lot's batch, MRP and dates on the row: where blank, or (overwrite) always."""
	if not details:
		return
	if details.batch_no and (overwrite or not row.get("custom_batch_code")):
		row.custom_batch_code = details.batch_no
	if flt(details.mrp) and (overwrite or not flt(row.get("custom_mrp"))):
		row.custom_mrp = details.mrp
	if details.manufacturing_date and (overwrite or not row.get("custom_mfg_date")):
		row.custom_mfg_date = details.manufacturing_date
	if details.expiry_date and (overwrite or not row.get("custom_exp_date")):
		row.custom_exp_date = details.expiry_date


def _stock_entry_outward(doc, row):
	transfer = bool(row.get("t_warehouse"))
	lot = row.get(MB.FIELD)
	if not lot and transfer and row.t_warehouse == row.s_warehouse and row.get(MB.TO_FIELD):
		# Stock with no lot being given one in place (mrp_batch.assign_existing_stock).
		return
	if lot:
		details = _assert_lot_item(row, lot, _("Stock Entry"))
		_fill_stock_entry_text(row, details)
		if transfer and not row.get(MB.TO_FIELD) and row.t_warehouse != row.s_warehouse:
			row.set(MB.TO_FIELD, lot)
		return
	if not MB.has_lots(row.item_code, row.s_warehouse):
		return
	stock_qty = flt(row.get("transfer_qty")) or flt(row.qty) * (flt(row.get("conversion_factor")) or 1.0)
	plan = MB.allocate(
		row.item_code,
		row.s_warehouse,
		stock_qty,
		prefer_mrp=row.get("custom_mrp"),
		prefer_batch=row.get("custom_batch_code"),
	)
	if not plan or abs(sum(q for _l, q in plan) - stock_qty) > 1e-6:
		# Not enough in the warehouse at all: ERPNext's own stock check says so, in its words.
		return
	if len(plan) == 1 and plan[0][0] is None:
		return

	factor = _box_factor(row.item_code)
	typed = _typed_text(row)

	def fix(target, part):
		target.set("transfer_qty", flt(part, 6))
		if target.meta.has_field("custom_box") and factor:
			target.custom_box = cint(round(part / factor))
		if transfer and target.t_warehouse != target.s_warehouse:
			target.set(MB.TO_FIELD, target.get(MB.FIELD))
		# Each part starts from what was typed and takes its own lot's batch, MRP and dates.
		target.update(typed)
		_fill_stock_entry_text(target, _lot_fields(target.get(MB.FIELD)), overwrite=True)

	MB.split_rows(doc, "items", row, plan, "qty", None, on_copy=fix)


# --------------------------------------------------------------- Pick List


def _so_line_mrp(row):
	if not row.get("sales_order_item"):
		return 0.0
	return flt(frappe.db.get_value("Sales Order Item", row.sales_order_item, "custom_customer_mrp"))


def pick_list_before_validate(doc, method=None):
	if not MB.enabled() or cint(doc.docstatus) == 2:
		return
	if not doc.meta.get_field("locations") or not frappe.get_meta("Pick List Item").has_field(MB.FIELD):
		return
	# Lots are taken when the Pick List is submitted, not while it is a draft: the Pick List
	# screen writes its quantities onto the rows after inserting the draft (pick_list_entry.
	# _build_pick_list_from_mapping), matched by order line, which would undo a split made
	# earlier, and a draft should not hold stock from other orders.
	submitting = doc.get("_action") == "submit"
	for row in list(doc.get("locations") or []):
		if not row.item_code or not row.get("warehouse") or not flt(row.get("qty")):
			continue
		lot = row.get(MB.FIELD)
		if lot:
			details = _assert_lot_item(row, lot, _("Pick List"))
			_fill_pick_list_text(row, details)
			continue
		if not submitting or not MB.has_lots(row.item_code, row.warehouse):
			continue
		stock_qty = flt(row.get("stock_qty")) or flt(row.qty) * (flt(row.get("conversion_factor")) or 1.0)
		plan = MB.allocate(
			row.item_code,
			row.warehouse,
			stock_qty,
			prefer_mrp=_so_line_mrp(row),
			prefer_batch=row.get("custom_batch_code"),
			exclude_pick_lists=[doc.name] if doc.name else [],
		)
		if not plan or abs(sum(q for _l, q in plan) - stock_qty) > 1e-6:
			continue
		if len(plan) == 1 and plan[0][0] is None:
			continue
		factor = _box_factor(row.item_code)
		typed = _typed_text(row)

		def fix(target, part, factor=factor, typed=typed):
			target.picked_qty = target.qty
			if target.meta.has_field("custom_box"):
				target.custom_box = flt(part / factor, 2) if factor else target.get("custom_box")
			# A part with no lot is stock from before lots: it keeps what was typed, not the
			# batch of the lot the part before it took.
			target.update(typed)
			_fill_pick_list_text(target, _lot_fields(target.get(MB.FIELD)), overwrite=True)

		ordered = flt(row.get("custom_ordered_qty"))
		parts = MB.split_rows(doc, "locations", row, plan, "qty", "stock_qty", on_copy=fix)
		if ordered and len(parts) > 1:
			# The order line's quantity is shared out, not repeated: each part ordered what it
			# picks, and the last keeps any real shortfall (and the remark that explains it).
			left = ordered
			for part in parts[:-1]:
				part.custom_ordered_qty = min(flt(part.qty), left)
				left -= part.custom_ordered_qty
			parts[-1].custom_ordered_qty = max(left, 0)


def _fill_pick_list_text(row, details, overwrite=False):
	"""The lot is what was picked, so its batch and dates are what the paperwork shows."""
	if not details:
		return
	if details.batch_no and (overwrite or row.get("custom_batch_code") != details.batch_no):
		row.custom_batch_code = details.batch_no
	if details.manufacturing_date and row.meta.has_field("custom_mfg_date"):
		row.custom_mfg_date = details.manufacturing_date
	if details.expiry_date and row.meta.has_field("custom_expiry_date"):
		row.custom_expiry_date = details.expiry_date
	if row.meta.has_field("custom_lot_mrp"):
		row.custom_lot_mrp = details.mrp


def pick_list_validate(doc, method=None):
	"""A lot named on the Pick List must still have that much free when it is submitted."""
	if not MB.enabled() or cint(doc.docstatus) != 1 or doc.get("_action") != "submit":
		return
	need = {}
	for row in doc.get("locations") or []:
		lot = row.get(MB.FIELD)
		if lot and row.get("warehouse"):
			key = (row.item_code, row.warehouse, lot)
			need[key] = flt(need.get(key)) + (flt(row.get("stock_qty")) or flt(row.qty))
	for (item_code, warehouse, lot), qty in need.items():
		lots, _free = MB.available(item_code, warehouse, exclude_pick_lists=[doc.name])
		free = next((d.qty for d in lots if d.lot == lot), 0.0)
		if qty - free > 1e-6:
			frappe.throw(
				_("{0} has only {1} of {2} free in {3}; this Pick List takes {4}. Choose another Batch / MRP for the rest.").format(
					frappe.bold(MB.describe(lot)), flt(free), item_code, warehouse, flt(qty)
				),
				title=_("Batch / MRP Short"),
			)


def saved_row_lot(item, item_data):
	"""{mrp_batch, custom_lot_mrp} to store on a Pick List row the Pick List screen saves.

	The screen writes rows straight to the database, so nothing re-checks the lot there. A
	lot is kept while it still fits what the row says: the batch typed on it and a quantity
	no larger than before. Otherwise it is cleared and chosen again at submit
	(pick_list_before_validate), the typed batch first. Empty when lots are not set up."""
	if not MB.enabled() or not frappe.get_meta("Pick List Item").has_field(MB.FIELD):
		return {}
	chosen = item_data.get(MB.FIELD) if MB.FIELD in item_data else item.get(MB.FIELD)
	lot = chosen or None
	details = MB.lot_details([lot]).get(lot) if lot else None
	if details and details.item_code != item.item_code:
		details = None
	typed = MB.clean_batch(item_data.get("custom_batch_code") or item_data.get("batch_no")).lower()
	if details and typed and typed != (details.batch_no or "").lower():
		details = None
	if details and lot == item.get(MB.FIELD) and flt(item_data.get("qty")) - flt(item.qty) > 1e-6:
		# More than the lot was chosen for, and nobody chose again: let submit decide.
		details = None
	return {MB.FIELD: details.name if details else None, "custom_lot_mrp": flt(details.mrp) if details else None}


def lot_display(rows):
	"""Batch / MRP of each Pick List row for the screen, with the order line's MRP beside it."""
	if not MB.enabled():
		return
	details = MB.lot_details([r.get(MB.FIELD) for r in rows if r.get(MB.FIELD)])
	so_items = [r.get("sales_order_item") for r in rows if r.get("sales_order_item")]
	order_mrp = dict(
		frappe.get_all("Sales Order Item", {"name": ("in", so_items)}, ["name", "custom_customer_mrp"], as_list=True)
	) if so_items and frappe.get_meta("Sales Order Item").has_field("custom_customer_mrp") else {}
	for row in rows:
		d = details.get(row.get(MB.FIELD))
		row["lot_title"] = (d.title or d.name) if d else ""
		row["lot_mrp"] = flt(d.mrp) if d else 0
		row["lot_batch"] = (d.batch_no or "") if d else ""
		row["order_mrp"] = flt(order_mrp.get(row.get("sales_order_item")))


@frappe.whitelist()
def get_lot_options(item_code, warehouse, pick_list=None, sales_order_item=None):
	"""Lots of `item_code` with free stock in `warehouse`, for the Pick List's Batch / MRP pick."""
	frappe.has_permission("Pick List", "read", throw=True)
	lots, unassigned = MB.available(item_code, warehouse, exclude_pick_lists=[pick_list] if pick_list else [])
	order_mrp = flt(frappe.db.get_value("Sales Order Item", sales_order_item, "custom_customer_mrp")) if sales_order_item else 0.0
	return {
		"order_mrp": order_mrp,
		"unassigned": unassigned,
		"lots": [
			{
				"lot": d.lot,
				"batch_no": d.batch_no,
				"mrp": flt(d.mrp),
				"manufacturing_date": d.manufacturing_date,
				"expiry_date": d.expiry_date,
				"title": d.title,
				"qty": flt(d.qty),
				"mrp_matches": (not order_mrp) or flt(d.mrp, 2) == flt(order_mrp, 2),
			}
			for d in lots
		],
	}


# ----------------------------------------------------------- Delivery Note


def delivery_note_before_validate(doc, method=None):
	"""A row not from a Pick List takes one lot, or stock with no lot, by itself.

	Rows from a Pick List carry the Pick List row's lot (delivery_note_hooks), and are not
	split here: the Delivery Note keeps one row per picked row."""
	if not MB.enabled() or cint(doc.docstatus) == 2:
		return
	if cint(doc.get("is_return")):
		_return_rows_take_their_lot(doc, "Delivery Note Item", "dn_detail", (MB.FIELD,))
		for row in doc.get("items") or []:
			if row.item_code and row.get(MB.FIELD):
				_assert_lot_item(row, row.get(MB.FIELD), _("Delivery Note"))
		return
	for row in doc.get("items") or []:
		if not row.item_code or not row.get("warehouse") or not flt(row.get("qty")):
			continue
		if row.get(MB.FIELD):
			_assert_lot_item(row, row.get(MB.FIELD), _("Delivery Note"))
			continue
		if row.get("pick_list_item"):
			continue
		if not MB.has_lots(row.item_code, row.warehouse):
			continue
		stock_qty = flt(row.get("stock_qty")) or flt(row.qty) * (flt(row.get("conversion_factor")) or 1.0)
		plan = MB.allocate(
			row.item_code,
			row.warehouse,
			stock_qty,
			prefer_mrp=flt(frappe.db.get_value("Sales Order Item", row.so_detail, "custom_customer_mrp")) if row.get("so_detail") else 0,
			prefer_batch=row.get("custom_batch_code"),
		)
		if len(plan) == 1 and abs(plan[0][1] - stock_qty) <= 1e-6:
			row.set(MB.FIELD, plan[0][0])


# ------------------------------------------------------------ GRN (Purchase Receipt)


def purchase_receipt_before_validate(doc, method=None):
	"""A GRN row's stock goes into the Batch / MRP its own batch and MRP name.

	grn.py sets the lot when it maps the inward, and this keeps it right when the batch or
	the MRP is corrected on the draft GRN. Accepted (or quarantined) and rejected stock of a
	row are the same goods, so both sides take the same lot. Only GRNs raised from a
	Purchase Inward are touched; a receipt keyed in by hand keeps whatever lot it names."""
	if not MB.enabled() or cint(doc.docstatus) != 0 or not frappe.get_meta("Purchase Receipt Item").has_field(MB.FIELD):
		return
	if cint(doc.get("is_return")):
		_return_rows_take_their_lot(doc, "Purchase Receipt Item", "purchase_receipt_item", (MB.FIELD, MB.REJECTED_FIELD))
		return
	if not doc.get("custom_purchase_inward"):
		return
	for row in doc.get("items") or []:
		if not row.item_code:
			continue
		batch = row.get("custom_internal_batch_no") or row.get("batch_no")
		if MB.clean_batch(batch) or flt(row.get("custom_mrp")):
			src = frappe._dict()
			if row.get("custom_purchase_inward_item"):
				src = frappe.db.get_value(
					"Purchase Inward Item", row.custom_purchase_inward_item,
					["manufacturing_date", "expiry_date", "purchase_rate"], as_dict=True,
				) or frappe._dict()
			row.set(MB.FIELD, MB.get_or_create(
				row.item_code, batch, row.get("custom_mrp"), src.manufacturing_date, src.expiry_date,
				source="Purchase Inward", supplier=doc.supplier,
				purchase_inward=doc.custom_purchase_inward, purchase_rate=flt(row.rate),
				reference_doctype="Purchase Inward", reference_name=doc.custom_purchase_inward,
			))
		if row.get(MB.FIELD):
			_assert_lot_item(row, row.get(MB.FIELD), _("GRN"))
		row.set(MB.REJECTED_FIELD, row.get(MB.FIELD) if flt(row.get("rejected_qty")) > 0 else None)



# ---------------------------------------------------------------- returns


def _return_rows_take_their_lot(doc, child_doctype, link_field, fields):
	"""A return brings back the goods of the row it returns, so it takes that row's Batch /
	MRP, whatever the return row was left with: "Create Return" copies it, but a cleared or
	changed one would put the stock back into the wrong lot, or into none."""
	for row in doc.get("items") or []:
		if not row.get(link_field):
			continue
		original = frappe.db.get_value(child_doctype, row.get(link_field), list(fields), as_dict=True)
		if original is None:
			continue
		for field in fields:
			row.set(field, original.get(field) or None)
