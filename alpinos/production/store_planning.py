"""Store Planning board — the server side of page `store_planning_board` (tasks 1-16).

Everything the calendar does goes through here, and every rule is checked here rather than
only in the browser:

    * planning a Sub PO on a day (drag from the unplanned list, click on an empty day, or
      the Edit Planning button) -> save_planning
    * moving a planned card to another day -> reschedule_planning
    * taking a Sub PO off the calendar -> cancel_planning (reason mandatory)
    * merging Sub POs of the same FG item and the same next process into one Machine Run

Planning itself REUSES sub_order.assign_process, which already knows every rule about an
Active process, a machine whose type matches and a date that is not in the past. The only
thing added around it is what the board needs on top: the parent must be Sent To Store, the
plan must not be locked by a Material Request, merges, and the Machine Run.

The lock (`custom_plan_locked`) is set by Material Management's generate_mr. It is honoured
everywhere here: no reschedule, no re-plan, no cancel, no merge once it is set.

Nothing in this module changes an existing status value or field; the two statuses
"Pending Store Issue" and "Ready to Run" and the lock field belong to Material Management.
"""

import calendar
import datetime
import json

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from alpinos.production import constants as C
from alpinos.production import sub_order as SO
from alpinos.production import stock_allocation as SA
from alpinos.production.store_planning_fields import MACHINE_RUN_FIELD, PROCESS_COLOR_FIELD
from alpinos.production.work_order_fields import (
	ASSIGNED_MACHINE_FIELD,
	ASSIGNED_PROCESS_FIELD,
	BATCH_FIELD,
	EXECUTION_STATUS_FIELD,
	IS_LOCKED_FIELD,
	PARENT_FIELD,
	PLANNED_DATE_FIELD,
	PRODUCTION_TYPE_FIELD,
	SPLIT_FROM_FIELD,
)

WORK_ORDER = "Work Order"
MACHINE_RUN = "Machine Run"
PRODUCTION_ORDER = "Production Order"

#: Material Management's fields (shared contract). Read only when they exist, so the board
#: still opens on a site where that half has not been migrated yet.
PLAN_LOCKED_FIELD = "custom_plan_locked"
MATERIAL_REQUEST_FIELD = "custom_material_request"

STATUS_UNASSIGNED = C.SUB_EXECUTION_UNASSIGNED
STATUS_ASSIGNED = C.SUB_EXECUTION_ASSIGNED
STATUS_PENDING_STORE_ISSUE = SA.STATUS_PENDING_STORE_ISSUE
STATUS_READY_TO_RUN = SA.STATUS_READY_TO_RUN
STATUS_IN_PROGRESS = C.SUB_EXECUTION_IN_PROGRESS
STATUS_COMPLETED = C.SUB_EXECUTION_COMPLETED

#: What the calendar shows.
CALENDAR_STATUSES = SA.ALLOCATING_STATUSES

RUN_PLANNED = "Planned"
RUN_CANCELLED = "Cancelled"

ROLE_STORE_PLANNER = "Store Planner"
ROLE_STORE_USER = "Store User"
ROLE_STORE_MANAGER = "Store Manager"

PLANNER_ROLES = {
	C.ROLE_PRODUCTION_ADMIN, C.ROLE_PRODUCTION_MANAGER, "System Manager", ROLE_STORE_PLANNER,
}
VIEWER_ROLES = PLANNER_ROLES | {C.ROLE_PRODUCTION_USER, ROLE_STORE_USER, ROLE_STORE_MANAGER}

#: Told when "Notify Purchase" is pressed. Whichever of these exist on the site.
PURCHASE_NOTIFY_ROLES = (
	"Purchase Manager", "Purchase User",
	"Purchase Inward Manager", "Purchase Inward User",
	"System Manager",
)

#: Card colours when a process has none set.
DEFAULT_COLOURS = (
	("mix", "#2F80ED"),
	("bak", "#F2994A"),
	("fill", "#27AE60"),
)
FALLBACK_COLOUR = "#828282"

UNPLANNED_LIMIT = 500

# Messages -- the wording the FRD asks for.
MSG_PAST_DATE = "You can't plan on a past date."
MSG_MR_EXISTS = "An MR exists for this sub order; cancel it before re-planning."
MSG_CAPACITY = "Total merged quantity cannot exceed the selected machine's maximum capacity."
MSG_MERGE_RULE = ("Only Sub Production Orders with the same FG Item and the same Process can be "
                  "selected for merging.")
MSG_REASON = "Please enter a cancellation reason before cancelling the planning."
MSG_DATE_REQUIRED = "Please choose the planned date."


# ------------------------------------------------------------------ helpers

def _roles():
	return set(frappe.get_roles())


def _may_plan():
	return bool(PLANNER_ROLES & _roles())


def _assert_can_view():
	if VIEWER_ROLES & _roles():
		return
	frappe.has_permission(WORK_ORDER, "read", throw=True)


def _assert_can_plan():
	if not _may_plan():
		frappe.throw(
			_("Only a Store Planner, Production Manager or Production Admin may change the planning."),
			title=_("Not A Planner"),
		)


