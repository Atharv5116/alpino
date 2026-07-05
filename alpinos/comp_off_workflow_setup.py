"""Approval workflow for Compensatory Leave Request (created on migrate).

Flow: Draft -> Pending RM Approval -> Approved (submit) / Rejected.

Requests are auto-raised by comp_off_automation when an employee works
> 4h (0.5) / > 6h (1.0) on a holiday or weekly off, and parked directly at
the RM step. Approve submits the document, which makes HRMS allocate the
compensatory leave (it then shows on the employee's leave screen). HR
Manager can always act as a safety valve. The employee is notified of the
outcome via comp_off_automation.notify_comp_off_outcome.
"""

import frappe

WORKFLOW_NAME = "Comp-Off Approval"
DOCTYPE = "Compensatory Leave Request"
STATE_FIELD = "workflow_state"

S_DRAFT = "Draft"
S_RM = "Pending RM Approval"
S_APPROVED = "Approved"
S_REJECTED = "Rejected"

WORKFLOW_ACTIONS = ("Submit for Approval", "Approve", "Reject", "Resubmit")

# (state, doc_status, allow_edit)
STATES = (
	(S_DRAFT, "0", "Employee"),
	(S_RM, "0", "HR Manager"),
	(S_APPROVED, "1", "HR Manager"),
	(S_REJECTED, "0", "HR Manager"),
)

# (state, action, next_state, allowed_role, condition)
TRANSITIONS = (
	(S_DRAFT, "Submit for Approval", S_RM, "Employee", ""),
	(S_RM, "Approve", S_APPROVED, "Reporting Manager", ""),
	(S_RM, "Reject", S_REJECTED, "Reporting Manager", ""),
	# HR Manager safety valve (employee may have no reporting person).
	(S_RM, "Approve", S_APPROVED, "HR Manager", ""),
	(S_RM, "Reject", S_REJECTED, "HR Manager", ""),
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
	"""Create (or refresh) the Comp-Off approval workflow."""
	if not frappe.db.exists("DocType", DOCTYPE):
		return

	_ensure_masters()

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
