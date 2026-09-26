"""The one custom field a Sub PO needs, and the naming that makes it read as PO-001-A.

A Sub PO IS an ERPNext Work Order. That is the whole point of the split described in
`production_order.py`: the Sub PO is where stock actually moves, so Work Order's native
on_submit -- Bin reservation, Job Cards, Stock Entries -- is exactly what is wanted, and
none of it is suppressed.

Which leaves precisely two things to add: a link back to the Parent, and a name that says
which Parent it belongs to.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

PARENT_FIELD = "custom_parent_production_order"

WORK_ORDER = "Work Order"


BATCH_FIELD = "custom_batch_number"
PRODUCTION_TYPE_FIELD = "custom_production_type"
CLIENT_FIELD = "custom_client_name"
IS_LOCKED_FIELD = "custom_is_locked"
SPLIT_FROM_FIELD = "custom_split_from"
EXECUTION_STATUS_FIELD = "custom_execution_status"
ASSIGNED_PROCESS_FIELD = "custom_assigned_process"
ASSIGNED_MACHINE_FIELD = "custom_assigned_machine"
PLANNED_DATE_FIELD = "custom_planned_date"

#: Task 27. Where a Sub PO stands on the floor, which is not the same question as the
#: Work Order's own docstatus.
EXECUTION_STATUSES = ("Unassigned", "Assigned", "In Progress", "Completed")


def _custom_fields():
	"""Task 27 / 32: what a Sub PO carries beyond what a Work Order already has.

	Copied onto the Sub PO rather than read back through the Parent, because Task 32 is
	explicit that changes to the Parent after the Sub PO exists do NOT flow down. A fetched
	value would quietly do the opposite.
	"""
	return {
		WORK_ORDER: [
			{
				"fieldname": PARENT_FIELD,
				"label": "Parent Production Order",
				"fieldtype": "Link",
				"options": "Production Order",
				"insert_after": "production_item",
				"in_standard_filter": 1,
				"read_only": 1,
				"no_copy": 1,
				"description": (
					"The Parent this Sub PO was split from. Permanent once set: a Sub PO that "
					"changed parents would take its materials and its batch number with it."
				),
			},
			{
				"fieldname": BATCH_FIELD,
				"label": "Batch Number",
				"fieldtype": "Data",
				"insert_after": PARENT_FIELD,
				"read_only": 1,
				"description": "Copied from the Parent. A split keeps the same batch number.",
			},
			{
				"fieldname": PRODUCTION_TYPE_FIELD,
				"label": "Production Type",
				"fieldtype": "Data",
				"insert_after": BATCH_FIELD,
				"read_only": 1,
				"in_standard_filter": 1,
				"description": "Copied from the Parent so the Sub PO list can filter on it.",
			},
			{
				"fieldname": CLIENT_FIELD,
				"label": "Client Name",
				"fieldtype": "Link",
				"options": "Customer",
				"insert_after": PRODUCTION_TYPE_FIELD,
				"read_only": 1,
				"in_standard_filter": 1,
			},
			{
				"fieldname": EXECUTION_STATUS_FIELD,
				"label": "Execution Status",
				"fieldtype": "Select",
				"options": "\n".join(EXECUTION_STATUSES),
				"default": EXECUTION_STATUSES[0],
				"insert_after": CLIENT_FIELD,
				"in_standard_filter": 1,
				"description": "Where this Sub PO stands on the floor.",
			},
			{
				"fieldname": IS_LOCKED_FIELD,
				"label": "Is Locked",
				"fieldtype": "Check",
				"default": "1",
				"insert_after": EXECUTION_STATUS_FIELD,
				"read_only": 1,
				"description": (
					"A Sub PO is locked from the moment it is created until the Parent is "
					"Sent To Store (Task 26). Nothing on the floor acts on a locked one."
				),
			},
			{
				"fieldname": ASSIGNED_PROCESS_FIELD,
				"label": "Assigned Process",
				"fieldtype": "Link",
				"options": "Process Master",
				"insert_after": EXECUTION_STATUS_FIELD,
				"read_only": 1,
				"in_standard_filter": 1,
				"description": "Set through Assign Process on the Sub PO list.",
			},
			{
				"fieldname": ASSIGNED_MACHINE_FIELD,
				"label": "Assigned Machine",
				"fieldtype": "Link",
				"options": "Machine",
				"insert_after": ASSIGNED_PROCESS_FIELD,
				"read_only": 1,
				"in_standard_filter": 1,
			},
			{
				"fieldname": PLANNED_DATE_FIELD,
				"label": "Planned Date",
				"fieldtype": "Date",
				"insert_after": ASSIGNED_MACHINE_FIELD,
				"read_only": 1,
				"in_standard_filter": 1,
				"description": "When this sub order is planned to run.",
			},
			{
				"fieldname": SPLIT_FROM_FIELD,
				"label": "Split From",
				"fieldtype": "Link",
				"options": "Work Order",
				"insert_after": IS_LOCKED_FIELD,
				"read_only": 1,
				"no_copy": 1,
				"description": "Filled only on a split (Task 28).",
			},
		],
	}


def setup_work_order_fields():
	create_custom_fields(_custom_fields(), ignore_validate=True)
