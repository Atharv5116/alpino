"""Sub PO creation — Task 27, at Approval.

SPO-01: a Sub PO is created when the Parent is APPROVED, not when it is submitted. The FRD
contradicts itself on this and the user has confirmed Approval. Three reasons it is the
right end of that contradiction:

    * Task 26 keeps every Sub PO `is_locked` until the Parent is Sent To Store, which is a
      step AFTER Approved. Creating them at Submit would leave them sitting locked and
      unusable, so it buys nothing.
    * A rejection sends the Parent back to Draft (Task 25). Sub POs are named -A / -B / -C
      and a cancelled one keeps its letter on purpose, so a submit / reject / resubmit cycle
      would leave a Parent whose only Sub PO is called -C.
    * A Sub PO is a real Work Order. Existing before approval means somebody can submit it
      and reserve stock against an order nobody has approved.

SPO-02: no manual Sub PO. SPO-03: exactly one -A, so approving twice cannot make a second.

The Sub PO is created as a DRAFT Work Order. That matters: a Work Order writes Bin --
`reserved_qty_for_production`, `planned_qty` -- and creates Job Cards on SUBMIT, and none of
that should happen at approval. Submitting it belongs to Send To Store, where the lock comes
off.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from alpinos.production import constants as C
from alpinos.production.work_order_fields import (
	ASSIGNED_MACHINE_FIELD,
	ASSIGNED_PROCESS_FIELD,
	BATCH_FIELD,
	CLIENT_FIELD,
	EXECUTION_STATUSES,
	EXECUTION_STATUS_FIELD,
	IS_LOCKED_FIELD,
	PARENT_FIELD,
	PLANNED_DATE_FIELD,
	PRODUCTION_TYPE_FIELD,
	SPLIT_FROM_FIELD,
)
from alpinos.production.work_order_naming import next_suffix

WORK_ORDER = "Work Order"

#: What a person may not change on a sub order by hand. Deliberately the fields that tie it
#: to its Parent and to the floor -- the planning fields (process, machine, planned date,
#: execution status) are changed through Assign Process and are not listed here.
_PROTECTED_FIELDS = (
	PARENT_FIELD,
	BATCH_FIELD,
	"qty",
	"production_item",
	"bom_no",
	"company",
	SPLIT_FROM_FIELD,
	IS_LOCKED_FIELD,
	# The planning fields too. `assign_process` sets the flag before it saves, so it still
	# works -- and everything it checks (an Active process, a machine whose type matches,
	# a date that is not in the past, the sub order not locked) would otherwise be skipped
	# entirely by a bare frappe.client.set_value.
	ASSIGNED_PROCESS_FIELD,
	ASSIGNED_MACHINE_FIELD,
	PLANNED_DATE_FIELD,
	EXECUTION_STATUS_FIELD,
)


def existing_sub_orders(parent):
	"""Every Sub PO of this Parent, cancelled ones included.

	Cancelled ones count: they hold a letter that must never be handed out twice, because a
	batch number and a Job Card were printed with it.
	"""
	if not parent:
		return []
	return frappe.get_all(
		WORK_ORDER,
		filters={PARENT_FIELD: parent},
		fields=["name", "qty", "status", "docstatus", IS_LOCKED_FIELD],
		order_by="name asc",
	)


def _resolve_fg_warehouse(item_code, company):
	"""Where the finished goods land. Never guessed.

	`fg_warehouse` is mandatory on a Work Order, and this site has fifteen warehouses of
	which several are Rejected, Quarantine and QC Hold -- picking one off a list would
	eventually book a production run into the Rejected warehouse. So it comes from a real
	default, and when there is none the approval is refused with something actionable.
	"""
	warehouse = frappe.db.get_single_value("Manufacturing Settings", "default_fg_warehouse")
	if warehouse:
		return warehouse

	row = frappe.db.get_value(
		"Item Default",
		{"parent": item_code, "parenttype": "Item", "company": company},
		"default_warehouse",
	)
	if row:
		return row

	# In practice this is what answers on this site: ERPNext copies Stock Settings'
	# default warehouse into an Item Default row on every new item, so the lookup above
	# almost always finds it. Named here as well so the chain does not silently depend on
	# that auto-row still being created.
	warehouse = frappe.db.get_single_value("Stock Settings", "default_warehouse")
	if warehouse and frappe.db.get_value("Warehouse", warehouse, "company") == company:
		return warehouse

	frappe.throw(
		_(
			"There is nowhere to put the finished goods. Set a Default Finished Goods "
			"Warehouse under Manufacturing Settings, or a default warehouse on {0}."
		).format(frappe.bold(item_code)),
		title=_("No Finished Goods Warehouse"),
	)


def _assert_bom_is_submitted(parent):
	"""ERPNext refuses a Work Order against a draft BOM, and says so as "BOM must be
	submitted" with no hint of which document sent it there.

	The Parent deliberately accepts a DRAFT BOM -- Production reads drafts, and only
	`is_active` / `is_default` decide which recipe applies. That difference only bites here,
	at approval, so it is named here rather than left to surface from inside ERPNext.
	"""
	if not parent.bom_no:
		frappe.throw(
			_("{0} has no BOM, so no sub order can be made from it.").format(parent.name),
			title=_("No BOM"),
		)
	if cint(frappe.db.get_value("BOM", parent.bom_no, "docstatus")) != 1:
		frappe.throw(
			_(
				"BOM {0} is still a draft. Submit it in BOM Master before approving {1} -- "
				"a sub order cannot be raised against an unsubmitted recipe."
			).format(frappe.bold(parent.bom_no), parent.name),
			title=_("BOM Not Submitted"),
		)


def assert_quantities_are_set(parent):
	"""Every material row needs a Total Required Qty before the order can be approved.

	The Sub PO inherits these numbers, so approving with zeroes would hand the floor a work
	order that asks for nothing. They are entered by hand for now -- the batch formula that
	would calculate them is one of the open decisions -- which is exactly why this has to be
	checked rather than assumed.
	"""
	missing = [
		row.item_code for row in (parent.get("items") or [])
		if row.item_code and flt(row.total_required_qty) <= 0
	]
	if missing:
		frappe.throw(
			_(
				"These materials have no Total Required Qty: {0}. Fill in the Material "
				"Requirement grid before approving {1}."
			).format(frappe.bold(", ".join(missing[:8])), parent.name),
			title=_("Material Quantities Not Set"),
		)


def create_sub_orders(parent):
	"""SPO-01 + SPO-03. The first Sub PO for an approved Parent, exactly once.

	Returns the Sub POs that now exist, whether this call made them or a previous one did,
	so a caller can report honestly either way.
	"""
	existing = existing_sub_orders(parent.name)
	if existing:
		# SPO-03. Approving again -- or an approval that got retried -- must not add a second.
		return existing

	_assert_bom_is_submitted(parent)
	assert_quantities_are_set(parent)

	sub = frappe.new_doc(WORK_ORDER)
	sub.set(PARENT_FIELD, parent.name)      # read by AlpinosWorkOrder.autoname for the -A
	sub.production_item = parent.fg_item
	sub.bom_no = parent.bom_no
	sub.qty = flt(parent.production_qty_kg)
	sub.company = parent.company or frappe.defaults.get_user_default("Company") or \
		frappe.db.get_single_value("Global Defaults", "default_company")
	sub.planned_start_date = parent.production_start_date or nowdate()
	sub.expected_delivery_date = parent.delivery_date or None
	sub.fg_warehouse = _resolve_fg_warehouse(parent.fg_item, sub.company)
	# No WIP transfer in this model: the Parent is planning and the Sub PO is the run, with
	# nothing staged between them. Without this ERPNext also demands a WIP warehouse.
	sub.skip_transfer = 1

	# Task 32, copied rather than fetched: a change to the Parent after the Sub PO exists
	# must NOT flow down, and a fetch_from would do exactly the opposite.
	sub.set(BATCH_FIELD, parent.batch_number)
	sub.set(PRODUCTION_TYPE_FIELD, parent.production_type)
	sub.set(CLIENT_FIELD, parent.client_name)
	sub.set(EXECUTION_STATUS_FIELD, EXECUTION_STATUSES[0])
	# Task 26: locked until the Parent reaches Sent To Store.
	sub.set(IS_LOCKED_FIELD, 1)
	sub.set(SPLIT_FROM_FIELD, None)

	sub.flags.alpinos_sub_order = True   # SPO-02 lets this one through
	sub.insert(ignore_permissions=True)
	return existing_sub_orders(parent.name)


def unlock_sub_orders(parent_name):
	"""Task D: Send To Store takes the lock off every Sub PO of this Parent."""
	names = [row["name"] for row in existing_sub_orders(parent_name)]
	for name in names:
		frappe.db.set_value(WORK_ORDER, name, IS_LOCKED_FIELD, 0, update_modified=False)
	return names


# ------------------------------------------------------------- the list (Task 30/31)

PAGE_LENGTHS = (50, 100, 200)
DEFAULT_PAGE_LENGTH = 50

LIST_FIELDS = (
	"name", "production_item", "item_name", "qty", "status", "docstatus",
	PARENT_FIELD, BATCH_FIELD, PRODUCTION_TYPE_FIELD, CLIENT_FIELD,
	ASSIGNED_PROCESS_FIELD, ASSIGNED_MACHINE_FIELD, PLANNED_DATE_FIELD,
	EXECUTION_STATUS_FIELD, IS_LOCKED_FIELD, SPLIT_FROM_FIELD,
)


@frappe.whitelist()
def get_sub_order_list(search=None, parent=None, batch=None, item=None, process=None,
                       machine=None, execution_status=None, production_type=None,
                       planned_from=None, planned_to=None, start=0,
                       page_length=DEFAULT_PAGE_LENGTH):
	"""One page of sub orders (Task 30), filtered as Task 31 asks.

	Only sub orders: the filter on the Parent link is what separates them from every
	ordinary Work Order on the site.
	"""
	frappe.has_permission(WORK_ORDER, "read", throw=True)

	start = max(cint(start), 0)
	page_length = min(max(cint(page_length) or DEFAULT_PAGE_LENGTH, 1), max(PAGE_LENGTHS))

	filters = {PARENT_FIELD: ("is", "set"), "docstatus": ("<", 2)}
	if parent:
		filters[PARENT_FIELD] = parent
	if batch:
		filters[BATCH_FIELD] = ("like", f"%{batch}%")
	if item:
		filters["production_item"] = item
	if process:
		filters[ASSIGNED_PROCESS_FIELD] = process
	if machine:
		filters[ASSIGNED_MACHINE_FIELD] = machine
	if execution_status:
		filters[EXECUTION_STATUS_FIELD] = execution_status
	if production_type:
		filters[PRODUCTION_TYPE_FIELD] = production_type
	if planned_from and planned_to:
		filters[PLANNED_DATE_FIELD] = ("between", [planned_from, planned_to])
	elif planned_from:
		filters[PLANNED_DATE_FIELD] = (">=", planned_from)
	elif planned_to:
		filters[PLANNED_DATE_FIELD] = ("<=", planned_to)

	or_filters = None
	if search:
		like = f"%{search}%"
		or_filters = {"name": ("like", like), "production_item": ("like", like),
		              BATCH_FIELD: ("like", like)}

	count = frappe.get_list(WORK_ORDER, fields=["count(name) as total"], filters=filters,
	                        or_filters=or_filters, limit_page_length=0)
	total = cint(count[0].get("total")) if count else 0

	rows = frappe.get_list(WORK_ORDER, filters=filters, or_filters=or_filters,
	                       fields=list(LIST_FIELDS), order_by="name asc",
	                       limit_start=start, limit_page_length=page_length + 1)
	has_more = len(rows) > page_length
	rows = rows[:page_length]

	# The process NAME, not its code -- PRC-MIX means nothing on a planning screen.
	names = {r[ASSIGNED_PROCESS_FIELD] for r in rows if r.get(ASSIGNED_PROCESS_FIELD)}
	labels = {}
	if names:
		labels = {p.name: p.process_name for p in frappe.get_all(
			"Process Master", filters={"name": ("in", list(names))},
			fields=["name", "process_name"])}
	for row in rows:
		row["process_label"] = labels.get(row.get(ASSIGNED_PROCESS_FIELD)) or \
			row.get(ASSIGNED_PROCESS_FIELD)

	return {
		"data": rows, "has_more": int(has_more), "start": start,
		"page_length": page_length, "total": total,
		"page_lengths": list(PAGE_LENGTHS),
		"execution_statuses": list(C.SUB_EXECUTION_STATUSES),
		"production_types": list(C.PRODUCTION_TYPES),
		"can_plan": bool(_user_may_plan()),
	}


@frappe.whitelist()
def split_sub_order_action(sub_order, split_qty, reason=None):
	"""Task 28, for the screen."""
	out = split_sub_order(sub_order, split_qty, reason)
	frappe.db.commit()
	return out


@frappe.whitelist()
def split_context(sub_order):
	"""What the Split dialog shows before anything is typed, including why it cannot."""
	frappe.has_permission(WORK_ORDER, "read", throw=True)
	sub = frappe.get_doc(WORK_ORDER, sub_order)
	parent_status = frappe.db.get_value("Production Order", sub.get(PARENT_FIELD), "status")
	blockers = [message for _code, message in activity_blockers(sub.name)]
	if parent_status not in C.PO_PLANNABLE_STATUSES:
		blockers.insert(0, _(VAL_06))
	return {
		"sub_order": sub.name,
		"parent": sub.get(PARENT_FIELD),
		"parent_status": parent_status,
		"item": sub.production_item,
		"qty": flt(sub.qty),
		"blockers": blockers,
		"can_split": bool(not blockers and _user_may_plan()),
	}


# ------------------------------------------- what has already happened to it

#: Task 29's three blockers, with the exact wording the FRD asks for.
VAL_01 = "Cannot split: A Material Request already exists for this order. Please cancel the request before splitting."
VAL_02 = "Cannot split: Materials have already been issued to the floor for this order."
VAL_03 = "Cannot split: Production activity has already started for this order."
VAL_05 = "Split quantity must be greater than 0 and less than the current quantity."
VAL_06 = "Only approved orders can be split."
VAL_04 = "Cannot merge: Production Orders can only be merged before any planning or production activity begins like splitting."
VAL_07 = "Select at least two orders."


def activity_blockers(sub_name):
	"""What has already happened to this sub order, as (code, message) pairs.

	One function for three callers -- Split (VAL-01..03), Cancel and Merge -- so "has work
	started" cannot come out differently depending on who asks.
	"""
	blockers = []

	if frappe.get_all("Material Request",
	                  filters={"work_order": sub_name, "docstatus": ("<", 2)}, limit=1):
		blockers.append(("VAL-01", _(VAL_01)))

	if frappe.get_all("Stock Entry",
	                  filters={"work_order": sub_name, "docstatus": 1}, limit=1):
		blockers.append(("VAL-02", _(VAL_02)))

	row = frappe.db.get_value(
		"Work Order", sub_name,
		["produced_qty", "material_transferred_for_manufacturing", "status"], as_dict=True)
	started = bool(row) and (
		flt(row.produced_qty) > 0
		or flt(row.material_transferred_for_manufacturing) > 0
		or row.status in ("In Process", "Completed")
	)
	if not started and frappe.get_all(
			"Job Card", filters={"work_order": sub_name, "docstatus": ("<", 2),
			                     "status": ("in", ("Work In Progress", "Completed"))}, limit=1):
		started = True
	if started:
		blockers.append(("VAL-03", _(VAL_03)))

	return blockers


def assert_can_be_planned(sub):
	"""Split and Merge both need a sub order that nothing has happened to yet."""
	for _code, message in activity_blockers(sub.name):
		frappe.throw(message, title=_("Work Has Already Started"))


def delete_sub_orders(parent_name):
	"""Remove a cancelled Parent's sub orders. Only ever called by `cancel_order`, which
	has already established that nothing on the floor points at them."""
	removed = []
	# A REQUEST flag, not a document one: frappe.delete_doc re-fetches the document to run
	# on_trash, so a flag set on this instance is gone by the time the guard reads it -- and
	# the guard then refused the very cleanup that is allowed to happen.
	previous = frappe.flags.get("alpinos_deleting_sub_orders")
	frappe.flags.alpinos_deleting_sub_orders = True
	try:
		for row in existing_sub_orders(parent_name):
			doc = frappe.get_doc(WORK_ORDER, row["name"])
			doc.flags.alpinos_sub_order = True
			doc.flags.ignore_permissions = True
			if cint(doc.docstatus) == 1:
				doc.cancel()
			frappe.delete_doc(WORK_ORDER, doc.name, force=True, ignore_permissions=True)
			removed.append(row["name"])
	finally:
		frappe.flags.alpinos_deleting_sub_orders = previous
	return removed


# ------------------------------------------------------------------- split

def split_sub_order(sub_name, split_qty, reason=None):
	"""Task 28. Take `split_qty` off this sub order and put it on a new next-letter one.

	The original SHRINKS and the new one carries the difference, so BR-PO-03 still holds:
	the sub orders always add up to the Parent. The rounding difference stays on the
	original for the same reason -- somewhere has to absorb it, and the original is the one
	whose number was already quoted.
	"""
	sub = frappe.get_doc(WORK_ORDER, sub_name)
	sub.check_permission("write")

	parent_name = sub.get(PARENT_FIELD)
	if not parent_name:
		frappe.throw(_("{0} is not a sub order, so it cannot be split.").format(sub_name),
		             title=_("Not A Sub Order"))

	parent = frappe.get_doc("Production Order", parent_name)
	if parent.status not in C.PO_PLANNABLE_STATUSES:
		frappe.throw(_(VAL_06), title=_("Cannot Split"))

	assert_can_be_planned(sub)

	split_qty = flt(split_qty)
	current = flt(sub.qty)
	if split_qty <= 0 or split_qty >= current:
		frappe.throw(_(VAL_05), title=_("Cannot Split"))

	suffix = next_suffix(parent_name)
	if not suffix:
		frappe.throw(_("{0} already has as many sub orders as the naming allows.").format(parent_name),
		             title=_("Too Many Sub Orders"))

	remaining = flt(current - split_qty, sub.precision("qty"))

	new = frappe.new_doc(WORK_ORDER)
	new.set(PARENT_FIELD, parent_name)
	new.production_item = sub.production_item
	new.bom_no = sub.bom_no
	new.qty = split_qty
	new.company = sub.company
	new.fg_warehouse = sub.fg_warehouse
	new.skip_transfer = 1
	new.planned_start_date = sub.planned_start_date
	new.expected_delivery_date = sub.expected_delivery_date
	# Task 28: the same batch number, no suffix. And the split inherits the approval --
	# it is the same approved work, divided.
	new.set(BATCH_FIELD, sub.get(BATCH_FIELD))
	new.set(PRODUCTION_TYPE_FIELD, sub.get(PRODUCTION_TYPE_FIELD))
	new.set(CLIENT_FIELD, sub.get(CLIENT_FIELD))
	new.set(EXECUTION_STATUS_FIELD, C.SUB_EXECUTION_UNASSIGNED)
	new.set(IS_LOCKED_FIELD, cint(sub.get(IS_LOCKED_FIELD)))
	new.set(SPLIT_FROM_FIELD, sub.name)
	new.flags.alpinos_sub_order = True
	new.insert(ignore_permissions=True)

	sub.flags.alpinos_sub_order = True
	sub.qty = remaining
	sub.save(ignore_permissions=True)

	_assert_sub_orders_match_parent(parent)

	if reason:
		frappe.get_doc({
			"doctype": "Comment", "comment_type": "Comment",
			"reference_doctype": WORK_ORDER, "reference_name": new.name,
			"content": _("Split from {0}: {1}").format(sub.name, reason),
		}).insert(ignore_permissions=True)

	return {"split_from": sub.name, "new_sub_order": new.name,
	        "remaining_qty": remaining, "split_qty": split_qty}


def _assert_sub_orders_match_parent(parent):
	"""BR-PO-03, checked on the server after every split."""
	total = sum(flt(row.get("qty")) for row in existing_sub_orders(parent.name)
	            if cint(row.get("docstatus")) != 2)
	expected = flt(parent.production_qty_kg)
	if abs(total - expected) > 0.001:
		frappe.throw(
			_("The sub orders add up to {0} but {1} is for {2}. The split was not saved.").format(
				total, parent.name, expected),
			title=_("Sub Orders Do Not Match The Parent"),
		)


# --------------------------------------------------------- Assign Process

def _user_may_plan():
	approvers = {C.ROLE_PRODUCTION_ADMIN, C.ROLE_PRODUCTION_MANAGER, "System Manager"}
	return bool(approvers & set(frappe.get_roles()))


@frappe.whitelist()
def assign_process_context(sub_order):
	"""What the Assign Process dialog needs: the sub order, the processes, and the default.

	PR-03 active processes only; the default is the next one by sequence, which is what a
	planner would pick nine times out of ten.
	"""
	frappe.has_permission(WORK_ORDER, "read", throw=True)
	sub = frappe.get_doc(WORK_ORDER, sub_order)

	processes = frappe.get_all(
		"Process Master", filters={"is_active": 1},
		fields=["name", "process_name", "process_sequence", "allow_machine_assignment"],
		order_by="process_sequence asc, name asc")

	current = sub.get(ASSIGNED_PROCESS_FIELD)
	default = None
	if current:
		# The NEXT one after what it is on now.
		seq = frappe.db.get_value("Process Master", current, "process_sequence")
		later = [p for p in processes if cint(p.process_sequence) > cint(seq)]
		default = later[0].name if later else None
	elif processes:
		default = processes[0].name

	return {
		"sub_order": sub.name,
		"parent": sub.get(PARENT_FIELD),
		"item": sub.production_item,
		"qty": flt(sub.qty),
		"is_locked": cint(sub.get(IS_LOCKED_FIELD)),
		"assigned_process": current,
		"assigned_machine": sub.get(ASSIGNED_MACHINE_FIELD),
		"planned_date": sub.get(PLANNED_DATE_FIELD),
		"processes": processes,
		"default_process": default,
		"can_assign": bool(_user_may_plan()),
	}


@frappe.whitelist()
def machines_for_process(process):
	"""PR-04 / PR-06: Active machines whose TYPE is linked to this process.

	A live query, not a stored list -- a machine added under a linked type is available at
	once, with nothing to re-save (PR-06).
	"""
	frappe.has_permission("Machine", "read", throw=True)
	if not process:
		return []
	types = frappe.get_all("Process Machine Type",
	                       filters={"parent": process, "parenttype": "Process Master"},
	                       pluck="machine_type")
	if not types:
		return []
	return frappe.get_all(
		"Machine",
		filters={"machine_type": ("in", types), "status": C.MACHINE_ACTIVE},
		fields=["name", "machine_name", "machine_type", "filling_process_category"],
		order_by="machine_name asc")


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def machine_query_for_process(doctype, txt, searchfield, start, page_len, filters):
	"""The Machine picker inside the Assign Process dialog.

	The same rule as `machines_for_process`, expressed as a Link query so the dialog can use
	it directly: Active machines whose type is linked to the chosen process.
	"""
	process = (filters or {}).get("process")
	if not process:
		return []
	types = frappe.get_all("Process Machine Type",
	                       filters={"parent": process, "parenttype": "Process Master"},
	                       pluck="machine_type")
	if not types:
		return []
	like = f"%{txt or ''}%"
	return frappe.db.sql(
		"""
		select name, machine_name
		from `tabMachine`
		where status = %(active)s
		  and machine_type in %(types)s
		  and (name like %(txt)s or machine_name like %(txt)s)
		order by machine_name asc
		limit %(start)s, %(page_len)s
		""",
		{"active": C.MACHINE_ACTIVE, "types": tuple(types), "txt": like,
		 "start": cint(start), "page_len": cint(page_len) or 20},
	)


@frappe.whitelist()
def assign_process(sub_order, process, machine=None, planned_date=None):
	"""Task 31. Put a sub order on a process, and optionally a machine and a date."""
	sub = frappe.get_doc(WORK_ORDER, sub_order)
	sub.check_permission("write")

	if not _user_may_plan():
		frappe.throw(
			_("Only a {0} or {1} may assign a process.").format(
				C.ROLE_PRODUCTION_MANAGER, C.ROLE_PRODUCTION_ADMIN),
			title=_("Not A Planner"))

	if cint(sub.get(IS_LOCKED_FIELD)):
		frappe.throw(
			_("{0} is locked until {1} is sent to store.").format(
				sub.name, sub.get(PARENT_FIELD)),
			title=_("Sub Order Is Locked"))

	if not process:
		frappe.throw(_("Please choose the process."), title=_("Process Required"))
	row = frappe.db.get_value("Process Master", process,
	                          ["is_active", "allow_machine_assignment", "process_name"],
	                          as_dict=True)
	if not row:
		frappe.throw(_("Process {0} does not exist.").format(process), title=_("Unknown Process"))
	if not cint(row.is_active):
		frappe.throw(_("Process {0} is inactive, so it cannot be assigned (PR-03).").format(process),
		             title=_("Inactive Process"))

	if machine:
		allowed = {m["name"] for m in machines_for_process(process)}
		if machine not in allowed:
			frappe.throw(
				_("{0} cannot run {1}: its machine type is not linked to that process, or it "
				  "is not Active.").format(machine, row.process_name or process),
				title=_("Machine Does Not Match The Process"))
	elif cint(row.allow_machine_assignment):
		frappe.throw(
			_("{0} needs a machine before it can start.").format(row.process_name or process),
			title=_("Machine Required"))

	if planned_date and getdate(planned_date) < getdate(nowdate()):
		frappe.throw(_("The planned date cannot be in the past."), title=_("Invalid Planned Date"))

	sub.flags.alpinos_sub_order = True
	sub.set(ASSIGNED_PROCESS_FIELD, process)
	sub.set(ASSIGNED_MACHINE_FIELD, machine or None)
	sub.set(PLANNED_DATE_FIELD, planned_date or None)
	if sub.get(EXECUTION_STATUS_FIELD) == C.SUB_EXECUTION_UNASSIGNED:
		sub.set(EXECUTION_STATUS_FIELD, C.SUB_EXECUTION_ASSIGNED)
	sub.save(ignore_permissions=True)
	frappe.db.commit()
	return {"name": sub.name, "process": process, "machine": machine,
	        "planned_date": planned_date,
	        "execution_status": sub.get(EXECUTION_STATUS_FIELD)}


# ------------------------------------------------------------------ SPO-02

def block_manual_sub_order(doc, method=None):
	"""SPO-02: a Sub PO is made by approving a Parent, and no other way.

	Wired at Work Order `validate`. A Work Order with no Parent is an ordinary ERPNext Work
	Order and is left completely alone -- this only guards the ones claiming a Parent.
	"""
	if not doc.get(PARENT_FIELD):
		return
	if doc.flags.get("alpinos_sub_order"):
		return
	if not doc.is_new():
		# A sub order is not edited by hand either. It is derived from its Parent -- change
		# the quantity and its materials, its batch number and the Parent's own total all
		# stop agreeing with it, and nothing puts them back.
		#
		# Everything that is MEANT to change one goes through this module with the flag set:
		# assigning a process, splitting, unlocking at Send To Store. ERPNext's own status
		# bookkeeping uses db_set, which does not come through validate at all.
		before = doc.get_doc_before_save()
		if not before:
			return
		# Named first, and on its own: moving a sub order to another Parent is the one
		# change worth explaining specifically, and the general message below would bury it.
		if (before.get(PARENT_FIELD) or "") != (doc.get(PARENT_FIELD) or ""):
			frappe.throw(
				_("A sub order cannot be moved to a different Parent Production Order."),
				title=_("Parent Cannot Be Changed"),
			)
		changed = [
			field for field in _PROTECTED_FIELDS
			if (before.get(field) or "") != (doc.get(field) or "")
		]
		if changed:
			frappe.throw(
				_(
					"A sub order is not edited directly -- it belongs to {0}. Use Split to "
					"change its quantity, or Assign Process to plan it. (Changed: {1}.)"
				).format(doc.get(PARENT_FIELD), ", ".join(changed)),
				title=_("Sub Orders Are Not Edited Directly"),
			)
		return
	frappe.throw(
		_(
			"A sub order is created by approving its Parent Production Order, not by hand. "
			"Approve {0} instead."
		).format(doc.get(PARENT_FIELD)),
		title=_("Sub Orders Are Not Created Manually"),
	)


def block_manual_sub_order_delete(doc, method=None):
	"""A sub order is not deleted by hand either.

	Deleting one silently breaks BR-PO-03 -- the sub orders must add up to the Parent -- and
	frees its letter, so the next split would reuse a name that a batch number and a printed
	Job Card already carry. Cancelling the Parent is what removes them, together.

	Wired at Work Order `on_trash`.
	"""
	if not doc.get(PARENT_FIELD) or doc.flags.get("alpinos_sub_order"):
		return
	if frappe.flags.get("alpinos_deleting_sub_orders"):
		return  # cancel_order is taking them all, together
	frappe.throw(
		_(
			"A sub order cannot be deleted on its own -- its quantity is part of {0}. "
			"Cancel the Parent Production Order instead."
		).format(doc.get(PARENT_FIELD)),
		title=_("Sub Orders Are Not Deleted Directly"),
	)
