import frappe


def raven_channel_query(user: str | None = None) -> str:
	"""
	Only show channels where the user is a member.
	This is used only for standard get_list/get_all security filtering.
	"""
	if not user:
		user = frappe.session.user
	escaped_user = frappe.db.escape(user)
	return f"""EXISTS (
		SELECT 1 FROM `tabRaven Channel Member`
		WHERE `tabRaven Channel Member`.channel_id = `tabRaven Channel`.name
		AND `tabRaven Channel Member`.user_id = {escaped_user}
	)"""


def raven_message_query(user: str | None = None) -> str:
	"""
	Only show messages in channels where the user is a member.
	Kept in alpinos so we don't need to modify the raven app.
	"""
	if not user:
		user = frappe.session.user
	escaped_user = frappe.db.escape(user)
	return f"""EXISTS (
		SELECT 1 FROM `tabRaven Channel Member`
		WHERE `tabRaven Channel Member`.channel_id = `tabRaven Message`.channel_id
		AND `tabRaven Channel Member`.user_id = {escaped_user}
	)"""

