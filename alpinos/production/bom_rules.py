"""BOM rules, on the BOM itself rather than on the screen that happens to write it.

These used to live in `bom_api.save_bom`, which meant they held for the BOM Master screen
and for nothing else: the standard desk form, the REST API and a data import all went
straight past them. A BOM written from the desk form could name an RM item as the thing it
makes, list a finished good as an ingredient, carry rows with no Process Stage, or hold the
same material twice in one stage -- and the Job Card would then print it.

So they run on the `validate` hook instead, where every writer passes.

**Forward-only, deliberately.** This bench already holds BOMs that break the new rules: one
with no variation name, two rows with no stage, two rows whose item is an FG. Enforcing
retroactively would make those records unopenable and unsaveable, which the user has ruled
out. A rule therefore fires only for a row or a value that is NEW or CHANGED in this save;
an untouched legacy row is left exactly as it is. Correcting one is what triggers the rule,
which is the right moment for it.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

from alpinos.production import constants as C
from alpinos.production.bom_fields import (
	MATERIAL_TYPE_FIELD,
	STAGE_FIELD,
	VARIATION_FIELD,
)
from alpinos.production.item_fields import MATERIAL_TYPE_FIELD as ITEM_MATERIAL_TYPE

#: Machine settings belong to SYREP and nowhere else, so they are cleared rather than
#: refused: a row moved from SYREP to another stage would otherwise carry a stale "36 MIN"
#: that the Job Card would not print and nobody would notice.
SYREP_ONLY_FIELDS = ("custom_time", "custom_temp", "custom_fan_speed")

#: The row fields a change to which makes a legacy row "touched", and so subject to the
#: rules. Editing the quantity alone is not enough -- that must stay possible on an old row.
_ROW_RULE_FIELDS = ("item_code", STAGE_FIELD, MATERIAL_TYPE_FIELD)


def item_material_type(item_code):
	"""The item's production classification, in the recipe's shorter vocabulary."""
	if not item_code:
		return None
	value = frappe.db.get_value("Item", item_code, ITEM_MATERIAL_TYPE)
	return {
		C.MATERIAL_RM: C.BOM_MATERIAL_RM,
		C.MATERIAL_PM: C.BOM_MATERIAL_PM,
		C.MATERIAL_ADDITIVE: C.BOM_MATERIAL_ADDITIVE,
	}.get(value)


def _before(doc):
	return doc.get_doc_before_save() if not doc.is_new() else None


def _previous_rows(doc):
	"""The stored rows by their row name, for telling a new row from an old one."""
	before = _before(doc)
	if not before:
		return {}
	return {row.name: row for row in before.get("items") or []}


def _row_is_touched(row, previous):
	"""True when this row is new, or when a field the rules care about has changed."""
	old = previous.get(row.name)
	if not old:
		return True
	return any(
		(row.get(field) or "") != (old.get(field) or "") for field in _ROW_RULE_FIELDS
	)


# --------------------------------------------------------------- the parent

def _validate_fg_parent(doc):
	"""BOM-01. What a recipe MAKES has to be a finished good.

	An item with no Material Type at all is allowed through: 226 of the 233 items on this
	bench predate the field, and refusing them would leave the screen unusable until
	somebody back-filled the catalogue.
	"""
	if not doc.item:
		return
	before = _before(doc)
	if before and before.item == doc.item:
		return  # unchanged; an existing BOM keeps opening whatever it was written for

	declared = frappe.db.get_value("Item", doc.item, ITEM_MATERIAL_TYPE)
	if declared and declared != C.MATERIAL_FG:
		frappe.throw(
			_("{0} is a {1} item. A BOM can only be written for a Finished Good.").format(
				doc.item, declared
			),
			title=_("Not A Finished Good"),
		)


def _validate_variation(doc):
	"""Every recipe needs a name to be told apart from the other recipes for the same FG.

	Only on a new BOM, or on one that already had a name -- the single BOM here without one
	must stay editable.
	"""
	if doc.get(VARIATION_FIELD):
		return
	before = _before(doc)
	if before is None or before.get(VARIATION_FIELD):
		frappe.throw(
			_("Please name this recipe, so it can be told apart from other BOMs for the same item."),
			title=_("BOM Variation Name Required"),
		)


# ----------------------------------------------------------------- the rows

def _validate_rows(doc):
	previous = _previous_rows(doc)
	for row in doc.get("items") or []:
		if not row.item_code:
			continue
		touched = _row_is_touched(row, previous)

		# Cleared on every row, touched or not: this is a correction, not a refusal, and a
		# stale machine setting on an untouched row is exactly the thing nobody notices.
		if (row.get(STAGE_FIELD) or "") != C.STAGE_SYREP:
			for field in SYREP_ONLY_FIELDS:
				row.set(field, None)

		if not touched:
			continue

		_validate_row_item(row)
		_validate_row_stage(row)
		_validate_row_material_type(row)

		if flt(row.qty) <= 0:
			frappe.throw(
				_("Row {0}: quantity must be more than zero.").format(row.idx),
				title=_("Invalid Quantity"),
			)


def _validate_row_item(row):
	"""A finished good is what a BOM MAKES; it is never a line inside one.

	An FG in the ingredient list gives the Job Card a material the shop floor cannot draw
	from anywhere, and makes the recipe look like it builds itself.
	"""
	declared = frappe.db.get_value("Item", row.item_code, ITEM_MATERIAL_TYPE)
	if declared == C.MATERIAL_FG:
		frappe.throw(
			_("Row {0}: {1} is a Finished Good, so it cannot be a material inside a recipe.").format(
				row.idx, row.item_code
			),
			title=_("Finished Good In The Recipe"),
		)


def _validate_row_stage(row):
	"""The Job Card is printed stage by stage, so a row with no stage has nowhere to print."""
	stage = row.get(STAGE_FIELD) or ""
	if not stage:
		frappe.throw(
			_("Row {0}: choose the Process Stage this material is used in.").format(row.idx),
			title=_("Process Stage Required"),
		)
	if stage not in C.BOM_PROCESS_STAGES:
		frappe.throw(
			_("Row {0}: {1} is not a Process Stage. Choose one of: {2}.").format(
				row.idx, stage, ", ".join(C.BOM_PROCESS_STAGES)
			),
			title=_("Unknown Process Stage"),
		)


def _validate_row_material_type(row):
	"""The Material Type is a fact about the item, not an opinion of whoever typed the row.

	Taken from the Item Master, and a row that disagrees is refused rather than silently
	corrected -- a PM item sitting in the recipe as RM would group into the wrong section
	of the Job Card.
	"""
	declared = row.get(MATERIAL_TYPE_FIELD)
	expected = item_material_type(row.item_code)
	if not expected:
		return
	if not declared:
		row.set(MATERIAL_TYPE_FIELD, expected)
	elif declared != expected:
		frappe.throw(
			_("Row {0}: {1} is a {2} item, but the row says {3}.").format(
				row.idx, row.item_code, expected, declared
			),
			title=_("Material Type Does Not Match The Item"),
		)


def _validate_no_duplicate_rows(doc):
	"""BOM-02. The same item twice in the same stage.

	Twice in DIFFERENT stages is legitimate -- water in Mixing and again in Syrup Prep is a
	real recipe -- so the stage is part of the key. ERPNext itself keeps both lines happily,
	and the Job Card then prints the item twice with two part quantities for the operator to
	add up.

	Only raised when one of the two rows was touched, so a legacy BOM that already holds a
	repeat stays openable.
	"""
	previous = _previous_rows(doc)
	seen = {}
	for row in doc.get("items") or []:
		if not row.item_code:
			continue
		key = (row.item_code, row.get(STAGE_FIELD) or "")
		if key in seen:
			first_idx, first_touched = seen[key]
			if first_touched or _row_is_touched(row, previous):
				stage = row.get(STAGE_FIELD) or _("no stage")
				frappe.throw(
					_("{0} is listed twice in {1} (rows {2} and {3}). Combine them into one line.").format(
						row.item_code, stage, first_idx, row.idx
					),
					title=_("Duplicate Material"),
				)
		else:
			seen[key] = (row.idx, _row_is_touched(row, previous))


def _warn_default_deactivated(doc):
	"""BOM-07. Deactivating the default recipe for a finished good.

	Not a block: retiring a recipe is a legitimate thing to do, and the FRD asks for a
	warning. But it leaves the FG with a default BOM that Production will refuse to use,
	and nothing else on the screen says so.

	Read off the stored document rather than from a flag the caller passes, so it warns on
	the desk form and through the API too, not only on the BOM Master screen.
	"""
	if cint(doc.is_active) or not cint(doc.is_default):
		return
	before = _before(doc)
	if not before or not cint(before.is_active):
		return  # already inactive; nothing is changing
	frappe.msgprint(
		_("{0} was the default recipe for {1} and is now inactive, so nothing will be able "
		  "to use it. Set another BOM as the default for that item.").format(doc.name, doc.item),
		title=_("Default Recipe Deactivated"),
		indicator="orange",
	)


# ------------------------------------------------------------- in-use guard

def assert_not_used_by_open_order(bom_name):
	"""BOM-06. A recipe in use by an open Production Order is frozen.

	Changing it mid-run would leave the shop floor holding a Job Card printed from one
	recipe while the system believed another.
	"""
	if not bom_name or not frappe.db.exists("DocType", "Production Order"):
		return
	open_orders = frappe.get_all(
		"Production Order",
		filters={
			"bom_no": bom_name,
			"docstatus": ("<", 2),
			"status": ("not in", ("Completed", "Cancelled", "Closed")),
		},
		pluck="name",
		limit=5,
	)
	if open_orders:
		frappe.throw(
			_("This BOM is in use by an open Production Order: {0}.").format(
				", ".join(open_orders)
			),
			title=_("BOM In Use"),
		)


# ------------------------------------------------------------------ the hook

def apply_bom_rules(doc, method=None):
	"""Every BOM rule, for every writer. Wired at BOM `validate` in hooks.py."""
	_validate_fg_parent(doc)
	_validate_variation(doc)
	_validate_rows(doc)
	_validate_no_duplicate_rows(doc)
	_warn_default_deactivated(doc)
	if not doc.is_new() and cint(doc.docstatus) == 0:
		assert_not_used_by_open_order(doc.name)
