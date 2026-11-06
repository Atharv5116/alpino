"""Who may raise, see and change a Goods Return Request (FSD 2.2 and 2.3).

Two-level authorization (2.3.1): creating, editing, submitting or cancelling a request
needs BOTH the Goods Return Coordinator role AND a role of the request's channel:

    Offline     Sales Manager, Sales Admin, Sales User                  (OFFLINE_ROLES)
    E-Commerce  E-Commerce Admin, E-Commerce Coordinator, E-Commerce Manager (ECOM_ROLES)

The channel role lists are the ones every Sales Order screen already uses
(alpinos.channel_access), so a person's channels are the same everywhere. The FSD's
"E-Commerce User" does not exist on Alpinos; E-Commerce Coordinator is that role here.

This deliberately does not use channel_access.resolve_access: that treats Warehouse and
Accounts roles as "every channel", while the FSD says a Coordinator without a Sales or
E-Commerce role may not raise a request at all (2.3.2, "Goods Return Coordinator only").

Seeing requests: an Executive works on both channels (2.2.1) and System Manager sees
everything; a Coordinator sees the requests of their own channels; nobody else sees any.

Under company-wise access the roles that count are the user's roles in the request's
company (company_scope.access.roles_for).
"""

import frappe
from frappe import _

from alpinos.channel_access import CHANNEL_ECOM, ECOM_ROLES, OFFLINE_CHANNELS, OFFLINE_ROLES
from alpinos.goods_return import COORDINATOR, EXECUTIVE, REQUEST
from alpinos.permission_compat import NO_OBJECTION

OFFLINE = "offline"
ECOM = "ecom"

# roles that see every channel's requests
SEE_ALL_ROLES = (EXECUTIVE, "System Manager")


def family(channel):
	"""'ecom', 'offline' or None for a Channel value."""
	if channel == CHANNEL_ECOM:
		return ECOM
	if channel in OFFLINE_CHANNELS:
		return OFFLINE
	return None


def _roles(user=None, company=None):
	from alpinos.company_scope.access import roles_for

	return set(roles_for(user or frappe.session.user, company))


def families_for_roles(roles):
	"""Channel families a set of roles may raise requests for: none without the Coordinator role."""
	roles = set(roles)
	if COORDINATOR not in roles:
		return []
	out = []
	if roles & set(OFFLINE_ROLES):
		out.append(OFFLINE)
	if roles & set(ECOM_ROLES):
		out.append(ECOM)
	return out


def channel_options():
	"""The Channel records a request can carry, offline family first."""
	existing = set(frappe.get_all("Channel", pluck="name"))
	return [c for c in (*OFFLINE_CHANNELS, CHANNEL_ECOM) if c in existing]


def request_channels(user=None, company=None):
	"""The channels this user may raise a Goods Return Request for (empty: none)."""
	families = families_for_roles(_roles(user, company))
	return [c for c in channel_options() if family(c) in families]


def _exempt(user=None):
	user = user or frappe.session.user
	return user == "Administrator" or bool(frappe.flags.goods_return_system)


@frappe.whitelist()
def get_request_access(company=None):
	"""What the request form needs: the channels the user may pick, the default, and whether
	the choice is locked (FSD 2.3.3). No channels means a new request cannot be raised."""
	from alpinos.company_scope.helpers import current_company

	company = company or current_company()
	if frappe.session.user == "Administrator":
		channels = channel_options()
	else:
		channels = request_channels(company=company)
	families = {family(c) for c in channels}
	default = None
	if channels:
		# one family: that family's first channel (Offline before General Trade)
		default = channels[0] if len(families) == 1 else None
	return {
		"channels": channels,
		"default": default,
		"locked": len(channels) == 1,
		"company": company,
	}


def assert_can_raise(doc, action):
	"""Throw unless the user may `action` (save / submit / cancel / update) this request.

	Checked on every save and on submit and cancel, not only when the form opens (2.3.3),
	so an API call or a changed channel cannot get past it.
	"""
	if _exempt():
		return
	roles = _roles(company=doc.get("company"))
	if COORDINATOR not in roles:
		frappe.throw(
			_("You need the {0} role to {1} a Goods Return Request.").format(frappe.bold(COORDINATOR), action),
			frappe.PermissionError,
			title=_("Not Permitted"),
		)
	families = families_for_roles(roles)
	if not families:
		frappe.throw(
			_("You also need a Sales role (Sales Manager, Sales Admin or Sales User) or an E-Commerce "
			  "role (E-Commerce Admin, Manager or Coordinator) to {0} a Goods Return Request.").format(action),
			frappe.PermissionError,
			title=_("Not Permitted"),
		)
	if family(doc.get("channel")) not in families:
		allowed = ", ".join(c for c in channel_options() if family(c) in families)
		frappe.throw(
			_("You cannot {0} a Goods Return Request for the {1} channel. Your roles allow: {2}.").format(
				action, frappe.bold(doc.get("channel") or _("blank")), allowed
			),
			frappe.PermissionError,
			title=_("Not Permitted"),
		)


