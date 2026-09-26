"""Server side of the Item Master screens.

Saving goes through here rather than straight to `frappe.client.save` for one reason:
Default Warehouse and Preferred Supplier are not fields on Item. They live in the
`item_defaults` child table, one row per company, and getting that row right (find the
company's row, create it if missing, leave every OTHER company's row alone) is not
something a screen should be reimplementing. Everything else is a plain field write, and
ERPNext's own Item.validate still runs on top of all of it.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint, flt

from alpinos.production import constants as C
from alpinos.production.item_fields import (
	ALLOWED_CATEGORIES_FIELD,
	HSN_FIELD,
	LEGACY_GST_PERCENT_FIELD,
	LOSS_PERCENT_FIELD,
	MATERIAL_CATEGORY_FIELD,
	MATERIAL_TYPE_FIELD,
	TARGET_SKU_NAME_FIELD,
)

#: The GST rate the screens show as "Tax Rate (GST %)".
#:
#: `custom_gst_percent`, not the `custom_tax_rate` this module once added: the percent field
#: pre-dates the module and 135 items already carry a real rate in it, while custom_tax_rate
#: held exactly one value and that was a test item. The two screens were already reading and
#: writing the percent field; this server was the only thing still on the other one, which is
#: why a rate typed into the form was accepted, silently dropped, and came back 0.
GST_FIELD = LEGACY_GST_PERCENT_FIELD

DOCTYPE = "Item"

#: Plain Item fields the screen owns. Anything not listed here it must not touch.
ITEM_FIELDS = (
	"item_name",
	"item_group",
	"description",
	"stock_uom",
	"purchase_uom",
	"sales_uom",
	"is_stock_item",
	"has_batch_no",
	"has_expiry_date",
	"shelf_life_in_days",
	"inspection_required_before_purchase",
	"lead_time_days",
	"disabled",
	MATERIAL_TYPE_FIELD,
	MATERIAL_CATEGORY_FIELD,
	HSN_FIELD,
	GST_FIELD,
	LOSS_PERCENT_FIELD,
	TARGET_SKU_NAME_FIELD,
)

#: The Item Master also SHOWS last_purchase_rate, labelled "Purchase Order Rate". It is
#: not listed above on purpose: get_form_context returns the whole document, so the screen
#: can read it, while save_item writes ITEM_FIELDS alone and therefore can never write it
#: back. Purchase Orders own that number (erpnext.buying.utils.update_last_purchase_rate
#: sets it on submit and puts it back on cancel), and a second column for the same figure
#: would drift the moment one writer missed an order.

LIST_FIELDS = (
	"name",
	"item_code",
	"item_name",
	"item_group",
	"stock_uom",
	"has_batch_no",
	"has_expiry_date",
	"shelf_life_in_days",
	"inspection_required_before_purchase",
	"disabled",
	MATERIAL_TYPE_FIELD,
	MATERIAL_CATEGORY_FIELD,
	HSN_FIELD,
	GST_FIELD,
)


def _default_company():
	return frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
		"Global Defaults", "default_company"
	)


def _defaults_row(doc, company):
	"""The item_defaults row for `company`, created empty if it is not there yet."""
	for row in doc.get("item_defaults") or []:
		if row.company == company:
			return row
	return doc.append("item_defaults", {"company": company})


#: Page sizes the screen offers, and the columns a header click may sort by. A sort field
#: that is not on this list falls back to the default rather than reaching the SQL.
PAGE_LENGTHS = (50, 100, 200)
DEFAULT_PAGE_LENGTH = 50

_SORTABLE = frozenset({
	"item_code",
	"item_name",
	"item_group",
	"stock_uom",
	"shelf_life_in_days",
	"modified",
	MATERIAL_TYPE_FIELD,
	MATERIAL_CATEGORY_FIELD,
	HSN_FIELD,
})


@frappe.whitelist()
def get_list(
	search=None,
	material_type=None,
	item_group=None,
	disabled=None,
	start=0,
	page_length=DEFAULT_PAGE_LENGTH,
	sort_field=None,
	sort_dir=None,
):
	"""One page of items for the Item Master list.

	Paged rather than capped: the previous version took a plain `limit` of 200 against a
	catalogue of 231, so the last 31 items were simply unreachable from the screen and
	nothing said so.
	"""
	frappe.has_permission(DOCTYPE, "read", throw=True)

	start = max(cint(start), 0)
	page_length = min(max(cint(page_length) or DEFAULT_PAGE_LENGTH, 1), max(PAGE_LENGTHS))

	filters = {}
	if material_type:
		filters[MATERIAL_TYPE_FIELD] = material_type
	if item_group:
		filters["item_group"] = item_group
	if disabled not in (None, "", "All"):
		filters["disabled"] = cint(disabled)

	or_filters = None
	if search:
		like = f"%{search}%"
		or_filters = {"item_code": ("like", like), "item_name": ("like", like)}

	sf = (sort_field or "").strip()
	sd = "asc" if str(sort_dir or "asc").lower() == "asc" else "desc"
	order_by = f"`{sf}` {sd}" if sf in _SORTABLE else "item_code asc"

	count_rows = frappe.get_list(
		DOCTYPE,
		fields=["count(name) as total"],
		filters=filters or None,
		or_filters=or_filters,
		limit_page_length=0,
	)
	total = cint(count_rows[0].get("total")) if count_rows else 0

	# One more than asked for, so "is there another page" needs no second query.
	rows = frappe.get_list(
		DOCTYPE,
		filters=filters or None,
		or_filters=or_filters,
		fields=list(LIST_FIELDS),
		order_by=order_by,
		limit_start=start,
		limit_page_length=page_length + 1,
	)
	has_more = len(rows) > page_length
	rows = rows[:page_length]

	return {
		"data": rows,
		"has_more": int(has_more),
		"start": start,
		"page_length": page_length,
		"total": total,
		"page_lengths": list(PAGE_LENGTHS),
	}


@frappe.whitelist()
def get_form_context(item=None):
	company = _default_company()
	if item and frappe.db.exists(DOCTYPE, item):
		doc = frappe.get_doc(DOCTYPE, item)
		doc.check_permission("read")
		row = None
		for default in doc.get("item_defaults") or []:
			if default.company == company:
				row = default
				break
		data = doc.as_dict()
		# Flattened onto the payload so the screen has one shape to bind to; they are
		# written back to the child row by save_item().
		data["default_warehouse"] = row.default_warehouse if row else None
		data["default_supplier"] = row.default_supplier if row else None
		# Flattened to a list of ids, which is what a MultiSelectPills control takes.
		data["allowed_filling_categories"] = [
			r.filling_process_category for r in doc.get(ALLOWED_CATEGORIES_FIELD) or []
		]
		can_write = frappe.has_permission(DOCTYPE, "write", doc=doc)
	else:
		doc = None
		data = None
		frappe.has_permission(DOCTYPE, "read", throw=True)
		can_write = frappe.has_permission(DOCTYPE, "create")

	return {
		"doc": data,
		"company": company,
		"can_write": bool(can_write),
		"material_types": list(C.ITEM_MATERIAL_TYPES),
		"material_categories": list(C.PM_CATEGORIES),
		"filling_categories": frappe.get_all(
			"Filling Process Category",
			filters={"is_active": 1},
			fields=["name", "category_name"],
			order_by="category_name asc",
		),
	}


@frappe.whitelist()
def save_item(payload):
	"""Create or update an Item from the Item Master screen.

	Only the fields in ITEM_FIELDS plus the two item_defaults values are written, so a
	screen that has never heard of an Item field cannot blank it.
	"""
	if isinstance(payload, str):
		payload = json.loads(payload or "{}")
	payload = payload or {}

	name = (payload.get("name") or "").strip()
	company = _default_company()

	if name:
		doc = frappe.get_doc(DOCTYPE, name)
		doc.check_permission("write")
	else:
		item_code = (payload.get("item_code") or "").strip()
		if not item_code:
			frappe.throw(_("Please enter the Item SKU Code."), title=_("SKU Code Required"))
		if frappe.db.exists(DOCTYPE, item_code):
			frappe.throw(
				_("Item {0} already exists.").format(item_code), title=_("Duplicate Item")
			)
		frappe.has_permission(DOCTYPE, "create", throw=True)
		doc = frappe.new_doc(DOCTYPE)
		doc.item_code = item_code

	# IM-06, the half the doctype cannot see: shelf life and lead time are Int fields, so
	# 2.5 has already been truncated to 2 by the time Item.validate runs. The raw payload
	# is the only place a decimal is still visible.
	for field, label in (("shelf_life_in_days", _("Shelf Life")),
	                     ("lead_time_days", _("Lead Time"))):
		raw = payload.get(field)
		if raw in (None, ""):
			continue
		if flt(raw) != int(flt(raw)):
			frappe.throw(
				_("{0} must be a whole number of days.").format(label),
				title=_("Invalid {0}").format(label),
			)

	for field in ITEM_FIELDS:
		if field in payload:
			doc.set(field, payload.get(field))

	# The Material Category rule (required for PM, cleared otherwise) is applied by the
	# Item validate hook, so it holds for every writer rather than just this one.

	# A finished good is the only thing that runs on a filling line, so the categories are
	# replaced wholesale for an FG and cleared for anything else -- a leftover list on an
	# item that stopped being FG would still satisfy the handshake in filling.py.
	if "allowed_filling_categories" in payload:
		doc.set(ALLOWED_CATEGORIES_FIELD, [])
		if doc.get(MATERIAL_TYPE_FIELD) == C.MATERIAL_FG:
			for category in payload.get("allowed_filling_categories") or []:
				if category:
					doc.append(ALLOWED_CATEGORIES_FIELD, {"filling_process_category": category})

	if company and ("default_warehouse" in payload or "default_supplier" in payload):
		row = _defaults_row(doc, company)
		if "default_warehouse" in payload:
			row.default_warehouse = payload.get("default_warehouse") or None
		if "default_supplier" in payload:
			row.default_supplier = payload.get("default_supplier") or None

	# IM-01 is not enforced on every Item insert in the system -- see
	# item_rules._material_type_is_required. This screen is the path that must enforce it,
	# so it says so outright instead of leaving the rule to infer it.
	frappe.flags.alpinos_item_master = True
	try:
		doc.save()
	finally:
		frappe.flags.alpinos_item_master = False
	frappe.db.commit()
	return {"name": doc.name, "item_code": doc.item_code}