def _as_list(value):
	if not value:
		return []
	if isinstance(value, str):
		value = value.strip()
		if value.startswith("["):
			value = json.loads(value)
		else:
			value = [v.strip() for v in value.split(",")]
	return [v for v in dict.fromkeys(value) if v]


def _date_str(value):
	return str(getdate(value)) if value else None


def _wo_has(field):
	return frappe.get_meta(WORK_ORDER).has_field(field)


def _sub_fields():
	fields = [
		"name", "production_item", "item_name", "qty", "company", "docstatus", "status",
		"planned_start_date", "expected_delivery_date",
		PARENT_FIELD, BATCH_FIELD, PRODUCTION_TYPE_FIELD, EXECUTION_STATUS_FIELD,
		IS_LOCKED_FIELD, ASSIGNED_PROCESS_FIELD, ASSIGNED_MACHINE_FIELD, PLANNED_DATE_FIELD,
		SPLIT_FROM_FIELD,
	]
	for optional in (PLAN_LOCKED_FIELD, MATERIAL_REQUEST_FIELD, MACHINE_RUN_FIELD):
		if _wo_has(optional):
			fields.append(optional)
	return fields


def _load(sub_order):
	row = frappe.db.get_value(WORK_ORDER, sub_order, _sub_fields(), as_dict=True)
	if not row:
		frappe.throw(_("Sub order {0} does not exist.").format(sub_order), title=_("Not Found"))
	if not row.get(PARENT_FIELD):
		frappe.throw(_("{0} is not a sub order, so it cannot be planned here.").format(sub_order),
		             title=_("Not A Sub Order"))
	return row


def _open_material_request(sub_name, linked=None):
	"""An MR that is not cancelled, made for this Sub PO (by any of the links it can carry)."""
	if linked and frappe.db.exists("Material Request", linked) \
			and cint(frappe.db.get_value("Material Request", linked, "docstatus")) < 2:
		return linked
	meta = frappe.get_meta("Material Request")
	for field in ("custom_sub_production_order", "work_order"):
		if not meta.has_field(field):
			continue
		found = frappe.get_all("Material Request",
		                       filters={field: sub_name, "docstatus": ("<", 2)},
		                       pluck="name", limit=1)
		if found:
			return found[0]
	return None


def _plan_locked(sub):
	return bool(cint(sub.get(PLAN_LOCKED_FIELD)))


def _parent_status(parent):
	return frappe.db.get_value(PRODUCTION_ORDER, parent, "status")


def _assert_replannable(sub):
	"""Everything that makes a Sub PO's planning untouchable, as one clear message each."""
	if cint(sub.get(IS_LOCKED_FIELD)):
		frappe.throw(_("{0} is locked until {1} is sent to store.").format(
			sub.name, sub.get(PARENT_FIELD)), title=_("Sub Order Is Locked"))
	parent_status = _parent_status(sub.get(PARENT_FIELD))
	if parent_status != C.PO_SENT_TO_STORE:
		frappe.throw(
			_("{0} cannot be planned until its Parent {1} is Sent To Store (it is {2}).").format(
				sub.name, sub.get(PARENT_FIELD), parent_status or _("missing")),
			title=_("Parent Not Sent To Store"))
	if _plan_locked(sub) or _open_material_request(sub.name, sub.get(MATERIAL_REQUEST_FIELD)) \
			or cint(sub.docstatus) == 2:
		frappe.throw(_(MSG_MR_EXISTS), title=_("Planning Is Locked"))
	status = sub.get(EXECUTION_STATUS_FIELD) or STATUS_UNASSIGNED
	if status not in (STATUS_UNASSIGNED, STATUS_ASSIGNED):
		frappe.throw(
			_("{0} is already {1}; its planning can no longer be changed.").format(sub.name, status),
			title=_("Planning Is Locked"))


def _assert_date(planned_date):
	if not planned_date:
		frappe.throw(_(MSG_DATE_REQUIRED), title=_("Planned Date Required"))
	if getdate(planned_date) < getdate(nowdate()):
		frappe.throw(_(MSG_PAST_DATE), title=_("Invalid Planned Date"))


# ---------------------------------------------------------------- processes

def _processes():
	fields = ["name", "process_name", "process_sequence", "allow_machine_assignment"]
	if frappe.get_meta("Process Master").has_field(PROCESS_COLOR_FIELD):
		fields.append(PROCESS_COLOR_FIELD)
	rows = frappe.get_all("Process Master", filters={"is_active": 1}, fields=fields,
	                      order_by="process_sequence asc, name asc")
	for row in rows:
		row["color"] = process_colour(row)
	return rows


def process_colour(process_row):
	"""The card colour: the process's own, else the FRD's defaults by name, else grey."""
	colour = (process_row.get(PROCESS_COLOR_FIELD) or "").strip() if process_row else ""
	if colour:
		return colour
	label = ((process_row or {}).get("process_name") or (process_row or {}).get("name") or "").lower()
	for word, value in DEFAULT_COLOURS:
		if word in label:
			return value
	return FALLBACK_COLOUR


