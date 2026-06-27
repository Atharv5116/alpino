"""
Sales Order — simplified Desk view (Alpinos).

Uses Property Setters only (Customize Form-compatible). Exactly the field groups
requested stay visible via a strict whitelist: required ERPNext bookkeeping fields
stay hidden unless listed (defaults / server-side logic still populate them).

**Scheme vs damage:** `custom_scheme_item_table` (Sales Order Scheme Item) holds scheme
rows only (includes **Scheme** column). When **Additional Units — Damage** is checked,
`custom_additional_units_damage_items` (Sales Order Additional Units Item) holds damage
lines (no scheme column).

**Customer header:** ``insert_after`` Property Setters reorder name, type, billing and
shipping addresses, date, PO#, GSTIN, and delivery date into the agreed sequence, with
labels matching the print spec. All tab headers are hidden so this block appears on the
main Details scroll area. Offline Buyer fields are inserted after GSTIN in ``custom_fields.py``
so they no longer sit between Customer and Customer Name.

Rollback: ``rollback_sales_order_desk_customizations()`` (or migrate patch
``alpinos.patches.v1_0.revert_sales_order_desk_layout`` — remove ``after_migrate``
``setup_sales_order_form_layout`` *before* migrate or the hook will re-apply).

"""

import frappe


def setup_sales_order_form_layout():
	_apply_sales_order_field_visibility()
	_apply_sales_order_item_grid()
	_apply_marketing_freebie_grid()
	_apply_scheme_item_grid()
	_apply_additional_units_damage_item_grid()


def rollback_sales_order_desk_customizations():
	"""Undo layout Property Setters; restore Alpinos SO base setters (SKU labels, …)."""

	frappe.db.sql(
		"""
		DELETE FROM `tabProperty Setter`
		WHERE doc_type IN (
			'Sales Order', 'Sales Order Item',
			'Sales Order Marketing Freebie', 'Sales Order Scheme Item',
			'Sales Order Additional Units Item'
		)
		AND IFNULL(doctype_or_field, '') = 'DocField'
		AND property IN ('hidden', 'label', 'in_list_view', 'insert_after')
		"""
	)
	frappe.db.commit()
	from alpinos.sales_order_custom_fields import setup_sales_order_custom_fields

	setup_sales_order_custom_fields()
	frappe.clear_cache()


def _upsert_docfield_prop(doc_type, fieldname, prop, value, property_type="Check"):
	if not fieldname:
		return
	existing = frappe.db.exists(
		"Property Setter",
		{"doc_type": doc_type, "field_name": fieldname, "property": prop},
	)
	payload = dict(
		doctype="Property Setter",
		doctype_or_field="DocField",
		doc_type=doc_type,
		field_name=fieldname,
		property=prop,
		property_type=property_type,
		value=str(value),
	)
	if existing:
		ps = frappe.get_doc("Property Setter", existing)
		ps.value = str(value)
		ps.property_type = property_type
		ps.save(ignore_permissions=True)
	else:
		frappe.get_doc(payload).insert(ignore_permissions=True)


def _apply_sales_order_customer_header(meta):
	"""Ordered customer block + labels (matches print / business spec)."""

	sequence = [
		"customer",
		"customer_name",
		"order_type",
		"customer_address",
		"address_display",
		"shipping_address_name",
		"shipping_address",
		"transaction_date",
		"po_no",
		"tax_id",
		"delivery_date",
	]
	for i in range(1, len(sequence)):
		fname = sequence[i]
		pred = sequence[i - 1]
		if not meta.get_field(fname):
			continue
		_upsert_docfield_prop(
			"Sales Order",
			fname,
			"insert_after",
			pred,
			property_type="Data",
		)

	label_map = {
		"customer_name": "Customer Name",
		"customer_address": "Billing Address",
		"shipping_address_name": "Shipping Address",
		"transaction_date": "Date",
		"po_no": "Purchase Order #",
	}
	for fname, lbl in label_map.items():
		if not meta.get_field(fname):
			continue
		_upsert_docfield_prop("Sales Order", fname, "label", lbl, property_type="Data")


