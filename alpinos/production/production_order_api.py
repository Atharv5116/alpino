"""Server side of the Parent Production Order screens.

The validations all live on the doctype (`production_order.py`) rather than here, so an
import, the REST API and the desk form obey them too -- Task 38 asks for exactly that. What
lives here is what a screen needs and a doctype should not know about: the list query, the
form context, and the Task E shortage report.

The ten open decisions are absent, not guessed. There is no submit / approve / reject
endpoint, because who may do what (Task 25 / 26) is undecided; no batch maths (Task 6); and
no Sub PO creation (Task 27).
"""

import json

import frappe
from frappe import _
from frappe.utils import cint, flt

from alpinos.production import constants as C
from alpinos.production.item_fields import MATERIAL_TYPE_FIELD as ITEM_MATERIAL_TYPE

DOCTYPE = "Production Order"

LIST_FIELDS = (
	"name",
	"production_type",
	"client_name",
	"fg_item",
	"fg_item_name",
	"production_qty_kg",
	"production_qty_pcs",
	"delivery_date",
	"production_start_date",
	"batch_number",
	"bom_no",
	"status",
	"docstatus",
	"modified",
)

#: Fields the screen owns. Anything else on the document it must not write -- the approval
#: stamps and the status in particular, which belong to a flow that does not exist yet.
WRITABLE_FIELDS = (
	"production_type",
	"client_name",
	"batch_number",
	"delivery_date",
	"fg_item",
	"production_qty_kg",
	"production_qty_pcs",
	"production_start_date",
	"total_batches",
	"total_rm_requirement",
	"total_additive_requirement",
	"total_material_requirement",
	"remarks",
)

PAGE_LENGTHS = (50, 100, 200)
DEFAULT_PAGE_LENGTH = 50

_SORTABLE = frozenset({
	"name", "production_type", "client_name", "fg_item", "production_qty_kg",
	"delivery_date", "production_start_date", "status", "modified",
})


@frappe.whitelist()
def get_list(search=None, production_type=None, fg_item=None, status=None, client=None,
             start_date_from=None, start_date_to=None, start=0,
             page_length=DEFAULT_PAGE_LENGTH, sort_field=None, sort_dir=None):
	"""One page of Parent POs, with the Sub PO count per row.

	Paged from the start rather than capped at a round number: the Item list had to be fixed
	after silently truncating at 200 of 231, and an order list grows faster than a catalogue.
	"""
	frappe.has_permission(DOCTYPE, "read", throw=True)

	start = max(cint(start), 0)
	page_length = min(max(cint(page_length) or DEFAULT_PAGE_LENGTH, 1), max(PAGE_LENGTHS))

	filters = {}
	if production_type:
		filters["production_type"] = production_type
	if fg_item:
		filters["fg_item"] = fg_item
	if status:
		filters["status"] = status
	if client:
		filters["client_name"] = client
	if start_date_from and start_date_to:
		filters["production_start_date"] = ("between", [start_date_from, start_date_to])
	elif start_date_from:
		filters["production_start_date"] = (">=", start_date_from)
	elif start_date_to:
		filters["production_start_date"] = ("<=", start_date_to)

	or_filters = None
	if search:
		like = f"%{search}%"
		or_filters = {"name": ("like", like), "fg_item": ("like", like),
		              "fg_item_name": ("like", like), "batch_number": ("like", like)}

	sf = (sort_field or "").strip()
	sd = "asc" if str(sort_dir or "desc").lower() == "asc" else "desc"
	order_by = f"`{sf}` {sd}" if sf in _SORTABLE else "creation desc"

	count_rows = frappe.get_list(
		DOCTYPE, fields=["count(name) as total"], filters=filters or None,
		or_filters=or_filters, limit_page_length=0,
	)
	total = cint(count_rows[0].get("total")) if count_rows else 0

	# One more than asked for, so "is there another page" needs no second query.
	rows = frappe.get_list(
		DOCTYPE, filters=filters or None, or_filters=or_filters, fields=list(LIST_FIELDS),
		order_by=order_by, limit_start=start, limit_page_length=page_length + 1,
	)
	has_more = len(rows) > page_length
	rows = rows[:page_length]

	_attach_sub_orders(rows)

	return {
		"data": rows,
		"has_more": int(has_more),
		"start": start,
		"page_length": page_length,
		"total": total,
		"page_lengths": list(PAGE_LENGTHS),
	}