def _completed_processes(sub, processes):
	"""Processes this Sub PO has finished. Only a Completed Sub PO has one on record: the
	sub order carries a single assigned process, and that and every earlier one by sequence
	count as done once it is Completed."""
	if (sub.get(EXECUTION_STATUS_FIELD) != STATUS_COMPLETED) or not sub.get(ASSIGNED_PROCESS_FIELD):
		return []
	seq = cint(frappe.db.get_value("Process Master", sub.get(ASSIGNED_PROCESS_FIELD), "process_sequence"))
	return [p for p in processes if cint(p.process_sequence) <= seq]


def _next_process(sub, processes):
	"""The next active process by sequence after the completed ones."""
	if not processes:
		return None
	done = _completed_processes(sub, processes)
	if not done:
		return processes[0].name
	last = max(cint(p.process_sequence) for p in done)
	later = [p for p in processes if cint(p.process_sequence) > last]
	return later[0].name if later else None


def _machines(process):
	"""sub_order.machines_for_process, plus each machine's capacity for the Merge Center."""
	if not process:
		return []
	if frappe.has_permission("Machine", "read"):
		rows = SO.machines_for_process(process)
	else:
		# A Store Planner may not read Machine directly; the rule is the same one.
		types = frappe.get_all("Process Machine Type",
		                       filters={"parent": process, "parenttype": "Process Master"},
		                       pluck="machine_type")
		rows = frappe.get_all(
			"Machine", filters={"machine_type": ("in", types or [""]), "status": C.MACHINE_ACTIVE},
			fields=["name", "machine_name", "machine_type"], order_by="machine_name asc")
	names = [r["name"] for r in rows]
	caps = {}
	if names:
		caps = {m.name: m for m in frappe.get_all(
			"Machine", filters={"name": ("in", names)},
			fields=["name", "max_capacity", "capacity_uom"])}
	out = []
	for r in rows:
		cap = caps.get(r["name"]) or {}
		out.append({
			"name": r["name"], "machine_name": r.get("machine_name") or r["name"],
			"machine_type": r.get("machine_type"),
			"max_capacity": flt(cap.get("max_capacity")), "capacity_uom": cap.get("capacity_uom"),
		})
	return out


def _validate_process_machine(process, machine):
	"""The same checks sub_order.assign_process makes, done once up front so a merge never
	fails half-way through its members."""
	if not process:
		frappe.throw(_("Please choose the process."), title=_("Process Required"))
	row = frappe.db.get_value("Process Master", process,
	                          ["is_active", "allow_machine_assignment", "process_name"], as_dict=True)
	if not row:
		frappe.throw(_("Process {0} does not exist.").format(process), title=_("Unknown Process"))
	if not cint(row.is_active):
		frappe.throw(_("Process {0} is inactive, so it cannot be assigned (PR-03).").format(process),
		             title=_("Inactive Process"))
	if machine:
		if machine not in {m["name"] for m in _machines(process)}:
			frappe.throw(
				_("{0} cannot run {1}: its machine type is not linked to that process, or it "
				  "is not Active.").format(machine, row.process_name or process),
				title=_("Machine Does Not Match The Process"))
	elif cint(row.allow_machine_assignment):
		frappe.throw(_("{0} needs a machine before it can start.").format(row.process_name or process),
		             title=_("Machine Required"))
	return row


def _apply_plan(sub_name, process, machine, planned_date):
	"""Put one Sub PO on process / machine / date.

	A Production Manager / Admin goes through sub_order.assign_process itself. A Store
	Planner is not one of the roles that function accepts, so for them the same checks
	(already made by _validate_process_machine / _assert_date / _assert_replannable) are
	followed by the same save, with the same flag.
	"""
	doc = frappe.get_doc(WORK_ORDER, sub_name)
	if cint(doc.docstatus) == 1:
		# Submitted by an MR that has since been cancelled (Material Management puts it
		# back to Assigned and unlocks it). A submitted document cannot be saved, so the
		# planning fields -- all read-only links -- are written directly.
		values = {ASSIGNED_PROCESS_FIELD: process, ASSIGNED_MACHINE_FIELD: machine or None,
		          PLANNED_DATE_FIELD: planned_date}
		if (doc.get(EXECUTION_STATUS_FIELD) or STATUS_UNASSIGNED) == STATUS_UNASSIGNED:
			values[EXECUTION_STATUS_FIELD] = STATUS_ASSIGNED
		frappe.db.set_value(WORK_ORDER, doc.name, values)
		return {"name": doc.name}
	if SO._user_may_plan():
		return SO.assign_process(sub_name, process, machine or None, planned_date)
	doc.flags.alpinos_sub_order = True
	doc.set(ASSIGNED_PROCESS_FIELD, process)
	doc.set(ASSIGNED_MACHINE_FIELD, machine or None)
	doc.set(PLANNED_DATE_FIELD, planned_date)
	if (doc.get(EXECUTION_STATUS_FIELD) or STATUS_UNASSIGNED) == STATUS_UNASSIGNED:
		doc.set(EXECUTION_STATUS_FIELD, STATUS_ASSIGNED)
	doc.save(ignore_permissions=True)
	return {"name": doc.name}


# ------------------------------------------------------------ Machine Runs

def _active_run(sub):
	run = sub.get(MACHINE_RUN_FIELD)
	if run and frappe.db.get_value(MACHINE_RUN, run, "status") == RUN_PLANNED:
		return run
	return None


