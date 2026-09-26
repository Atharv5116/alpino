"""Server side of the Process Master screens.

Only what the standard client API cannot do in one round trip lives here: the list needs
each process's Machine Types, which sit in a child table, and `frappe.client.get_list`
returns parent rows only. Everything else — insert, save, delete — goes through the
standard endpoints, so `ProcessMaster.validate` stays the single place the rules live.
"""

import frappe
from frappe.utils import cint

DOCTYPE = "Process Master"

LIST_FIELDS = (
	"name",
	"process_code",
	"process_name",
	"process_sequence",
	"description",
	"qc_required",
	"allow_inward_entry",
	"allow_machine_assignment",
	"is_active",
	"modified",
)


@frappe.whitelist()
def get_list(search=None, machine_type=None, is_active=None, limit=200):
	"""The Process Master list, each row carrying the Machine Types it allows.

	`frappe.get_list` (not get_all) so the permission query and has_permission hooks
	apply — these rows are about to be shown to somebody.
	"""
	frappe.has_permission(DOCTYPE, "read", throw=True)

	filters = {}
	if is_active not in (None, "", "All"):
		filters["is_active"] = cint(is_active)

	or_filters = None
	if search:
		like = f"%{search}%"
		or_filters = {"process_code": ("like", like), "process_name": ("like", like)}

	if machine_type:
		# The child table is the filter, so resolve it to parents first rather than
		# joining -- a parent with no matching row must not appear at all.
		parents = frappe.get_all(
			"Process Machine Type",
			filters={"machine_type": machine_type, "parenttype": DOCTYPE},
			pluck="parent",
		)
		if not parents:
			return []
		filters["name"] = ("in", parents)

	rows = frappe.get_list(
		DOCTYPE,
		filters=filters,
		or_filters=or_filters,
		fields=list(LIST_FIELDS),
		order_by="process_sequence asc, process_name asc",
		limit_page_length=cint(limit) or 200,
	)
	if not rows:
		return []

	links = frappe.get_all(
		"Process Machine Type",
		filters={"parent": ("in", [r["name"] for r in rows]), "parenttype": DOCTYPE},
		fields=["parent", "machine_type"],
		order_by="idx asc",
	)
	by_parent = {}
	for link in links:
		by_parent.setdefault(link.parent, []).append(link.machine_type)

	# The type's readable name, not its TYP- id, because that is what the list shows.
	names = {}
	wanted = {t for types in by_parent.values() for t in types}
	if wanted:
		names = {
			row.name: row.machine_type_name
			for row in frappe.get_all(
				"Machine Type",
				filters={"name": ("in", list(wanted))},
				fields=["name", "machine_type_name"],
			)
		}

	for row in rows:
		types = by_parent.get(row["name"], [])
		row["machine_types"] = types
		row["machine_type_labels"] = [names.get(t, t) for t in types]
	return rows


@frappe.whitelist()
def get_machine_types():
	"""The Machine Types a process may be linked to, for the screen's pickers."""
	frappe.has_permission("Machine Type", "read", throw=True)
	return frappe.get_all(
		"Machine Type",
		filters={"is_active": 1},
		fields=["name", "machine_type_name"],
		order_by="machine_type_name asc",
	)


@frappe.whitelist()
def get_form_context(process_master=None):
	"""What the entry screen needs to draw itself, in one call."""
	if process_master and frappe.db.exists(DOCTYPE, process_master):
		doc = frappe.get_doc(DOCTYPE, process_master)
		doc.check_permission("read")
		can_write = frappe.has_permission(DOCTYPE, "write", doc=doc)
	else:
		frappe.has_permission(DOCTYPE, "read", throw=True)
		doc = None
		can_write = frappe.has_permission(DOCTYPE, "create")

	return {
		"doc": doc.as_dict() if doc else None,
		"can_write": bool(can_write),
		"can_delete": bool(doc and frappe.has_permission(DOCTYPE, "delete", doc=doc)),
		"machine_types": get_machine_types(),
		# Next free sequence, so a new process does not default to colliding with one.
		"next_sequence": (
			frappe.db.sql(
				"select ifnull(max(process_sequence), 0) + 1 from `tabProcess Master`"
			)[0][0]
			if not doc
			else None
		),
	}