# ------------------------------------------------------------------ permission hooks


def query_conditions(user=None):
	"""List / report / link search: a Coordinator sees their channels, an Executive both."""
	user = user or frappe.session.user
	if user == "Administrator":
		return ""
	roles = set(frappe.get_roles(user))
	if roles & set(SEE_ALL_ROLES):
		return ""
	channels = [c for c in channel_options() if family(c) in families_for_roles(roles)]
	if not channels:
		return "1=0"
	values = ", ".join(frappe.db.escape(c) for c in channels)
	return f"`tab{REQUEST}`.channel IN ({values})"


def has_permission(doc, ptype=None, user=None, debug=False):
	"""Deny-only: one request, judged by the user's roles in its company."""
	user = user or frappe.session.user
	if user == "Administrator" or not doc.get("creation") or (hasattr(doc, "is_new") and doc.is_new()):
		return NO_OBJECTION
	roles = _roles(user, doc.get("company"))
	if roles & set(SEE_ALL_ROLES):
		return NO_OBJECTION
	if family(doc.get("channel")) in families_for_roles(roles):
		return NO_OBJECTION
	return False


# ------------------------------------------------------------------ form endpoints


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def customer_query(doctype, txt, searchfield, start, page_len, filters):
	"""Returning Party: customers with a Buyer Master in the request's channel (the same pool
	the Sales Order screens pick from, company tags applied). `any_channel` lists every
	buyer, for the destination of a redistribution."""
	from alpinos.sales_order_offline_buyer import _customers_with_offline_buyer_master_query

	filters = filters or {}
	if filters.get("any_channel"):
		channel = None
	else:
		fam = family(filters.get("channel"))
		if not fam:
			return []
		channel = CHANNEL_ECOM if fam == ECOM else "Offline"
	return _customers_with_offline_buyer_master_query(txt, start, page_len, channel=channel, parents_only=True)


def customer_in_channel(customer, channel):
	"""The customer's Buyer Master in that channel's family (a root buyer first), or None.

	Offline takes blank too, as every Sales Order screen does: a buyer saved before Channel
	was mandatory was an offline buyer.
	"""
	fam = family(channel)
	if not customer or not fam:
		return None
	if fam == ECOM:
		clause = f"m.channel = {frappe.db.escape(CHANNEL_ECOM)}"
	else:
		values = ", ".join(frappe.db.escape(c) for c in ("", *OFFLINE_CHANNELS))
		clause = f"IFNULL(m.channel, '') IN ({values})"
	rows = frappe.db.sql(
		f"""
		SELECT m.name FROM `tabBuyer Master` m
		WHERE m.customer = %(customer)s AND {clause}
		ORDER BY (IFNULL(m.is_parent, 0) = 1 OR IFNULL(m.parent_buyer, '') = '') DESC, m.creation
		LIMIT 1
		""",
		{"customer": customer},
	)
	return rows[0][0] if rows else None


@frappe.whitelist()
def get_delivery_note_items(delivery_note):
	"""Rows for "Get Items from Delivery Note": each shipped line with its batch and MRP.

	The expected quantity starts at what was shipped; the user lowers it and picks a reason.
	"""
	from alpinos.company_scope.helpers import assert_company

	dn = frappe.get_doc("Delivery Note", delivery_note)
	dn.check_permission("read")
	assert_company(dn, "Delivery Note", "read")
	if dn.docstatus != 1 or dn.get("is_return"):
		frappe.throw(_("Delivery Note {0} is not a submitted delivery.").format(frappe.bold(dn.name)))
	lots = {}
	lot_names = [d.get("mrp_batch") for d in dn.items if d.get("mrp_batch")]
	if lot_names and frappe.db.exists("DocType", "MRP Batch"):
		for lot in frappe.get_all(
			"MRP Batch", filters={"name": ["in", lot_names]}, fields=["name", "mrp", "batch_no"]
		):  # company-scope: n/a (lots of a Delivery Note already checked with assert_company above)
			lots[lot.name] = lot
	rows = []
	for d in dn.items:
		lot = lots.get(d.get("mrp_batch")) or {}
		rows.append(
			{
				"item_code": d.item_code,
				"item_name": d.item_name,
				"uom": d.get("stock_uom") or d.get("uom"),
				"expected_qty": d.get("stock_qty") or d.qty,
				"batch_code": d.get("custom_batch_code") or d.get("batch_no") or lot.get("batch_no"),
				"mrp": lot.get("mrp"),
				"mrp_batch": d.get("mrp_batch"),
				"delivery_note_item": d.name,
			}
		)
	return {
		"customer": dn.customer,
		"company": dn.company,
		"sales_order": dn.get("custom_sales_order_id"),
		"rows": rows,
	}
