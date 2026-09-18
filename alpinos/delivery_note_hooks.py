"""Server-side sync + validation for Alpinos Delivery Note customizations."""

from math import ceil

import frappe
from frappe.utils import flt


def strip_non_batch_item_batches(doc, method=None):
	"""before_validate: keep batch_no only on batch-tracked items with a real Batch master (typed code stays in custom_batch_code)."""
	if doc.get("is_return"):
		return
	meta_dn_item = frappe.get_meta("Delivery Note Item")
	has_code_field = bool(meta_dn_item.get_field("custom_batch_code"))
	for row in doc.get("items") or []:
		if not row.get("batch_no"):
			continue
		non_batch_item = row.get("item_code") and not frappe.db.get_value(
			"Item", row.item_code, "has_batch_no"
		)
		if non_batch_item or not frappe.db.exists("Batch", row.batch_no):
			if has_code_field and not row.get("custom_batch_code"):
				row.custom_batch_code = row.batch_no
			row.batch_no = None


def validate_delivery_note(doc, method=None):
	if doc.get("is_return"):
		return

	_sync_sales_order_header(doc)
	_sync_items_from_pick_list(doc)
	_align_value_with_sales_order(doc)
	_recalc_dn_totals(doc)
	_validate_dn_mandatory(doc)


def _sync_sales_order_header(doc):
	so_names = [row.against_sales_order for row in (doc.items or []) if row.against_sales_order]
	if not so_names:
		return

	primary_so = so_names[0]
	if not doc.get("custom_sales_order_id"):
		doc.custom_sales_order_id = primary_so

	if doc.get("custom_sales_order_id"):
		cname = frappe.db.get_value("Sales Order", doc.custom_sales_order_id, "customer_name")
		if cname:
			doc.custom_dn_so_customer_name = cname


def _pick_list_item_fields():
	meta = frappe.get_meta("Pick List Item")
	fields = ["batch_no", "item_code", "picked_qty", "qty"]
	for fname in ("custom_box", "custom_mfg_date", "custom_expiry_date", "custom_batch_code"):
		if meta.get_field(fname):
			fields.append(fname)
	return fields


def _box_factor(item_code):
	if not item_code:
		return None
	v = frappe.db.get_value(
		"UOM Conversion Detail",
		{"parent": item_code, "parenttype": "Item", "uom": "Box"},
		"conversion_factor",
	)
	return flt(v) if v else None


def _sync_items_from_pick_list(doc):
	pl_fields = _pick_list_item_fields()
	meta_dn_item = frappe.get_meta("Delivery Note Item")

	for row in doc.items or []:
		if not row.get("against_pick_list") or not row.get("pick_list_item"):
			continue

		pli = frappe.db.get_value("Pick List Item", row.pick_list_item, pl_fields, as_dict=True)
		if not pli:
			continue

		if pli.get("custom_box") is not None and meta_dn_item.get_field("custom_box"):
			row.custom_box = flt(pli.get("custom_box"))
		elif row.item_code and row.qty:
			f = _box_factor(row.item_code) or 1
			row.custom_box = ceil(flt(row.qty) / f) if flt(row.qty) else 0

		# free-text batch code always travels with the row; batch_no (Link) only for
		# batch-tracked items with a real Batch master, else DN batch validation fails on submit
		if pli.get("custom_batch_code") and meta_dn_item.get_field("custom_batch_code"):
			row.custom_batch_code = pli.get("custom_batch_code")

		has_batch = row.item_code and frappe.db.get_value("Item", row.item_code, "has_batch_no")
		if not has_batch:
			row.batch_no = None
		elif pli.get("batch_no"):
			row.batch_no = pli.get("batch_no")

		if meta_dn_item.get_field("custom_mfg_date"):
			if pli.get("custom_mfg_date"):
				row.custom_mfg_date = pli.get("custom_mfg_date")
			elif row.batch_no:
				row.custom_mfg_date = frappe.db.get_value("Batch", row.batch_no, "manufacturing_date")

		if meta_dn_item.get_field("custom_expiry_date"):
			if pli.get("custom_expiry_date"):
				row.custom_expiry_date = pli.get("custom_expiry_date")
			elif row.batch_no:
				row.custom_expiry_date = frappe.db.get_value("Batch", row.batch_no, "expiry_date")