def _run_members(run):
	if not run:
		return []
	return frappe.get_all("Machine Run Sub Order",
	                      filters={"parent": run, "parenttype": MACHINE_RUN},
	                      pluck="sub_order", order_by="idx asc")


def _stamp_run(sub_names, run):
	if not _wo_has(MACHINE_RUN_FIELD):
		return
	for name in sub_names:
		# A read-only link and nothing else: db_set-style, so a submitted (MR-locked)
		# member can still be unlinked when its run is cancelled.
		frappe.db.set_value(WORK_ORDER, name, MACHINE_RUN_FIELD, run, update_modified=False)


def _save_run(run, members, process, machine, planned_date):
	rows = frappe.get_all(WORK_ORDER, filters={"name": ("in", members)},
	                      fields=["name", "production_item", "qty"])
	by_name = {r.name: r for r in rows}
	doc = frappe.get_doc(MACHINE_RUN, run) if run else frappe.new_doc(MACHINE_RUN)
	doc.run_process = process
	doc.machine = machine or None
	doc.planned_date = planned_date
	doc.status = RUN_PLANNED
	doc.production_item = by_name[members[0]].production_item if members[0] in by_name else None
	doc.set("sub_orders", [])
	for name in members:
		r = by_name.get(name) or {}
		doc.append("sub_orders", {"sub_order": name, "production_item": r.get("production_item"),
		                          "qty": flt(r.get("qty"))})
	doc.flags.ignore_permissions = True
	if run:
		doc.save(ignore_permissions=True)
	else:
		doc.insert(ignore_permissions=True)
	return doc.name


def _cancel_run(run, reason=None):
	if not run or not frappe.db.exists(MACHINE_RUN, run):
		return []
	members = _run_members(run)
	frappe.db.set_value(MACHINE_RUN, run, {"status": RUN_CANCELLED, "cancel_reason": reason or None})
	if _wo_has(MACHINE_RUN_FIELD):
		for name in members:
			if frappe.db.get_value(WORK_ORDER, name, MACHINE_RUN_FIELD) == run:
				frappe.db.set_value(WORK_ORDER, name, MACHINE_RUN_FIELD, None, update_modified=False)
	return members


def _capacity_check_enabled():
	try:
		from alpinos.production import production_settings
	except ImportError:
		return False
	try:
		return bool(production_settings.capacity_check_enabled())
	except Exception:
		return False


# -------------------------------------------------------------- unplanned

def _unplanned_rows(extra_filters=None):
	"""Sub POs waiting for the calendar: unlocked (Parent Sent To Store), Unassigned, draft."""
	filters = {
		PARENT_FIELD: ("is", "set"),
		IS_LOCKED_FIELD: 0,
		EXECUTION_STATUS_FIELD: STATUS_UNASSIGNED,
		# Draft per the FRD; a submitted one only exists when an MR was generated and then
		# cancelled and the planning cancelled after it, and it must not vanish.
		"docstatus": ("<", 2),
	}
	filters.update(extra_filters or {})
	rows = frappe.get_all(WORK_ORDER, filters=filters, fields=_sub_fields(),
	                      order_by="planned_start_date asc, name asc",
	                      limit_page_length=UNPLANNED_LIMIT)
	parents = {r.get(PARENT_FIELD) for r in rows}
	sent = set()
	if parents:
		sent = set(frappe.get_all(PRODUCTION_ORDER,
		                          filters={"name": ("in", list(parents)), "status": C.PO_SENT_TO_STORE},
		                          pluck="name"))
	return [r for r in rows if r.get(PARENT_FIELD) in sent]


def _merge_candidates(sub, process, processes=None, exclude=None):
	processes = processes if processes is not None else _processes()
	exclude = set(exclude or []) | {sub.name}
	out = []
	for row in _unplanned_rows({"production_item": sub.production_item}):
		if row.name in exclude:
			continue
		if _next_process(row, processes) != process:
			continue
		out.append({
			"name": row.name, "qty": flt(row.qty), "parent": row.get(PARENT_FIELD),
			"planned_start_date": _date_str(row.planned_start_date),
			"expected_delivery_date": _date_str(row.expected_delivery_date),
			"batch": row.get(BATCH_FIELD),
		})
	return out


# -------------------------------------------------------------- board data

def _month_range(year, month):
	today = getdate(nowdate())
	year = cint(year) or today.year
	month = cint(month) or today.month
	first = datetime.date(year, month, 1)
	last = datetime.date(year, month, calendar.monthrange(year, month)[1])
	grid_start = first - datetime.timedelta(days=first.weekday())
	grid_end = last + datetime.timedelta(days=6 - last.weekday())
	return year, month, first, last, grid_start, grid_end


def _labels(doctype, names, field):
	names = [n for n in set(names) if n]
	if not names:
		return {}
	return {r.name: r.get(field) or r.name for r in frappe.get_all(
		doctype, filters={"name": ("in", names)}, fields=["name", field])}


