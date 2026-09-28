"""Shared helpers for Material Management (MR / MI / MRT).

Role checks, the Sub PO header every document copies, stock look-ups and the paging
arithmetic -- one copy of each, so the three documents cannot drift apart.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

from alpinos.production import constants as C
from alpinos.production import material_constants as M
from alpinos.production.work_order_fields import (
	ASSIGNED_PROCESS_FIELD,
	EXECUTION_STATUS_FIELD,
	IS_LOCKED_FIELD,
	PARENT_FIELD,
	PLANNED_DATE_FIELD,
	PRODUCTION_TYPE_FIELD,
)

WORK_ORDER = "Work Order"


# ---------------------------------------------------------------------- roles

def _has_any(roles):
	return bool(set(roles) & set(frappe.get_roles()))


def may_write():
	return _has_any(M.STORE_WRITE_ROLES)


def may_manage():
	return _has_any(M.STORE_MANAGE_ROLES)


def may_plan():
	return _has_any(M.STORE_PLAN_ROLES)


def may_read():
	return _has_any(M.STORE_READ_ROLES)


def assert_may_read():
	if not may_read():
		frappe.throw(_("You do not have access to Material Management."),
		             frappe.PermissionError, title=_("Not Permitted"))


def assert_may_write():
	if not may_write():
		frappe.throw(
			_("Only a {0} or {1} may create or submit store documents.").format(
				M.ROLE_STORE_USER, M.ROLE_STORE_MANAGER),
			frappe.PermissionError, title=_("Not Permitted"))


def assert_may_manage(action=None):
	if not may_manage():
		frappe.throw(
			_("Only a {0} may {1}.").format(M.ROLE_STORE_MANAGER, action or _("do this")),
			frappe.PermissionError, title=_("Not Permitted"))


def assert_may_plan():
	if not may_plan():
		frappe.throw(
			_("Only a {0} or {1} may generate a Material Request from a planned sub order.").format(
				M.ROLE_STORE_PLANNER, M.ROLE_STORE_MANAGER),
			frappe.PermissionError, title=_("Not Permitted"))


# ------------------------------------------------------------------- sub order

def sub_order_header(sub_name):
	"""What every store document copies from its Sub PO, checked for BR-MR rules.

	The Sub PO must exist, be a real sub order, and belong to a Parent that is Sent To
	Store (which is what takes the lock off it).
	"""
	if not sub_name:
		frappe.throw(_("Please choose the Sub Production Order."), title=_("Sub PO Required"))
	sub = frappe.db.get_value(
		WORK_ORDER, sub_name,
		["name", "production_item", "item_name", "qty", "company", "docstatus", PARENT_FIELD,
		 PRODUCTION_TYPE_FIELD, IS_LOCKED_FIELD, EXECUTION_STATUS_FIELD, ASSIGNED_PROCESS_FIELD,
		 PLANNED_DATE_FIELD],
		as_dict=True)
	if not sub:
		frappe.throw(_("Sub Production Order {0} does not exist.").format(sub_name),
		             title=_("Unknown Sub PO"))
	if not sub.get(PARENT_FIELD):
		frappe.throw(_("{0} is not a Sub Production Order.").format(sub_name),
		             title=_("Not A Sub PO"))
	if cint(sub.docstatus) == 2:
		frappe.throw(_("{0} is cancelled.").format(sub_name), title=_("Sub PO Cancelled"))
	parent_status = frappe.db.get_value("Production Order", sub.get(PARENT_FIELD), "status")
	if parent_status != C.PO_SENT_TO_STORE:
		frappe.throw(
			_("{0} belongs to {1}, which is {2}. Materials can only be requested once the "
			  "Parent Production Order is Sent To Store.").format(
				sub_name, sub.get(PARENT_FIELD), parent_status or _("unknown")),
			title=_("Parent Not Sent To Store"))
	if cint(sub.get(IS_LOCKED_FIELD)):
		frappe.throw(_("{0} is still locked until its Parent is sent to store.").format(sub_name),
		             title=_("Sub PO Locked"))
	if not sub.production_item:
		frappe.throw(_("{0} has no FG item.").format(sub_name), title=_("FG Item Missing"))
	sub["parent_status"] = parent_status
	return sub


def parent_rows(parent_name):
	"""{item_code: Production Order Item row} of the Parent -- standard qty and type."""
	if not parent_name:
		return {}
	out = {}
	for row in frappe.get_all(
			"Production Order Item",
			filters={"parent": parent_name, "parenttype": "Production Order"},
			fields=["item_code", "material_type", "standard_qty", "total_required_qty", "uom"],
			order_by="idx asc"):
		out.setdefault(row.item_code, row)
	return out


def item_info(item_codes):
	"""{item: {item_name, stock_uom, has_batch_no, material_type}}."""
	codes = [c for c in set(item_codes or []) if c]
	if not codes:
		return {}
	fields = ["name", "item_name", "stock_uom", "has_batch_no"]
	if frappe.get_meta("Item").has_field("custom_material_type"):
		fields.append("custom_material_type")
	out = {}
	for row in frappe.get_all("Item", filters={"name": ("in", codes)}, fields=fields):
		out[row.name] = frappe._dict(
			item_name=row.item_name, stock_uom=row.stock_uom,
			has_batch_no=cint(row.has_batch_no),
			material_type=row.get("custom_material_type") or "")
	return out


# ------------------------------------------------------------------------ stock

def bin_qty(item_codes, warehouse):
	"""{item: actual qty} in one warehouse, off Bin."""
	codes = [c for c in set(item_codes or []) if c]
	if not codes or not warehouse:
		return {}
	out = {}
	for row in frappe.get_all("Bin", filters={"item_code": ("in", codes), "warehouse": warehouse},
	                          fields=["item_code", "sum(actual_qty) as qty"], group_by="item_code"):
		out[row.item_code] = flt(row.qty)
	return out


def batch_qty(batch_no, warehouse, item_code=None):
	"""Stock of one batch in one warehouse."""
	if not (batch_no and warehouse):
		return 0.0
	try:
		from erpnext.stock.doctype.batch.batch import get_batch_qty
		return flt(get_batch_qty(batch_no=batch_no, warehouse=warehouse, item_code=item_code))
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Material Management: batch qty")
		return 0.0


def batches_fefo(item_code, warehouse):
	"""Batches of this item with stock in the warehouse, earliest expiry first (FEFO)."""
	if not (item_code and warehouse):
		return []
	try:
		from erpnext.stock.doctype.batch.batch import get_batch_qty
		rows = get_batch_qty(item_code=item_code, warehouse=warehouse) or []
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Material Management: batch list")
		rows = []
	qty = {}
	for row in rows:
		row = frappe._dict(row)
		if row.get("batch_no") and flt(row.get("qty")) > 0:
			qty[row.batch_no] = qty.get(row.batch_no, 0) + flt(row.qty)
	if not qty:
		return []
	meta = {b.name: b for b in frappe.get_all(
		"Batch", filters={"name": ("in", list(qty))},
		fields=["name", "expiry_date", "manufacturing_date", "disabled"])}
	out = []
	for name, q in qty.items():
		b = meta.get(name) or frappe._dict()
		if cint(b.get("disabled")):
			continue
		out.append({"batch_no": name, "qty": q, "expiry_date": b.get("expiry_date"),
		            "manufacturing_date": b.get("manufacturing_date")})
	# No expiry sorts last: a batch that never expires is the one to keep for later.
	out.sort(key=lambda r: (r["expiry_date"] is None, str(r["expiry_date"] or ""),
	                        str(r["manufacturing_date"] or ""), r["batch_no"]))
	return out


# ------------------------------------------------------------------ notification

def users_with_roles(roles):
	users = set()
	for role in roles:
		if frappe.db.exists("Role", role):
			users.update(frappe.get_all("Has Role", filters={"role": role, "parenttype": "User"},
			                            pluck="parent"))
	return {u for u in users if u and u not in ("Administrator", "Guest")
	        and frappe.db.get_value("User", u, "enabled")}


def notify(roles, subject, doctype, name):
	"""A desk notification to every enabled user with one of these roles. Never fails the
	caller: a notification is a courtesy, the document is the fact."""
	users = users_with_roles(roles)
	for user in users:
		try:
			frappe.get_doc({
				"doctype": "Notification Log",
				"subject": subject,
				"for_user": user,
				"type": "Alert",
				"document_type": doctype,
				"document_name": name,
			}).insert(ignore_permissions=True)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "Material Management: notification")
	return sorted(users)


# ----------------------------------------------------------------------- paging

def page_args(start, page_length):
	start = max(cint(start), 0)
	page_length = min(max(cint(page_length) or M.DEFAULT_PAGE_LENGTH, 1), max(M.PAGE_LENGTHS))
	return start, page_length


def date_range(filters, field, date_from, date_to):
	if date_from and date_to:
		filters[field] = ("between", [date_from, date_to])
	elif date_from:
		filters[field] = (">=", date_from)
	elif date_to:
		filters[field] = ("<=", date_to)


def se_status(docstatus):
	return {0: M.SE_DRAFT, 1: M.SE_SUBMITTED, 2: M.SE_CANCELLED}.get(cint(docstatus), M.SE_DRAFT)


def parse(payload):
	if isinstance(payload, str):
		payload = frappe.parse_json(payload)
	return frappe._dict(payload or {})


# ----------------------------------------------------- split / cancel guard helper

def material_activity_blockers(sub_name, existing_codes=()):
	"""Store documents linked to a Sub PO through custom_sub_production_order.

	sub_order.activity_blockers already finds an MR through its `work_order` link and an
	issue through Stock Entry `work_order`. A manual MR, and an issue raised against a Sub PO
	that was never submitted, carry only custom_sub_production_order -- this finds those,
	with the same codes and wording, and skips a code the caller already reported.
	"""
	from alpinos.production.sub_order import VAL_01, VAL_02

	out = []
	existing = set(existing_codes or ())
	if "VAL-01" not in existing and frappe.get_meta("Material Request").has_field(
			"custom_sub_production_order"):
		if frappe.get_all("Material Request",
		                  filters={"custom_sub_production_order": sub_name, "docstatus": ("<", 2)},
		                  limit=1):
			out.append(("VAL-01", _(VAL_01)))
	if "VAL-02" not in existing and frappe.get_meta("Stock Entry").has_field(
			"custom_sub_production_order"):
		if frappe.get_all("Stock Entry",
		                  filters={"custom_sub_production_order": sub_name,
		                           "custom_entry_kind": M.KIND_ISSUE, "docstatus": 1},
		                  limit=1):
			out.append(("VAL-02", _(VAL_02)))
	return out
