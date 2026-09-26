"""Force Close for a Purchase Order -- the Administrator's escape hatch.

An order that will never be fulfilled, and that the normal Cancel path refuses because
something downstream already points at it, has to be able to stop being live. Force Close
moves it to a terminal status and records who did it, when, and why.

Deliberately Administrator only, checked on the server. The button is hidden from everyone
else, but a hidden button is not a permission -- `frappe.session.user` is the gate, and
the whitelisted method refuses anybody else whatever the screen shows.

Modelled on alpinos.forced_close, which does the same job for a Sales Order: same field
names (custom_force_closed / _reason / _by / _on), so the two read the same way in a
report and in the database.
"""

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import cint, now

from alpinos.purchase import constants as C

DOCTYPE = "Purchase Order"
STATUS_FIELD = "custom_approval_status"

FORCE_CLOSED_FIELD = "custom_force_closed"
REASON_FIELD = "custom_force_close_reason"
BY_FIELD = "custom_force_closed_by"
ON_FIELD = "custom_force_closed_on"

#: The one account that may do this.
FORCE_CLOSE_USER = "Administrator"


def _custom_fields():
	return {
		DOCTYPE: [
			dict(
				fieldname="custom_force_close_section",
				label="Force Close",
				fieldtype="Section Break",
				insert_after=STATUS_FIELD,
				collapsible=1,
				# Nothing to show until it has happened.
				depends_on="eval:doc.custom_force_closed",
			),
			dict(
				fieldname=FORCE_CLOSED_FIELD,
				label="Force Closed",
				fieldtype="Check",
				insert_after="custom_force_close_section",
				read_only=1,
				# allow_on_submit: the whole point is to close an order that is already live.
				allow_on_submit=1,
				description="Set only by the Administrator, through Force Close.",
			),
			dict(
				fieldname=REASON_FIELD,
				label="Force Close Reason",
				fieldtype="Small Text",
				insert_after=FORCE_CLOSED_FIELD,
				read_only=1,
				allow_on_submit=1,
			),
			dict(
				fieldname=BY_FIELD,
				label="Force Closed By",
				fieldtype="Link",
				options="User",
				insert_after=REASON_FIELD,
				read_only=1,
				allow_on_submit=1,
			),
			dict(
				fieldname=ON_FIELD,
				label="Force Closed On",
				fieldtype="Datetime",
				insert_after=BY_FIELD,
				read_only=1,
				allow_on_submit=1,
			),
		]
	}


def setup_force_close_fields():
	create_custom_fields(_custom_fields(), ignore_validate=True, update=True)
	frappe.db.commit()


def may_force_close(user=None):
	"""Only the Administrator. Not a role -- a role can be granted by anyone who can edit
	roles, and this is meant to stay with one account."""
	return (user or frappe.session.user) == FORCE_CLOSE_USER


def is_force_closed(purchase_order) -> bool:
	if not purchase_order:
		return False
	return bool(frappe.db.get_value(DOCTYPE, purchase_order, FORCE_CLOSED_FIELD))


@frappe.whitelist()
def can_force_close(purchase_order=None):
	"""What the screen asks before drawing the button."""
	if not may_force_close():
		return {"allowed": False, "reason": _("Only the Administrator can force close an order.")}
	if not purchase_order or not frappe.db.exists(DOCTYPE, purchase_order):
		return {"allowed": False, "reason": _("Save the order first.")}
	row = frappe.db.get_value(
		DOCTYPE, purchase_order, ["docstatus", STATUS_FIELD, FORCE_CLOSED_FIELD], as_dict=True
	)
	if cint(row.get(FORCE_CLOSED_FIELD)):
		return {"allowed": False, "reason": _("This order is already Force Closed.")}
	if cint(row.get("docstatus")) == 2:
		return {"allowed": False, "reason": _("This order is cancelled.")}
	return {"allowed": True, "reason": ""}


@frappe.whitelist()
def force_close_purchase_order(purchase_order, reason):
	"""Move an order to Force Closed. Administrator only, reason required.

	db_set rather than doc.save(): the order is submitted by this point and these four
	fields are allow_on_submit, so a full save would run the whole validate chain over a
	document nobody is otherwise editing -- including the approval edit guard, which would
	refuse it.
	"""
	if not may_force_close():
		frappe.throw(
			_("Only the Administrator can force close a Purchase Order."),
			title=_("Not Permitted"),
			exc=frappe.PermissionError,
		)
	if not purchase_order or not frappe.db.exists(DOCTYPE, purchase_order):
		frappe.throw(_("Purchase Order {0} does not exist.").format(purchase_order))

	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("A reason is required to force close an order."), title=_("Reason Needed"))

	doc = frappe.get_doc(DOCTYPE, purchase_order)
	if cint(doc.get(FORCE_CLOSED_FIELD)):
		frappe.throw(_("Order {0} is already Force Closed.").format(frappe.bold(purchase_order)))
	if cint(doc.docstatus) == 2:
		frappe.throw(_("Order {0} is cancelled.").format(frappe.bold(purchase_order)))

	doc.db_set(
		{
			FORCE_CLOSED_FIELD: 1,
			REASON_FIELD: reason,
			BY_FIELD: frappe.session.user,
			ON_FIELD: now(),
			STATUS_FIELD: C.PO_FORCE_CLOSED,
		},
		update_modified=True,
	)
	frappe.db.commit()
	return {
		"name": doc.name,
		"status": C.PO_FORCE_CLOSED,
		"force_closed": 1,
		"reason": reason,
	}


def execute():
	setup_force_close_fields()
