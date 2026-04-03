"""
Override Frappe's User doctype to enable impersonation for users with Impersonate role
"""

import frappe
from frappe import _
from frappe.core.doctype.user.user import User


class CustomUser(User):
	"""Extend User to allow impersonation for users with Impersonate role"""
	pass


@frappe.whitelist(methods=["POST"])
def impersonate(user: str, reason: str):
	"""
	Override Frappe's impersonate function to allow users with Impersonate role
	Original function only allows Administrator
	"""
	# Allow Administrator OR users with Impersonate role
	if frappe.session.user != "Administrator" and "Impersonate" not in frappe.get_roles():
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	impersonator = frappe.session.user
	
	# Log the impersonation
	frappe.get_doc(
		{
			"doctype": "Activity Log",
			"user": user,
			"status": "Success",
			"subject": _("User {0} impersonated as {1}").format(impersonator, user),
			"operation": "Impersonate",
		}
	).insert(ignore_permissions=True, ignore_links=True)

	# Notify the user being impersonated
	notification = frappe.new_doc(
		"Notification Log",
		for_user=user,
		from_user=frappe.session.user,
		subject=_("{0} just impersonated as you. They gave this reason: {1}").format(impersonator, reason),
	)
	notification.set("type", "Alert")
	notification.insert(ignore_permissions=True)
	
	# Perform the impersonation
	frappe.local.login_manager.impersonate(user)
