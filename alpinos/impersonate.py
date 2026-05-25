"""
User Impersonation Feature
Allows users with "Impersonate" role to temporarily login as another user
"""

import frappe
from frappe import _
from frappe.utils import now_datetime


@frappe.whitelist()
def get_users_for_impersonation():
	"""Get list of users that can be impersonated (excludes current user and Administrator)"""
	if not frappe.has_permission("User", "read") or "Impersonate" not in frappe.get_roles():
		frappe.throw(_("You don't have permission to impersonate users"), frappe.PermissionError)
	
	current_user = frappe.session.user
	
	users = frappe.get_all(
		"User",
		filters={
			"enabled": 1,
			"name": ["not in", [current_user, "Administrator", "Guest"]]
		},
		fields=["name", "full_name", "user_image", "email"],
		order_by="full_name"
	)
	
	return users


@frappe.whitelist()
def start_impersonation(target_user):
	"""Start impersonating another user"""
	# Security checks
	if "Impersonate" not in frappe.get_roles():
		frappe.throw(_("You don't have permission to impersonate users"), frappe.PermissionError)
	
	if not frappe.db.exists("User", target_user):
		frappe.throw(_("User {0} does not exist").format(target_user))
	
	if target_user in ["Administrator", "Guest"]:
		frappe.throw(_("Cannot impersonate system users"))
	
	if target_user == frappe.session.user:
		frappe.throw(_("Cannot impersonate yourself"))
	
	# Check if user is enabled
	if not frappe.db.get_value("User", target_user, "enabled"):
		frappe.throw(_("Cannot impersonate disabled user"))
	
	# Store original user in session
	original_user = frappe.session.user
	
	# Log the impersonation
	log_impersonation(original_user, target_user, "start")
	
	# Store impersonation data in session
	frappe.session.data.impersonating = True
	frappe.session.data.original_user = original_user
	frappe.session.data.impersonated_user = target_user
	
	# Switch to target user
	frappe.set_user(target_user)
	
	return {
		"success": True,
		"message": _("Now impersonating {0}").format(target_user),
		"impersonated_user": target_user,
		"original_user": original_user
	}


@frappe.whitelist()
def stop_impersonation():
	"""Stop impersonating and return to original user"""
	if not frappe.session.data.get("impersonating"):
		frappe.throw(_("You are not currently impersonating anyone"))
	
	original_user = frappe.session.data.get("original_user")
	impersonated_user = frappe.session.data.get("impersonated_user")
	
	if not original_user:
		frappe.throw(_("Original user not found in session"))
	
	# Log the end of impersonation
	log_impersonation(original_user, impersonated_user, "stop")
	
	# Clear impersonation data
	frappe.session.data.impersonating = False
	frappe.session.data.original_user = None
	frappe.session.data.impersonated_user = None
	
	# Switch back to original user
	frappe.set_user(original_user)
	
	return {
		"success": True,
		"message": _("Stopped impersonating {0}").format(impersonated_user),
		"original_user": original_user
	}


@frappe.whitelist()
def get_impersonation_status():
	"""Check if currently impersonating"""
	return {
		"impersonating": frappe.session.data.get("impersonating", False),
		"original_user": frappe.session.data.get("original_user"),
		"impersonated_user": frappe.session.data.get("impersonated_user"),
		"current_user": frappe.session.user
	}


def log_impersonation(original_user, target_user, action):
	"""Log impersonation activity"""
	try:
		frappe.get_doc({
			"doctype": "Activity Log",
			"subject": f"Impersonation {action}: {original_user} -> {target_user}",
			"status": "Success",
			"user": original_user,
			"reference_doctype": "User",
			"reference_name": target_user,
			"operation": f"impersonate_{action}",
			"timeline_doctype": "User",
			"timeline_name": target_user,
			"full_name": frappe.db.get_value("User", original_user, "full_name"),
			"ip_address": frappe.local.request_ip if hasattr(frappe.local, "request_ip") else None
		}).insert(ignore_permissions=True)
		
		frappe.db.commit()
	except Exception as e:
		frappe.log_error(f"Error logging impersonation: {str(e)}", "Impersonation Log Error")


def create_impersonate_role():
	"""Create Impersonate role if it doesn't exist"""
	if not frappe.db.exists("Role", "Impersonate"):
		role = frappe.get_doc({
			"doctype": "Role",
			"role_name": "Impersonate",
			"desk_access": 1,
			"disabled": 0
		})
		role.insert(ignore_permissions=True)
		frappe.db.commit()
		print("✅ Created 'Impersonate' role")
	else:
		print("✅ 'Impersonate' role already exists")
