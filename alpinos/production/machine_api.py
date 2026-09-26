"""Server side of the Machine and Machine Type screens.

Same division of labour as `process_api`: only what the standard client API cannot do in
one round trip lives here. That is the readable Machine Type name next to each machine
(a Link stores the TYP- id, and the list shows the name), and the machine count on a
type, which the list needs to say whether a type is safe to retire.

Writes are NOT here. Insert, save and delete go through the standard endpoints so
`Machine.validate` and `MachineType.validate` stay the single place the rules live.
"""

import frappe
from frappe.utils import cint

from alpinos.production import constants as C

MACHINE = "Machine"
MACHINE_TYPE = "Machine Type"

#: BRD 2.2: Machine ID, Machine Name, Machine Type, Max Capacity, Status.
MACHINE_LIST_FIELDS = (
	"name",
	"machine_name",
	"machine_type",
	"max_capacity",
	"capacity_uom",
	"filling_process_category",
	"status",
	"description",
	"modified",
)

MACHINE_TYPE_LIST_FIELDS = (
	"name",
	"machine_type_name",
	"type_code",
	"is_active",
	"description",
	"modified",
)


def _type_names(type_ids):
	"""TYP- id -> readable name, for the ids actually on screen."""
	if not type_ids:
		return {}
	return {
		row.name: row.machine_type_name
		for row in frappe.get_all(
			MACHINE_TYPE,
			filters={"name": ("in", list(type_ids))},
			fields=["name", "machine_type_name"],
		)
	}


# --- Machine -----------------------------------------------------------------


#: Page sizes the screens offer. Same contract as the Item list, which had to be fixed
#: after silently showing 200 of 231 rows with nothing saying so.
PAGE_LENGTHS = (50, 100, 200)
DEFAULT_PAGE_LENGTH = 50


@frappe.whitelist()
def get_machine_list(search=None, machine_type=None, status=None,
                     filling_category=None, start=0,
                     page_length=DEFAULT_PAGE_LENGTH, limit=None):
	"""One page of the Machine list (BRD 2.2), filtered by type and status (BRD 2.2.1).

	`frappe.get_list`, not get_all, so the permission query applies -- these rows are
	about to be shown to somebody.

	`limit` is still accepted so an older caller keeps working; it sets the page size.
	"""
	frappe.has_permission(MACHINE, "read", throw=True)

	start = max(cint(start), 0)
	page_length = cint(page_length) or cint(limit) or DEFAULT_PAGE_LENGTH
	page_length = min(max(page_length, 1), max(PAGE_LENGTHS))

	filters = {}
	if machine_type:
		filters["machine_type"] = machine_type
	if filling_category:
		filters["filling_process_category"] = filling_category
	if status and status != "All":
		filters["status"] = status

	or_filters = None
	if search:
		like = f"%{search}%"
		or_filters = {"name": ("like", like), "machine_name": ("like", like)}

	count_rows = frappe.get_list(
		MACHINE, fields=["count(name) as total"], filters=filters,
		or_filters=or_filters, limit_page_length=0,
	)
	total = cint(count_rows[0].get("total")) if count_rows else 0

	# One more than asked for, so "is there another page" needs no second query.
	rows = frappe.get_list(
		MACHINE,
		filters=filters,
		or_filters=or_filters,
		fields=list(MACHINE_LIST_FIELDS),
		order_by="machine_name asc",
		limit_start=start,
		limit_page_length=page_length + 1,
	)
	has_more = len(rows) > page_length
	rows = rows[:page_length]

	names = _type_names({r["machine_type"] for r in rows if r.get("machine_type")})
	for row in rows:
		row["machine_type_label"] = names.get(row.get("machine_type"), row.get("machine_type"))
	return {
		"data": rows, "has_more": int(has_more), "start": start,
		"page_length": page_length, "total": total,
		"page_lengths": list(PAGE_LENGTHS),
		# The screen hides Add Machine when this is false, rather than offering a button
		# whose save the server is going to refuse.
		"can_create": bool(frappe.has_permission(MACHINE, "create")),
	}


@frappe.whitelist()
def get_machine_form_context(machine=None):
	"""What the Machine entry screen needs to draw itself, in one call."""
	if machine and frappe.db.exists(MACHINE, machine):
		doc = frappe.get_doc(MACHINE, machine)
		doc.check_permission("read")
		can_write = frappe.has_permission(MACHINE, "write", doc=doc)
	else:
		frappe.has_permission(MACHINE, "read", throw=True)
		doc = None
		can_write = frappe.has_permission(MACHINE, "create")

	return {
		"doc": doc.as_dict() if doc else None,
		"can_write": bool(can_write),
		"can_delete": bool(doc and frappe.has_permission(MACHINE, "delete", doc=doc)),
		"machine_types": get_machine_types(),
		"statuses": list(C.MACHINE_STATUSES),
		"capacity_uoms": list(C.MACHINE_CAPACITY_UOMS),
		# Which processes this machine can be put to work on, resolved through its type
		# rather than stored (Machine Master rules 4 and 5).
		"processes": processes_for_machine(doc.machine_type) if doc and doc.machine_type else [],
	}


