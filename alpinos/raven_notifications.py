"""Raven approval notifications, DM'd to the applicant and the current-stage approver(s)."""

import frappe


def _raven_installed():
	return bool(frappe.db.exists("DocType", "Raven Message"))


def _bot_name():
	return frappe.conf.get("raven_notification_bot") or "HR & RM Notifier"


def setup_raven_notification_bot():
	"""Create the notification bot (after_migrate). No-op without Raven."""
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


# --------------------------------------------------------------------------- recipients


def _applicant_user(doc):
	"""User id of the person the request is for."""
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


def _hod_users(doc):
	"""HOD-role users in the applicant's own department."""
	dept = doc.get("department") or frappe.db.get_value("Employee", doc.get("employee"), "department")
	if not dept:
		return []
	return frappe.db.sql_list(
		"""
		SELECT DISTINCT e.user_id
		FROM `tabEmployee` e
		JOIN `tabHas Role` hr ON hr.parent = e.user_id AND hr.parenttype = 'User'
		JOIN `tabUser` u ON u.name = e.user_id AND u.enabled = 1
		WHERE hr.role = 'HOD' AND e.department = %s AND e.status = 'Active'
			AND IFNULL(e.user_id, '') != '' AND e.user_id NOT IN ('Administrator', 'Guest')
		""",
		dept,
	)


def _approvers_for_state(doc, state):
	"""Users who need to act at this stage, scoped to the applicant."""
	s = (state or "").lower()
	if "reporting manager" in s or "rm approval" in s:
		rm = _rm_user(doc)
		return [rm] if rm else []
	if "hod" in s:
		return _hod_users(doc)
	if "hr approval" in s or "pending hr" in s:
		return _role_users("HR Manager")
	return []


# --------------------------------------------------------------------------- helpers


def _emp(doc):
	return doc.get("employee_name") or doc.get("employee") or doc.get("requested_by") or "—"


def _fmt_date(value):
	"""Render a date in the site's date format (falls back to the raw value)."""
	try:
		return frappe.utils.formatdate(value)
	except Exception:
		return value


def _fmt_range(from_date, to_date=None):
	if to_date and str(to_date) != str(from_date):
		return f"{_fmt_date(from_date)} to {_fmt_date(to_date)}"
	return _fmt_date(from_date)


def _stage_icon(state):
	s = (state or "").lower()
	if any(k in s for k in ("approved", "live", "completed", "paid")):
		return "✅"
	if any(k in s for k in ("rejected", "returned", "cancelled", "hold")):
		return "❌"
	return "🔔"


def _send_dm(bot, user, text, doc=None):
	"""DM one user as the bot; silent no-op on failure."""
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
	"""DM the applicant a status update and ping the stage's approver(s)."""
	bot = _get_bot()
	if not bot:
		return
	applicant = _applicant_user(doc)
	_send_dm(
		bot,
		applicant,
		f"{_stage_icon(state)} Your <b>{label}</b> request{detail} is now <b>{state}</b>.",
		doc,
	)
	for user in _approvers_for_state(doc, state):
		if user and user != applicant:
			_send_dm(
				bot,
				user,
				f"🔔 <b>{label}</b> request from <b>{_emp(doc)}</b>{detail} needs your approval.",
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
		f"🔔 Your <b>{label}</b> request{detail} was submitted — pending approval.",
		doc,
	)
	rm = _rm_user(doc)
	if rm and rm != applicant:
		_send_dm(
			bot,
			rm,
			f"🔔 <b>{label}</b> request from <b>{who}</b>{detail} needs your approval.",
			doc,
		)


# --------------------------------------------------------------------------- doc events


def notify_leave_application(doc, method=None):
	# per-stage, driven by workflow_state; pending stages are on_update, outcomes on_submit
	if method == "on_update" and not doc.has_value_changed("workflow_state"):
		return
	state = doc.get("workflow_state")
	if not state or state == "Draft":
		return
	when = _fmt_range(doc.get("from_date"), doc.get("to_date"))
	_notify_stage("Leave Application", doc, state, f" ({doc.get('leave_type')}, {when})")


def notify_attendance_request(doc, method=None):
	if method == "on_submit":
		when = _fmt_date(doc.get("custom_request_date") or doc.get("from_date"))
		_submitted("Attendance Request", _emp(doc), f" ({doc.get('reason')}, {when})", doc)


def notify_work_from_home(doc, method=None):
	# workflow-driven via the status field
	if method == "on_update" and doc.has_value_changed("status"):
		status = doc.get("status")
		if not status or status == "Draft":
			return
		when = _fmt_range(doc.get("date"), doc.get("to_date"))
		if doc.get("half_day"):
			period = doc.get("custom_half_day_period")
			when += f", Half Day ({period})" if period else ", Half Day"
		_notify_stage("Work From Home", doc, status, f" for <b>{when}</b>")


def notify_job_requisition(doc, method=None):
	# notify the next approver on each state change
	if method == "on_update" and doc.has_value_changed("workflow_state"):
		state = doc.get("workflow_state")
		if not state or state == "Draft":
			return
		_notify_stage("Job Requisition", doc, state, f" ({doc.get('designation') or ''})")


def notify_expense_claim(doc, method=None):
	# per-stage via approval_status / workflow_state
	if method in ("on_update", "on_update_after_submit") and not (
		doc.has_value_changed("approval_status") or doc.has_value_changed("workflow_state")
	):
		return
	state = doc.get("approval_status") or doc.get("workflow_state")
	if not state or state == "Draft":
		return
	amt = doc.get("total_claimed_amount") or doc.get("grand_total") or 0
	_notify_stage("Expense Claim", doc, state, f" (₹{amt})")
