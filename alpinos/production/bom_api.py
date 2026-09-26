"""Server side of the BOM Master screens.

Saving is done here rather than from the client because two things have to be true of
every BOM this screen writes, and neither should be re-derived by a browser:

    * Base Batch Size is 1. The grid quantities ARE one batch, so the number is not a
      variable the recipe writer sets -- the screen shows it read-only and this enforces it.
    * Only one BOM per finished good is the default. ERPNext already enforces this in
      manage_default_bom(), but only on submit/cancel -- two DRAFTS can both carry the
      tick until one is submitted. Production reads drafts, so it is enforced here too.

On the UOM: the BRD asks for "Batch", but BOM.uom is not a free field. ERPNext's
validate_main_item() overwrites it with the FG item's stock UOM on every save, and the
quantity maths downstream assumes the two agree -- so forcing "Batch" would either be
silently reverted or break the conversion. "One batch" is carried by Base Batch Size = 1
instead, and the screen shows the real UOM read-only rather than a label that lies.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint, flt

from alpinos.production import constants as C
from alpinos.production.bom_fields import MATERIAL_TYPE_FIELD, STAGE_FIELD, VARIATION_FIELD
from alpinos.production.bom_rules import (
	SYREP_ONLY_FIELDS,
	assert_not_used_by_open_order as _assert_not_used_by_open_order,
	item_material_type as _item_material_type,
)

DOCTYPE = "BOM"

LIST_FIELDS = (
	"name",
	"item",
	"item_name",
	"quantity",
	"uom",
	"is_active",
	"is_default",
	"docstatus",
	"modified",
	VARIATION_FIELD,
)

ROW_FIELDS = ("item_code", "qty", "uom", STAGE_FIELD, MATERIAL_TYPE_FIELD,
              "custom_time", "custom_temp", "custom_fan_speed")


#: Page sizes the screen offers. Same contract as the Item list, which had to be fixed
#: after silently showing 200 of 231 items with nothing saying so.
PAGE_LENGTHS = (50, 100, 200)
DEFAULT_PAGE_LENGTH = 50


@frappe.whitelist()
def get_list(search=None, fg_item=None, is_active=None, start=0,
             page_length=DEFAULT_PAGE_LENGTH, limit=None):
	"""One page of BOMs, with the line count per recipe.

	`limit` is still accepted so an older caller keeps working; it sets the page size.
	"""
	frappe.has_permission(DOCTYPE, "read", throw=True)

	start = max(cint(start), 0)
	page_length = cint(page_length) or cint(limit) or DEFAULT_PAGE_LENGTH
	page_length = min(max(page_length, 1), max(PAGE_LENGTHS))

	filters = {"docstatus": ("<", 2)}
	if fg_item:
		filters["item"] = fg_item
	if is_active not in (None, "", "All"):
		filters["is_active"] = cint(is_active)

	or_filters = None
	if search:
		like = f"%{search}%"
		or_filters = {
			"name": ("like", like),
			"item": ("like", like),
			"item_name": ("like", like),
			VARIATION_FIELD: ("like", like),
		}

	count_rows = frappe.get_list(
		DOCTYPE, fields=["count(name) as total"], filters=filters,
		or_filters=or_filters, limit_page_length=0,
	)
	total = cint(count_rows[0].get("total")) if count_rows else 0

	# One more than asked for, so "is there another page" needs no second query.
	rows = frappe.get_list(
		DOCTYPE,
		filters=filters,
		or_filters=or_filters,
		fields=list(LIST_FIELDS),
		order_by="modified desc",
		limit_start=start,
		limit_page_length=page_length + 1,
	)
	has_more = len(rows) > page_length
	rows = rows[:page_length]

	def _envelope(data):
		return {
			"data": data, "has_more": int(has_more), "start": start,
			"page_length": page_length, "total": total,
			"page_lengths": list(PAGE_LENGTHS),
		}

	if not rows:
		return _envelope([])

	# How many lines each recipe has, so the list can show the size of a BOM without
	# loading every child row.
	counts = frappe.get_all(
		"BOM Item",
		filters={"parent": ("in", [r["name"] for r in rows]), "parenttype": DOCTYPE},
		# NOT "as lines": `lines` is a reserved word in MariaDB and the query dies with a
		# syntax error, which surfaces as an empty list rather than as anything readable.
		fields=["parent", "count(name) as line_count"],
		group_by="parent",
	)
	by_parent = {c["parent"]: c["line_count"] for c in counts}
	for row in rows:
		row["line_count"] = by_parent.get(row["name"], 0)
	return _envelope(rows)


@frappe.whitelist()
def get_form_context(bom=None):
	if bom and frappe.db.exists(DOCTYPE, bom):
		doc = frappe.get_doc(DOCTYPE, bom)
		doc.check_permission("read")
		data = doc.as_dict()
		can_write = frappe.has_permission(DOCTYPE, "write", doc=doc) and cint(doc.docstatus) == 0
	else:
		doc = None
		data = None
		frappe.has_permission(DOCTYPE, "read", throw=True)
		can_write = frappe.has_permission(DOCTYPE, "create")

	return {
		"doc": data,
		"can_write": bool(can_write),
		"can_submit": bool(doc and cint(doc.docstatus) == 0
		                   and frappe.has_permission(DOCTYPE, "submit", doc=doc)),
		"docstatus": cint(doc.docstatus) if doc else 0,
		"process_stages": list(C.BOM_PROCESS_STAGES),
		"material_types": list(C.BOM_MATERIAL_TYPES),
		"base_batch_size": C.BOM_BASE_BATCH_SIZE,
	}


@frappe.whitelist()
def get_item_details(item_code):
	"""UOM and name for a recipe line, fetched from the Item Master as the grid is filled."""
	frappe.has_permission("Item", "read", throw=True)
	row = frappe.db.get_value(
		"Item", item_code, ["item_name", "stock_uom"], as_dict=True
	)
	if not row:
		return {}
	return {
		"item_name": row.item_name,
		"uom": row.stock_uom,
		# The Item Master decides the classification; the grid only displays it.
		"material_type": _item_material_type(item_code),
	}


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def fg_item_query(doctype, txt, searchfield, start, page_len, filters):
	"""Items an FG picker may offer: a Finished Good, or one not classified yet.

	The second half is not laxness. 226 of the 233 items on this bench have no Material
	Type -- offering FG only would leave the picker with a handful of entries and no way to
	reach a real product, and back-filling the catalogue is off the table. The server
	refuses a wrong type on save and lets a blank one through the same way, so the picker
	and the rule agree.

	Written as SQL because the rule is "= FG OR IS NULL OR = ''", and expressing the empty
	half as `("in", ("FG", ""))` would rely on frappe treating '' inside `in` as also
	matching NULL -- true today, surprising, and the source of a past data loss here.
	"""
	return _item_query_by_type(txt, start, page_len, C.MATERIAL_FG, include_fg=True)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def component_item_query(doctype, txt, searchfield, start, page_len, filters):
	"""Items a recipe ROW may offer: anything that is not a Finished Good.

	The mirror of `fg_item_query`, and unclassified items are offered for the same reason.
	Written as SQL for the same reason too: `!= 'FG'` would also drop every NULL, which is
	almost every item here.
	"""
	return _item_query_by_type(txt, start, page_len, C.MATERIAL_FG, include_fg=False)


def _item_query_by_type(txt, start, page_len, material_type, include_fg):
	comparison = "=" if include_fg else "!="
	txt = f"%{txt or ''}%"
	return frappe.db.sql(
		f"""
		select name, item_name
		from `tabItem`
		where disabled = 0
		  and (custom_material_type {comparison} %(mt)s
		       or ifnull(custom_material_type, '') = '')
		  and (name like %(txt)s or item_name like %(txt)s)
		order by
			case when custom_material_type {comparison} %(mt)s then 0 else 1 end,
			name asc
		limit %(start)s, %(page_len)s
		""",
		{"mt": material_type, "txt": txt, "start": cint(start),
		 "page_len": cint(page_len) or 20},
	)


def _clear_other_defaults(bom_name, fg_item):
	"""One default BOM per finished good, drafts included.

	ERPNext's manage_default_bom() does this on submit/cancel only, and its lookup filters
	docstatus=1 -- so two drafts could both sit ticked, and whichever was submitted last
	would silently win. Production reads draft BOMs, so the rule is applied on save.
	"""
	others = frappe.get_all(
		DOCTYPE,
		filters={"item": fg_item, "is_default": 1, "docstatus": ("<", 2)},
		pluck="name",
	)
	for other in others:
		if other != bom_name:
			frappe.db.set_value(DOCTYPE, other, "is_default", 0, update_modified=False)


@frappe.whitelist()
def save_bom(payload):
	if isinstance(payload, str):
		payload = json.loads(payload or "{}")
	payload = payload or {}

	name = (payload.get("name") or "").strip()

	if name:
		doc = frappe.get_doc(DOCTYPE, name)
		doc.check_permission("write")
		if cint(doc.docstatus) != 0:
			frappe.throw(_("Only a draft BOM can be changed."), title=_("BOM Not Editable"))
	else:
		frappe.has_permission(DOCTYPE, "create", throw=True)
		doc = frappe.new_doc(DOCTYPE)

	fg_item = payload.get("item")
	if not fg_item:
		frappe.throw(_("Please choose the Finished Good this recipe makes."),
		             title=_("FG Item Required"))

	variation = (payload.get(VARIATION_FIELD) or "").strip()
	if not variation:
		frappe.throw(
			_("Please name this recipe, so it can be told apart from other BOMs for the same item."),
			title=_("BOM Variation Name Required"),
		)

	doc.item = fg_item
	doc.set(VARIATION_FIELD, variation)
	# Locked to one batch: the grid quantities are the recipe for exactly one. The UOM is
	# not set here -- ERPNext takes it from the FG item and would overwrite anything else.
	doc.quantity = C.BOM_BASE_BATCH_SIZE
	doc.is_active = cint(payload.get("is_active", 1))
	doc.is_default = cint(payload.get("is_default", 0))
	if not doc.company:
		doc.company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
			"Global Defaults", "default_company"
		)

	rows = payload.get("items") or []
	if not rows:
		frappe.throw(_("Add at least one material to the recipe."), title=_("No Materials"))

	doc.set("items", [])
	for row in rows:
		if not row.get("item_code"):
			continue
		child = doc.append("items", {})
		for field in ROW_FIELDS:
			child.set(field, row.get(field))
		child.qty = flt(row.get("qty"))
		# The rules are NOT applied here any more. doc.save() runs them through the BOM
		# validate hook (alpinos.production.bom_rules), so this screen, the desk form and
		# the REST API all get the same answer from one implementation.

	if not doc.get("items"):
		frappe.throw(_("Add at least one material to the recipe."), title=_("No Materials"))

	doc.save()
	if cint(doc.is_default):
		_clear_other_defaults(doc.name, doc.item)
	frappe.db.commit()
	return {"name": doc.name}


@frappe.whitelist()
def submit_bom(bom):
	doc = frappe.get_doc(DOCTYPE, bom)
	doc.check_permission("submit")
	doc.submit()
	if cint(doc.is_default):
		_clear_other_defaults(doc.name, doc.item)
	frappe.db.commit()
	return {"name": doc.name, "docstatus": doc.docstatus}