def _shortage_alerts(stock, subs_by_name):
	alerts = []
	for name, rows in stock.items():
		sub = subs_by_name.get(name)
		if not sub:
			continue
		for row in rows:
			if row["status"] != "Shortage":
				continue
			alerts.append({
				"sub_order": name,
				"parent": sub.get(PARENT_FIELD),
				"planned_date": sub.get(PLANNED_DATE_FIELD),
				"execution_status": sub.get(EXECUTION_STATUS_FIELD),
				"item": row["item"], "item_name": row["item_name"], "uom": row["uom"],
				"required": row["required"], "available": row["available"],
				"deficit": row["deficit"],
			})
	alerts.sort(key=lambda a: (str(a["planned_date"] or "9999-12-31"), a["sub_order"], a["item"]))
	return alerts


def _alert_scope():
	"""Unplanned + planned-but-not-yet-issued Sub POs, and their stock rows."""
	planned = frappe.get_all(
		WORK_ORDER,
		filters={PARENT_FIELD: ("is", "set"), "docstatus": ("<", 2),
		         EXECUTION_STATUS_FIELD: ("in", (STATUS_ASSIGNED, STATUS_PENDING_STORE_ISSUE))},
		fields=_sub_fields())
	unplanned = _unplanned_rows()
	subs = {r.name: r for r in planned + unplanned}
	return subs, unplanned


@frappe.whitelist()
def get_board(year=None, month=None, process=None, machine=None):
	"""Everything the board draws for one month: cards, unplanned list, alerts, legend."""
	_assert_can_view()
	year, month, first, last, grid_start, grid_end = _month_range(year, month)

	filters = {
		PARENT_FIELD: ("is", "set"),
		"docstatus": ("<", 2),
		EXECUTION_STATUS_FIELD: ("in", CALENDAR_STATUSES),
		PLANNED_DATE_FIELD: ("between", [grid_start, grid_end]),
	}
	if process:
		filters[ASSIGNED_PROCESS_FIELD] = process
	if machine:
		filters[ASSIGNED_MACHINE_FIELD] = machine
	cards = frappe.get_all(WORK_ORDER, filters=filters, fields=_sub_fields(),
	                       order_by=PLANNED_DATE_FIELD + " asc, name asc")

	alert_subs, unplanned = _alert_scope()
	stock = SA.stock_status_map(list(alert_subs) + [c.name for c in cards])

	processes = _processes()
	all_process_rows = {p.name: p for p in frappe.get_all(
		"Process Master", fields=["name", "process_name"] + (
			[PROCESS_COLOR_FIELD] if frappe.get_meta("Process Master").has_field(PROCESS_COLOR_FIELD) else []))}
	machine_labels = _labels("Machine", [c.get(ASSIGNED_MACHINE_FIELD) for c in cards], "machine_name")

	run_counts = {}
	runs = [c.get(MACHINE_RUN_FIELD) for c in cards if c.get(MACHINE_RUN_FIELD)]
	if runs:
		active = set(frappe.get_all(MACHINE_RUN, filters={"name": ("in", list(set(runs))),
		                                                   "status": RUN_PLANNED}, pluck="name"))
		for row in frappe.get_all("Machine Run Sub Order",
		                          filters={"parent": ("in", list(active)), "parenttype": MACHINE_RUN},
		                          fields=["parent"]):
			run_counts[row.parent] = run_counts.get(row.parent, 0) + 1

	out_cards = []
	for c in cards:
		proc = all_process_rows.get(c.get(ASSIGNED_PROCESS_FIELD)) or {}
		rows = stock.get(c.name) or []
		short = [r for r in rows if r["status"] == "Shortage"]
		run = c.get(MACHINE_RUN_FIELD)
		out_cards.append({
			"name": c.name, "parent": c.get(PARENT_FIELD), "qty": flt(c.qty),
			"production_item": c.production_item, "item_name": c.item_name,
			"process": c.get(ASSIGNED_PROCESS_FIELD),
			"process_label": proc.get("process_name") or c.get(ASSIGNED_PROCESS_FIELD),
			"color": process_colour(proc) if proc else FALLBACK_COLOUR,
			"machine": c.get(ASSIGNED_MACHINE_FIELD),
			"machine_label": machine_labels.get(c.get(ASSIGNED_MACHINE_FIELD)) or c.get(ASSIGNED_MACHINE_FIELD),
			"planned_date": c.get(PLANNED_DATE_FIELD),
			"execution_status": c.get(EXECUTION_STATUS_FIELD),
			"plan_locked": int(_plan_locked(c)),
			"material_request": c.get(MATERIAL_REQUEST_FIELD),
			"machine_run": run if run in run_counts else None,
			"merged_count": run_counts.get(run, 0),
			"stock_ok": int(not short),
			"has_stock_rows": int(bool(rows)),
			"shortages": short,
		})

	out_unplanned = []
	for u in unplanned:
		rows = stock.get(u.name) or []
		short = [r for r in rows if r["status"] == "Shortage"]
		out_unplanned.append({
			"name": u.name, "parent": u.get(PARENT_FIELD), "qty": flt(u.qty),
			"production_item": u.production_item, "item_name": u.item_name,
			"production_type": u.get(PRODUCTION_TYPE_FIELD), "batch": u.get(BATCH_FIELD),
			"planned_start_date": _date_str(u.planned_start_date),
			"expected_delivery_date": _date_str(u.expected_delivery_date),
			"stock_ok": int(not short), "has_stock_rows": int(bool(rows)),
			"shortages": short,
		})

	return {
		"year": year, "month": month,
		"first": str(first), "last": str(last),
		"grid_start": str(grid_start), "grid_end": str(grid_end),
		"today": nowdate(),
		"cards": out_cards,
		"unplanned": out_unplanned,
		"alerts": _shortage_alerts(stock, alert_subs),
		"processes": [{"name": p.name, "process_name": p.process_name, "color": p.color}
		              for p in processes],
		"can_plan": int(_may_plan()),
		"can_split": int(SO._user_may_plan()),
		"capacity_check": int(_capacity_check_enabled()),
	}


