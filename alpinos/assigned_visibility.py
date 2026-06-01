"""Role-based visibility for Pick List and Delivery Note.

Two roles, created idempotently on `bench migrate`:

* **Alpinos Full Access** — sees every Pick List and Delivery Note (no filter).
* **Alpinos Assigned Only** — sees only documents where `custom_assigned_to`
  equals the user OR `owner` equals the user.

Users with neither role fall through to Frappe's standard permission system
(no extra filter applied here). Administrator always bypasses.
"""

import frappe


ASSIGNED_ONLY_ROLE = "Alpinos Assigned Only"
FULL_ACCESS_ROLE = "Alpinos Full Access"


def setup_visibility_roles():
	"""Create the two visibility roles if they don't exist. Idempotent; safe to
	run on every migrate.
	"""
	for role_name, description in [
		(
			FULL_ACCESS_ROLE,
			"Sees every Pick List and Delivery Note regardless of assignment.",
		),
		(
			ASSIGNED_ONLY_ROLE,
			"Sees only Pick Lists and Delivery Notes assigned to the user (or owned by them).",
		),
	]:
		if not frappe.db.exists("Role", role_name):
			frappe.get_doc(
				{
					"doctype": "Role",
					"role_name": role_name,
					"desk_access": 1,
					"description": description,
				}
			).insert(ignore_permissions=True)
	frappe.db.commit()


def _has_role(user, role):
	if not user:
		return False
	return role in frappe.get_roles(user)


def _is_full_access(user):
	if user == "Administrator":
		return True
	return _has_role(user, FULL_ACCESS_ROLE)


def _filter_for_doctype(user, doctype):
	"""Return a SQL fragment (or '') used by permission_query_conditions."""
	if _is_full_access(user):
		return ""
	if not _has_role(user, ASSIGNED_ONLY_ROLE):
		return ""
	u = frappe.db.escape(user)
	return (
		f"(`tab{doctype}`.custom_assigned_to = {u} "
		f"OR `tab{doctype}`.owner = {u})"
	)


def _row_visible(doc, user):
	if _is_full_access(user):
		return True
	if not _has_role(user, ASSIGNED_ONLY_ROLE):
		return True
	return (
		doc.get("custom_assigned_to") == user
		or doc.get("owner") == user
	)


def pick_list_query_conditions(user):
	return _filter_for_doctype(user, "Pick List")


def pick_list_has_permission(doc, user, permission_type=None):
	return _row_visible(doc, user)


def delivery_note_query_conditions(user):
	return _filter_for_doctype(user, "Delivery Note")


def delivery_note_has_permission(doc, user, permission_type=None):
	return _row_visible(doc, user)
