"""Attendance Request approval workflow, (re)created on migrate.

Missing punch: Reporting Manager approves. Punch edit: Reporting Manager then HR Manager.
"""

import frappe

WORKFLOW_NAME = "Attendance Request Approval"
DOCTYPE = "Attendance Request"
STATE_FIELD = "workflow_state"

S_DRAFT = "Draft"
S_RM = "Pending RM Approval"
S_HR = "Pending HR Approval"
S_APPROVED = "Approved"
S_REJECTED = "Rejected"

# EDIT overwrites a punch already on record; MISSING fills a missing side. Stamped onto
# custom_is_punch_edit during validate (see CustomAttendanceRequest._set_punch_edit_flag).
EDIT_COND = "doc.custom_is_punch_edit"
MISSING_COND = "not doc.custom_is_punch_edit"

# Only the employee's OWN reporting person (reporting_person holds their user) may act.
RM_IS_OWN_MANAGER = "frappe.session.user == doc.reporting_person"


def _and(*conds):
	return " and ".join(f"({c})" for c in conds if c)


WORKFLOW_ACTIONS = ("Submit for Approval", "Approve", "Reject", "Resubmit")

# (state, doc_status, allow_edit)
STATES = (
	(S_DRAFT, "0", "Employee"),
	(S_RM, "0", "HR Manager"),
	(S_HR, "0", "HR Manager"),
	(S_APPROVED, "1", "HR Manager"),
	(S_REJECTED, "0", "Employee"),
)

# (state, action, next_state, allowed_role, condition)
TRANSITIONS = (
	(S_DRAFT, "Submit for Approval", S_RM, "Employee", ""),
	# RM step: only the employee's own reporting person; branch missing vs edit
	(S_RM, "Approve", S_APPROVED, "Reporting Manager", _and(MISSING_COND, RM_IS_OWN_MANAGER)),
	(S_RM, "Approve", S_HR, "Reporting Manager", _and(EDIT_COND, RM_IS_OWN_MANAGER)),
	(S_RM, "Reject", S_REJECTED, "Reporting Manager", RM_IS_OWN_MANAGER),
	# HR Manager safety valve on the RM step (same branching, no own-manager restriction).
	(S_RM, "Approve", S_APPROVED, "HR Manager", MISSING_COND),
	(S_RM, "Approve", S_HR, "HR Manager", EDIT_COND),
	(S_RM, "Reject", S_REJECTED, "HR Manager", ""),
	# HR Manager step (only reached by edits).
	(S_HR, "Approve", S_APPROVED, "HR Manager", ""),
	(S_HR, "Reject", S_REJECTED, "HR Manager", ""),
	# Resubmit a rejected request.
	(S_REJECTED, "Resubmit", S_RM, "Employee", ""),
)


def _ensure_masters():
	for state, _ds, _ae in STATES:
		if not frappe.db.exists("Workflow State", state):
			frappe.get_doc(
				{"doctype": "Workflow State", "workflow_state_name": state, "style": ""}
			).insert(ignore_permissions=True)
	for action in WORKFLOW_ACTIONS:
		if not frappe.db.exists("Workflow Action Master", action):
			frappe.get_doc(
				{"doctype": "Workflow Action Master", "workflow_action_name": action}
			).insert(ignore_permissions=True)


def execute():
	"""Create (or refresh) the Attendance Request approval workflow."""
	if not frappe.db.exists("DocType", DOCTYPE):
		return

	_ensure_masters()

	# Recreate for idempotency / to pick up any definition change.
	if frappe.db.exists("Workflow", WORKFLOW_NAME):
		frappe.delete_doc("Workflow", WORKFLOW_NAME, force=1, ignore_permissions=True)

	wf = frappe.get_doc(
		{
			"doctype": "Workflow",
			"workflow_name": WORKFLOW_NAME,
			"document_type": DOCTYPE,
			"is_active": 1,
			"workflow_state_field": STATE_FIELD,
			"send_email_alert": 0,
		}
	)
	for state, doc_status, allow_edit in STATES:
		wf.append(
			"states",
			{
				"state": state,
				"doc_status": doc_status,
				"allow_edit": allow_edit,
				"update_field": "",
				"update_value": "",
			},
		)
	for state, action, next_state, allowed, condition in TRANSITIONS:
		wf.append(
			"transitions",
			{
				"state": state,
				"action": action,
				"next_state": next_state,
				"allowed": allowed,
				"condition": condition,
				"allow_self_approval": 1,
			},
		)
	wf.insert(ignore_permissions=True)
	frappe.db.commit()
	frappe.clear_cache(doctype=DOCTYPE)
