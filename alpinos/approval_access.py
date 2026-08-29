"""Gate the Approvals workspace to HR + reporting managers/HODs, and grant Reporting Manager to every user with reports."""

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