def _apply_sales_order_field_visibility():
	meta = frappe.get_meta("Sales Order")

	_apply_sales_order_customer_header(meta)

	# User-visible Sales Order canvas (actual fields — not wrappers).
	base_show_data = frozenset(
		{
			"customer",
			"customer_name",
			"order_type",
			"tax_id",
			"transaction_date",
			"delivery_date",
			"po_no",
			"customer_address",
			"address_display",
			"shipping_address_name",
			"shipping_address",
			"set_warehouse",
			"scan_barcode",
			"items",
			"custom_marketing_freebies",
			"custom_scheme_item_table",
			"custom_additional_units_damage",
			"custom_additional_units_damage_items",
			"total_qty",
			"total",
			"net_total",
			"total_taxes_and_charges",
			"grand_total",
			"rounding_adjustment",
			"rounded_total",
			"disable_rounded_total",
			"custom_cash_discount",
			"custom_cash_discount_amount",
		}
	)

	BACKEND_ONLY_HIDDEN = frozenset(
		{
			"naming_series",
			"company",
			"currency",
			"conversion_rate",
			"selling_price_list",
			"price_list_currency",
			"plc_conversion_rate",
		}
	)

	hide_always = frozenset(
		{
			"tax_category",
			"taxes_and_charges",
			"shipping_rule",
			"incoterm",
			"named_place",
			"column_break_38",
			"column_break_49",
			"section_break_40",
			"taxes",
			"other_charges_calculation",
			"sec_tax_breakup",
			"section_break_48",
			"apply_discount_on",
			"additional_discount_percentage",
			"discount_amount",
			"base_discount_amount",
			"coupon_code",
			"column_break_50",
			# Contact tab noise (billing/shipping handled via address fields kept above)
			"contact_person",
			"contact_display",
			"contact_mobile",
			"contact_email",
			"company_address_display",
			"company_address",
			# Optional / duplicated address blocks elsewhere on the DocType
			"dispatch_address_name",
			"dispatch_address",
			# Company-currency echoes (not requested on canvas)
			"base_total",
			"base_net_total",
			"base_total_taxes_and_charges",
			"base_grand_total",
			# Misc.
			"total_net_weight",
			"po_date",
			"territory",
			"ignore_pricing_rule",
			"pricing_rules",
			"campaign",
			"source",
			"reserve_stock",
			"group_same_items",
		}
	)

	KEEP_SECTION_BREAKS = frozenset(
		{
			"customer_section",
			# Keep address split wrapper visible for customer/shipping blocks.
			"col_break46",
			# Items ladder
			"sec_warehouse",
			"items_section",
			"section_break_31",
			# Totals ladder (charge rows hidden; totals still readable)
			"section_break_43",
			"totals",
			"custom_cash_discount_section",
			"custom_other_details_section",
		}
	)

	# Labels (totals / items area)
	_upsert_docfield_prop(
		"Sales Order",
		"order_type",
		"label",
		"Customer Type",
		property_type="Data",
	)
	_upsert_docfield_prop("Sales Order", "tax_id", "label", "GSTIN", property_type="Data")
	_upsert_docfield_prop(
		"Sales Order",
		"custom_other_details_section",
		"label",
		"Order Items Details",
		property_type="Data",
	)
	_upsert_docfield_prop(
		"Sales Order",
		"total_taxes_and_charges",
		"label",
		"Total GST Amount",
		property_type="Data",
	)
	_upsert_docfield_prop(
		"Sales Order",
		"total",
		"label",
		"Total Amount",
		property_type="Data",
	)
	_upsert_docfield_prop(
		"Sales Order",
		"net_total",
		"label",
		"Total Amount (Excl. GST)",
		property_type="Data",
	)

	# Keep Address & Contact tab visible so customer/billing/shipping block is reachable.
	for df in meta.fields:
		if df.fieldtype != "Tab Break" or not df.fieldname:
			continue
		hidden = "0" if df.fieldname == "contact_info" else "1"
		_upsert_docfield_prop("Sales Order", df.fieldname, "hidden", hidden, property_type="Check")

	for df in meta.fields:
		if df.fieldtype != "Section Break" or not df.fieldname:
			continue
		hidden = str(int(df.fieldname not in KEEP_SECTION_BREAKS))
		_upsert_docfield_prop("Sales Order", df.fieldname, "hidden", hidden, property_type="Check")

	for df in meta.fields:
		fn = df.fieldname
		if not fn or df.fieldtype in ("Tab Break", "Section Break", "Column Break"):
			continue

		if fn in BACKEND_ONLY_HIDDEN:
			_upsert_docfield_prop("Sales Order", fn, "hidden", "1", property_type="Check")
			continue
		if fn in hide_always:
			_upsert_docfield_prop("Sales Order", fn, "hidden", "1", property_type="Check")
			continue
		if fn in base_show_data:
			_upsert_docfield_prop("Sales Order", fn, "hidden", "0", property_type="Check")
		else:
			_upsert_docfield_prop("Sales Order", fn, "hidden", "1", property_type="Check")


