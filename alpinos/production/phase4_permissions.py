"""Permissions for the Phase 4+ doctypes (Execution / QC / Filling / Inventory).

One dict per builder, each {doctype: {role: level}}, where level is one of the levels in
alpinos.production.roles._level_ptypes: "VIEW", "CREATE_EDIT", "FULL",
"CREATE_EDIT_SUBMIT", "FULL_SUBMIT". Each builder appends ONLY to its own dict.

setup_phase4_permissions() merges the three and grants them the same way the production
roles are granted (Custom DocPerm rows, nothing revoked). A doctype that does not exist yet,
or a role that does not exist, is skipped and picked up on the next migrate.
"""

import frappe

#: Builder 1 -- Production Run, Process Inward, Production QC.
EXECUTION_PERMS = {
	"Production Run": {
		"Production Operator": "CREATE_EDIT",
		"Production Manager": "FULL",
		"Production Admin": "FULL",
		"Production User": "VIEW",
		"Plant Head": "VIEW",
		"QC Inspector": "VIEW",
		"QC Manager": "VIEW",
	},
	"Process Inward": {
		"Production Operator": "CREATE_EDIT_SUBMIT",
		"Production Manager": "FULL_SUBMIT",
		"Production Admin": "FULL_SUBMIT",
		"Production User": "VIEW",
		"Plant Head": "VIEW",
		"QC Inspector": "VIEW",
		"QC Manager": "VIEW",
	},
	"Production QC": {
		"QC Inspector": "CREATE_EDIT_SUBMIT",
		"QC Manager": "FULL_SUBMIT",
		"Production Manager": "VIEW",
		"Production Admin": "VIEW",
		"Plant Head": "VIEW",
	},
}

#: Builder 2 -- Filling Plan, Filling Inward, Final QC, Production Yield Record.
FILLING_PERMS = {
	"Filling Plan": {
		"Production Admin": "FULL",
		"Production Manager": "FULL",
		"Production Operator": "VIEW",
		"Production User": "VIEW",
		"Plant Head": "VIEW",
	},
	"Filling Inward": {
		"Production Operator": "CREATE_EDIT_SUBMIT",
		"Production Manager": "FULL_SUBMIT",
		"Production Admin": "FULL_SUBMIT",
		"Production User": "VIEW",
		"Plant Head": "VIEW",
		"QC Inspector": "VIEW",
		"QC Manager": "VIEW",
	},
	"Final QC": {
		"QC Inspector": "CREATE_EDIT_SUBMIT",
		"QC Manager": "FULL_SUBMIT",
		"Production Manager": "VIEW",
		"Production Admin": "VIEW",
		"Plant Head": "VIEW",
	},
	"Production Yield Record": {
		"Production Manager": "VIEW",
		"Production Admin": "VIEW",
		"Plant Head": "VIEW",
	},
	# The FG batches are read on the Filling / Final QC screens, and submitting a Stock Entry
	# of a batch-tracked item makes ERPNext create a Serial and Batch Bundle as the user.
	"Batch": {
		"Production Operator": "VIEW",
		"QC Inspector": "VIEW",
		"QC Manager": "VIEW",
		"Plant Head": "VIEW",
	},
	"Serial and Batch Bundle": {
		"Production Operator": "CREATE_EDIT_SUBMIT",
		"QC Inspector": "CREATE_EDIT_SUBMIT",
		"QC Manager": "FULL_SUBMIT",
	},
}

#: Builder 3 -- Production Transfer, Inventory Adjustment.
INVENTORY_PERMS = {
	"Production Transfer": {
		"Store User": "CREATE_EDIT_SUBMIT",
		"Store Manager": "FULL_SUBMIT",
		"Production Manager": "FULL_SUBMIT",
		"Production Admin": "FULL_SUBMIT",
		"Production User": "VIEW",
		"Plant Head": "VIEW",
	},
	"Inventory Adjustment": {
		"Store Manager": "CREATE_EDIT_SUBMIT",
		# Plant Head approves (write); the approval itself goes through
		# inventory_api.approve_adjustment / reject_adjustment.
		"Plant Head": "CREATE_EDIT",
		"Production Admin": "FULL_SUBMIT",
		"Production Manager": "VIEW",
	},
}

#: Groundwork's own doctypes. Production Shift is a small master.
GROUNDWORK_PERMS = {
	"Production Shift": {
		"Production Admin": "FULL",
		"Production Manager": "CREATE_EDIT",
		"Production User": "VIEW",
		"Production Operator": "VIEW",
		"QC Inspector": "VIEW",
		"QC Manager": "VIEW",
		"Plant Head": "VIEW",
	},
}


def merged_permissions():
	merged = {}
	for source in (GROUNDWORK_PERMS, EXECUTION_PERMS, FILLING_PERMS, INVENTORY_PERMS):
		for doctype, role_levels in (source or {}).items():
			merged.setdefault(doctype, {}).update(role_levels or {})
	return merged


def setup_phase4_permissions():
	from frappe.core.doctype.doctype.doctype import validate_permissions_for_doctype

	from alpinos.production.roles import _grant, ensure_phase4_roles

	try:
		ensure_phase4_roles()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Phase 4 roles: create")

	for doctype, role_levels in merged_permissions().items():
		if not frappe.db.exists("DocType", doctype):
			continue
		try:
			for role, level in role_levels.items():
				if not frappe.db.exists("Role", role):
					continue
				_grant(doctype, role, level)
			validate_permissions_for_doctype(doctype)
		except Exception:
			# One awkward doctype must not stop the migrate; the rest are still granted.
			frappe.log_error(frappe.get_traceback(), f"Phase 4 permissions: {doctype}")
		frappe.clear_cache(doctype=doctype)
	frappe.db.commit()
