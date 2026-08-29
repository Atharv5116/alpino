"""Override User to allow impersonation for users with the Impersonate role."""

import frappe
from frappe import _
from frappe.core.doctype.user.user import User


class CustomUser(User):
	pass


@frappe.whitelist(methods=["POST"])
def impersonate(user: str, reason: str):
	"""Allow users with the Impersonate role to impersonate (core allows only Administrator)."""
	if frappe.session.user != "Administrator" and "Impersonate" not in frappe.get_roles():
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	impersonator = frappe.session.user

	frappe.get_doc(
		{
			"doctype": "Activity Log",
			"user": user,
			"status": "Success",
			"subject": _("User {0} impersonated as {1}").format(impersonator, user),
			"operation": "Impersonate",
		}
	).insert(ignore_permissions=True, ignore_links=True)

	notification = frappe.new_doc(
		"Notification Log",
		for_user=user,
		from_user=frappe.session.user,
		subject=_("{0} just impersonated as you. They gave this reason: {1}").format(impersonator, reason),
	)
	notification.set("type", "Alert")
	notification.insert(ignore_permissions=True)

	frappe.local.login_manager.impersonate(user)
