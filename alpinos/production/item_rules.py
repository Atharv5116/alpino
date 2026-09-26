"""Item Master validation rules IM-01 .. IM-10.

All of it runs on the server, on the Item `validate` hook, so the Item Master screen, the
standard desk form, the REST API and a data import all obey the same rules. The field
properties (`depends_on`, `mandatory_depends_on`) are decoration: `mandatory_depends_on`
in particular is read by frappe's save.js and layout.js and by nothing on the server.

Two rules are deliberately narrower than the spec, because the alternative breaks records
that already exist and the user has ruled out modifying existing data:

    IM-01  required on a NEW item saved by a person, and an item that already carries a
           type may not have it cleared -- that second half holds for every writer. 226 of
           233 items are blank, so a blanket block would make every one of them
           unsaveable; and see `_material_type_is_required` for why "every new item" had to
           become "every new item someone types in".
    IM-04  the Batch No Tracking auto-tick applies to NEW items only. ERPNext's
           `Item.cant_change()` (item.py:1041) refuses a change to `has_batch_no` once the
           item has stock, so auto-ticking an existing RM item does not warn -- it throws,
           and the item can no longer be saved at all.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

from alpinos.production import constants as C
from alpinos.production.item_fields import (
	ALLOWED_CATEGORIES_FIELD,
	LOSS_PERCENT_FIELD,
	MATERIAL_CATEGORY_FIELD,
	MATERIAL_TYPE_FIELD,
)

#: The types whose stock is tracked in batches (IM-04).
BATCH_TRACKED_TYPES = (C.MATERIAL_RM, C.MATERIAL_ADDITIVE)


def _was(doc, fieldname):
	"""The stored value before this save, or None on a new document."""
	before = doc.get_doc_before_save() if not doc.is_new() else None
	return before.get(fieldname) if before else None


# --------------------------------------------------------------------- IM-01

def _material_type_is_required(doc):
	"""Whether a blank Material Type should block THIS save.

	Enforcing it on every Item insert made the field mandatory system-wide, and the first
	thing that broke was unrelated: the purchase task suite aborted on its own fixture
	items, which have no business knowing about a Production field. A data import, an
	install, a patch or any server script that creates an Item would have gone the same
	way.

	So the requirement follows a person filling in a form -- the Item Master screen, the
	desk form, or a REST client acting as one, all of which arrive on a web request. An
	insert with no request behind it is machinery, and for machinery an unclassified item
	is the same legacy blank the user already chose to keep saveable.
	"""
	# The Item Master screen owns this rule, so it says so rather than relying on the
	# request heuristic below to infer it.
	if frappe.flags.get("alpinos_item_master"):
		return True
	if (
		frappe.flags.in_install
		or frappe.flags.in_migrate
		or frappe.flags.in_patch
		or frappe.flags.in_import
		or frappe.flags.in_test
	):
		return False
	return bool(getattr(frappe, "request", None))


def _validate_material_type(doc):
	material_type = doc.get(MATERIAL_TYPE_FIELD)
	if material_type:
		return

	if doc.is_new():
		if _material_type_is_required(doc):
			frappe.throw(_("Material Type is required."), title=_("Material Type Required"))
		return

	# Not new. Only refuse when the value is being taken AWAY -- a legacy item that never
	# had one keeps saving.
	if _was(doc, MATERIAL_TYPE_FIELD):
		frappe.throw(
			_("Material Type cannot be cleared once it has been set."),
			title=_("Material Type Required"),
		)


# ----------------------------------------------------------- IM-02 and IM-03

def _validate_material_category(doc):
	if doc.get(MATERIAL_TYPE_FIELD) != C.MATERIAL_PM:
		# IM-03. A category left on an item that is no longer PM would keep surfacing in
		# filters, reports and exports, which `depends_on` does not reach.
		if doc.get(MATERIAL_CATEGORY_FIELD):
			doc.set(MATERIAL_CATEGORY_FIELD, None)
		return

	if not doc.get(MATERIAL_CATEGORY_FIELD):
		frappe.throw(
			_("Material Category is required for PM items. Choose {0}.").format(
				" or ".join(C.PM_CATEGORIES)
			),
			title=_("Material Category Required"),
		)


# --------------------------------------------------------------------- IM-04

def _apply_batch_tracking(doc):
	"""RM and Additive are batch-tracked, and stay that way once they are.

	Two halves, and the second was missing. Ticking Batch No on a NEW item is the auto-set
	(new items only -- `Item.cant_change()` at item.py:1041 refuses the change once stock
	exists, so an existing item would not warn but throw). Keeping it ticked is the LOCK:
	nothing stopped somebody clearing it afterwards, and an RM item that quietly stopped
	being batch-tracked takes its expiry and its traceability with it -- the whole reason
	the flag is set in the first place.

	Turning it ON by hand is fine; only turning it off is refused, and only for the types
	that are supposed to carry it. The 4 RM/Additive items already untracked here keep
	saving, because their stored value is 0 and clearing 0 changes nothing.
	"""
	material_type = doc.get(MATERIAL_TYPE_FIELD)
	if doc.is_new():
		if material_type in BATCH_TRACKED_TYPES and not cint(doc.has_batch_no):
			doc.has_batch_no = 1
		return

	if material_type not in BATCH_TRACKED_TYPES or cint(doc.has_batch_no):
		return
	if cint(_was(doc, "has_batch_no")):
		frappe.throw(
			_("{0} is a {1} item, so Batch No Tracking cannot be switched off.").format(
				doc.name, material_type
			),
			title=_("Batch Tracking Is Required"),
		)


# --------------------------------------------------- Task 19: filling categories

def _validate_filling_categories(doc):
	"""Only a finished good may name filling categories, and only active ones.

	`item_api.save_item` already cleared these for a non-FG and the screen only offers
	active categories, but both are one writer. The desk form, the REST API and an import
	went straight past: an RM item could be given filling categories, and an FG could point
	at a retired one. Either way the 8.4 handshake reads those rows and hands the shop floor
	a line that cannot run the SKU.

	A non-FG is corrected rather than refused -- the rows are meaningless there, and
	throwing would block an otherwise fine item over a field its type does not even show.
	An inactive category IS refused, because that one is a real choice someone made.
	"""
	if not doc.meta.has_field(ALLOWED_CATEGORIES_FIELD):
		return

	rows = doc.get(ALLOWED_CATEGORIES_FIELD) or []
	if not rows:
		return

	if doc.get(MATERIAL_TYPE_FIELD) != C.MATERIAL_FG:
		doc.set(ALLOWED_CATEGORIES_FIELD, [])
		return

	before = doc.get_doc_before_save() if not doc.is_new() else None
	kept_before = {
		r.filling_process_category for r in (before.get(ALLOWED_CATEGORIES_FIELD) or [])
	} if before else set()

	for row in rows:
		category = row.filling_process_category
		if not category:
			continue
		# Forward-only: a category retired AFTER it was chosen keeps the item saveable.
		# Only a newly added inactive one is refused.
		if category in kept_before:
			continue
		if not cint(frappe.db.get_value("Filling Process Category", category, "is_active")):
			frappe.throw(
				_("Filling Process Category {0} is inactive, so it cannot be added to {1}.").format(
					category, doc.name or doc.item_code
				),
				title=_("Inactive Filling Category"),
			)


# --------------------------------------------------------------------- IM-05

def _validate_expiry(doc):
	if cint(doc.get("has_expiry_date")) and cint(doc.get("shelf_life_in_days")) <= 0:
		frappe.throw(
			_("Shelf Life is required when Expiry Tracking is enabled."),
			title=_("Shelf Life Required"),
		)


# --------------------------------------------------------------------- IM-06

def _validate_day_counts(doc):
	"""Shelf Life at least 1, Lead Time at least 0, both whole numbers.

	Only the lower bounds are checked here. Both fields are Int on the doctype, so a
	decimal has already been truncated by the time validate runs -- that half of IM-06 is
	caught in `item_api.save_item`, which still has the raw payload.
	"""
	if cint(doc.get("shelf_life_in_days")) < 0:
		frappe.throw(_("Shelf Life cannot be negative."), title=_("Invalid Shelf Life"))

	if cint(doc.get("has_expiry_date")) and cint(doc.get("shelf_life_in_days")) < 1:
		frappe.throw(_("Shelf Life must be 1 day or more."), title=_("Invalid Shelf Life"))

	if cint(doc.get("lead_time_days")) < 0:
		frappe.throw(_("Lead Time cannot be negative."), title=_("Invalid Lead Time"))


# --------------------------------------------------------------------- IM-09

def _validate_loss_percent(doc):
	loss = doc.get(LOSS_PERCENT_FIELD)
	if loss in (None, ""):
		return
	if flt(loss) < 0 or flt(loss) > 100:
		frappe.throw(
			_("Loss % must be between 0 and 100."), title=_("Invalid Loss %")
		)


# --------------------------------------------------------------------- IM-10

def _warn_if_used_in_active_bom(doc):
	"""A warning, not a block: the spec says warn, and an item can legitimately be retired
	while old recipes still mention it."""
	if doc.is_new() or not cint(doc.get("disabled")):
		return
	if cint(_was(doc, "disabled")):
		return  # already disabled; nothing changed

	boms = frappe.get_all(
		"BOM Item",
		filters={"item_code": doc.name},
		fields=["parent"],
		limit=20,
	)
	if not boms:
		return
	active = frappe.get_all(
		"BOM",
		filters={"name": ("in", list({b.parent for b in boms})), "is_active": 1,
		         "docstatus": ("<", 2)},
		pluck="name",
		limit=5,
	)
	if active:
		frappe.msgprint(
			_("Item is used in BOM {0}.").format(", ".join(active)),
			title=_("Item Is Still In Use"),
			indicator="orange",
		)


# ---------------------------------------------------------------- entry point

def apply_item_rules(doc, method=None):
	"""IM-01 .. IM-10, in the order a person would check them."""
	_validate_material_type(doc)
	_validate_material_category(doc)
	_apply_batch_tracking(doc)
	_validate_filling_categories(doc)
	_validate_expiry(doc)
	_validate_day_counts(doc)
	_validate_loss_percent(doc)
	_warn_if_used_in_active_bom(doc)
