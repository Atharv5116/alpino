"""Which sales channel each role may see: Sales Orders, Pick Lists, Delivery Notes.

Changes(HP) #22 (and the channel rule of #34, the Order Fulfilment Report):

  * E-Commerce Admin / Coordinator / Manager -> E-com only.
  * Sales Manager / Admin / User             -> the offline family only: Offline and
                                                General Trade (and a legacy order with
                                                no channel, which was always Offline).
  * Warehouse Admin / Manager, Accounts User, System Manager -> every channel.

A user holding roles from both restricted groups sees both families. A user holding a
Warehouse or Accounts role is unrestricted whatever else they hold, and a user with none
of these roles is left as they were (their ordinary permissions still apply).

Enforced on the DATA, through the permission hooks on the three doctypes, so it covers
the desk list and Report view, their export, opening a record by URL, and every
frappe.get_list call. Pages and reports that read with frappe.get_all or raw SQL bypass
those hooks and apply `allowed_sales_orders` themselves.
"""

import frappe

CHANNEL_ECOM = "E-com"
CHANNEL_OFFLINE = "Offline"
OFFLINE_CHANNELS = ("Offline", "General Trade")

ECOM_ROLES = ("E-Commerce Admin", "E-Commerce Coordinator", "E-Commerce Manager")
OFFLINE_ROLES = ("Sales Manager", "Sales Admin", "Sales User")
UNRESTRICTED_ROLES = ("Warehouse Admin", "Warehouse Manager", "Accounts User")


def _roles(user=None):
	return set(frappe.get_roles(user or frappe.session.user))


def resolve_access(user=None):
	"""What channels this user may see, and whether a channel filter is theirs to change."""
	user = user or frappe.session.user
	if user == "Administrator":
		return {"channels": None, "locked": False, "default": None, "group": "unrestricted"}
	roles = _roles(user)

	if roles.intersection(UNRESTRICTED_ROLES) or "System Manager" in roles:
		return {"channels": None, "locked": False, "default": None, "group": "unrestricted"}

	ecom = bool(roles.intersection(ECOM_ROLES))
	offline = bool(roles.intersection(OFFLINE_ROLES))
	if ecom and offline:
		return {
			"channels": [CHANNEL_ECOM, *OFFLINE_CHANNELS], "locked": False,
			"default": None, "group": "ecom+offline",
		}
	if ecom:
		return {"channels": [CHANNEL_ECOM], "locked": True, "default": CHANNEL_ECOM, "group": "ecom"}
	if offline:
		return {
			"channels": list(OFFLINE_CHANNELS), "locked": True,
			"default": CHANNEL_OFFLINE, "group": "offline",
		}
	return {"channels": None, "locked": False, "default": None, "group": "unnamed"}


def allowed_channel_values(user=None):
	"""Stored custom_channel values this user may see, or None for every channel.

	The offline family includes the empty value: an order saved before Channel was
	mandatory was an offline order.
	"""
	channels = resolve_access(user)["channels"]
	if channels is None:
		return None
	values = list(channels)
	if CHANNEL_OFFLINE in values:
		values.append("")
	return values


def _in_list(values):
	return "(" + ", ".join(frappe.db.escape(v) for v in values) + ")"


def allowed_sales_orders(user=None):
	"""Every Sales Order name this user may see, or None when unrestricted."""
	values = allowed_channel_values(user)
	if values is None:
		return None
	return frappe.db.sql_list(
		f"SELECT name FROM `tabSales Order` WHERE IFNULL(custom_channel, '') IN {_in_list(values)}"
	)


def channel_allowed(channel, user=None):
	values = allowed_channel_values(user)
	return values is None or (channel or "") in values


# ------------------------------------------------------------------ hooks


def sales_order_query_conditions(user):
	values = allowed_channel_values(user)
	if values is None:
		return ""
	return f"IFNULL(`tabSales Order`.custom_channel, '') IN {_in_list(values)}"


def _linked_order_condition(doctype, user):
	values = allowed_channel_values(user)
	if values is None:
		return ""
	return (
		f"`tab{doctype}`.custom_sales_order_id IN (SELECT so.name FROM `tabSales Order` so "
		f"WHERE IFNULL(so.custom_channel, '') IN {_in_list(values)})"
	)


def pick_list_query_conditions(user):
	return _linked_order_condition("Pick List", user)


def delivery_note_query_conditions(user):
	return _linked_order_condition("Delivery Note", user)


# frappe.permissions.has_controller_permissions takes the FIRST hook that returns something
# other than None. These hooks therefore only ever DENY (False) and otherwise return None,
# so the assigned-visibility hooks on Pick List / Delivery Note still get their say.


def _is_unsaved(doc):
	return not doc.get("creation") or (hasattr(doc, "is_new") and doc.is_new())


def sales_order_has_permission(doc, user=None, permission_type=None):
	# A new, unsaved order has no channel to judge yet; creating one is governed by the
	# role's create permission, and reading it back afterwards by this rule.
	if _is_unsaved(doc):
		return None
	return None if channel_allowed(doc.get("custom_channel"), user) else False


def _linked_order_allowed(doc, user):
	if _is_unsaved(doc) or resolve_access(user)["channels"] is None:
		return None
	so = doc.get("custom_sales_order_id")
	channel = frappe.db.get_value("Sales Order", so, "custom_channel") if so else None
	if so and channel_allowed(channel, user):
		return None
	return False


def pick_list_has_permission(doc, user=None, permission_type=None):
	return _linked_order_allowed(doc, user)


def delivery_note_has_permission(doc, user=None, permission_type=None):
	return _linked_order_allowed(doc, user)