def _user_may_approve():
	"""Task 25: Admin / Production Manager approve; a User does not.

	The same set the doctype enforces -- this only decides whether the screen DRAWS the
	button, and the refusal itself lives on ProductionOrder.approve().
	"""
	approvers = {C.ROLE_PRODUCTION_ADMIN, C.ROLE_PRODUCTION_MANAGER, "System Manager"}
	return bool(approvers & set(frappe.get_roles()))


def _sub_order_field():
	"""The Work Order field that points back at a Parent, if it has been added yet."""
	field = "custom_parent_production_order"
	if frappe.get_meta("Work Order").has_field(field):
		return field
	return None


def _attach_sub_orders(rows):
	"""Sub PO count and ids per Parent, in one query rather than one per row.

	Returns zeroes while the Work Order link field does not exist yet, so the column reads
	as "none" rather than breaking the whole list.
	"""
	field = _sub_order_field()
	for row in rows:
		row["sub_order_count"] = 0
		row["sub_orders"] = []
	if not field or not rows:
		return

	by_parent = {}
	for sub in frappe.get_all(
		"Work Order",
		filters={field: ("in", [r["name"] for r in rows]), "docstatus": ("<", 2)},
		fields=[f"{field} as parent_po", "name", "qty", "status"],
		order_by="name asc",
	):
		by_parent.setdefault(sub.parent_po, []).append(sub)

	for row in rows:
		subs = by_parent.get(row["name"], [])
		row["sub_order_count"] = len(subs)
		row["sub_orders"] = [
			{"name": s.name, "qty": flt(s.qty), "status": s.status} for s in subs
		]


@frappe.whitelist()
def get_form_context(production_order=None):
	if production_order and frappe.db.exists(DOCTYPE, production_order):
		doc = frappe.get_doc(DOCTYPE, production_order)
		doc.check_permission("read")
		data = doc.as_dict()
		# Editable only while the order is still a draft. Which fields stay editable after
		# approval (PPO-05) is one of the open decisions, so for now approval closes the
		# screen rather than half-opening it on a guess.
		can_write = (
			frappe.has_permission(DOCTYPE, "write", doc=doc)
			and cint(doc.docstatus) == 0
			and doc.status in C.PO_EDITABLE_STATUSES
		)
		sub_orders = _sub_orders_for(production_order)
	else:
		doc = None
		data = None
		frappe.has_permission(DOCTYPE, "read", throw=True)
		can_write = frappe.has_permission(DOCTYPE, "create")
		sub_orders = []

	return {
		"doc": data,
		"can_write": bool(can_write),
		"can_delete": bool(doc and frappe.has_permission(DOCTYPE, "delete", doc=doc)
		                   and cint(doc.docstatus) == 0),
		"docstatus": cint(doc.docstatus) if doc else 0,
		"production_types": list(C.PRODUCTION_TYPES),
		"types_needing_client": list(C.PRODUCTION_TYPES_NEEDING_CLIENT),
		"statuses": list(C.PO_STATUSES),
		"sub_orders": sub_orders,
		# What the screen may offer. Submit and Approve exist; Reject and Send To Store do
		# not yet, and the screen says so rather than drawing dead buttons.
		"can_submit_order": bool(
			doc and cint(doc.docstatus) == 0 and doc.status == C.PO_DRAFT
			and frappe.has_permission(DOCTYPE, "submit", doc=doc)
		),
		"can_approve_order": bool(
			doc and doc.status == C.PO_PENDING_APPROVAL and _user_may_approve()
		),
		"can_reject_order": bool(
			doc and doc.status == C.PO_PENDING_APPROVAL and _user_may_approve()
		),
		"can_send_to_store": bool(
			doc and doc.status == C.PO_APPROVED and _user_may_approve()
		),
		"can_cancel_order": bool(
			doc and _user_may_approve()
			and doc.status in (C.PO_DRAFT, C.PO_PENDING_APPROVAL, C.PO_APPROVED, C.PO_REJECTED)
		),
		"is_approver": _user_may_approve(),
	}


