"""Shared vocabulary and helpers for Inventory (FRD Phase 10), Dispatch rules (Phase 11)
and the Production Reports (Phase 12).

Everything here reads; nothing posts stock. The Stock Entries themselves are made by
inventory_api (Production Transfer / Inventory Adjustment) and checked by inventory_rules.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

from alpinos.production import constants as C
from alpinos.production import material_constants as M

# --- doctypes -----------------------------------------------------------------------

TRANSFER = "Production Transfer"
ADJUSTMENT = "Inventory Adjustment"
SE = "Stock Entry"

# --- Stock Entry kinds owned by this module (custom_entry_kind) ------------------------

KIND_TRANSFER = "Production Transfer"
KIND_ADJUSTMENT = "Inventory Adjustment"
OWN_KINDS = (KIND_TRANSFER, KIND_ADJUSTMENT)

#: Points from a Stock Entry back at the Production Transfer / Inventory Adjustment.
REFERENCE_FIELD = "custom_inventory_reference"

# --- Production Transfer (10.2) ---------------------------------------------------------

TRANSFER_TYPES = ("Floor to Warehouse", "Warehouse to Warehouse", "Quarantine to Floor")
TRANSFER_REASONS = ("Production Transfer", "Warehouse Movement", "QC Transfer", "Rework", "Other")
TRANSFER_REASON_OTHER = "Other"

# --- Inventory Adjustment (10.3) --------------------------------------------------------

ADJ_ADD = "Add Stock"
ADJ_DEDUCT = "Deduct Stock"
ADJUSTMENT_TYPES = (ADJ_ADD, ADJ_DEDUCT)
ADJUSTMENT_REASONS = ("Damage/Scrap", "Audit Correction", "Expired", "Theft/Lost")

ADJ_DRAFT = "Draft"
ADJ_PENDING = "Pending Approval"
ADJ_POSTED = "Posted"
ADJ_REJECTED = "Rejected"
ADJ_CANCELLED = "Cancelled"
ADJUSTMENT_STATUSES = (ADJ_DRAFT, ADJ_PENDING, ADJ_POSTED, ADJ_REJECTED, ADJ_CANCELLED)

# --- FG status on Batch (Builder 2 creates Batch.custom_fg_status) ---------------------

FG_STATUS_FIELD = "custom_fg_status"
FG_HOLD = "FG-Hold"
FG_CLEARED = "FG-Cleared"
FG_REJECTED = "QC-Rejected"
FG_STATUSES = (FG_HOLD, FG_CLEARED, FG_REJECTED)

MSG_UNAPPROVED = "Cannot dispatch unapproved stock."
MSG_INSUFFICIENT = "Insufficient stock in source location."

# --- roles --------------------------------------------------------------------------------

ROLE_PLANT_HEAD = "Plant Head"
ROLE_SYSTEM_MANAGER = "System Manager"

#: Who may create / submit a Production Transfer.
TRANSFER_WRITE_ROLES = (M.ROLE_STORE_USER, M.ROLE_STORE_MANAGER, C.ROLE_PRODUCTION_MANAGER,
                        C.ROLE_PRODUCTION_ADMIN, ROLE_SYSTEM_MANAGER)
#: Who may cancel one.
TRANSFER_MANAGE_ROLES = (M.ROLE_STORE_MANAGER, C.ROLE_PRODUCTION_MANAGER, C.ROLE_PRODUCTION_ADMIN,
                         ROLE_SYSTEM_MANAGER)
#: Who may create / submit an Inventory Adjustment.
ADJUSTMENT_WRITE_ROLES = (M.ROLE_STORE_MANAGER, C.ROLE_PRODUCTION_ADMIN, ROLE_SYSTEM_MANAGER)
#: Who approves a high-value deduction (FRD 13.2: Plant Head).
# default pending BA confirmation: System Manager may also approve (break-glass).
ADJUSTMENT_APPROVE_ROLES = (ROLE_PLANT_HEAD, ROLE_SYSTEM_MANAGER)
#: Who is told a deduction is waiting.
ADJUSTMENT_NOTIFY_ROLES = (ROLE_PLANT_HEAD,)

#: Who may open the inventory dashboards / lists.
INVENTORY_READ_ROLES = tuple(set(
	M.STORE_READ_ROLES + (ROLE_PLANT_HEAD, "Production Operator", "QC Inspector", "QC Manager",
	                      ROLE_SYSTEM_MANAGER)))

#: FRD 12.4 RBAC: only Admin / Manager roles see the reports.
REPORT_ROLES = (C.ROLE_PRODUCTION_ADMIN, C.ROLE_PRODUCTION_MANAGER, ROLE_PLANT_HEAD,
                ROLE_SYSTEM_MANAGER)

#: Who may open Dispatch Tracking (read-only).
DISPATCH_READ_ROLES = tuple(set(REPORT_ROLES + (M.ROLE_STORE_USER, M.ROLE_STORE_MANAGER,
                                                "Stock User", "Stock Manager", "Sales User",
                                                "Sales Manager", "QC Manager")))


# ====================================================================== role checks

def has_any(roles):
	return frappe.session.user == "Administrator" or bool(set(roles) & set(frappe.get_roles()))


def assert_roles(roles, what):
	if not has_any(roles):
		frappe.throw(_("You are not permitted to {0}.").format(what), frappe.PermissionError,
		             title=_("Not Permitted"))


# ======================================================================== settings

def setting(fieldname):
	"""A Production Settings value, or None -- never throws (dashboards, dispatch rules)."""
	try:
		if not frappe.db.exists("DocType", "Production Settings"):
			return None
		meta = frappe.get_meta("Production Settings")
		if not meta.has_field(fieldname):
			return None
		return frappe.get_cached_doc("Production Settings").get(fieldname) or None
	except Exception:
		return None


def baked_wip_wh():
	return setting("baked_wip_warehouse") or setting("wip_warehouse")


def approval_threshold_kg():
	try:
		from alpinos.production.production_settings import adjustment_approval_kg
		return flt(adjustment_approval_kg())
	except Exception:
		value = setting("adjustment_approval_kg")
		return flt(value) if value not in (None, "") else 500.0


# ======================================================================= meta guards

def doctype_exists(doctype):
	return bool(frappe.db.exists("DocType", doctype))


def has_field(doctype, fieldname):
	try:
		return doctype_exists(doctype) and frappe.get_meta(doctype).has_field(fieldname)
	except Exception:
		return False


def first_field(doctype, candidates):
	"""The first of `candidates` that exists on the doctype, else None. Used where another
	builder owns the doctype and the exact field name is not ours to fix."""
	if not doctype_exists(doctype):
		return None
	meta = frappe.get_meta(doctype)
	for name in candidates:
		if meta.has_field(name):
			return name
	return None


def batch_fg_tracked():
	return has_field("Batch", FG_STATUS_FIELD)


# ============================================================================ items

def item_meta(item_codes):
	"""{item: dict(item_name, stock_uom, has_batch_no, material_type, weight_per_unit,
	weight_uom, pack_size_kg)}."""
	codes = [c for c in set(item_codes or []) if c]
	if not codes:
		return {}
	meta = frappe.get_meta("Item")
	fields = ["name", "item_name", "stock_uom", "has_batch_no", "weight_per_unit", "weight_uom"]
	for f in ("custom_material_type", "custom_pack_size_kg"):
		if meta.has_field(f):
			fields.append(f)
	out = {}
	for r in frappe.get_all("Item", filters={"name": ("in", codes)}, fields=fields):
		out[r.name] = frappe._dict(
			item_name=r.item_name, stock_uom=r.stock_uom, has_batch_no=cint(r.has_batch_no),
			material_type=r.get("custom_material_type") or "",
			weight_per_unit=flt(r.weight_per_unit), weight_uom=(r.weight_uom or ""),
			pack_size_kg=flt(r.get("custom_pack_size_kg")))
	return out


_KG = ("kg", "kgs", "kilogram", "kilograms")
_G = ("g", "gm", "gms", "gram", "grams")


def qty_in_kg(qty, info):
	"""Stock qty expressed in KG.

	# default pending BA confirmation: KG UOM as is; grams / 1000; otherwise the FG pack size
	# (custom_pack_size_kg), else the Item's weight per unit; else the qty itself.
	"""
	qty = flt(qty)
	if not info:
		return qty
	uom = (info.stock_uom or "").strip().lower()
	if uom in _KG:
		return qty
	if uom in _G:
		return qty / 1000.0
	if flt(info.pack_size_kg):
		return qty * flt(info.pack_size_kg)
	if flt(info.weight_per_unit):
		wuom = (info.weight_uom or "").strip().lower()
		per = flt(info.weight_per_unit) / (1000.0 if wuom in _G else 1.0)
		return qty * per
	return qty


# ============================================================================ stock

def bin_qty(item_code, warehouse):
	if not (item_code and warehouse):
		return 0.0
	return flt(frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse},
	                               "actual_qty"))


def batch_qty(batch_no, warehouse, item_code=None):
	if not (batch_no and warehouse):
		return 0.0
	try:
		from erpnext.stock.doctype.batch.batch import get_batch_qty
		return flt(get_batch_qty(batch_no=batch_no, warehouse=warehouse, item_code=item_code))
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Inventory: batch qty")
		return 0.0


def available_qty(item_code, warehouse, batch_no=None):
	return batch_qty(batch_no, warehouse, item_code) if batch_no else bin_qty(item_code, warehouse)


def batch_stock(item_codes=None, warehouses=None, batch_nos=None):
	"""[{item_code, batch_no, warehouse, qty}] with qty != 0, off the stock ledger.

	Counts both the v15 Serial and Batch Bundle rows and legacy ledger rows that carry
	batch_no directly, so old and new stock agree.
	"""
	cond_b, cond_l, values = [], [], {}
	if item_codes:
		values["items"] = tuple(item_codes)
		cond_b.append("sle.item_code in %(items)s")
		cond_l.append("sle.item_code in %(items)s")
	if warehouses:
		values["whs"] = tuple(warehouses)
		cond_b.append("sbe.warehouse in %(whs)s")
		cond_l.append("sle.warehouse in %(whs)s")
	if batch_nos:
		values["batches"] = tuple(batch_nos)
		cond_b.append("sbe.batch_no in %(batches)s")
		cond_l.append("sle.batch_no in %(batches)s")
	where_b = " and ".join(["sle.is_cancelled = 0", "ifnull(sbe.batch_no, '') != ''"] + cond_b)
	where_l = " and ".join(["sle.is_cancelled = 0", "ifnull(sle.batch_no, '') != ''",
	                        "ifnull(sle.serial_and_batch_bundle, '') = ''"] + cond_l)
	rows = frappe.db.sql(
		f"""
		select item_code, batch_no, warehouse, sum(qty) as qty from (
			select sle.item_code, sbe.batch_no, sbe.warehouse, sbe.qty
			from `tabSerial and Batch Entry` sbe
			join `tabStock Ledger Entry` sle on sle.serial_and_batch_bundle = sbe.parent
			where {where_b}
			union all
			select sle.item_code, sle.batch_no, sle.warehouse, sle.actual_qty as qty
			from `tabStock Ledger Entry` sle
			where {where_l}
		) t
		group by item_code, batch_no, warehouse
		having abs(sum(qty)) > 0.0000001
		order by item_code, batch_no, warehouse
		""", values, as_dict=True)
	return rows


def fg_status_map(batch_nos):
	"""{batch: dict(fg_status, sub_order, parent, mfg, expiry)}; fg fields guarded."""
	batch_nos = [b for b in set(batch_nos or []) if b]
	if not batch_nos:
		return {}
	meta = frappe.get_meta("Batch")
	fields = ["name", "manufacturing_date", "expiry_date"]
	extra = {"custom_fg_status": "fg_status", "custom_sub_production_order": "sub_order",
	         "custom_parent_production_order": "parent"}
	for f in extra:
		if meta.has_field(f):
			fields.append(f)
	out = {}
	for r in frappe.get_all("Batch", filters={"name": ("in", batch_nos)}, fields=fields):
		out[r.name] = frappe._dict(
			fg_status=r.get("custom_fg_status") or "", sub_order=r.get("custom_sub_production_order") or "",
			parent=r.get("custom_parent_production_order") or "",
			mfg=r.manufacturing_date, expiry=r.expiry_date)
	return out


def company_of_warehouse(warehouse):
	return frappe.db.get_value("Warehouse", warehouse, "company") if warehouse else None


# ====================================================================== side effects

def notify(roles, subject, doctype=None, name=None, email=False):
	try:
		from alpinos.production.notify import notify as _notify
		return _notify(list(roles), subject, doctype=doctype, name=name, email=email)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Inventory: notify")
		return []


def audit(doctype, name, action, details="", reason=""):
	try:
		from alpinos.production.audit import log_event
		return log_event(doctype, name, action, details=details, reason=reason)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Inventory: audit")
		return None


def parse(payload):
	if isinstance(payload, str):
		payload = frappe.parse_json(payload)
	return frappe._dict(payload or {})
