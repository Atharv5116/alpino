"""Restrict the Approvals workspace to HR + reporting managers / HODs.

The Approvals workspace and its pending-approvals queue (alpinos.approval_dashboard)
are meant only for HR Managers/Users and reporting managers (anyone with direct
reports). A Frappe workspace gates visibility by ROLE, but the "Reporting Manager" /
"HOD" roles are typically unassigned. Those roles carry NO doctype permissions — their
only effect here is the sidebar entry — so we safely grant "Reporting Manager" to every
user who is someone's reports_to, and gate the workspace by HR + Reporting Manager + HOD.

A public workspace with no roles is shown to everyone; once roles are set, only users
with one of them (or System/Workspace Managers) see it.
"""

import frappe

WORKSPACE = "Approvals"
WORKSPACE_ROLES = ("HR Manager", "HR User", "Reporting Manager", "HOD")
RM_ROLE = "Reporting Manager"
SKIP_USERS = {"Administrator", "Guest"}


def setup_approvals_access():
	"""after_migrate: gate the Approvals workspace and backfill manager roles."""
	restrict_approvals_workspace()
	sync_reporting_manager_roles()


def restrict_approvals_workspace():
	"""Add the allowed roles to the Approvals workspace (idempotent)."""
	if not frappe.db.exists("Workspace", WORKSPACE):
		return
	ws = frappe.get_doc("Workspace", WORKSPACE)
	existing = {r.role for r in ws.roles}
	added = False
	for role in WORKSPACE_ROLES:
		if role not in existing and frappe.db.exists("Role", role):
			ws.append("roles", {"role": role})
			added = True
	if added:
		ws.save(ignore_permissions=True)
		ws.clear_cache()


def _grant_rm_role(user):
	if not user or user in SKIP_USERS or not frappe.db.exists("User", user):
		return False
	if frappe.db.exists(
		"Has Role", {"parent": user, "parenttype": "User", "role": RM_ROLE}
	):
		return False
	try:
		frappe.get_doc("User", user).add_roles(RM_ROLE)
		return True
	except Exception:
		frappe.log_error(frappe.get_traceback(), "approval_access: grant RM role")
		return False


def sync_reporting_manager_roles():
	"""Grant the Reporting Manager role to every active employee's manager."""
	if not frappe.db.exists("Role", RM_ROLE):
		return
	managers = set(
		filter(
			None,
			frappe.get_all(
				"Employee",
				filters={"reports_to": ["is", "set"], "status": "Active"},
				pluck="reports_to",
			),
		)
	)
	for emp in managers:
		_grant_rm_role(frappe.db.get_value("Employee", emp, "user_id"))


def grant_rm_role_for_employee(doc, method=None):
	"""Employee on_update: ensure this employee's manager has the RM role."""
	if doc.get("reports_to"):
		_grant_rm_role(frappe.db.get_value("Employee", doc.reports_to, "user_id"))
