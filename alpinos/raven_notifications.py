"""Raven approval notifications — sent as DIRECT MESSAGES to the people who need them.

Whenever an approval request moves through its workflow, the dedicated Raven bot DMs:
  * the **applicant** — a status update on their own request, and
  * the **approver(s) for the current stage** — Pending Reporting Manager -> the employee's
    reporting manager; Pending HOD -> users with the HOD role; Pending HR -> HR Managers.

So each person sees only what's relevant to them (no broadcast channels). The bot
(default name "HR & RM Notifier", overridable via site_config `raven_notification_bot`)
is created on migrate by setup_raven_notification_bot.

Everything is defensive: if Raven isn't installed or a recipient/bot can't be resolved, it
is a silent no-op — it never blocks the underlying submit/approve.
"""

import frappe


def _raven_installed():
	return bool(frappe.db.exists("DocType", "Raven Message"))


def _bot_name():
	return frappe.conf.get("raven_notification_bot") or "HR & RM Notifier"


def setup_raven_notification_bot():
	"""Create the notification bot (after_migrate). No-op without Raven.

	Notifications are DMs to the relevant people (applicant, reporting manager, HOD, HR),
	so no broadcast channels are created — only the bot is needed.
	"""
	if not _raven_installed() or not frappe.db.exists("DocType", "Raven Bot"):
		return
	name = _bot_name()
	if frappe.db.exists("Raven Bot", name):
		return
	try:
		bot = frappe.get_doc(
			{
				"doctype": "Raven Bot",
				"bot_name": name,
				"description": "DMs approval notifications to the people who need to act + the applicant.",
			}
		)
		bot.insert(ignore_permissions=True)
		frappe.db.commit()
		print(f"✅ Created Raven notification bot '{name}'")
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Raven notification bot setup")


def _get_bot():
	"""The Raven Bot to DM as, or None when Raven/the bot isn't available."""
	if not _raven_installed():
		return None
	name = _bot_name()
	if not frappe.db.exists("Raven Bot", name):
		setup_raven_notification_bot()  # self-heal if after_migrate hasn't run yet
		if not frappe.db.exists("Raven Bot", name):
			return None
	try:
		return frappe.get_doc("Raven Bot", name)
	except Exception:
		return None


def _doc_link(doc):
	route = doc.doctype.lower().replace(" ", "-")
	return f"{frappe.utils.get_url()}/app/{route}/{doc.name}"


# --------------------------------------------------------------------------- recipients


def _applicant_user(doc):
	"""User id of the person the request is FOR (gets updates on their own request)."""
	emp = doc.get("employee")
	return frappe.db.get_value("Employee", emp, "user_id") if emp else None


def _rm_user(doc):
	"""User id of the employee's reporting manager (Employee.reports_to)."""
	emp = doc.get("employee")
	if not emp:
		return None
	rm = frappe.db.get_value("Employee", emp, "reports_to")
	return frappe.db.get_value("Employee", rm, "user_id") if rm else None


def _role_users(role):
	"""Enabled users holding `role` (excludes Administrator/Guest)."""
	return frappe.db.sql_list(
		"""
		SELECT DISTINCT hr.parent FROM `tabHas Role` hr
		JOIN `tabUser` u ON u.name = hr.parent
		WHERE hr.role = %s AND hr.parenttype = 'User' AND u.enabled = 1
			AND u.name NOT IN ('Administrator', 'Guest')
		""",
		role,
	)


def _approvers_for_state(doc, state):
	"""Users who need to ACT at this stage. Pending RM -> the reporting manager;
	Pending HOD -> HODs; Pending HR -> HR Managers. Outcomes -> nobody (applicant only)."""
	s = (state or "").lower()
	if "reporting manager" in s or "rm approval" in s:
		rm = _rm_user(doc)
		return [rm] if rm else []
	if "hod" in s:
		return _role_users("HOD")
	if "hr approval" in s or "pending hr" in s:
		return _role_users("HR Manager")
	return []


# --------------------------------------------------------------------------- helpers


def _emp(doc):
	return doc.get("employee_name") or doc.get("employee") or doc.get("requested_by") or "—"


def _stage_icon(state):
	s = (state or "").lower()
	if any(k in s for k in ("approved", "live", "completed", "paid")):
		return "✅"
	if any(k in s for k in ("rejected", "returned", "cancelled", "hold")):
		return "❌"
	return "🔔"