@frappe.whitelist()
def get_sub_order_stock(sub_order, planned_date=None):
	"""The mini stock table (👁) and the stock section of the popups."""
	_assert_can_view()
	return SA.sub_order_stock(sub_order, as_of_date=planned_date or None)


@frappe.whitelist()
def machines_with_capacity(process):
	_assert_can_view()
	return _machines(process)


@frappe.whitelist()
def get_planning_context(sub_order, planned_date=None, process=None):
	"""What the Process Assignment popup needs."""
	_assert_can_view()
	sub = _load(sub_order)
	processes = _processes()
	completed = _completed_processes(sub, processes)
	current = sub.get(ASSIGNED_PROCESS_FIELD) if sub.get(EXECUTION_STATUS_FIELD) == STATUS_ASSIGNED else None
	default_process = process or current or _next_process(sub, processes)
	date = planned_date or sub.get(PLANNED_DATE_FIELD)
	run = _active_run(sub)
	run_members = [m for m in _run_members(run) if m != sub.name]
	return {
		"sub_order": sub.name,
		"parent": sub.get(PARENT_FIELD),
		"item": sub.production_item,
		"item_name": sub.item_name,
		"qty": flt(sub.qty),
		"execution_status": sub.get(EXECUTION_STATUS_FIELD),
		"planned_date": str(date) if date else None,
		"today": nowdate(),
		"processes": processes,
		"completed_processes": [p.process_name or p.name for p in completed],
		"default_process": default_process,
		"assigned_machine": sub.get(ASSIGNED_MACHINE_FIELD),
		"machines": _machines(default_process),
		"merge_candidates": _merge_candidates(sub, default_process, processes, exclude=run_members),
		"machine_run": run,
		"run_members": [{"name": r.name, "qty": flt(r.qty)} for r in frappe.get_all(
			WORK_ORDER, filters={"name": ("in", run_members)}, fields=["name", "qty"])] if run_members else [],
		"stock": SA.sub_order_stock(sub.name, as_of_date=date or None),
		"plan_locked": int(_plan_locked(sub)),
		"capacity_check": int(_capacity_check_enabled()),
		"can_plan": int(_may_plan()),
	}


@frappe.whitelist()
def get_merge_candidates(sub_order, process):
	_assert_can_view()
	sub = _load(sub_order)
	run_members = _run_members(_active_run(sub))
	return _merge_candidates(sub, process, exclude=run_members)


@frappe.whitelist()
def unplanned_options(planned_date=None):
	"""The Sub PO dropdown when an empty day is clicked: unplanned ones only."""
	_assert_can_view()
	return [{"name": r.name, "qty": flt(r.qty), "production_item": r.production_item,
	         "item_name": r.item_name, "parent": r.get(PARENT_FIELD)} for r in _unplanned_rows()]


# ----------------------------------------------------------------- actions

@frappe.whitelist()
def save_planning(sub_order, process, machine=None, planned_date=None, merge_with=None):
	"""Plan a Sub PO -- and any Sub POs merged with it -- on a process, machine and day.

	Reuses sub_order.assign_process for each one (status Unassigned -> Assigned). With
	merges, a Machine Run records them together and each is stamped with it.
	"""
	_assert_can_plan()
	_assert_date(planned_date)
	planned_date = str(getdate(planned_date))
	machine = machine or None
	merge_with = _as_list(merge_with)

	sub = _load(sub_order)
	_assert_replannable(sub)
	_validate_process_machine(process, machine)

	processes = _processes()
	run = _active_run(sub)
	members = [sub.name]
	for name in _run_members(run):
		if name in members:
			continue
		member = _load(name)
		_assert_replannable(member)
		members.append(name)

	new_merges = [m for m in merge_with if m not in members]
	for name in new_merges:
		other = _load(name)
		_assert_replannable(other)
		if other.get(EXECUTION_STATUS_FIELD) != STATUS_UNASSIGNED:
			frappe.throw(_("{0} is already planned; only unplanned Sub POs can be merged.").format(name),
			             title=_("Cannot Merge"))
		if other.production_item != sub.production_item or _next_process(other, processes) != process:
			frappe.throw(_(MSG_MERGE_RULE), title=_("Cannot Merge"))
	members += new_merges

	if len(members) > 1 and machine and _capacity_check_enabled():
		max_capacity = flt(frappe.db.get_value("Machine", machine, "max_capacity"))
		total = sum(flt(frappe.db.get_value(WORK_ORDER, name, "qty")) for name in members)
		if max_capacity and total > max_capacity:
			frappe.throw(_(MSG_CAPACITY), title=_("Machine Capacity Exceeded"))

	for name in members:
		_apply_plan(name, process, machine, planned_date)

	if len(members) > 1:
		run = _save_run(run, members, process, machine, planned_date)
		_stamp_run(members, run)

	frappe.db.commit()
	stock = SA.stock_status_map(members)
	shortages = [dict(r, sub_order=name) for name in members
	             for r in (stock.get(name) or []) if r["status"] == "Shortage"]
	return {"sub_orders": members, "machine_run": run if len(members) > 1 else None,
	        "planned_date": planned_date, "process": process, "machine": machine,
	        "shortages": shortages}


