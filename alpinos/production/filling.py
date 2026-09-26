"""The SKU / machine filling handshake — FRD 4.9 (Phase 8) 8.4.

The Planning and Filling Entry screens do not exist yet. What those screens will need is
a single answer to "may this machine run this SKU, and if so which input component do I
draw?", so that answer lives here now and the screens call it when they are built. None
of it is hardcoded against category names: the component key IS the category, so a new
filling process needs a new row in the category master and a new component, and nothing
here changes (8.5).
"""

import json

import frappe
from frappe import _
from frappe.utils import cint

from alpinos.production import constants as C
from alpinos.production.item_fields import ALLOWED_CATEGORIES_FIELD

#: 8.4.2 — the exact wording the FRD asks for on a conflict.
MISMATCH_MESSAGE = "Mismatch: This machine cannot process this SKU type."


def allowed_categories(item_code):
	"""The filling categories an SKU may run on."""
	if not item_code or not frappe.get_meta("Item").has_field(ALLOWED_CATEGORIES_FIELD):
		return []
	return frappe.get_all(
		"Item Filling Category",
		filters={"parent": item_code, "parenttype": "Item"},
		pluck="filling_process_category",
		order_by="idx asc",
	)


def machine_category(machine):
	if not machine:
		return None
	return frappe.db.get_value("Machine", machine, "filling_process_category")


@frappe.whitelist()
def check_compatibility(machine, item_code):
	"""8.4.1 handshake + 8.4.4 availability, as data rather than as an exception.

	Returns a dict the caller can render. `assert_compatible` is the throwing twin for
	the moment a plan is actually saved -- a screen warns with this, the save uses that.
	"""
	frappe.has_permission("Machine", "read", throw=True)

	row = frappe.db.get_value(
		"Machine", machine, ["name", "status", "filling_process_category"], as_dict=True
	) if machine else None

	if not row:
		return {"ok": False, "reason": _("Machine {0} does not exist.").format(machine)}

	# 8.4.4: an unavailable machine never reaches planning or production at all.
	if row.status not in C.MACHINE_ASSIGNABLE_STATUSES:
		return {
			"ok": False,
			"available": False,
			"machine_category": row.filling_process_category,
			"reason": _("Machine {0} is {1} and cannot be planned.").format(
				machine, row.status
			),
		}

	allowed = allowed_categories(item_code)
	result = {
		"ok": False,
		"available": True,
		"machine_category": row.filling_process_category,
		"allowed_categories": allowed,
		# 8.4.3: the caller draws the component named by the machine's category. Passed
		# through as the category itself so no mapping table has to be maintained here.
		"component": row.filling_process_category,
	}

	if not row.filling_process_category:
		result["reason"] = _("Machine {0} has no Filling Process Category set.").format(machine)
		return result

	if not allowed:
		result["reason"] = _(
			"{0} has no Allowed Filling Categories set, so it cannot be assigned to a line yet."
		).format(item_code)
		return result

	if row.filling_process_category not in allowed:
		result["reason"] = _(MISMATCH_MESSAGE)
		return result

	result["ok"] = True
	return result


def assert_compatible(machine, item_code):
	"""The throwing twin, for the moment a plan is saved (8.4.2 is a hard block)."""
	verdict = check_compatibility(machine, item_code)
	if not verdict.get("ok"):
		frappe.throw(
			verdict.get("reason") or _(MISMATCH_MESSAGE),
			title=_("Machine and SKU Do Not Match"),
		)
	return verdict


#: The FRD names these two `validate_sku_machine` and `is_machine_available`. The logic was
#: already written and tested under the names above, so these are thin aliases rather than
#: a rewrite -- the spec and the code should be greppable from each other.

@frappe.whitelist()
def validate_sku_machine(sku, machine):
	"""FRD 8.4.2 by its own name. Argument order follows the spec, not `check_compatibility`."""
	return assert_compatible(machine, sku)


@frappe.whitelist()
def is_machine_available(machine):
	"""FRD 8.4.4. Availability alone, with no SKU in the question."""
	frappe.has_permission("Machine", "read", throw=True)
	status = frappe.db.get_value("Machine", machine, "status") if machine else None
	return bool(status and status in C.MACHINE_ASSIGNABLE_STATUSES)


# --- the category master screens ---------------------------------------------

CATEGORY_DOCTYPE = "Filling Process Category"

CATEGORY_LIST_FIELDS = ("name", "category_name", "is_active", "description", "modified")


