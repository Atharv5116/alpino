"""Production Execution -- the shop floor (FRD Phase 4: 4.3 - 4.7). Page `production_floor`.

    get_floor          the rows (one per Sub PO, or one per merged Machine Run), with the
                       gate result (VAL-GATE-01/02/03), the live run and allowed actions
    start_production   Ready to Run -> Running            (4.5)
    pause_production   Running -> Paused, reason mandatory (4.6)
    resume_production  Paused -> Running, downtime added   (4.6)
    complete_production Running -> Process Completed       (4.7, BR-CMP-01..04)

One Production Run is created per Sub PO per process (or per Machine Run when the Sub POs
were merged: BR-MRG-02, all actions are taken against the run). Its child table is the
Production Audit Log and also the downtime ledger. Every status change is written to every
member Sub PO's custom_execution_status with frappe.db.set_value.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, now_datetime, time_diff_in_seconds

from alpinos.production import execution_common as X
from alpinos.production.work_order_fields import (
	ASSIGNED_MACHINE_FIELD,
	ASSIGNED_PROCESS_FIELD,
	BATCH_FIELD,
	EXECUTION_STATUS_FIELD,
	PARENT_FIELD,
	PLANNED_DATE_FIELD,
)

GATE_NO_MI = "Waiting for Material Issue"
GATE_NO_PROCESS = "Pending Process Assignment"
GATE_PREVIOUS = "Previous process not done"


# ======================================================================== minutes

def _minutes(start, end):
	if not (start and end):
		return 0.0
	return max(flt(time_diff_in_seconds(get_datetime(end), get_datetime(start)) / 60.0, 2), 0.0)


def compute_minutes(doc):
	"""BR-CMP-04: net = gross - every recorded pause. Gross runs to completion (or now)."""
	if not doc.get("started_on"):
		doc.gross_minutes = doc.downtime_minutes = doc.net_minutes = 0
		return
	end = doc.get("completed_on") or now_datetime()
	gross = _minutes(doc.started_on, end)
	downtime = sum(flt(r.duration_minutes) for r in (doc.get("logs") or []) if r.event == "Resume")
	if doc.get("status") == X.RUN_PAUSED and doc.get("paused_since"):
		downtime += _minutes(doc.paused_since, end)
	doc.gross_minutes = flt(gross, 2)
	doc.downtime_minutes = flt(downtime, 2)
	doc.net_minutes = flt(max(gross - downtime, 0), 2)


# ======================================================================== the gate

def gate_problems(members, process):
	"""VAL-GATE-01/02/03 for a Sub PO (or all members of a Machine Run).

	Returns a list of {code, message}. Empty = the gate passes.
	"""
	problems = []
	if not process:
		problems.append({"code": "VAL-GATE-02", "message": _(GATE_NO_PROCESS)})
	if not X.has_material_issue(members):
		problems.append({"code": "VAL-GATE-01", "message": _(GATE_NO_MI)})
	if process:
		prev = X.previous_process(process)
		# Without the completed-processes field (groundwork not migrated yet) the sequence
		# cannot be checked; the gate does not invent a block it cannot explain.
		if prev and X.wo_has(X.COMPLETED_PROCESSES_FIELD):
			pending = [m for m in members if prev.name not in X.completed_processes(m)]
			if pending:
				problems.append({
					"code": "VAL-GATE-03",
					"message": _("{0}: {1} ({2})").format(
						_(GATE_PREVIOUS), prev.process_name or prev.name, ", ".join(pending)),
				})
	return problems


def _open_run(members, process, machine_run=None):
	"""The newest not-Closed Production Run of this Sub PO / Machine Run for this process."""
	if not process:
		return None
	filters = {"process_master": process, "status": ("in", X.RUN_OPEN_STATUSES)}
	if machine_run:
		filters["machine_run"] = machine_run
	else:
		filters["sub_order"] = members[0]
	rows = frappe.get_all(X.RUN_DOCTYPE, filters=filters, pluck="name", order_by="creation desc",
	                      limit=1)
	return rows[0] if rows else None


def _closed_run_exists(members, process, machine_run=None):
	filters = {"process_master": process, "status": X.RUN_CLOSED}
	if machine_run:
		filters["machine_run"] = machine_run
	else:
		filters["sub_order"] = members[0]
	return bool(frappe.get_all(X.RUN_DOCTYPE, filters=filters, limit=1))


# ======================================================================== floor data

def _floor_subs(process=None, machine=None, date_from=None, date_to=None, search=None):
	fields = ["name", "production_item", "item_name", "qty", "docstatus", PARENT_FIELD, BATCH_FIELD,
	          EXECUTION_STATUS_FIELD, ASSIGNED_PROCESS_FIELD, ASSIGNED_MACHINE_FIELD,
	          PLANNED_DATE_FIELD]
	for f in (X.MACHINE_RUN_FIELD, X.CURRENT_RUN_FIELD):
		if X.wo_has(f):
			fields.append(f)
	filters = {PARENT_FIELD: ("is", "set"), "docstatus": ("<", 2),
	           EXECUTION_STATUS_FIELD: ("in", X.FLOOR_STATUSES),
	           ASSIGNED_PROCESS_FIELD: ("is", "set")}
	if process:
		filters[ASSIGNED_PROCESS_FIELD] = process
	if machine:
		filters[ASSIGNED_MACHINE_FIELD] = machine
	if date_from and date_to:
		filters[PLANNED_DATE_FIELD] = ("between", [date_from, date_to])
	elif date_from:
		filters[PLANNED_DATE_FIELD] = (">=", date_from)
	elif date_to:
		filters[PLANNED_DATE_FIELD] = ("<=", date_to)
	or_filters = None
	if search:
		like = f"%{search}%"
		or_filters = {"name": ("like", like), BATCH_FIELD: ("like", like),
		              "production_item": ("like", like), PARENT_FIELD: ("like", like)}
	return frappe.get_all(X.WORK_ORDER, filters=filters, or_filters=or_filters, fields=fields,
	                      order_by=f"{PLANNED_DATE_FIELD} asc, name asc", limit_page_length=500)


def _run_payload(run_name):
	if not run_name:
		return None
	run = frappe.get_doc(X.RUN_DOCTYPE, run_name)
	compute_minutes(run)
	return {
		"name": run.name, "status": run.status, "started_on": run.started_on,
		"completed_on": run.completed_on, "paused_since": run.paused_since,
		"pause_reason": run.pause_reason, "gross_minutes": run.gross_minutes,
		"downtime_minutes": run.downtime_minutes, "net_minutes": run.net_minutes,
		"process_inward": run.process_inward,
		"downtime_logged": flt(sum(flt(r.duration_minutes) for r in run.logs if r.event == "Resume"), 2),
		"logs": [{"event": r.event, "at": r.at, "user": r.user, "reason": r.reason,
		          "remarks": r.remarks, "duration_minutes": r.duration_minutes} for r in run.logs],
	}


def _card(key, members_rows, machine_run, processes, may_write):
	first = members_rows[0]
	process = first.get(ASSIGNED_PROCESS_FIELD)
	members = [r.name for r in members_rows]
	if machine_run:
		members = X.machine_run_members(machine_run) or members
	proc = processes.get(process) or X.process_row(process) or {}
	run_name = _open_run(members, process, machine_run)
	run = _run_payload(run_name)
	statuses = {r.get(EXECUTION_STATUS_FIELD) for r in members_rows}
	sub_status = first.get(EXECUTION_STATUS_FIELD)

	gate = []
	if not run or run["status"] == X.RUN_READY:
		gate = gate_problems(members, process)
	startable = (not gate and all(s in X.STARTABLE_STATUSES for s in statuses)
	             and not _closed_run_exists(members, process, machine_run))
	if run and run["status"] != X.RUN_READY:
		display = run["status"]
	elif startable:
		display = X.ST_READY_TO_RUN
	elif gate:
		display = gate[0]["message"] if sub_status in X.STARTABLE_STATUSES else sub_status
	else:
		display = sub_status

	run_status = run["status"] if run else None
	allow_inward = cint(proc.get("allow_inward_entry")) if proc else 1
	return {
		"key": key,
		"machine_run": machine_run,
		"members": members,
		"rows": [{
			"name": r.name, "qty": flt(r.qty), "parent": r.get(PARENT_FIELD),
			"batch": r.get(BATCH_FIELD), "status": r.get(EXECUTION_STATUS_FIELD),
		} for r in members_rows],
		"production_item": first.production_item,
		"item_name": first.item_name,
		"qty": flt(sum(flt(r.qty) for r in members_rows), 3),
		"batch": first.get(BATCH_FIELD),
		"process": process,
		"process_label": proc.get("process_name") or process,
		"machine": first.get(ASSIGNED_MACHINE_FIELD),
		"machine_label": (frappe.db.get_value("Machine", first.get(ASSIGNED_MACHINE_FIELD), "machine_name")
		                  if first.get(ASSIGNED_MACHINE_FIELD) else None),
		"planned_date": first.get(PLANNED_DATE_FIELD),
		"sub_status": sub_status,
		"display_status": display,
		"gate": gate,
		"run": run,
		"can_start": int(may_write and startable and (not run or run_status == X.RUN_READY)),
		"can_pause": int(may_write and run_status == X.RUN_RUNNING),
		"can_resume": int(may_write and run_status == X.RUN_PAUSED),
		"can_complete": int(may_write and run_status == X.RUN_RUNNING),
		"can_inward": int(may_write and run_status == X.RUN_COMPLETED and bool(allow_inward)
		                  and not (run or {}).get("process_inward")),
		"open_inward": (run or {}).get("process_inward"),
	}


@frappe.whitelist()
def get_floor(process=None, machine=None, date_from=None, date_to=None, status=None, search=None):
	"""The shop floor rows, grouped per Machine Run when merged."""
	X.assert_roles(X.FLOOR_READ_ROLES, _("open the Shop Floor"))
	if not frappe.db.table_exists(X.RUN_DOCTYPE):
		frappe.throw(_("The Shop Floor is not installed yet. Ask the administrator to run the "
		               "site migration."), title=_("Not Installed"))
	may_write = X.may(X.FLOOR_WRITE_ROLES)
	processes = {p.name: p for p in X.active_processes()}
	groups, order = {}, []
	for row in _floor_subs(process, machine, date_from, date_to, search):
		if X.is_filling_process(row.get(ASSIGNED_PROCESS_FIELD)):
			continue
		machine_run = X.planned_machine_run(row)
		key = machine_run or row.name
		if key not in groups:
			groups[key] = {"machine_run": machine_run, "rows": []}
			order.append(key)
		groups[key]["rows"].append(row)

	cards = []
	for key in order:
		g = groups[key]
		card = _card(key, g["rows"], g["machine_run"], processes, may_write)
		if status and card["display_status"] != status and card["sub_status"] != status:
			continue
		cards.append(card)

	machines = sorted({(c["machine"], c["machine_label"] or c["machine"]) for c in cards if c["machine"]})
	return {
		"cards": cards,
		"server_time": now_datetime(),
		"processes": [{"name": p.name, "label": p.process_name or p.name}
		              for p in processes.values() if not X.is_filling_process(p.name)],
		"machines": [{"name": m[0], "label": m[1]} for m in machines],
		"statuses": [X.ST_READY_TO_RUN, X.ST_RUNNING, X.ST_PAUSED, X.ST_PROCESS_COMPLETED,
		             X.ST_INWARD_LOGGED, X.ST_PENDING_QC, X.ST_ASSIGNED, X.ST_PENDING_STORE_ISSUE,
		             GATE_NO_MI, GATE_PREVIOUS],
		"pause_reasons": list(X.PAUSE_REASONS),
		"can_write": int(may_write),
	}


# ======================================================================== actions

def _lock_subs(members):
	if members:
		frappe.db.sql("select name from `tabWork Order` where name in %(n)s for update",
		              {"n": tuple(members)})


def _load_run(production_run):
	if not production_run or not frappe.db.exists(X.RUN_DOCTYPE, production_run):
		frappe.throw(_("Production Run {0} does not exist.").format(production_run or ""),
		             title=_("Not Found"))
	frappe.db.sql("select name from `tabProduction Run` where name = %s for update", production_run)
	return frappe.get_doc(X.RUN_DOCTYPE, production_run)


def _log(run, event, reason=None, remarks=None, duration=None):
	run.append("logs", {"event": event, "at": now_datetime(), "user": frappe.session.user,
	                    "reason": reason or None, "remarks": remarks or None,
	                    "duration_minutes": flt(duration, 2) if duration is not None else None})


def _save_run(run):
	run.flags.ignore_permissions = True
	run.save(ignore_permissions=True)


def _audit_members(run, action, details="", reason=""):
	X.log_event(X.RUN_DOCTYPE, run.name, action, details, reason)
	for m in X.run_members(run):
		X.log_event(X.WORK_ORDER, m, action, f"{run.name}: {details}" if details else run.name, reason)


@frappe.whitelist()
def start_production(sub_order):
	"""4.5: Start Production on a Sub PO, or on the Machine Run it is merged into."""
	X.assert_roles(X.FLOOR_WRITE_ROLES, _("start production"))
	sub = X.sub_info(sub_order)
	machine_run = X.planned_machine_run(sub)
	members = X.machine_run_members(machine_run) if machine_run else [sub.name]
	members = members or [sub.name]
	_lock_subs(members)

	process = sub.get(ASSIGNED_PROCESS_FIELD)
	if X.is_filling_process(process):
		frappe.throw(_("Filling is recorded on the Filling Entry screen, not on the Shop Floor."),
		             title=_("Filling Process"))
	existing = _open_run(members, process, machine_run)
	if existing:
		status = frappe.db.get_value(X.RUN_DOCTYPE, existing, "status")
		if status in (X.RUN_RUNNING, X.RUN_PAUSED):
			frappe.throw(_("Production is already {0} on {1}.").format(status, existing),
			             title=_("Already Started"))
		if status != X.RUN_READY:
			frappe.throw(_("Production for this process is already completed ({0}); it cannot be "
			               "restarted (BR-CMP-02).").format(existing), title=_("Already Completed"))
	if _closed_run_exists(members, process, machine_run):
		frappe.throw(_("Production for this process is already completed; it cannot be restarted "
		               "(BR-CMP-02)."), title=_("Already Completed"))

	problems = gate_problems(members, process)
	if problems:
		frappe.throw("<br>".join(f"{p['code']}: {p['message']}" for p in problems),
		             title=_("Not Ready to Run"))

	rows = {m: X.sub_info(m) for m in members}
	for m, r in rows.items():
		status = r.get(EXECUTION_STATUS_FIELD)
		if status not in X.STARTABLE_STATUSES:
			frappe.throw(_("{0} is {1}. Only a Sub PO that is Ready to Run can be started.").format(
				m, status or X.ST_UNASSIGNED), title=_("Not Ready to Run"))
		if r.get(ASSIGNED_PROCESS_FIELD) != process:
			frappe.throw(_("{0} is assigned to a different process than {1}.").format(m, sub.name),
			             title=_("Process Mismatch"))
		if cint(r.docstatus) == 2:
			frappe.throw(_("{0} is cancelled.").format(m), title=_("Sub PO Cancelled"))

	machine = sub.get(ASSIGNED_MACHINE_FIELD) or (
		frappe.db.get_value(X.MACHINE_RUN, machine_run, "machine") if machine_run else None)
	if machine:
		m_status = frappe.db.get_value("Machine", machine, "status")
		if m_status != "Active":
			frappe.throw(_("Machine {0} is {1}; only an Active machine can be started.").format(
				machine, m_status or _("missing")), title=_("Machine Not Active"))
		busy = frappe.get_all(X.RUN_DOCTYPE, filters={"machine": machine,
		                                             "status": ("in", (X.RUN_RUNNING, X.RUN_PAUSED))},
		                      pluck="name", limit=1)
		if busy:
			frappe.throw(_("Machine {0} is already in use by {1}. Complete that run first.").format(
				machine, busy[0]), title=_("Machine Busy"))

	run = frappe.get_doc(X.RUN_DOCTYPE, existing) if existing else frappe.new_doc(X.RUN_DOCTYPE)
	run.sub_order = None if machine_run else sub.name
	run.machine_run = machine_run
	run.member_sub_orders = ", ".join(members)
	run.parent_production_order = sub.get(PARENT_FIELD)
	run.process_master = process
	run.machine = machine
	run.production_item = sub.production_item
	run.total_qty = flt(sum(flt(r.qty) for r in rows.values()), 3)
	run.batch_number = sub.get(BATCH_FIELD)
	run.planned_date = sub.get(PLANNED_DATE_FIELD)
	run.status = X.RUN_RUNNING
	run.started_on = now_datetime()
	run.started_by = frappe.session.user
	_log(run, "Start")
	if run.is_new():
		run.insert(ignore_permissions=True)
	else:
		_save_run(run)
	X.set_sub_status(members, X.ST_RUNNING, run=run.name)
	_audit_members(run, "Production Started")
	frappe.db.commit()
	return {"name": run.name, "status": run.status}


@frappe.whitelist()
def pause_production(production_run, reason=None, remarks=None):
	"""4.6: Pause with a mandatory reason; Other needs remarks."""
	X.assert_roles(X.FLOOR_WRITE_ROLES, _("pause production"))
	run = _load_run(production_run)
	if run.status != X.RUN_RUNNING:
		frappe.throw(_("Only running production can be paused ({0} is {1}).").format(run.name, run.status),
		             title=_("Not Running"))
	if not reason:
		frappe.throw(_("Please select the reason for pausing the production."), title=_("Reason Required"))
	if reason not in X.PAUSE_REASONS:
		frappe.throw(_("{0} is not a valid pause reason.").format(reason), title=_("Invalid Reason"))
	if reason == X.PAUSE_OTHER and not (remarks or "").strip():
		frappe.throw(_("Please enter the reason in the Remarks field."), title=_("Remarks Required"))
	run.status = X.RUN_PAUSED
	run.paused_since = now_datetime()
	run.pause_reason = reason
	_log(run, "Pause", reason, remarks)
	_save_run(run)
	X.set_sub_status(X.run_members(run), X.ST_PAUSED, run=run.name)
	_audit_members(run, "Production Paused", reason, remarks or "")
	frappe.db.commit()
	return {"name": run.name, "status": run.status}


@frappe.whitelist()
def resume_production(production_run):
	"""4.6.5: Resume logs the recovery time and adds the pause to the downtime ledger."""
	X.assert_roles(X.FLOOR_WRITE_ROLES, _("resume production"))
	run = _load_run(production_run)
	if run.status != X.RUN_PAUSED:
		frappe.throw(_("Only paused production can be resumed ({0} is {1}).").format(run.name, run.status),
		             title=_("Not Paused"))
	duration = _minutes(run.paused_since, now_datetime()) if run.paused_since else 0
	reason = run.pause_reason
	run.status = X.RUN_RUNNING
	run.paused_since = None
	run.pause_reason = None
	_log(run, "Resume", reason, None, duration)
	_save_run(run)
	X.set_sub_status(X.run_members(run), X.ST_RUNNING, run=run.name)
	_audit_members(run, "Production Resumed", _("downtime {0} min").format(flt(duration, 2)))
	frappe.db.commit()
	return {"name": run.name, "status": run.status}


@frappe.whitelist()
def complete_production(production_run):
	"""4.7: Running -> Process Completed. No inventory is created here (BR-CMP-03)."""
	X.assert_roles(X.FLOOR_WRITE_ROLES, _("complete production"))
	run = _load_run(production_run)
	if run.status != X.RUN_RUNNING:
		frappe.throw(_("Production can only be completed if it is currently in Running status "
		               "(BR-CMP-01). {0} is {1}.").format(run.name, run.status), title=_("Not Running"))
	run.status = X.RUN_COMPLETED
	run.completed_on = now_datetime()
	run.completed_by = frappe.session.user
	_log(run, "Complete")
	_save_run(run)
	members = X.run_members(run)
	X.set_sub_status(members, X.ST_PROCESS_COMPLETED, run=run.name)
	_audit_members(run, "Production Completed",
	               _("net {0} min, downtime {1} min").format(run.net_minutes, run.downtime_minutes))

	proc = X.process_row(run.process_master) or {}
	inward_allowed = cint(proc.get("allow_inward_entry"))
	if not inward_allowed:
		# A process with no data sheet has nothing to declare: it is done when it completes.
		# default pending BA confirmation: allow_inward_entry = 0 -> Ready for Next Stage on Complete.
		for m in members:
			X.add_completed_process(m, run.process_master)
		X.set_sub_status(members, X.ST_READY_NEXT, clear_run=True)
		X.clear_planning(members)
		frappe.db.set_value(X.RUN_DOCTYPE, run.name, "status", X.RUN_CLOSED)
	frappe.db.commit()
	return {"name": run.name, "status": X.RUN_CLOSED if not inward_allowed else run.status,
	        "inward_allowed": inward_allowed}


@frappe.whitelist()
def get_run(production_run):
	X.assert_roles(X.FLOOR_READ_ROLES, _("view a Production Run"))
	payload = _run_payload(production_run)
	payload["server_time"] = now_datetime()
	return payload
