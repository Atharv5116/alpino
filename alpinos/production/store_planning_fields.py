"""Store Planning — the fields the planning board needs on existing doctypes.

Additive only, the same way work_order_fields.py does it:

    * Work Order `custom_machine_run` -- the Machine Run a merged Sub PO belongs to. Read
      only: it is stamped by the board when Sub POs are merged and cleared when that
      planning is cancelled.
    * Process Master `color` -- the colour of the process's cards on the calendar. Only
      added when the doctype does not already carry a field of that name.

Also gives the production and store roles access to the new Machine Run doctype, through
the same Custom DocPerm helper the Production masters use, so nothing is revoked.

Registered in hooks.py `after_migrate` as
"alpinos.production.store_planning_fields.setup_store_planning_fields".
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from alpinos.production.work_order_fields import PLANNED_DATE_FIELD

WORK_ORDER = "Work Order"
PROCESS_MASTER = "Process Master"
MACHINE_RUN = "Machine Run"

MACHINE_RUN_FIELD = "custom_machine_run"
PROCESS_COLOR_FIELD = "color"

#: Who may see / change a Machine Run. Roles that do not exist on the site are skipped, so
#: this can run before or after the Store roles are created.
MACHINE_RUN_PERMISSIONS = {
	"Production Admin": "FULL",
	"Production Manager": "FULL",
	"Production User": "VIEW",
	"Store Planner": "CREATE_EDIT",
	"Store User": "VIEW",
	"Store Manager": "VIEW",
}


def _custom_fields():
	fields = {
		WORK_ORDER: [
			{
				"fieldname": MACHINE_RUN_FIELD,
				"label": "Machine Run",
				"fieldtype": "Link",
				"options": MACHINE_RUN,
				"insert_after": PLANNED_DATE_FIELD,
				"read_only": 1,
				"no_copy": 1,
				# Re-planning after a cancelled MR writes this on a submitted Sub PO.
				"allow_on_submit": 1,
				"description": "Set when this Sub PO is merged with others on the Store Planning board.",
			},
		],
	}
	if frappe.db.exists("DocType", PROCESS_MASTER) and not frappe.get_meta(PROCESS_MASTER).has_field(
		PROCESS_COLOR_FIELD
	):
		fields[PROCESS_MASTER] = [
			{
				"fieldname": PROCESS_COLOR_FIELD,
				"label": "Planning Colour",
				"fieldtype": "Color",
				"insert_after": "process_sequence",
				"description": "Colour of this process's cards on the Store Planning board, e.g. #2F80ED.",
			},
		]
	return fields


def _grant_machine_run_permissions():
	if not frappe.db.exists("DocType", MACHINE_RUN):
		return
	# Imported, not edited: roles.py owns the helper and its matrix.
	from alpinos.production.roles import _grant

	granted = False
	for role, level in MACHINE_RUN_PERMISSIONS.items():
		if not frappe.db.exists("Role", role):
			continue
		_grant(MACHINE_RUN, role, level)
		granted = True
	if granted:
		frappe.clear_cache(doctype=MACHINE_RUN)


def setup_store_planning_fields():
	create_custom_fields(_custom_fields(), ignore_validate=True)
	try:
		_grant_machine_run_permissions()
	except Exception:
		# Permissions are a convenience here (every write goes through the board's API);
		# a failure must never stop the rest of migrate.
		frappe.log_error(frappe.get_traceback(), "Store Planning: Machine Run permissions")
	frappe.db.commit()


def execute():
	setup_store_planning_fields()
