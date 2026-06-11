"""Approval workflow for Attendance Request (created on migrate).

Flow:
  - MISSING request (no prior punch on record): Reporting Manager approves -> done.
  - EDIT request  (a prior punch exists)       : Reporting Manager approves -> HR Manager approves -> done.

Everything below is enforced from this setup script — there is nothing to configure by
hand:

  * "Missing vs edit" is decided from the request's Existing Check-in Logs snapshot: if
    any logged check-in/check-out is set, a prior punch existed (edit); otherwise it's
    missing. The branch happens at the Reporting Manager step via two same-action
    transitions whose conditions are mutually exclusive (only one is ever valid).

  * Only the employee's OWN reporting person may act on the Reporting Manager step — not
    any reporting manager. The request stores that person's user in `reporting_person`
    (set on validate from Employee.reports_to -> user_id), so the condition is simply
    `frappe.session.user == doc.reporting_person`.

Approved = submitted (doc_status 1), which is when the app applies the requested
check-ins (Attendance Request on_submit). HR Manager is also allowed on the Reporting
Manager step as a safety valve so a request can never get stuck if the employee has no
reporting person on record.
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

# Truthy when the request's Existing Check-in Logs hold a prior punch -> it is an EDIT.
EDIT_COND = (
	"frappe.db.get_value('Attendance Request Log', "
	"{'parent': doc.name, 'parentfield': 'custom_existing_logs', 'check_in': ['is','set']}, 'name') "
	"or frappe.db.get_value('Attendance Request Log', "
	"{'parent': doc.name, 'parentfield': 'custom_existing_logs', 'check_out': ['is','set']}, 'name')"
)
MISSING_COND = f"not ({EDIT_COND})"

# Only the employee's OWN reporting person (reporting_person holds their user) may act.
RM_IS_OWN_MANAGER = "frappe.session.user == doc.reporting_person"


def _and(*conds):
	"""Join non-empty condition fragments with AND (each parenthesised)."""
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
	# Reporting Manager step — only the employee's OWN reporting person; branch missing vs edit.
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
