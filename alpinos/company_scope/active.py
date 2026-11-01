"""The company a user works in.

Stored as the user default `alpinos_active_company` (a company name, or ALL for "All my
companies"). It is per user, not per browser tab: every tab and device of the user follows
it, and switch_company tells the other tabs to reload.

It is mirrored into the standard `company` user default, which is what ERPNext fills a new
document's Company from and what HRMS / ERPNext dashboard cards filter on. In All mode the
mirror is the user's default membership. Frappe's Session Defaults would clear `company` on
logout, so Company is taken out of Session Default Settings (setup.py) and the mirror is
re-applied when a session starts.

Both are ordinary DefaultValue rows of the user (frappe.defaults.set_default).
"""

import frappe

from alpinos.company_scope import ALL, access

ACTIVE_KEY = "alpinos_active_company"


def _stored(user):
	return frappe.defaults.get_defaults_for(user).get(ACTIVE_KEY) or None


def get_active(user=None):
	"""The active company, ALL, or the default membership when nothing valid is stored."""
	user = user or frappe.session.user
	cache = getattr(frappe.local, "alpinos_cs_active", None)
	if cache is None:
		cache = frappe.local.alpinos_cs_active = {}
	if user in cache:
		return cache[user]
	members = access.member_companies(user)
	value = _stored(user)
	if value != ALL and value not in members:
		value = access.default_company(user)
	if value == ALL and len(members) < 2:
		value = members[0] if members else None
	cache[user] = value
	return value


def mirror_company(user, selection):
	"""What the standard `company` default should hold for a selection."""
	if selection and selection != ALL:
		return selection
	return access.default_company(user)


def set_active(user, selection):
	"""Store a selection (a member company or ALL) and its `company` mirror."""
	members = access.member_companies(user)
	if selection != ALL and selection not in members:
		frappe.throw(
			frappe._("{0} is not one of the companies given to {1}.").format(selection, user),
			frappe.PermissionError,
		)
	_write_default(user, ACTIVE_KEY, selection)
	mirror = mirror_company(user, selection)
	if mirror:
		_write_default(user, "company", mirror)
	frappe.clear_cache(user=user)
	cache = getattr(frappe.local, "alpinos_cs_active", None)
	if cache is not None:
		cache.pop(user, None)
	return selection


def _write_default(user, key, value):
	frappe.defaults.set_default(key, value, user)


def apply_mirror(user=None):
	"""Make sure `company` matches the active selection (session start, after a sync)."""
	from alpinos.company_scope import enabled

	user = user or frappe.session.user
	if not enabled() or user in ("Administrator", "Guest") or not access.is_managed(user):
		return
	selection = get_active(user)
	mirror = mirror_company(user, selection)
	current = frappe.defaults.get_defaults_for(user).get("company")
	if mirror and current != mirror:
		_write_default(user, "company", mirror)


def on_session_creation(login_manager=None):
	try:
		apply_mirror(frappe.session.user)
	except Exception:
		frappe.log_error(title="Company-wise access: could not set the company on login")
