"""Shared helpers for Filling (FRD Phase 6/7) and Post-Filling QC (Phase 9).

Vocabulary, role checks, stock look-ups / stock-entry rows, the Code128 barcode for the FG
label, and thin wrappers around the groundwork notify / audit helpers (imported lazily so
this module loads even before those are deployed).
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, nowdate

from alpinos.production import constants as C

WORK_ORDER = "Work Order"
SE = "Stock Entry"

PLAN = "Filling Plan"
PLAN_ROW = "Filling Plan Row"
INWARD = "Filling Inward"
FINAL_QC = "Final QC"
YIELD = "Production Yield Record"

PARENT_FIELD = "custom_parent_production_order"
BATCH_FIELD = "custom_batch_number"
EXEC_FIELD = "custom_execution_status"
WIP_QTY_FIELD = "custom_wip_qty"
PACK_SIZE_FIELD = "custom_pack_size_kg"

# --- Batch custom fields (created in filling_setup) ---------------------------------
B_SUB = "custom_sub_production_order"
B_PARENT = "custom_parent_production_order"
B_STATUS = "custom_fg_status"
B_LINE = "custom_filling_line"
B_INWARD = "custom_filling_inward"
B_BARCODE = "custom_fg_barcode_svg"

FG_HOLD = "FG-Hold"
FG_CLEARED = "FG-Cleared"
QC_REJECTED = "QC-Rejected"
FG_STATUSES = (FG_HOLD, FG_CLEARED, QC_REJECTED)

# --- Filling Plan ---------------------------------------------------------------------
PLAN_PLANNED = "Planned"
PLAN_IN_PROGRESS = "In Progress"
PLAN_COMPLETED = "Completed"
PLAN_SHORT_CLOSED = "Short-Closed"
PLAN_REROUTED = "Re-Routed"
PLAN_STATUSES = (PLAN_PLANNED, PLAN_IN_PROGRESS, PLAN_COMPLETED, PLAN_SHORT_CLOSED, PLAN_REROUTED)
PLAN_OPEN_STATUSES = (PLAN_PLANNED, PLAN_IN_PROGRESS)

ROW_OPEN = "Open"
ROW_CLOSED = "Closed"

# --- Filling Inward -------------------------------------------------------------------
SUB_PARTIAL = "Partial Inward"
SUB_FINAL = "Final Inward"
SUBMISSION_TYPES = (SUB_PARTIAL, SUB_FINAL)

APPROVAL_NOT_REQUIRED = "Not Required"
APPROVAL_PENDING = "Pending"
APPROVAL_APPROVED = "Approved"

# FRD 7.1 / 7.3.5 messages, verbatim.
MSG_EMPTY = "Cannot submit an empty inward log."
MSG_VAL_FILL_01 = "Actual Production Quantity is required before submitting the inward."
MSG_VAL_FILL_02 = ("Actual Production Quantity cannot exceed the planned quantity. Please contact "
                   "the Production Admin to update the plan.")
MSG_VAL_FILL_03 = "Please enter the Filling Wastage (KG) to complete the inward."
MSG_VAL_FILL_04 = "Entered Filling Wastage exceeds the available WIP quantity."

# --- Final QC -------------------------------------------------------------------------
QC_DRAFT = "Draft"
QC_PENDING_LAB = "Pending Lab Test"
QC_APPROVED = "Approved"
QC_REJECTED_STATUS = "Rejected"
QC_PARTIAL = "Partially Approved"
QC_REVOKED = "Revoked"

DECISION_APPROVE = "Approve Batch"
DECISION_REJECT = "Reject Batch"
DECISION_PARTIAL = "Partial Approval"
DECISIONS = (DECISION_APPROVE, DECISION_REJECT, DECISION_PARTIAL)

TEST_PASS, TEST_FAIL, TEST_PENDING = "Pass", "Fail", "Pending"
STANDARD_TESTS = ("Visual Check", "Seal Integrity", "Weight Check", "Lab Test")
REJECTION_REASONS = ("Seal Leak", "Underweight", "Damaged Packaging", "Contamination", "Other")
CAT_DIRECT = "Direct Reject"
CAT_REPAIR = "Chance of Repair"
CAT_IMPROVE = "Improvement Required"
REJECTION_CATEGORIES = (CAT_DIRECT, CAT_REPAIR, CAT_IMPROVE)
REWORK_CATEGORIES = (CAT_REPAIR, CAT_IMPROVE)

MSG_VAL_QC_01 = "QC quantity mismatch. Please verify the entered quantities."
MSG_VAL_QC_02 = "Please select the rejection reason."
MSG_VAL_QC_03 = "Please enter the Approved Quantity for a Partial Approval."

# --- Roles ----------------------------------------------------------------------------
ROLE_OPERATOR = "Production Operator"
ROLE_QC_INSPECTOR = "QC Inspector"
ROLE_QC_MANAGER = "QC Manager"
ROLE_PLANT_HEAD = "Plant Head"
SYS = "System Manager"

PLANNER_ROLES = (C.ROLE_PRODUCTION_ADMIN, C.ROLE_PRODUCTION_MANAGER, SYS)
OPERATOR_ROLES = (ROLE_OPERATOR,) + PLANNER_ROLES
#: "request an Admin to use the Reverse & Adjust Inward tool" (FRD 7.4.3).
REVERSE_ROLES = (C.ROLE_PRODUCTION_ADMIN, SYS)
#: Replaces the Supervisor PIN of FRD 7.1. default pending BA confirmation: approver roles.
APPROVER_ROLES = (C.ROLE_PRODUCTION_MANAGER, C.ROLE_PRODUCTION_ADMIN, ROLE_PLANT_HEAD, SYS)
QC_ROLES = (ROLE_QC_INSPECTOR, ROLE_QC_MANAGER, SYS)
QC_MANAGER_ROLES = (ROLE_QC_MANAGER, SYS)
FILLING_READ_ROLES = OPERATOR_ROLES + (C.ROLE_PRODUCTION_USER, ROLE_PLANT_HEAD) + QC_ROLES

EPS = 0.0005


def has_any(roles):
	if frappe.session.user == "Administrator":
		return True
	return bool(set(roles) & set(frappe.get_roles()))


def require(roles, action):
	if not has_any(roles):
		frappe.throw(_("You are not allowed to {0}.").format(action), frappe.PermissionError,
		             title=_("Not Permitted"))


def parse(payload):
	if isinstance(payload, str):
		payload = frappe.parse_json(payload or "{}")
	return frappe._dict(payload or {})


def has_field(doctype, field):
	return bool(frappe.db.exists("DocType", doctype)) and frappe.get_meta(doctype).has_field(field)


# --------------------------------------------------------------------------- settings

def S():
	from alpinos.production import production_settings
	return production_settings


def default_company():
	return (frappe.defaults.get_user_default("Company")
	        or frappe.db.get_single_value("Global Defaults", "default_company"))


# ------------------------------------------------------------------------ sub orders

def sub_info(sub_name):
	if not sub_name:
		return None
	fields = ["name", "production_item", "item_name", "qty", "company", "docstatus", "bom_no",
	          PARENT_FIELD, BATCH_FIELD, EXEC_FIELD]
	if has_field(WORK_ORDER, WIP_QTY_FIELD):
		fields.append(WIP_QTY_FIELD)
	row = frappe.db.get_value(WORK_ORDER, sub_name, fields, as_dict=True)
	if row:
		row["wip_qty"] = flt(row.get(WIP_QTY_FIELD))
	return row


def set_sub_wip(sub_name, value):
	if has_field(WORK_ORDER, WIP_QTY_FIELD):
		frappe.db.set_value(WORK_ORDER, sub_name, WIP_QTY_FIELD, max(flt(value, 3), 0),
		                    update_modified=False)


def pack_size(item_code):
	if not item_code or not has_field("Item", PACK_SIZE_FIELD):
		return 0.0
	return flt(frappe.db.get_value("Item", item_code, PACK_SIZE_FIELD))


def sku_name(item_code):
	if not item_code:
		return ""
	fields = ["item_name"]
	if has_field("Item", "custom_target_sku_name"):
		fields.append("custom_target_sku_name")
	row = frappe.db.get_value("Item", item_code, fields, as_dict=True) or {}
	return row.get("custom_target_sku_name") or row.get("item_name") or item_code


# ---------------------------------------------------------------------------- stock

def bin_qty(item, warehouse):
	if not (item and warehouse):
		return 0.0
	return flt(frappe.db.get_value("Bin", {"item_code": item, "warehouse": warehouse}, "actual_qty"))


def batch_qty(batch_no, warehouse, item_code=None):
	from alpinos.production.material_common import batch_qty as _bq
	return flt(_bq(batch_no, warehouse, item_code))


def draw_rows(item, qty, warehouses, prefer_sub=None):
	"""Stock Entry source rows taking `qty` of `item` from `warehouses` in order, split by
	batch (FEFO, the Sub PO's own batches first) for batch-tracked items. Throws a clear
	message when there is not enough."""
	from alpinos.production.material_common import batches_fefo

	qty = flt(qty, 6)
	if qty <= EPS:
		return []
	has_batch = cint(frappe.db.get_value("Item", item, "has_batch_no"))
	rows, left, found = [], qty, 0.0
	warehouses = [w for w in warehouses if w]
	for wh in warehouses:
		if left <= EPS:
			break
		if has_batch:
			batches = batches_fefo(item, wh)
			if prefer_sub and has_field("Batch", B_SUB) and batches:
				own = set(frappe.get_all("Batch", filters={
					"name": ("in", [b["batch_no"] for b in batches]), B_SUB: prefer_sub}, pluck="name"))
				batches.sort(key=lambda b: 0 if b["batch_no"] in own else 1)
			for b in batches:
				if left <= EPS:
					break
				take = min(left, flt(b["qty"]))
				if take <= EPS:
					continue
				rows.append({"item_code": item, "qty": flt(take, 6), "s_warehouse": wh,
				             "batch_no": b["batch_no"]})
				left -= take
				found += take
		else:
			avail = bin_qty(item, wh)
			take = min(left, max(avail, 0))
			if take > EPS:
				rows.append({"item_code": item, "qty": flt(take, 6), "s_warehouse": wh})
				left -= take
				found += take
	if left > 0.001:
		frappe.throw(
			_("Not enough {0} in {1}: {2} needed, {3} available.").format(
				frappe.bold(item), ", ".join(warehouses), flt(qty, 3), flt(found, 3)),
			title=_("Insufficient Stock"))
	return rows


def se_row(row, item_meta=None):
	"""Complete a stock entry row dict with UOM fields."""
	item = row["item_code"]
	uom = frappe.db.get_value("Item", item, "stock_uom")
	out = dict(row)
	out.update({"uom": uom, "stock_uom": uom, "conversion_factor": 1,
	            "transfer_qty": flt(row["qty"], 6)})
	if row.get("batch_no"):
		out["use_serial_batch_fields"] = 1
	return out


def make_stock_entry(purpose, rows, company=None, posting_date=None, sub=None, parent=None,
                     fg_item=None, remarks=""):
	"""Insert + submit a Stock Entry built by this module. Returns its name."""
	se = frappe.new_doc(SE)
	se.purpose = purpose
	se.stock_entry_type = purpose
	se.company = company or default_company()
	if posting_date and str(posting_date) != str(nowdate()):
		se.set_posting_time = 1
	se.posting_date = posting_date or nowdate()
	for field, value in ((B_SUB, sub), (B_PARENT, parent), ("custom_target_fg_item", fg_item)):
		if value and has_field(SE, field):
			se.set(field, value)
	se.remarks = remarks or ""
	for row in rows:
		se.append("items", se_row(row))
	se.flags.alpinos_phase4 = True
	se.flags.alpinos_filling = True
	se.flags.ignore_permissions = True
	se.insert(ignore_permissions=True)
	se.submit()
	return se.name


def cancel_stock_entry(name):
	if not name or not frappe.db.exists(SE, name):
		return
	se = frappe.get_doc(SE, name)
	if cint(se.docstatus) != 1:
		return
	se.flags.alpinos_phase4 = True
	se.flags.alpinos_filling = True
	se.flags.ignore_permissions = True
	try:
		se.cancel()
	except frappe.ValidationError as e:
		frappe.throw(_("Stock Entry {0} could not be reversed: {1}").format(name, e),
		             title=_("Cannot Reverse Stock"))


# -------------------------------------------------------------------- PM from BOM

def sku_bom(sku):
	bom = frappe.db.get_value("Item", sku, "default_bom")
	if bom and cint(frappe.db.get_value("BOM", bom, "is_active")) and \
			cint(frappe.db.get_value("BOM", bom, "docstatus")) < 2:
		return bom
	return frappe.db.get_value("BOM", {"item": sku, "is_active": 1, "is_default": 1,
	                                   "docstatus": ("<", 2)}, "name") or \
		frappe.db.get_value("BOM", {"item": sku, "is_active": 1, "docstatus": ("<", 2)}, "name")


def pm_per_pack(sku):
	"""{pm_item: qty per pack} from the PM rows of the SKU's default active BOM, or None when
	the SKU has no BOM. default pending BA confirmation: PM = BOM rows whose material type
	(row or Item) is PM; qty per pack = row stock qty / BOM quantity."""
	bom = sku_bom(sku) if sku else None
	if not bom:
		return None
	bom_qty = flt(frappe.db.get_value("BOM", bom, "quantity")) or 1
	fields = ["item_code", "stock_qty", "qty"]
	if has_field("BOM Item", "custom_material_type"):
		fields.append("custom_material_type")
	rows = frappe.get_all("BOM Item", filters={"parent": bom, "parenttype": "BOM"}, fields=fields)
	codes = [r.item_code for r in rows]
	types = {}
	if codes and has_field("Item", "custom_material_type"):
		types = dict(frappe.get_all("Item", filters={"name": ("in", codes)},
		                            fields=["name", "custom_material_type"], as_list=True))
	out = {}
	for r in rows:
		mtype = r.get("custom_material_type") or types.get(r.item_code)
		if mtype != C.MATERIAL_PM:
			continue
		out[r.item_code] = out.get(r.item_code, 0) + flt(r.stock_qty or r.qty) / bom_qty
	return out


def pm_warehouses():
	"""default pending BA confirmation: PM is taken from the WIP (shop floor) first, then
	from the Main store."""
	out = []
	for fn in ("wip_warehouse", "main_warehouse"):
		try:
			wh = getattr(S(), fn)()
		except Exception:
			wh = None
		if wh and wh not in out:
			out.append(wh)
	return out


def pm_stock(item):
	return sum(bin_qty(item, wh) for wh in pm_warehouses())


def available_pm_packs(sku):
	"""Packs the current PM stock can make, or None when the SKU has no BOM / no PM rows."""
	per = pm_per_pack(sku)
	if not per:
		return None
	packs = None
	for item, q in per.items():
		if q <= 0:
			continue
		can = int(pm_stock(item) // q)
		packs = can if packs is None else min(packs, can)
	return packs


# -------------------------------------------------------------------- notify / audit

def notify(roles, subject, doctype=None, name=None, email=False):
	try:
		from alpinos.production.notify import notify as _notify
		return _notify(list(roles), subject, doctype=doctype, name=name, email=email)
	except ImportError:
		from alpinos.production.material_common import notify as _mc_notify
		try:
			return _mc_notify(roles, subject, doctype, name)
		except Exception:
			return []
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Filling: notify")
		return []


def audit(doctype, name, action, details="", reason=""):
	try:
		from alpinos.production.audit import log_event
		return log_event(doctype, name, action, details=details, reason=reason)
	except ImportError:
		try:
			frappe.get_doc({
				"doctype": "Comment", "comment_type": "Info",
				"reference_doctype": doctype, "reference_name": name,
				"content": frappe.utils.escape_html(
					f"[{action}] by {frappe.session.user}: {details}" + (f" ({reason})" if reason else "")),
			}).insert(ignore_permissions=True)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "Filling: audit")


def current_shift_name():
	try:
		from alpinos.production.shifts import current_shift
		shift = current_shift()
		return shift.get("name") if shift else ""
	except Exception:
		return ""


# ------------------------------------------------------------------- Code128 barcode

_CODE128 = (
	"212222", "222122", "222221", "121223", "121322", "131222", "122213", "122312", "132212",
	"221213", "221312", "231212", "112232", "122132", "122231", "113222", "123122", "123221",
	"223211", "221132", "221231", "213212", "223112", "312131", "311222", "321122", "321221",
	"312212", "322112", "322211", "212123", "212321", "232121", "111323", "131123", "131321",
	"112313", "132113", "132311", "211313", "231113", "231311", "112133", "112331", "132131",
	"113123", "113321", "133121", "313121", "211331", "231131", "213113", "213311", "213131",
	"311123", "311321", "331121", "312113", "312311", "332111", "314111", "221411", "431111",
	"111224", "111422", "121124", "121421", "141122", "141221", "112214", "112412", "122114",
	"122411", "142112", "142211", "241211", "221114", "413111", "241112", "134111", "111242",
	"121142", "121241", "114212", "124112", "124211", "411212", "421112", "421211", "212141",
	"214121", "412121", "111143", "111341", "131141", "114113", "114311", "411113", "411311",
	"113141", "114131", "311141", "411131", "211412", "211214", "211232", "2331112",
)
_START_B, _STOP = 104, 106


def code128_svg(text, height=34, module=1.2):
	"""Code128-B as an inline SVG string (printable ASCII only; others become '?')."""
	text = "".join(ch if 32 <= ord(ch) <= 126 else "?" for ch in (text or ""))
	values = [ord(ch) - 32 for ch in text]
	check = (_START_B + sum((i + 1) * v for i, v in enumerate(values))) % 103
	codes = [_START_B] + values + [check, _STOP]
	pattern = "".join(_CODE128[c] for c in codes)
	quiet = 10
	x = quiet
	bars = []
	for i, width in enumerate(pattern):
		w = int(width)
		if i % 2 == 0:
			bars.append(f'<rect x="{x * module:.2f}" y="0" width="{w * module:.2f}" height="{height}"/>')
		x += w
	total = (x + quiet) * module
	return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{total:.2f}" height="{height}" '
	        f'viewBox="0 0 {total:.2f} {height}" preserveAspectRatio="none">'
	        f'<rect width="100%" height="100%" fill="#fff"/><g fill="#000">{"".join(bars)}</g></svg>')