def _sub_orders_for(production_order):
	field = _sub_order_field()
	if not field:
		return []
	return frappe.get_all(
		"Work Order",
		filters={field: production_order, "docstatus": ("<", 2)},
		fields=["name", "qty", "status", "planned_start_date"],
		order_by="name asc",
	)


@frappe.whitelist()
def default_bom(fg_item):
	"""Task 4, for the screen: which BOM will be snapshotted, before the save happens.

	The same lookup the doctype does, exposed so the screen can show the BOM and its rows as
	soon as the FG is picked instead of only after a save.
	"""
	frappe.has_permission("BOM", "read", throw=True)
	if not fg_item:
		return {}

	declared = frappe.db.get_value("Item", fg_item, ITEM_MATERIAL_TYPE)
	if declared and declared != C.MATERIAL_FG:
		return {"error": _("{0} is a {1} item, not a Finished Good.").format(fg_item, declared)}

	rows = frappe.get_all(
		"BOM",
		filters={"item": fg_item, "is_active": 1, "is_default": 1, "docstatus": ("<", 2)},
		pluck="name", order_by="modified desc", limit=1,
	)
	if not rows:
		return {"error": _("No active default BOM found for {0}. Create one in BOM Master.").format(fg_item)}

	from alpinos.production.bom_fields import MATERIAL_TYPE_FIELD, STAGE_FIELD

	bom = rows[0]
	item = frappe.db.get_value("Item", fg_item, ["item_name", "stock_uom"], as_dict=True)
	return {
		"bom_no": bom,
		"fg_item_name": item.item_name if item else None,
		"uom": item.stock_uom if item else None,
		"items": frappe.get_all(
			"BOM Item",
			filters={"parent": bom},
			fields=["item_code", "item_name", "uom", "qty as standard_qty",
			        f"{MATERIAL_TYPE_FIELD} as material_type",
			        f"{STAGE_FIELD} as process_stage"],
			order_by="idx asc",
		),
	}


@frappe.whitelist()
def save_production_order(payload):
	"""Create or update a Parent PO from its screen.

	Only WRITABLE_FIELDS are written, so a screen cannot touch the status or an approval
	stamp even by sending one. Every rule runs in ProductionOrder.validate on top.
	"""
	if isinstance(payload, str):
		payload = json.loads(payload or "{}")
	payload = payload or {}

	name = (payload.get("name") or "").strip()
	if name:
		doc = frappe.get_doc(DOCTYPE, name)
		doc.check_permission("write")
		if cint(doc.docstatus) != 0:
			frappe.throw(_("Only a draft Production Order can be changed."),
			             title=_("Not Editable"))
		if doc.status not in C.PO_EDITABLE_STATUSES:
			frappe.throw(
				_("A Production Order that is {0} cannot be changed.").format(doc.status),
				title=_("Not Editable"),
			)
	else:
		frappe.has_permission(DOCTYPE, "create", throw=True)
		doc = frappe.new_doc(DOCTYPE)

	for field in WRITABLE_FIELDS:
		if field in payload:
			doc.set(field, payload.get(field))

	# Total Required Qty is the one thing on a row a person may set, because the formula that
	# would calculate it is undecided. Matched by item_code plus stage, which is what makes a
	# row unique (BOM-02 refuses a repeat of that pair), so a reordered grid still lands on
	# the right row.
	overrides = {}
	for row in payload.get("items") or []:
		if row.get("item_code"):
			overrides[(row.get("item_code"), row.get("process_stage") or "")] = row.get("total_required_qty")

	doc.save()

	if overrides:
		touched = False
		for row in doc.get("items") or []:
			key = (row.item_code, row.process_stage or "")
			if key in overrides and overrides[key] is not None:
				row.total_required_qty = flt(overrides[key])
				touched = True
		if touched:
			doc.save()

	frappe.db.commit()
	return {"name": doc.name, "status": doc.status}


@frappe.whitelist()
def submit_production_order(production_order):
	"""Hand the order to its approver. Task 26: Draft / Rejected -> Pending Approval."""
	doc = frappe.get_doc(DOCTYPE, production_order)
	doc.submit_for_approval()
	frappe.db.commit()
	return {"name": doc.name, "status": doc.status}


