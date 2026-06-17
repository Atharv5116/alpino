"""Raven notifications to the HR and RM channels for actions needing approval/involvement.

Whenever a request is submitted for approval (and again when it is approved/rejected), a
message is posted — as a dedicated Raven bot — to the shared HR and RM Raven channels so the
relevant upper authorities are informed.

The bot (default name "HR & RM Notifier", overridable via site_config `raven_notification_bot`)
is created on migrate by setup_raven_notification_bot.

Channel resolution (first match wins):
  1. site_config keys `raven_hr_channel` / `raven_rm_channel` — a Raven Channel id or name.
  2. otherwise a non-DM Raven Channel whose channel_name is "HR" / "RM".

Everything is defensive: if Raven is not installed, or a channel can't be resolved, it is a
silent no-op (never blocks the underlying submit/approve).
"""

import frappe


def _raven_installed():
	return bool(frappe.db.exists("DocType", "Raven Message"))


def _bot_name():
	return frappe.conf.get("raven_notification_bot") or "HR & RM Notifier"


def setup_raven_notification_bot():
	"""Create the notification bot + HR/RM channels (after_migrate). No-op without Raven."""
	if not _raven_installed() or not frappe.db.exists("DocType", "Raven Bot"):
		return
	name = _bot_name()
	if not frappe.db.exists("Raven Bot", name):
		try:
			bot = frappe.get_doc(
				{
					"doctype": "Raven Bot",
					"bot_name": name,
					"description": "Posts HR / RM approval notifications for requests needing action.",
				}
			)
			bot.insert(ignore_permissions=True)
			frappe.db.commit()
			print(f"✅ Created Raven notification bot '{name}'")
		except Exception:
			frappe.log_error(frappe.get_traceback(), "Raven notification bot setup")
	_ensure_hr_rm_channels()


def _ensure_hr_rm_channels():
	"""Create the 'HR' and 'RM' channels (Open) if missing, so the bot has somewhere to
	post — you only add members afterwards. Best-effort; never blocks migrate. Skipped for
	a kind whose channel is pinned via site_config (raven_hr_channel / raven_rm_channel)."""
	if not frappe.db.exists("DocType", "Raven Channel"):
		return
	# A channel needs a workspace; use whatever workspace exists (else let the user create it).
	workspace = frappe.db.get_value("Raven Workspace", {}, "name")
	for kind, label in (("hr", "HR"), ("rm", "RM")):
		if frappe.conf.get(f"raven_{kind}_channel"):
			continue  # pinned to a specific channel in site_config
		if _resolve_channel(kind):
			continue  # already exists
		try:
			ch = frappe.get_doc(
				{
					"doctype": "Raven Channel",
					"channel_name": label,
					"type": "Open",
					"workspace": workspace,
				}
			)
			ch.insert(ignore_permissions=True)
			frappe.db.commit()
			print(f"✅ Created Raven '{label}' channel")
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"Raven {label} channel setup")


def _get_bot():
	"""The Raven Bot to post as, or None when Raven/the bot isn't available."""
	if not _raven_installed():
		return None
	name = _bot_name()
	if not frappe.db.exists("Raven Bot", name):
		# Self-heal if the after_migrate setup hasn't run yet.
		setup_raven_notification_bot()
		if not frappe.db.exists("Raven Bot", name):
			return None
	try:
		return frappe.get_doc("Raven Bot", name)
	except Exception:
		return None


def _resolve_channel(kind):
	"""Return the Raven Channel id for kind 'hr' or 'rm', or None."""
	configured = frappe.conf.get(f"raven_{kind}_channel")
	if configured:
		if frappe.db.exists("Raven Channel", configured):
			return configured
		by_name = frappe.db.get_value(
			"Raven Channel", {"channel_name": configured, "is_direct_message": 0}, "name"
		)
		if by_name:
			return by_name
	label = "HR" if kind == "hr" else "RM"
	return frappe.db.get_value(
		"Raven Channel", {"channel_name": label, "is_direct_message": 0}, "name"
	)


def _doc_link(doc):
	route = doc.doctype.lower().replace(" ", "-")
	return f"{frappe.utils.get_url()}/app/{route}/{doc.name}"


def post_to_hr_rm(text, doc=None):
	"""Post `text` to the HR and RM channels as the notification bot (deduped).

	Silent no-op when Raven isn't installed, the bot is unavailable, or a channel can't be
	resolved — so it never blocks the underlying submit/approve.
	"""
	bot = _get_bot()
	if not bot:
		return
	channels = []
	for kind in ("hr", "rm"):
		ch = _resolve_channel(kind)
		if ch and ch not in channels:
			channels.append(ch)
	for channel_id in channels:
		try:
			bot.send_message(
				channel_id=channel_id,
				text=text,
				link_doctype=doc.doctype if doc is not None else None,
				link_document=doc.name if doc is not None else None,
			)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "Raven HR/RM notification")


# --------------------------------------------------------------------------- helpers


def _emp(doc):
	return doc.get("employee_name") or doc.get("employee") or doc.get("requested_by") or "—"


def _submitted(label, who, detail, doc):
	post_to_hr_rm(
		f"🔔 <b>{label}</b> {doc.name} submitted by <b>{who}</b>{detail} — pending approval.<br>{_doc_link(doc)}",
		doc,
	)


def _outcome(label, who, status, doc):
	icon = "✅" if status and status.lower() in ("approved", "live", "completed") else "❌"
	post_to_hr_rm(
		f"{icon} <b>{label}</b> {doc.name} for <b>{who}</b> was <b>{status}</b>.<br>{_doc_link(doc)}",
		doc,
	)


def _stage_icon(state):
	s = (state or "").lower()
	if any(k in s for k in ("approved", "live", "completed", "paid")):
		return "✅"
	if any(k in s for k in ("rejected", "returned", "cancelled", "hold")):
		return "❌"
	return "🔔"


def _notify_stage(label, doc, state, detail=""):
	"""Post a per-stage 'is now <state>' message to the HR & RM channels, with an icon
	picked from the state (✅ approved/paid, ❌ rejected, 🔔 pending stages)."""
	post_to_hr_rm(
		f"{_stage_icon(state)} <b>{label}</b> {doc.name} for <b>{_emp(doc)}</b>{detail} "
		f"is now <b>{state}</b>.<br>{_doc_link(doc)}",
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
		if status in ("Approved", "Live", "Rejected"):
			_outcome("Work From Home", _emp(doc), status, doc)
		else:
			post_to_hr_rm(
				f"🔔 <b>Work From Home</b> {doc.name} for <b>{_emp(doc)}</b> "
				f"({doc.get('date')}) is now <b>{status}</b>.<br>{_doc_link(doc)}",
				doc,
			)


def notify_job_requisition(doc, method=None):
	# Workflow-driven: notify on each state change so the next approver (RM/HOD/HR) is informed.
	if method == "on_update" and doc.has_value_changed("workflow_state"):
		state = doc.get("workflow_state")
		if not state:
			return
		post_to_hr_rm(
			f"🔔 <b>Job Requisition</b> {doc.name} ({doc.get('designation') or ''}) is now "
			f"<b>{state}</b>.<br>{_doc_link(doc)}",
			doc,
		)


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