# A Sales Order line's rate is its amount divided by the quantity and rounded to paise,
# so rate x qty can miss the amount by up to half a paisa per unit.
_ROUNDING_PER_UNIT = 0.005


def _align_value_with_sales_order(doc):
	"""Keep the Delivery Note's value on the Sales Order's own line amounts.

	A Sales Order line carries the amount the customer agreed, rounded once from the
	GST-inclusive price (alpinos.sales_order_api._apply_clean_gst_amounts), so the line
	amount is not always rate x qty -- the rate is that amount per unit, rounded to
	paise. ERPNext then rebuilds every Delivery Note line as rate x qty, which brings
	the dropped fraction back multiplied by the quantity and by GST, and a fully
	delivered order's Delivery Note stops totalling what its Sales Order does.

	So put the Sales Order's own figure back on the line -- the delivered share of it on
	a part delivery -- and re-derive the totals from there. Only a gap the size of that
	rounding is closed: a line someone repriced, or a Sales Order whose discount is
	spread over the items, is left exactly as ERPNext calculated it.
	"""
	if doc.get("is_return") or not (doc.get("items") or []):
		return

	# A discount applied on the Net Total is distributed into the item amounts, and an
	# inclusive tax is carried inside the rate: in both the line amount is no longer the
	# Sales Order's figure, so leave the whole document to ERPNext.
	if doc.get("discount_amount") and doc.get("apply_discount_on") != "Grand Total":
		return
	if any(t.get("included_in_print_rate") for t in (doc.get("taxes") or [])):
		return

	conversion_rate = flt(doc.get("conversion_rate")) or 1.0
	changed = False

	for row in doc.get("items") or []:
		if not row.get("so_detail"):
			continue
		so_row = frappe.db.get_value(
			"Sales Order Item", row.so_detail, ["qty", "amount"], as_dict=True
		)
		if not so_row or not flt(so_row.qty):
			continue

		expected = flt(flt(so_row.amount) * flt(row.qty) / flt(so_row.qty), 2)
		gap = expected - flt(row.amount)
		if abs(gap) < 0.005:
			continue
		# Anything larger than the rounding residue is a real difference, not this one.
		if abs(gap) > _ROUNDING_PER_UNIT * flt(row.qty) + 0.02:
			continue

		was_net = abs(flt(row.net_amount) - flt(row.amount)) < 0.005
		row.amount = expected
		row.base_amount = flt(expected * conversion_rate, 2)
		if was_net:
			row.net_amount = expected
			row.base_net_amount = row.base_amount
		changed = True

	if not changed:
		return

	total = flt(sum(flt(r.amount) for r in doc.items), 2)
	net_total = flt(sum(flt(r.net_amount) for r in doc.items), 2)
	doc.total = total
	doc.base_total = flt(total * conversion_rate, 2)
	doc.net_total = net_total
	doc.base_net_total = flt(net_total * conversion_rate, 2)

	# GST rows follow the corrected net total; any other charge keeps what ERPNext worked out.
	running = net_total
	total_taxes = 0.0
	for tax in doc.get("taxes") or []:
		if tax.charge_type == "On Net Total" and flt(tax.rate):
			tax_amount = flt(net_total * flt(tax.rate) / 100.0, 2)
		else:
			tax_amount = flt(tax.tax_amount)
		tax.tax_amount = tax_amount
		tax.base_tax_amount = flt(tax_amount * conversion_rate, 2)
		tax.tax_amount_after_discount_amount = tax_amount
		tax.base_tax_amount_after_discount_amount = tax.base_tax_amount
		running = flt(running + tax_amount, 2)
		tax.total = running
		tax.base_total = flt(running * conversion_rate, 2)
		total_taxes = flt(total_taxes + tax_amount, 2)

	doc.total_taxes_and_charges = total_taxes
	doc.base_total_taxes_and_charges = flt(total_taxes * conversion_rate, 2)

	grand = flt(net_total + total_taxes, 2)
	if flt(doc.get("additional_discount_percentage")) and doc.get("apply_discount_on") == "Grand Total":
		doc.discount_amount = flt(grand * flt(doc.additional_discount_percentage) / 100.0, 2)
		doc.base_discount_amount = flt(flt(doc.discount_amount) * conversion_rate, 2)
	if doc.get("apply_discount_on") == "Grand Total":
		grand = flt(grand - flt(doc.get("discount_amount")), 2)

	doc.grand_total = grand
	doc.base_grand_total = flt(grand * conversion_rate, 2)

	if doc.get("disable_rounded_total"):
		doc.rounded_total = doc.base_rounded_total = 0
		doc.rounding_adjustment = doc.base_rounding_adjustment = 0
	else:
		rounded = flt(round(grand), 2)
		doc.rounded_total = rounded
		doc.base_rounded_total = flt(rounded * conversion_rate, 2)
		doc.rounding_adjustment = flt(rounded - grand, 2)
		doc.base_rounding_adjustment = flt(doc.rounding_adjustment * conversion_rate, 2)

	if hasattr(doc, "set_total_in_words"):
		doc.set_total_in_words()