@frappe.whitelist()
def get_category_list(search=None, is_active=None, limit=200):
	"""Categories plus what depends on each one.

	The counts are the point of the screen. A category is a vocabulary entry that two other
	masters point at, so the question asked of this list is "what breaks if I retire this",
	and a bare name and tick cannot answer it.
	"""
	frappe.has_permission(CATEGORY_DOCTYPE, "read", throw=True)

	filters = {}
	if is_active not in (None, "", "All"):
		filters["is_active"] = cint(is_active)

	or_filters = None
	if search:
		like = f"%{search}%"
		or_filters = {"name": ("like", like), "category_name": ("like", like)}

	rows = frappe.get_all(
		CATEGORY_DOCTYPE,
		filters=filters,
		or_filters=or_filters,
		fields=list(CATEGORY_LIST_FIELDS),
		order_by="category_name asc",
		limit_page_length=cint(limit) or 200,
	)
	if not rows:
		return []

	ids = [r["name"] for r in rows]

	machines = {}
	for row in frappe.get_all(
		"Machine",
		filters={"filling_process_category": ("in", ids)},
		fields=["filling_process_category", "status", "count(name) as qty"],
		group_by="filling_process_category, status",
	):
		bucket = machines.setdefault(row.filling_process_category, {"total": 0, "active": 0})
		bucket["total"] += cint(row.qty)
		if row.status == C.MACHINE_ACTIVE:
			bucket["active"] += cint(row.qty)

	# Counted off the child table directly. Going through Item would count an item once per
	# row it holds, which is the same number only by accident.
	skus = {}
	for row in frappe.get_all(
		"Item Filling Category",
		filters={"filling_process_category": ("in", ids), "parenttype": "Item"},
		fields=["filling_process_category", "count(distinct parent) as qty"],
		group_by="filling_process_category",
	):
		skus[row.filling_process_category] = cint(row.qty)

	for row in rows:
		bucket = machines.get(row["name"], {"total": 0, "active": 0})
		row["machine_count"] = bucket["total"]
		row["active_machine_count"] = bucket["active"]
		row["sku_count"] = skus.get(row["name"], 0)
	return rows


@frappe.whitelist()
def get_category_form_context(category=None):
	if category and frappe.db.exists(CATEGORY_DOCTYPE, category):
		doc = frappe.get_doc(CATEGORY_DOCTYPE, category)
		doc.check_permission("read")
		data = doc.as_dict()
		can_write = frappe.has_permission(CATEGORY_DOCTYPE, "write", doc=doc)
		can_delete = frappe.has_permission(CATEGORY_DOCTYPE, "delete", doc=doc)
	else:
		doc = None
		data = None
		frappe.has_permission(CATEGORY_DOCTYPE, "read", throw=True)
		can_write = frappe.has_permission(CATEGORY_DOCTYPE, "create")
		can_delete = False

	return {
		"doc": data,
		"can_write": bool(can_write),
		"can_delete": bool(can_delete),
		"machines": frappe.get_all(
			"Machine",
			filters={"filling_process_category": category} if category else {"name": ("is", "not set")},
			fields=["name", "machine_name", "machine_type", "status"],
			order_by="machine_name asc",
		) if category else [],
		"skus": frappe.get_all(
			"Item Filling Category",
			filters={"filling_process_category": category, "parenttype": "Item"},
			fields=["parent as item_code"],
			order_by="parent asc",
		) if category else [],
	}


@frappe.whitelist()
def save_category(payload):
	if isinstance(payload, str):
		payload = json.loads(payload or "{}")
	payload = payload or {}

	name = (payload.get("name") or "").strip()
	if name:
		doc = frappe.get_doc(CATEGORY_DOCTYPE, name)
		doc.check_permission("write")
	else:
		frappe.has_permission(CATEGORY_DOCTYPE, "create", throw=True)
		doc = frappe.new_doc(CATEGORY_DOCTYPE)

	category_name = (payload.get("category_name") or "").strip()
	if not category_name:
		frappe.throw(_("Please name the category."), title=_("Category Name Required"))
	doc.category_name = category_name
	doc.is_active = cint(payload.get("is_active", 1))
	doc.description = payload.get("description")

	doc.save()
	frappe.db.commit()
	return {"name": doc.name}


@frappe.whitelist()
def delete_category(category):
	"""Removing a category that a machine or an SKU still points at would leave both
	pointing at nothing -- and the FRD 8.4 handshake reads exactly those two fields, so the
	failure would surface on the shop floor rather than here. Frappe's own link check covers
	the Machine field; the SKU side is a child table, which that check does not reach."""
	doc = frappe.get_doc(CATEGORY_DOCTYPE, category)
	doc.check_permission("delete")

	machines = frappe.get_all(
		"Machine", filters={"filling_process_category": category}, pluck="machine_name", limit=5
	)
	if machines:
		frappe.throw(
			_("These machines are set to this category: {0}.").format(", ".join(machines)),
			title=_("Category In Use"),
		)

	skus = frappe.get_all(
		"Item Filling Category",
		filters={"filling_process_category": category, "parenttype": "Item"},
		pluck="parent",
		limit=5,
	)
	if skus:
		frappe.throw(
			_("These items allow this category: {0}.").format(", ".join(sorted(set(skus)))),
			title=_("Category In Use"),
		)

	doc.delete()
	frappe.db.commit()
	return {"deleted": category}


@frappe.whitelist()
def machines_for_category(category=None, item_code=None):
	"""Active machines a plan may choose, optionally narrowed to one SKU (8.4.1 + 8.4.4).

	Passing `item_code` returns only the machines that SKU is actually allowed on, so the
	Planning screen can filter the picker instead of letting someone choose a machine and
	then be refused.
	"""
	frappe.has_permission("Machine", "read", throw=True)

	filters = {"status": ("in", list(C.MACHINE_ASSIGNABLE_STATUSES))}
	if category:
		filters["filling_process_category"] = category
	elif item_code:
		allowed = allowed_categories(item_code)
		if not allowed:
			return []
		filters["filling_process_category"] = ("in", allowed)

	return frappe.get_all(
		"Machine",
		filters=filters,
		fields=["name", "machine_name", "machine_type", "filling_process_category",
		        "max_capacity", "capacity_uom", "status"],
		order_by="machine_name asc",
	)