@frappe.whitelist()
def get_machine_types(include_inactive=0):
	"""The Machine Types a machine may be filed under.

	Inactive types are offered only when one is already selected on the document being
	edited -- otherwise editing an old machine would silently blank its type.
	"""
	frappe.has_permission(MACHINE_TYPE, "read", throw=True)
	filters = {} if cint(include_inactive) else {"is_active": 1}
	return frappe.get_all(
		MACHINE_TYPE,
		filters=filters,
		fields=["name", "machine_type_name", "is_active"],
		order_by="machine_type_name asc",
	)


@frappe.whitelist()
def processes_for_machine(machine_type):
	"""Every Active process whose linked types include this one.

	Read live, never stored: a process that adds this type tomorrow shows up here with
	nothing to re-map on the machine (Machine Master rules 4/5, Process rule 6).
	"""
	if not machine_type:
		return []
	frappe.has_permission("Process Master", "read", throw=True)
	parents = frappe.get_all(
		"Process Machine Type",
		filters={"machine_type": machine_type, "parenttype": "Process Master"},
		pluck="parent",
	)
	if not parents:
		return []
	return frappe.get_all(
		"Process Master",
		filters={"name": ("in", parents), "is_active": 1},
		fields=["name", "process_code", "process_name", "process_sequence"],
		order_by="process_sequence asc",
	)


# --- Machine Type ------------------------------------------------------------


@frappe.whitelist()
def get_machine_type_list(search=None, is_active=None, limit=200):
	"""The Machine Type list, each row carrying how many machines are filed under it."""
	frappe.has_permission(MACHINE_TYPE, "read", throw=True)

	filters = {}
	if is_active not in (None, "", "All"):
		filters["is_active"] = cint(is_active)

	or_filters = None
	if search:
		like = f"%{search}%"
		or_filters = {"name": ("like", like), "machine_type_name": ("like", like)}

	rows = frappe.get_list(
		MACHINE_TYPE,
		filters=filters,
		or_filters=or_filters,
		fields=list(MACHINE_TYPE_LIST_FIELDS),
		order_by="machine_type_name asc",
		limit_page_length=cint(limit) or 200,
	)
	if not rows:
		return []

	ids = [r["name"] for r in rows]
	counts = {}
	for row in frappe.get_all(
		MACHINE,
		filters={"machine_type": ("in", ids)},
		fields=["machine_type", "status", "count(name) as qty"],
		group_by="machine_type, status",
	):
		bucket = counts.setdefault(row.machine_type, {"total": 0, "active": 0})
		bucket["total"] += cint(row.qty)
		if row.status == C.MACHINE_ACTIVE:
			bucket["active"] += cint(row.qty)

	# Same live query the machine screens use, so the two never disagree about which
	# processes a type feeds.
	process_parents = {}
	for row in frappe.get_all(
		"Process Machine Type",
		filters={"machine_type": ("in", ids), "parenttype": "Process Master"},
		fields=["machine_type", "parent"],
	):
		process_parents.setdefault(row.machine_type, set()).add(row.parent)

	for row in rows:
		bucket = counts.get(row["name"], {"total": 0, "active": 0})
		row["machine_count"] = bucket["total"]
		row["active_machine_count"] = bucket["active"]
		row["process_count"] = len(process_parents.get(row["name"], ()))
	return rows


@frappe.whitelist()
def get_machine_type_form_context(machine_type=None):
	"""What the Machine Type entry screen needs, in one call.

	The machines and processes panels are what make deleting a type an informed choice:
	`MachineType.on_trash` refuses a type a process still uses, and this shows why before
	the button is pressed rather than after.
	"""
	if machine_type and frappe.db.exists(MACHINE_TYPE, machine_type):
		doc = frappe.get_doc(MACHINE_TYPE, machine_type)
		doc.check_permission("read")
		can_write = frappe.has_permission(MACHINE_TYPE, "write", doc=doc)
	else:
		frappe.has_permission(MACHINE_TYPE, "read", throw=True)
		doc = None
		can_write = frappe.has_permission(MACHINE_TYPE, "create")

	machines = []
	processes = []
	if doc:
		machines = frappe.get_all(
			MACHINE,
			filters={"machine_type": doc.name},
			fields=["name", "machine_name", "max_capacity", "capacity_uom", "status"],
			order_by="machine_name asc",
		)
		processes = processes_for_machine(doc.name)

	return {
		"doc": doc.as_dict() if doc else None,
		"can_write": bool(can_write),
		"can_delete": bool(doc and frappe.has_permission(MACHINE_TYPE, "delete", doc=doc)),
		"machines": machines,
		"processes": processes,
	}


@frappe.whitelist()
def machine_types_without_process():
	"""PR-09 -- Active Machine Types that no process links to.

	A type nothing maps to is invisible to planning: its machines can never be assigned,
	because a machine is only reachable through Process -> Machine Type. Reported rather
	than blocked, since a type may legitimately be set up before its process is written.
	"""
	frappe.has_permission("Machine Type", "read", throw=True)
	linked = set(
		frappe.get_all(
			"Process Machine Type",
			filters={"parenttype": "Process Master"},
			pluck="machine_type",
		)
	)
	return [
		row
		for row in frappe.get_all(
			"Machine Type",
			filters={"is_active": 1},
			fields=["name", "machine_type_name"],
			order_by="machine_type_name asc",
		)
		if row["name"] not in linked
	]
