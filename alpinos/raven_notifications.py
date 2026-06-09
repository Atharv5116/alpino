"""Raven notifications to the HR and RM channels for actions needing approval/involvement.

Whenever a request is submitted for approval (and again when it is approved/rejected), a
message is posted to the shared HR and RM Raven channels so the relevant upper authorities
are informed.

Channel resolution (first match wins):
  1. site_config keys `raven_hr_channel` / `raven_rm_channel` — a Raven Channel id or name.
  2. otherwise a non-DM Raven Channel whose channel_name is "HR" / "RM".

Everything is defensive: if Raven is not installed, or a channel can't be resolved, it is a
silent no-op (never blocks the underlying submit/approve).
"""

import frappe


def _raven_installed():
	return bool(frappe.db.exists("DocType", "Raven Message"))


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
	"""Post `text` to both the HR and RM channels (deduped). Silent no-op without Raven."""
	if not _raven_installed():
		return
	channels = []
	for kind in ("hr", "rm"):
		ch = _resolve_channel(kind)
		if ch and ch not in channels:
			channels.append(ch)
	for channel_id in channels:
		try:
			msg = frappe.new_doc("Raven Message")
			msg.channel_id = channel_id
			msg.text = text
			if doc is not None:
				msg.link_doctype = doc.doctype
				msg.link_document = doc.name
			msg.flags.ignore_permissions = True
			msg.insert(ignore_permissions=True)
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


# --------------------------------------------------------------------------- doc events


def notify_leave_application(doc, method=None):
	if method == "on_submit":
		detail = f" ({doc.get('leave_type')}, {doc.get('from_date')} to {doc.get('to_date')})"
		_submitted("Leave Application", _emp(doc), detail, doc)
	elif method == "on_update_after_submit" and doc.has_value_changed("status") and doc.get("status") in (
		"Approved",
		"Rejected",
	):
		_outcome("Leave Application", _emp(doc), doc.get("status"), doc)


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
	if method == "on_submit":
		_submitted(
			"Expense Claim", _emp(doc), f" (₹{doc.get('total_claimed_amount') or doc.get('grand_total') or 0})", doc
		)
	elif method == "on_update_after_submit":
		status = doc.get("approval_status") or doc.get("workflow_state")
		if (doc.has_value_changed("approval_status") or doc.has_value_changed("workflow_state")) and status:
			_outcome("Expense Claim", _emp(doc), status, doc)