@frappe.whitelist()
def reject_production_order(production_order, reason):
	"""Task 25 / 26: Pending Approval -> Rejected, with a reason, back to the planner."""
	doc = frappe.get_doc(DOCTYPE, production_order)
	doc.reject(reason)
	frappe.db.commit()
	return {"name": doc.name, "status": doc.status, "rejection_reason": doc.rejection_reason}


@frappe.whitelist()
def cancel_production_order(production_order, reason):
	"""PPO-06: cancel the order and, with it, its draft sub orders."""
	doc = frappe.get_doc(DOCTYPE, production_order)
	out = doc.cancel_order(reason)
	frappe.db.commit()
	out["name"] = doc.name
	return out


@frappe.whitelist()
def send_to_store(production_order):
	"""Task D: Approved -> Sent To Store, and the sub orders come off the lock."""
	doc = frappe.get_doc(DOCTYPE, production_order)
	out = doc.send_to_store()
	frappe.db.commit()
	out["name"] = doc.name
	return out


@frappe.whitelist()
def approve_production_order(production_order):
	"""SPO-01: approving a Parent is what creates its first Sub PO."""
	doc = frappe.get_doc(DOCTYPE, production_order)
	sub_orders = doc.approve()
	frappe.db.commit()
	return {"name": doc.name, "status": doc.status, "sub_orders": sub_orders}


@frappe.whitelist()
def get_sub_orders(production_order):
	"""The Sub POs of a Parent, for the screen to list."""
	frappe.has_permission(DOCTYPE, "read", throw=True)
	from alpinos.production.sub_order import existing_sub_orders

	return existing_sub_orders(production_order)


# --- Tasks 35 / 36: merge, which is a VIEW and not a record ------------------

def _merge_blockers(name):
	"""Why this order may not take part in a merge. Task 36."""
	from alpinos.production.sub_order import activity_blockers, existing_sub_orders

	status = frappe.db.get_value(DOCTYPE, name, "status")
	if status not in C.PO_PLANNABLE_STATUSES:
		return [_("{0} is {1}.").format(name, status or _("missing"))]

	subs = existing_sub_orders(name)
	# "not split" -- more than one sub order means it has been.
	if len([s for s in subs if cint(s.get("docstatus")) != 2]) > 1:
		return [_("{0} has already been split.").format(name)]
	for sub in subs:
		if activity_blockers(sub["name"]):
			return [_("{0} has already started.").format(name)]
	return []


@frappe.whitelist()
def merge_eligibility(production_orders):
	"""Which of these orders may be merged, and why the others may not."""
	frappe.has_permission(DOCTYPE, "read", throw=True)
	if isinstance(production_orders, str):
		production_orders = json.loads(production_orders or "[]")
	out = {}
	for name in production_orders or []:
		out[name] = _merge_blockers(name)
	return out


