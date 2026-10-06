"""Shared helpers for Production Execution (Phase 4) and Production QC (Phase 5).

Vocabulary, role checks, Sub PO status writes, the issued-material arithmetic, and thin
wrappers around the groundwork helpers (notify / audit / shifts / settings) that are
imported lazily so this module still loads on a site where those are not deployed yet.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

from alpinos.production import constants as C
from alpinos.production import material_constants as M
from alpinos.production.work_order_fields import (
	ASSIGNED_MACHINE_FIELD,
	ASSIGNED_PROCESS_FIELD,
	BATCH_FIELD,
	EXECUTION_STATUS_FIELD,
	PARENT_FIELD,
	PLANNED_DATE_FIELD,
)

WORK_ORDER = "Work Order"
MACHINE_RUN = "Machine Run"
PROCESS_MASTER = "Process Master"
RUN_DOCTYPE = "Production Run"
INWARD_DOCTYPE = "Process Inward"
QC_DOCTYPE = "Production QC"

SUB_FIELD = "custom_sub_production_order"
MACHINE_RUN_FIELD = "custom_machine_run"
COMPLETED_PROCESSES_FIELD = "custom_completed_processes"
CURRENT_RUN_FIELD = "custom_current_run"
WIP_QTY_FIELD = "custom_wip_qty"
PLAN_LOCKED_FIELD = "custom_plan_locked"

#: Stock Entry fields added by execution_setup.
SE_INWARD_FIELD = "custom_process_inward"
SE_QC_FIELD = "custom_production_qc"

# --- Sub PO execution statuses (shared contract) -----------------------------------------
ST_UNASSIGNED = C.SUB_EXECUTION_UNASSIGNED
ST_ASSIGNED = C.SUB_EXECUTION_ASSIGNED
ST_PENDING_STORE_ISSUE = M.SUB_EXECUTION_PENDING_STORE_ISSUE
ST_READY_TO_RUN = M.SUB_EXECUTION_READY_TO_RUN
ST_RUNNING = "Running"
ST_PAUSED = "Paused"
ST_PROCESS_COMPLETED = "Process Completed"
ST_INWARD_LOGGED = "Inward Logged"
ST_PENDING_QC = "Pending QC"
ST_READY_NEXT = "Ready for Next Stage"
ST_QC_REJECTED = "QC Rejected"
ST_COMPLETED = C.SUB_EXECUTION_COMPLETED

#: A Sub PO in one of these may be started once the gate passes. "Ready for Next Stage"
#: is here because a Sub PO that comes back for its next process keeps that status until
#: it is started again (the planner only re-assigns process / machine / date).
STARTABLE_STATUSES = (ST_READY_TO_RUN, ST_READY_NEXT)

#: What the shop floor lists.
FLOOR_STATUSES = (ST_ASSIGNED, ST_PENDING_STORE_ISSUE, ST_READY_TO_RUN, ST_READY_NEXT,
                  ST_RUNNING, ST_PAUSED, ST_PROCESS_COMPLETED, ST_INWARD_LOGGED, ST_PENDING_QC)

# --- Production Run statuses ----------------------------------------------------------
RUN_READY = "Ready"
RUN_RUNNING = "Running"
RUN_PAUSED = "Paused"
RUN_COMPLETED = "Process Completed"
RUN_INWARD_LOGGED = "Inward Logged"
RUN_PENDING_QC = "Pending QC"
RUN_CLOSED = "Closed"
RUN_OPEN_STATUSES = (RUN_READY, RUN_RUNNING, RUN_PAUSED, RUN_COMPLETED, RUN_INWARD_LOGGED,
                     RUN_PENDING_QC)

# --- Pause reasons (FRD 4.6.1) --------------------------------------------------------
PAUSE_OTHER = "Other"
PAUSE_REASONS = (
	"Machine Breakdown",
	"Power Failure",
	"Shift Change",
	"Material Shortage",
	"Quality Hold",
	"Planned Maintenance",
	"Cleaning / Sanitization",
	"Operator Unavailable",
	PAUSE_OTHER,
)

# --- QC ---------------------------------------------------------------------------
QC_REJECTION_REASONS = ("Overbaked", "Underbaked", "Contaminated", "Other")

# --- Roles ------------------------------------------------------------------------
ROLE_OPERATOR = "Production Operator"
ROLE_QC_INSPECTOR = "QC Inspector"
ROLE_QC_MANAGER = "QC Manager"
ROLE_PLANT_HEAD = "Plant Head"

SUPER = (C.ROLE_PRODUCTION_ADMIN, C.ROLE_PRODUCTION_MANAGER, "System Manager")
FLOOR_WRITE_ROLES = (ROLE_OPERATOR,) + SUPER
FLOOR_READ_ROLES = FLOOR_WRITE_ROLES + (C.ROLE_PRODUCTION_USER, ROLE_PLANT_HEAD,
                                        ROLE_QC_INSPECTOR, ROLE_QC_MANAGER)
REVERSE_ROLES = (C.ROLE_PRODUCTION_ADMIN, "System Manager")
QC_WRITE_ROLES = (ROLE_QC_INSPECTOR, ROLE_QC_MANAGER, "System Manager")
QC_READ_ROLES = QC_WRITE_ROLES + (C.ROLE_PRODUCTION_ADMIN, C.ROLE_PRODUCTION_MANAGER,
                                  ROLE_PLANT_HEAD, C.ROLE_PRODUCTION_USER)
QC_NOTIFY_ROLES = (ROLE_QC_INSPECTOR, ROLE_QC_MANAGER)
REJECTION_NOTIFY_ROLES = (ROLE_PLANT_HEAD, C.ROLE_PRODUCTION_MANAGER)

FILLING_CODES = ("PRC-FIL",)


def _has_any(roles):
	if frappe.session.user == "Administrator":
		return True
	return bool(set(roles) & set(frappe.get_roles()))


def may(roles):
	return _has_any(roles)


def assert_roles(roles, action):
	if not _has_any(roles):
		frappe.throw(_("You are not permitted to {0}.").format(action), frappe.PermissionError,
		             title=_("Not Permitted"))


# ------------------------------------------------------------------------- meta

def wo_has(field):
	return frappe.get_meta(WORK_ORDER).has_field(field)


def se_has(field):
	return frappe.get_meta("Stock Entry").has_field(field)


def parse(payload):
	if isinstance(payload, str):
		payload = frappe.parse_json(payload)
	return frappe._dict(payload or {})


# -------------------------------------------------------------------- processes

def process_row(process):
	if not process:
		return None
	return frappe.db.get_value(
		PROCESS_MASTER, process,
		["name", "process_code", "process_name", "process_sequence", "is_active", "qc_required",
		 "allow_inward_entry", "allow_machine_assignment"], as_dict=True)


def is_filling_process(process):
	"""Filling runs on its own screens (Builder 2), not on the Mixing/Baking shop floor."""
	if not process:
		return False
	row = process_row(process) or {}
	code = (row.get("process_code") or process or "").upper()
	return code in FILLING_CODES or "fill" in (row.get("process_name") or "").lower()


def active_processes():
	return frappe.get_all(PROCESS_MASTER, filters={"is_active": 1},
	                      fields=["name", "process_code", "process_name", "process_sequence",
	                              "qc_required", "allow_inward_entry"],
	                      order_by="process_sequence asc, name asc")


def previous_process(process):
	"""The active process immediately before this one in sequence, or None."""
	row = process_row(process)
	if not row:
		return None
	seq = cint(row.process_sequence)
	earlier = [p for p in active_processes() if cint(p.process_sequence) < seq]
	return earlier[-1] if earlier else None


def is_output_stage(process):
	"""Does the inward of this process put physical WIP into the baked WIP warehouse?

	Mixing and Baking are recorded on one sheet but the material only becomes a weighable
	product once (after Baking). Posting stock at both would count the same kilograms
	twice. So stock is posted only by the process that comes immediately before Filling
	(or by the last process when there is none after it).
	# default pending BA confirmation: only the last pre-filling process posts stock.
	"""
	row = process_row(process)
	if not row or is_filling_process(process):
		return False
	seq = cint(row.process_sequence)
	later = [p for p in active_processes() if cint(p.process_sequence) > seq]
	return not later or is_filling_process(later[0].name)


def completed_processes(sub_name):
	if not wo_has(COMPLETED_PROCESSES_FIELD):
		return []
	raw = frappe.db.get_value(WORK_ORDER, sub_name, COMPLETED_PROCESSES_FIELD) or ""
	return [p.strip() for p in raw.replace("\n", ",").split(",") if p.strip()]


def add_completed_process(sub_name, process):
	if not wo_has(COMPLETED_PROCESSES_FIELD) or not process:
		return
	done = completed_processes(sub_name)
	if process not in done:
		done.append(process)
	frappe.db.set_value(WORK_ORDER, sub_name, COMPLETED_PROCESSES_FIELD, ", ".join(done))


def remove_completed_process(sub_name, process):
	if not wo_has(COMPLETED_PROCESSES_FIELD) or not process:
		return
	done = [p for p in completed_processes(sub_name) if p != process]
	frappe.db.set_value(WORK_ORDER, sub_name, COMPLETED_PROCESSES_FIELD, ", ".join(done))


# ------------------------------------------------------------------ sub orders

def set_sub_status(sub_names, status, run=None, clear_run=False):
	"""Write the execution status on every Sub PO of a run (db.set_value: they are
	submitted Work Orders and this is a status move, not an edit)."""
	for name in sub_names or []:
		values = {EXECUTION_STATUS_FIELD: status}
		if wo_has(CURRENT_RUN_FIELD):
			if run:
				values[CURRENT_RUN_FIELD] = run
			elif clear_run:
				values[CURRENT_RUN_FIELD] = None
		frappe.db.set_value(WORK_ORDER, name, values)


def clear_planning(sub_names):
	"""Back to the planning backlog for the next process: only the planning fields."""
	for name in sub_names or []:
		values = {ASSIGNED_PROCESS_FIELD: None, ASSIGNED_MACHINE_FIELD: None,
		          PLANNED_DATE_FIELD: None}
		if wo_has(MACHINE_RUN_FIELD):
			values[MACHINE_RUN_FIELD] = None
		frappe.db.set_value(WORK_ORDER, name, values)


def restore_planning(sub_names, process, machine, planned_date=None, machine_run=None):
	for name in sub_names or []:
		values = {ASSIGNED_PROCESS_FIELD: process, ASSIGNED_MACHINE_FIELD: machine or None}
		if planned_date:
			values[PLANNED_DATE_FIELD] = planned_date
		if machine_run and wo_has(MACHINE_RUN_FIELD):
			values[MACHINE_RUN_FIELD] = machine_run
		frappe.db.set_value(WORK_ORDER, name, values)


def add_wip_qty(sub_name, qty):
	if not wo_has(WIP_QTY_FIELD) or not flt(qty):
		return
	current = flt(frappe.db.get_value(WORK_ORDER, sub_name, WIP_QTY_FIELD))
	frappe.db.set_value(WORK_ORDER, sub_name, WIP_QTY_FIELD, max(flt(current + flt(qty), 3), 0))


def sub_info(sub_name):
	fields = ["name", "production_item", "item_name", "qty", "company", "docstatus", "status",
	          "bom_no", "stock_uom", PARENT_FIELD, BATCH_FIELD, EXECUTION_STATUS_FIELD,
	          ASSIGNED_PROCESS_FIELD, ASSIGNED_MACHINE_FIELD, PLANNED_DATE_FIELD]
	for f in (MACHINE_RUN_FIELD, CURRENT_RUN_FIELD, COMPLETED_PROCESSES_FIELD, WIP_QTY_FIELD):
		if wo_has(f):
			fields.append(f)
	row = frappe.db.get_value(WORK_ORDER, sub_name, fields, as_dict=True)
	if not row:
		frappe.throw(_("Sub Production Order {0} does not exist.").format(sub_name),
		             title=_("Not Found"))
	if not row.get(PARENT_FIELD):
		frappe.throw(_("{0} is not a Sub Production Order.").format(sub_name), title=_("Not A Sub PO"))
	return row


def planned_machine_run(sub):
	"""The (Planned) Machine Run this Sub PO is merged into, or None."""
	run = sub.get(MACHINE_RUN_FIELD)
	if run and frappe.db.get_value(MACHINE_RUN, run, "status") == "Planned":
		return run
	return None


def machine_run_members(run):
	if not run:
		return []
	return frappe.get_all("Machine Run Sub Order", filters={"parent": run, "parenttype": MACHINE_RUN},
	                      pluck="sub_order", order_by="idx asc")


def split_members(text):
	return [s.strip() for s in (text or "").replace("\n", ",").split(",") if s.strip()]


def run_members(run_doc):
	members = split_members(run_doc.get("member_sub_orders"))
	if not members and run_doc.get("sub_order"):
		members = [run_doc.sub_order]
	return members


# ------------------------------------------------------------------ materials

def has_material_issue(sub_names):
	"""VAL-GATE-01: a submitted Material Issue against any of these Sub POs."""
	if not sub_names or not se_has("custom_entry_kind") or not se_has(SUB_FIELD):
		return False
	return bool(frappe.get_all("Stock Entry", filters={
		"custom_entry_kind": M.KIND_ISSUE, "docstatus": 1, SUB_FIELD: ("in", list(sub_names))},
		limit=1))


def _kind_qty_by_item(kind, sub_name):
	if not se_has("custom_entry_kind") or not se_has(SUB_FIELD):
		return {}
	names = frappe.get_all("Stock Entry", filters={"custom_entry_kind": kind, "docstatus": 1,
	                                               SUB_FIELD: sub_name}, pluck="name")
	out = {}
	if not names:
		return out
	for r in frappe.get_all("Stock Entry Detail", filters={"parent": ("in", names)},
	                        fields=["item_code", "transfer_qty", "qty"]):
		out[r.item_code] = out.get(r.item_code, 0) + flt(r.transfer_qty or r.qty)
	return out


def net_issued_by_item(sub_name):
	"""Submitted MIs minus submitted Material Returns, per item -- the same arithmetic as
	the Sub PO view (sub_order_view.get_sub_order_view)."""
	issued = _kind_qty_by_item(M.KIND_ISSUE, sub_name)
	returned = _kind_qty_by_item(M.KIND_RETURN, sub_name)
	return {code: flt(qty) - flt(returned.get(code)) for code, qty in issued.items()
	        if flt(qty) - flt(returned.get(code)) > 0}


def issued_rm_kg(sub_name):
	"""Total Issued RM for the mass balance: RM + Additive rows (PM is packaging, it does
	not go into the mix).
	# default pending BA confirmation: PM excluded from Total Issued RM.
	"""
	net = net_issued_by_item(sub_name)
	if not net:
		return 0.0
	types = {}
	if frappe.get_meta("Item").has_field("custom_material_type"):
		types = dict(frappe.get_all("Item", filters={"name": ("in", list(net))},
		                            fields=["name", "custom_material_type"], as_list=True))
	return flt(sum(q for code, q in net.items() if (types.get(code) or "") != C.MATERIAL_PM), 3)


# -------------------------------------------------------------- groundwork wrappers

def notify(roles, subject, doctype=None, name=None, email=False):
	try:
		from alpinos.production.notify import notify as _notify
	except ImportError:
		try:
			from alpinos.production.material_common import notify as _mc_notify
			return _mc_notify(roles, subject, doctype, name)
		except Exception:
			return []
	return _notify(list(roles), subject, doctype=doctype, name=name, email=email)


def log_event(doctype, name, action, details="", reason=""):
	try:
		from alpinos.production.audit import log_event as _log
	except ImportError:
		try:
			frappe.get_doc(doctype, name).add_comment(
				"Info", f"[{action}] {details}" + (f" ({reason})" if reason else ""))
		except Exception:
			pass
		return None
	return _log(doctype, name, action, details=details, reason=reason)


def current_shift():
	try:
		from alpinos.production.shifts import current_shift as _cs
	except ImportError:
		return None
	return _cs()


def wip_warehouse():
	from alpinos.production.production_settings import wip_warehouse as _w

	return _w()


def baked_wip_warehouse():
	from alpinos.production import production_settings as PS

	fn = getattr(PS, "baked_wip_warehouse", None)
	return fn() if fn else PS.wip_warehouse()


def rejected_warehouse():
	from alpinos.production import production_settings as PS

	fn = getattr(PS, "rejected_warehouse", None)
	if fn:
		return fn()
	frappe.throw(_("Set the Rejected Warehouse in Production Settings."),
	             title=_("Rejected Warehouse Not Set"))
