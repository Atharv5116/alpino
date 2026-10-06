"""In-app (and optional email) notifications for the Phase 4+ production screens.

notify() never raises: a failed notification must never undo a production action.
"""

import frappe
from frappe.utils import get_url_to_form

#: How long notify_once() suppresses a repeat of the same key.
ONCE_TTL_SECONDS = 600


def _users_with_roles(roles):
	roles = [r for r in (roles or []) if r]
	if not roles:
		return []
	return frappe.get_all(
		"Has Role",
		filters={"role": ("in", roles), "parenttype": "User", "parent": ("not in", ("Administrator", "Guest"))},
		pluck="parent",
		distinct=True,
	)


def _enabled(users):
	users = sorted({u for u in (users or []) if u and u not in ("Guest",)})
	if not users:
		return []
	return frappe.get_all(
		"User",
		filters={"name": ("in", users), "enabled": 1, "user_type": "System User"},
		pluck="name",
	)


def _has_outgoing_account():
	try:
		return bool(frappe.db.exists("Email Account", {"enable_outgoing": 1}))
	except Exception:
		return False


def notify(roles, subject, doctype=None, name=None, email=False, users=None):
	"""Notification Log (type Alert, linked to the document) for every enabled user holding
	one of `roles`, plus `users`. With email=True also emails them when an outgoing email
	account exists. Returns the list of users notified; never raises."""
	try:
		recipients = _enabled(list(_users_with_roles(roles)) + list(users or []))
		if not recipients:
			return []
		sender = frappe.session.user if frappe.session else None
		link = None
		if doctype and name:
			try:
				link = get_url_to_form(doctype, name)
			except Exception:
				link = None
		for user in recipients:
			try:
				log = frappe.new_doc("Notification Log")
				log.update({
					"subject": subject,
					"type": "Alert",
					"for_user": user,
					"from_user": sender,
					"document_type": doctype,
					"document_name": name,
					"email_content": subject,
				})
				if link and log.meta.has_field("link"):
					log.link = link
				log.insert(ignore_permissions=True)
			except Exception:
				frappe.log_error(frappe.get_traceback(), "notify: Notification Log")

		if email and _has_outgoing_account():
			try:
				emails = [e for e in frappe.get_all(
					"User", filters={"name": ("in", recipients)}, pluck="email") if e]
				if emails:
					message = frappe.utils.escape_html(subject)
					if link:
						message += f'<br><br><a href="{link}">{frappe.utils.escape_html(name)}</a>'
					frappe.sendmail(
						recipients=emails,
						subject=subject,
						message=message,
						reference_doctype=doctype,
						reference_name=name,
						delayed=True,
					)
			except Exception:
				frappe.log_error(frappe.get_traceback(), "notify: email")
		return recipients
	except Exception:
		frappe.log_error(frappe.get_traceback(), "notify")
		return []


def notify_once(key, roles, subject, doctype=None, name=None, email=False, users=None):
	"""notify(), but at most once per `key` within 10 minutes (anti-spam). Never raises."""
	try:
		cache_key = f"alpinos:notify_once:{key}"
		cache = frappe.cache()
		if cache.get_value(cache_key):
			return []
		cache.set_value(cache_key, 1, expires_in_sec=ONCE_TTL_SECONDS)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "notify_once: cache")
	return notify(roles, subject, doctype=doctype, name=name, email=email, users=users)