@frappe.whitelist()
def merge_view(production_orders, warehouse=None):
	"""Task 35: the Consolidated Planning View. Nothing is written.

	The Parent orders and their sub orders stay completely independent -- this is a way of
	looking at several at once before planning, not an operation on them. That is why it
	returns data and creates no document: there is nothing to undo afterwards.
	"""
	frappe.has_permission(DOCTYPE, "read", throw=True)
	if isinstance(production_orders, str):
		production_orders = json.loads(production_orders or "[]")
	names = sorted({n for n in (production_orders or []) if n})

	if len(names) < 2:
		frappe.throw(_("Select at least two orders."), title=_("Cannot Merge"))

	if not _user_may_approve():
		frappe.throw(
			_("Only a {0} or {1} may merge Production Orders.").format(
				C.ROLE_PRODUCTION_MANAGER, C.ROLE_PRODUCTION_ADMIN),
			title=_("Not An Approver"))

	ineligible = {n: _merge_blockers(n) for n in names}
	ineligible = {n: why for n, why in ineligible.items() if why}
	if ineligible:
		frappe.throw(
			_("Cannot merge: Production Orders can only be merged before any planning or "
			  "production activity begins like splitting.")
			+ "<br><br>" + "<br>".join(f"{n}: {' '.join(why)}" for n, why in ineligible.items()),
			title=_("Cannot Merge"))

	orders = []
	materials = {}
	total_kg = total_pcs = total_batches = 0.0
	for name in names:
		doc = frappe.get_doc(DOCTYPE, name)
		doc.check_permission("read")
		orders.append({
			"name": doc.name, "fg_item": doc.fg_item, "fg_item_name": doc.fg_item_name,
			"production_qty_kg": flt(doc.production_qty_kg),
			"production_qty_pcs": cint(doc.production_qty_pcs),
			"production_start_date": doc.production_start_date,
			"delivery_date": doc.delivery_date, "status": doc.status,
			"batch_number": doc.batch_number,
		})
		total_kg += flt(doc.production_qty_kg)
		total_pcs += cint(doc.production_qty_pcs)
		total_batches += flt(doc.total_batches)
		for row in doc.get("items") or []:
			if not row.item_code:
				continue
			bucket = materials.setdefault(row.item_code, {
				"item_code": row.item_code, "item_name": row.item_name,
				"material_type": row.material_type, "uom": row.uom, "required_qty": 0.0,
			})
			bucket["required_qty"] += flt(row.total_required_qty)

	available = _available_stock(sorted(materials), warehouse)
	rows = []
	for code in sorted(materials):
		row = dict(materials[code])
		row["available_qty"] = flt(available.get(code, 0))
		shortage = row["required_qty"] - row["available_qty"]
		row["shortage_qty"] = shortage if shortage > 0 else 0
		row["status"] = "Not Set" if row["required_qty"] <= 0 else (
			"Short" if shortage > 0 else "OK")
		rows.append(row)

	return {
		"orders": orders,
		"materials": rows,
		"totals": {"kg": total_kg, "pcs": total_pcs, "batches": total_batches,
		           "orders": len(orders)},
		"warehouse": warehouse,
		"saved": False,
	}


# --- Task E: the material shortage report -------------------------------------

@frappe.whitelist()
def material_shortage(production_order, warehouse=None):
	"""BR-STK-01. What this order needs against what is actually in stock.

	A warning and nothing more: it blocks no save, no approval and no send to store, which is
	what the FRD asks for. So it returns data and never throws on a shortage.

	Required Qty is each row's Total Required Qty. While the batch formula is undecided those
	are whatever someone entered, often zero -- so the report says which rows have no
	requirement recorded rather than quietly reporting them as fully stocked.
	"""
	doc = frappe.get_doc(DOCTYPE, production_order)
	doc.check_permission("read")

	rows = doc.get("items") or []
	if not rows:
		return {"warehouse": warehouse, "rows": [], "short_count": 0, "unset_count": 0}

	codes = sorted({row.item_code for row in rows if row.item_code})
	available = _available_stock(codes, warehouse)

	out = []
	short_count = 0
	unset_count = 0
	for row in rows:
		required = flt(row.total_required_qty)
		stock = flt(available.get(row.item_code, 0))
		shortage = required - stock
		if required <= 0:
			status = "Not Set"
			unset_count += 1
			shortage = 0
		elif shortage > 0:
			status = "Short"
			short_count += 1
		else:
			status = "OK"
			shortage = 0
		out.append({
			"item_code": row.item_code,
			"item_name": row.item_name,
			"material_type": row.material_type,
			"process_stage": row.process_stage,
			"uom": row.uom,
			"required_qty": required,
			"available_qty": stock,
			"shortage_qty": shortage,
			"status": status,
		})

	return {
		"warehouse": warehouse,
		"rows": out,
		"short_count": short_count,
		"unset_count": unset_count,
	}


def _available_stock(item_codes, warehouse=None):
	"""actual_qty per item, summed across warehouses unless one is named.

	Read off Bin, which is ERPNext's own running total, rather than summing Stock Ledger
	Entry -- the ledger is the audit trail and summing it here would disagree with every
	stock report on the site the moment one entry is cancelled.
	"""
	if not item_codes:
		return {}
	filters = {"item_code": ("in", list(item_codes))}
	if warehouse:
		filters["warehouse"] = warehouse
	out = {}
	for row in frappe.get_all(
		"Bin", filters=filters,
		fields=["item_code", "sum(actual_qty) as qty"], group_by="item_code",
	):
		out[row.item_code] = flt(row.qty)
	return out