@frappe.whitelist()
def reschedule_planning(sub_order, planned_date):
	"""Dragging a planned card to another day. A merged card moves with its whole run."""
	_assert_can_plan()
	sub = _load(sub_order)
	if sub.get(EXECUTION_STATUS_FIELD) != STATUS_ASSIGNED or not sub.get(ASSIGNED_PROCESS_FIELD):
		if _plan_locked(sub) or sub.get(EXECUTION_STATUS_FIELD) in (
				STATUS_PENDING_STORE_ISSUE, STATUS_READY_TO_RUN, STATUS_IN_PROGRESS):
			frappe.throw(_(MSG_MR_EXISTS), title=_("Planning Is Locked"))
		frappe.throw(_("{0} is not planned yet; drag it from the unplanned list instead.").format(sub.name),
		             title=_("Not Planned"))
	return save_planning(sub.name, sub.get(ASSIGNED_PROCESS_FIELD), sub.get(ASSIGNED_MACHINE_FIELD),
	                     planned_date)


@frappe.whitelist()
def cancel_planning(sub_order, reason=None):
	"""Take a Sub PO off the calendar: back to Unassigned, its Machine Run cancelled."""
	_assert_can_plan()
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_(MSG_REASON), title=_("Reason Required"))
	sub = _load(sub_order)
	if sub.get(EXECUTION_STATUS_FIELD) == STATUS_UNASSIGNED and not sub.get(ASSIGNED_PROCESS_FIELD):
		frappe.throw(_("{0} is not planned, so there is nothing to cancel.").format(sub.name),
		             title=_("Not Planned"))
	_assert_replannable(sub)

	cleared = {ASSIGNED_PROCESS_FIELD: None, ASSIGNED_MACHINE_FIELD: None,
	           PLANNED_DATE_FIELD: None, EXECUTION_STATUS_FIELD: STATUS_UNASSIGNED}
	if cint(sub.docstatus) == 1:
		# Submitted by an MR that was cancelled since; see _apply_plan.
		frappe.db.set_value(WORK_ORDER, sub.name, cleared)
	else:
		doc = frappe.get_doc(WORK_ORDER, sub.name)
		doc.flags.alpinos_sub_order = True
		doc.update(cleared)
		doc.save(ignore_permissions=True)

	run = sub.get(MACHINE_RUN_FIELD)
	released = _cancel_run(run, reason) if run else []

	frappe.get_doc({
		"doctype": "Comment", "comment_type": "Comment",
		"reference_doctype": WORK_ORDER, "reference_name": sub.name,
		"content": _("Planning cancelled: {0}").format(frappe.utils.escape_html(reason)),
	}).insert(ignore_permissions=True)
	frappe.db.commit()
	return {"name": sub.name, "machine_run": run, "released": released}


@frappe.whitelist()
def get_sub_order_summary(sub_order):
	"""The card summary modal."""
	_assert_can_view()
	sub = _load(sub_order)
	process_label = frappe.db.get_value("Process Master", sub.get(ASSIGNED_PROCESS_FIELD), "process_name") \
		if sub.get(ASSIGNED_PROCESS_FIELD) else None
	machine_label = frappe.db.get_value("Machine", sub.get(ASSIGNED_MACHINE_FIELD), "machine_name") \
		if sub.get(ASSIGNED_MACHINE_FIELD) else None

	history = []
	run_names = frappe.get_all("Machine Run Sub Order",
	                           filters={"sub_order": sub.name, "parenttype": MACHINE_RUN},
	                           pluck="parent")
	if run_names:
		for run in frappe.get_all(MACHINE_RUN, filters={"name": ("in", list(set(run_names)))},
		                          fields=["name", "status", "planned_date", "machine", "total_qty",
		                                  "cancel_reason", "creation"],
		                          order_by="creation desc"):
			run["members"] = _run_members(run.name)
			history.append(run)

	status = sub.get(EXECUTION_STATUS_FIELD)
	locked = _plan_locked(sub)
	material_request = sub.get(MATERIAL_REQUEST_FIELD) or _open_material_request(sub.name)
	may_plan = _may_plan()
	editable = (may_plan and not locked and not material_request and cint(sub.docstatus) < 2
	            and not cint(sub.get(IS_LOCKED_FIELD)) and status in (STATUS_UNASSIGNED, STATUS_ASSIGNED))
	return {
		"sub_order": sub.name,
		"parent": sub.get(PARENT_FIELD),
		"parent_status": _parent_status(sub.get(PARENT_FIELD)),
		"item": sub.production_item, "item_name": sub.item_name, "qty": flt(sub.qty),
		"batch": sub.get(BATCH_FIELD),
		"process": sub.get(ASSIGNED_PROCESS_FIELD), "process_label": process_label,
		"machine": sub.get(ASSIGNED_MACHINE_FIELD), "machine_label": machine_label,
		"planned_date": sub.get(PLANNED_DATE_FIELD),
		"execution_status": status,
		"plan_locked": int(locked),
		"material_request": material_request,
		"machine_run": _active_run(sub),
		"split_from": sub.get(SPLIT_FROM_FIELD),
		"merge_history": history,
		"stock": SA.sub_order_stock(sub.name),
		"can_edit": int(editable),
		"can_cancel": int(editable and status == STATUS_ASSIGNED),
		"can_generate_mr": int(may_plan and status == STATUS_ASSIGNED and not locked
		                       and not material_request and bool(sub.get(PLANNED_DATE_FIELD))),
	}