def _recalc_dn_totals(doc):
	total_boxes = 0.0
	total_units = 0.0
	gross = 0.0

	pl_gross_done = set()
	meta_pl = frappe.get_meta("Pick List")

	for row in doc.items or []:
		total_boxes += flt(row.get("custom_box"))
		total_units += flt(row.get("qty"))

		if row.get("against_pick_list") and meta_pl.get_field("custom_gross_weight"):
			pl = row.against_pick_list
			if pl and pl not in pl_gross_done:
				gross += flt(frappe.db.get_value("Pick List", pl, "custom_gross_weight"))
				pl_gross_done.add(pl)

	if frappe.get_meta("Delivery Note").get_field("custom_total_boxes"):
		doc.custom_total_boxes = total_boxes
	if frappe.get_meta("Delivery Note").get_field("custom_total_units_dn"):
		doc.custom_total_units_dn = total_units
	if frappe.get_meta("Delivery Note").get_field("custom_dn_order_gross_weight"):
		doc.custom_dn_order_gross_weight = gross


def _validate_dn_mandatory(doc):
	if doc.flags.ignore_mandatory:
		return

	if not doc.get("custom_sales_order_id"):
		frappe.throw("Sales Order ID is mandatory.")
	if not doc.get("custom_dn_so_customer_name"):
		frappe.throw("Customer Name is mandatory.")
	if not doc.get("custom_dispatch_date"):
		frappe.throw("Dispatch Date is mandatory.")
	if not doc.get("custom_delivery_date"):
		frappe.throw("Delivery Date is mandatory.")
	if not doc.get("custom_transporter_name"):
		frappe.throw("Transporter is mandatory.")
	if not doc.get("vehicle_no"):
		frappe.throw("Picklist PO No. is mandatory.")
	if doc.docstatus == 1 and doc.get("custom_lr_gr_no") in (None, ""):
		frappe.throw("LR No. (GR No.) is mandatory.")
	if not doc.get("custom_dispatch_from"):
		frappe.throw("Dispatch From is mandatory.")
	if not (doc.get("custom_dispatch_to") or []):
		frappe.throw("At least one Dispatch To row is required.")

	meta_dn_item = frappe.get_meta("Delivery Note Item")
	for row in doc.items or []:
		if not row.item_code:
			frappe.throw(f"Row #{row.idx}: SKU is mandatory.")
		if not flt(row.qty):
			frappe.throw(f"Row #{row.idx}: Quantity is mandatory.")
		# Box is no longer mandatory on the Delivery Note (per spec)
		has_batch_no = frappe.db.get_value("Item", row.item_code, "has_batch_no") if row.item_code else 0
		if has_batch_no:
			if not row.batch_no:
				frappe.throw(f"Row #{row.idx}: Batch No. is mandatory.")
			if meta_dn_item.get_field("custom_mfg_date") and not row.get("custom_mfg_date"):
				frappe.throw(f"Row #{row.idx}: MFG Date is mandatory.")
			if meta_dn_item.get_field("custom_expiry_date") and not row.get("custom_expiry_date"):
				frappe.throw(f"Row #{row.idx}: Expiry Date is mandatory.")
		# expiry must be on or after MFG when both are present
		if row.get("custom_mfg_date") and row.get("custom_expiry_date"):
			from frappe.utils import getdate
			if getdate(row.custom_expiry_date) < getdate(row.custom_mfg_date):
				frappe.throw(
					f"Row #{row.idx} ({row.item_code}): Expiry Date ({row.custom_expiry_date}) cannot be earlier than Manufacturing Date ({row.custom_mfg_date})."
				)
