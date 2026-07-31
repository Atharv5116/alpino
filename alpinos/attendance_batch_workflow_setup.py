"""Approval workflow for Monthly Attendance Batch (created on migrate).

Flow: Draft -> Pending Approval -> Approved (submit) -> Locked.

  * HR User / HR Manager build the batch in Draft (fetch/upload/edit rows).
  * Submit for Approval parks it with HR Manager.
  * Approve submits the document (docstatus 1) — Frappe then blocks all edits,
    and the controller additionally blocks populate_rows outside Draft.
  * Lock is the month-end hard stop (payroll has consumed the batch). Same
    docstatus, but pages and APIs treat Locked as terminal.
  * Reject returns the batch to Draft for correction.
"""

import frappe

WORKFLOW_NAME = "Monthly Attendance Batch Approval"
DOCTYPE = "Monthly Attendance Batch"
STATE_FIELD = "workflow_state"

S_DRAFT = "Draft"
S_PENDING = "Pending Approval"
S_APPROVED = "Approved"
S_LOCKED = "Locked"

WORKFLOW_ACTIONS = ("Submit for Approval", "Approve", "Reject", "Lock")

# (state, doc_status, allow_edit)
STATES = (
	(S_DRAFT, "0", "HR User"),
	(S_PENDING, "0", "HR Manager"),
	(S_APPROVED, "1", "HR Manager"),
	(S_LOCKED, "1", "HR Manager"),
)

# (state, action, next_state, allowed_role, condition)
TRANSITIONS = (
	(S_DRAFT, "Submit for Approval", S_PENDING, "HR User", ""),
	(S_DRAFT, "Submit for Approval", S_PENDING, "HR Manager", ""),
	(S_PENDING, "Approve", S_APPROVED, "HR Manager", ""),
	(S_PENDING, "Reject", S_DRAFT, "HR Manager", ""),
	(S_APPROVED, "Lock", S_LOCKED, "HR Manager", ""),
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
	"""Create (or refresh) the Monthly Attendance Batch approval workflow."""
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