# ---------------------------------------------------- Material Management

def _material_request_module():
	try:
		from alpinos.production import material_request
	except ImportError:
		frappe.throw(_("Material Management is not installed on this site yet, so an MR cannot be generated."),
		             title=_("Not Available"))
	return material_request


@frappe.whitelist()
def generate_mr(sub_order):
	"""Pass-through to Material Management's generate_mr (it owns the rules and the lock)."""
	_assert_can_plan()
	return _material_request_module().generate_mr(sub_order)


@frappe.whitelist()
def week_mr_candidates(date=None):
	"""Planned (Assigned), unlocked Sub POs in the Mon-Sun week of `date` (default today),
	for "Generate MR for this week"."""
	_assert_can_view()
	day = getdate(date or nowdate())
	start = day - datetime.timedelta(days=day.weekday())
	end = start + datetime.timedelta(days=6)
	rows = frappe.get_all(
		WORK_ORDER,
		filters={PARENT_FIELD: ("is", "set"), "docstatus": ("<", 2),
		         EXECUTION_STATUS_FIELD: STATUS_ASSIGNED,
		         PLANNED_DATE_FIELD: ("between", [start, end])},
		fields=_sub_fields(), order_by=PLANNED_DATE_FIELD + " asc, name asc")
	return {
		"from": str(start), "to": str(end),
		"sub_orders": [r.name for r in rows if not _plan_locked(r) and not r.get(MATERIAL_REQUEST_FIELD)],
	}


@frappe.whitelist()
def generate_mr_bulk(sub_orders):
	_assert_can_plan()
	sub_orders = _as_list(sub_orders)
	if not sub_orders:
		frappe.throw(_("There are no planned Sub POs to generate an MR for."), title=_("Nothing Selected"))
	return _material_request_module().generate_mr_bulk(sub_orders)


# ------------------------------------------------------------ notifications

@frappe.whitelist()
def notify_purchase():
	"""Tell Purchase about every current shortage (Notification Log)."""
	_assert_can_plan()
	subs, _unplanned = _alert_scope()
	alerts = _shortage_alerts(SA.stock_status_map(list(subs)), subs)
	if not alerts:
		frappe.throw(_("There are no shortages to report."), title=_("Nothing To Notify"))

	by_item = {}
	for a in alerts:
		entry = by_item.setdefault(a["item"], {"item_name": a["item_name"], "uom": a["uom"],
		                                       "deficit": 0.0, "subs": []})
		entry["deficit"] = max(entry["deficit"], flt(a["deficit"]))
		entry["subs"].append(a["sub_order"])

	subject = _("Material shortage for planned production: {0} item(s) short across {1} Sub PO(s).").format(
		len(by_item), len({a["sub_order"] for a in alerts}))
	lines = "".join(
		"<tr><td>{0}</td><td>{1}</td><td style='text-align:right'>{2} {3}</td><td>{4}</td></tr>".format(
			frappe.utils.escape_html(item), frappe.utils.escape_html(v["item_name"] or ""),
			frappe.format_value(v["deficit"], {"fieldtype": "Float"}), frappe.utils.escape_html(v["uom"] or ""),
			frappe.utils.escape_html(", ".join(sorted(set(v["subs"])))))
		for item, v in sorted(by_item.items()))
	body = ("<table border='1' cellpadding='4' style='border-collapse:collapse'>"
	        "<tr><th>Item</th><th>Name</th><th>Short By</th><th>Sub POs</th></tr>" + lines + "</table>")

	users = set()
	for role in PURCHASE_NOTIFY_ROLES:
		if frappe.db.exists("Role", role):
			users.update(frappe.get_all("Has Role", filters={"role": role, "parenttype": "User"},
			                            pluck="parent"))
	users = {u for u in users if u and u not in ("Administrator", "Guest")
	         and frappe.db.get_value("User", u, "enabled")}
	first_sub = alerts[0]["sub_order"]
	for user in users:
		try:
			frappe.get_doc({
				"doctype": "Notification Log", "subject": subject, "email_content": body,
				"for_user": user, "type": "Alert",
				"document_type": WORK_ORDER, "document_name": first_sub,
			}).insert(ignore_permissions=True)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "Store Planning: purchase notification")
	frappe.db.commit()
	return {"notified": sorted(users), "items": len(by_item)}