def _send_dm(bot, user, text, doc=None):
	"""DM one user as the bot. Silent no-op on any failure — never blocks submit/approve."""
	if not (bot and user):
		return
	try:
		bot.send_direct_message(
			user,
			text=text,
			link_doctype=doc.doctype if doc is not None else None,
			link_document=doc.name if doc is not None else None,
		)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Raven approval DM")


def _notify_stage(label, doc, state, detail=""):
	"""Targeted DMs for a stage change: the applicant gets a status update on their own
	request; the stage's approver(s) get an action ping."""
	bot = _get_bot()
	if not bot:
		return
	applicant = _applicant_user(doc)
	_send_dm(
		bot,
		applicant,
		f"{_stage_icon(state)} Your <b>{label}</b> {doc.name}{detail} is now <b>{state}</b>.<br>{_doc_link(doc)}",
		doc,
	)
	for user in _approvers_for_state(doc, state):
		if user and user != applicant:
			_send_dm(
				bot,
				user,
				f"🔔 <b>{label}</b> {doc.name} from <b>{_emp(doc)}</b>{detail} needs your approval "
				f"(<b>{state}</b>).<br>{_doc_link(doc)}",
				doc,
			)


def _submitted(label, who, detail, doc):
	"""A fresh submission: tell the applicant + ping the reporting manager."""
	bot = _get_bot()
	if not bot:
		return
	applicant = _applicant_user(doc)
	_send_dm(
		bot,
		applicant,
		f"🔔 Your <b>{label}</b> {doc.name}{detail} was submitted — pending approval.<br>{_doc_link(doc)}",
		doc,
	)
	rm = _rm_user(doc)
	if rm and rm != applicant:
		_send_dm(
			bot,
			rm,
			f"🔔 <b>{label}</b> {doc.name} from <b>{who}</b>{detail} needs your approval.<br>{_doc_link(doc)}",
			doc,
		)


# --------------------------------------------------------------------------- doc events


def notify_leave_application(doc, method=None):
	# Per-stage, workflow-driven via `workflow_state`
	# (Draft -> Pending Reporting Manager Approval -> HOD -> HR -> Approved/Rejected).
	# Pending stages are docstatus 0 (on_update); Approved/Rejected submit (on_submit).
	if method == "on_update" and not doc.has_value_changed("workflow_state"):
		return
	state = doc.get("workflow_state")
	if not state or state == "Draft":
		return
	when = doc.get("from_date")
	if doc.get("to_date") and doc.get("to_date") != doc.get("from_date"):
		when = f"{doc.get('from_date')} to {doc.get('to_date')}"
	_notify_stage("Leave Application", doc, state, f" ({doc.get('leave_type')}, {when})")


def notify_attendance_request(doc, method=None):
	if method == "on_submit":
		when = doc.get("custom_request_date") or doc.get("from_date")
		_submitted("Attendance Request", _emp(doc), f" ({doc.get('reason')}, {when})", doc)


def notify_work_from_home(doc, method=None):
	# Workflow-driven via the `status` field (Pending RM -> HOD -> HR -> Approved/Rejected).
	if method == "on_update" and doc.has_value_changed("status"):
		status = doc.get("status")
		if not status or status == "Draft":
			return
		_notify_stage("Work From Home", doc, status, f" ({doc.get('date')})")


def notify_job_requisition(doc, method=None):
	# Workflow-driven: notify the next approver (RM/HOD/HR) on each state change.
	if method == "on_update" and doc.has_value_changed("workflow_state"):
		state = doc.get("workflow_state")
		if not state or state == "Draft":
			return
		_notify_stage("Job Requisition", doc, state, f" ({doc.get('designation') or ''})")


def notify_expense_claim(doc, method=None):
	# Per-stage via approval_status / workflow_state
	# (Draft -> Pending RM Approval -> Approved by RM -> Submitted to Payroll -> Paid / Rejected).
	if method in ("on_update", "on_update_after_submit") and not (
		doc.has_value_changed("approval_status") or doc.has_value_changed("workflow_state")
	):
		return
	state = doc.get("approval_status") or doc.get("workflow_state")
	if not state or state == "Draft":
		return
	amt = doc.get("total_claimed_amount") or doc.get("grand_total") or 0
	_notify_stage("Expense Claim", doc, state, f" (₹{amt})")