def _apply_sales_order_item_grid():
	# Exact grid columns (Sr. No. → Amount); all others hidden; all eleven in list view.
	visible_ordered = [
		"idx",
		"custom_product_image",
		"item_code",
		"item_name",
		"qty",
		"custom_box",
		"custom_item_mrp",
		"custom_customer_mrp",
		"custom_flat_discount",
		"custom_offer",
		"custom_additional_discount",
		"amount",
	]
	visible = frozenset(visible_ordered)
	structural_ft = frozenset({"Section Break", "Column Break", "Tab Break", "Fold"})

	label_map = {
		"idx": "Sr. No.",
		"item_code": "SKU",
		"item_name": "Item Name",
		"qty": "Qty",
		"custom_product_image": "Product Image",
		"custom_flat_discount": "Flat Disc.%",
		"custom_offer": "Offer Disc.%",
		"custom_additional_discount": "Add. Disc.%",
		"custom_item_mrp": "MRP",
		"custom_customer_mrp": "Valuation Rate",
	}
	meta = frappe.get_meta("Sales Order Item")
	for fname, lbl in label_map.items():
		if not meta.get_field(fname):
			continue
		_upsert_docfield_prop("Sales Order Item", fname, "label", lbl, property_type="Data")

	for i in range(1, len(visible_ordered)):
		fname = visible_ordered[i]
		pred = visible_ordered[i - 1]
		if not meta.get_field(fname) or not meta.get_field(pred):
			continue
		_upsert_docfield_prop(
			"Sales Order Item",
			fname,
			"insert_after",
			pred,
			property_type="Data",
		)

	targets = {df.fieldname for df in meta.fields if df.fieldname}
	if meta.get_field("idx"):
		targets.add("idx")

	for fname in sorted(targets):
		df = meta.get_field(fname)
		ft = getattr(df, "fieldtype", None) or ""
		is_structural = ft in structural_ft
		show = fname in visible and not is_structural
		if is_structural:
			# Keep native section wrappers so row editor can render visible fields.
			continue
		_upsert_docfield_prop(
			"Sales Order Item",
			fname,
			"hidden",
			"0" if show else "1",
			property_type="Check",
		)
		_upsert_docfield_prop(
			"Sales Order Item",
			fname,
			"in_list_view",
			"1" if show else "0",
			property_type="Check",
		)


def _apply_marketing_freebie_grid():
	view = frozenset({"item_code", "item_name", "qty", "remarks"})
	meta = frappe.get_meta("Sales Order Marketing Freebie")
	_upsert_docfield_prop("Sales Order Marketing Freebie", "item_code", "label", "SKU", property_type="Data")
	for df in meta.fields:
		if not df.fieldname:
			continue
		_upsert_docfield_prop(
			"Sales Order Marketing Freebie",
			df.fieldname,
			"in_list_view",
			str(int(df.fieldname in view)),
			property_type="Check",
		)


def _apply_scheme_item_grid():
	view = frozenset({"item_code", "item_name", "qty", "scheme"})
	meta = frappe.get_meta("Sales Order Scheme Item")
	_upsert_docfield_prop("Sales Order Scheme Item", "item_code", "label", "SKU", property_type="Data")
	for df in meta.fields:
		if not df.fieldname:
			continue
		_upsert_docfield_prop(
			"Sales Order Scheme Item",
			df.fieldname,
			"in_list_view",
			str(int(df.fieldname in view)),
			property_type="Check",
		)


def _apply_additional_units_damage_item_grid():
	view = frozenset({"item_code", "item_name", "qty", "previous_order_id", "remarks"})
	if not frappe.db.exists("DocType", "Sales Order Additional Units Item"):
		return
	meta = frappe.get_meta("Sales Order Additional Units Item")
	_upsert_docfield_prop(
		"Sales Order Additional Units Item", "item_code", "label", "SKU", property_type="Data"
	)
	for df in meta.fields:
		if not df.fieldname:
			continue
		_upsert_docfield_prop(
			"Sales Order Additional Units Item",
			df.fieldname,
			"in_list_view",
			str(int(df.fieldname in view)),
			property_type="Check",
		)
