"""Cancel a Draft Sales Order, and duplicate one.

Sections 12 and 13 of "Buyer Master & Sales Order - Required Changes" (03-10-2026).

    12. Sales Officer, Primary POC and Secondary POC can cancel a Sales Order while it is
        still in the permitted Draft stage, captured in the Activity / Audit Trail with the
        Sales Order ID, who cancelled it, their role, the time, the previous and new status,
        and the reason.
    13. Duplication is allowed from a Draft or a Submitted Sales Order. A completely new
        Sales Order is created in Draft status and the original remains unchanged.

Cancelling a Draft is a workflow-status change, not a docstatus cancel: Frappe reserves
cancellation for submitted documents, and the order has never been submitted. The record is
kept rather than deleted, because the trail has to be able to say what happened to it.
"""

import frappe
from frappe import _
from frappe.utils import today

from alpinos.alpinos_development.doctype.field_change_log.field_change_log import (
	acting_role,
	log_field_change,
)
from alpinos.buyer_assignment import SALES_OFFICER_ROLE
from alpinos.sales_order_authority import SO_BUYER_FIELD, is_poc_for_buyer

SO_DRAFT = "Draft"
SO_CANCELLED = "Cancelled"

#: Section 9's matrix gives Cancel Draft and Duplicate to all three assignment roles.
ACTION_OVERRIDE_ROLES = {"Sales Admin", "Sales Manager", "System Manager", "Administrator"}

#: Child tables copied with the order. The three sample tables travel with it because a
#: duplicate that silently dropped the freebies would be wrong in a quiet way.
_COPIED_TABLES = (
	"items",
	"custom_marketing_freebies",
	"custom_scheme_item_table",
	"custom_additional_units_damage_items",
)

#: Never carried into the copy: these belong to the original's own life.
_RESET_FIELDS = (
	"custom_invoice_no",
	"custom_invoice_pdf",
	"custom_force_closed",
	"custom_force_close_reason",
	"custom_force_closed_by",
	"custom_force_closed_on",
	"custom_rejection_reason",
	"per_delivered",
	"per_billed",
)

#: Dispatch date is deliberately NOT reset: it is mandatory on a Sales Order, so blanking it
#: would make every duplicate unsaveable. The copy carries the original's date for the user
#: to change, which is what they would do anyway.


def _may_act(sales_order, user=None):
	"""Whether this user may cancel or duplicate that order."""
	user = user or frappe.session.user
	roles = set(frappe.get_roles(user))
	if user == "Administrator" or (roles & ACTION_OVERRIDE_ROLES):
		return True
	buyer = frappe.db.get_value("Sales Order", sales_order, SO_BUYER_FIELD)
	if is_poc_for_buyer(buyer, user):
		return True
	# An assigned Sales Officer of that Buyer, per the section 9 matrix.
	if SALES_OFFICER_ROLE in roles:
		employee = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name")
		return bool(
			employee
			and buyer
			and frappe.db.exists(
				"Buyer Sales Officer",
				{"parent": buyer, "parenttype": "Buyer Master", "employee": employee},
			)
		)
	return False


@frappe.whitelist()
def cancel_draft_sales_order(sales_order, reason=None):
	"""Cancel a Draft Sales Order and record it in the trail."""
	if not _may_act(sales_order):
		frappe.throw(
			_("You are not assigned to this Buyer, so you cannot cancel this Sales Order."),
			frappe.PermissionError,
			title=_("Not Permitted"),
		)

	row = frappe.db.get_value(
		"Sales Order", sales_order, ["docstatus", "custom_workflow_status"], as_dict=True
	)
	if not row:
		frappe.throw(_("No such Sales Order."))
	if row.docstatus != 0:
		frappe.throw(
			_("Only a Draft Sales Order can be cancelled this way. This one is already submitted."),
			title=_("Not a Draft"),
		)
	previous = row.custom_workflow_status or SO_DRAFT
	if previous == SO_CANCELLED:
		frappe.throw(_("This Sales Order is already cancelled."))

	reason = (reason or "").strip()
	frappe.db.set_value(
		"Sales Order", sales_order, "custom_workflow_status", SO_CANCELLED, update_modified=False
	)
	log_field_change(
		"Sales Order", sales_order, _("Status"), previous, SO_CANCELLED,
		after_submit=0, action="Cancelled", reason=reason or None,
	)
	frappe.db.commit()
	return {
		"sales_order": sales_order,
		"previous_status": previous,
		"new_status": SO_CANCELLED,
		"cancelled_by": frappe.session.user,
		"user_role": acting_role(),
		"reason": reason,
	}


@frappe.whitelist()
def duplicate_sales_order(sales_order):
	"""Copy a Sales Order -- Draft or Submitted -- into a brand new Draft.

	The original is not read back afterwards and not written to at all: section 13 is
	explicit that it must remain unchanged.
	"""
	if not _may_act(sales_order):
		frappe.throw(
			_("You are not assigned to this Buyer, so you cannot duplicate this Sales Order."),
			frappe.PermissionError,
			title=_("Not Permitted"),
		)
	if not frappe.db.exists("Sales Order", sales_order):
		frappe.throw(_("No such Sales Order."))

	src = frappe.get_doc("Sales Order", sales_order)
	new = frappe.new_doc("Sales Order")

	skip = {
		"name", "naming_series", "amended_from", "docstatus", "owner", "creation",
		"modified", "modified_by", "idx", "doctype", "status", "custom_workflow_status",
	} | set(_RESET_FIELDS) | set(_COPIED_TABLES)
	for field, value in src.as_dict().items():
		if field in skip or field.startswith("_"):
			continue
		new.set(field, value)

	for table in _COPIED_TABLES:
		for row in (src.get(table) or []):
			data = row.as_dict()
			for k in ("name", "parent", "parenttype", "parentfield", "creation", "modified",
			          "modified_by", "owner", "docstatus", "idx"):
				data.pop(k, None)
			# Fulfilment figures belong to the original, never to a fresh draft.
			for k in ("delivered_qty", "returned_qty", "billed_amt", "picked_qty",
			          "work_order_qty", "produced_qty"):
				data.pop(k, None)
			new.append(table, data)

	new.transaction_date = today()
	new.custom_workflow_status = SO_DRAFT
	# The original's dispatch date may now be in the past, or today after the 2 PM cutoff.
	# Carrying it would make the copy unsaveable, so fall back to the app's own default
	# rather than inventing a date or leaving a mandatory field blank.
	from alpinos.dispatch_date_utils import get_default_dispatch_date, validate_dispatch_date

	if not new.custom_dispatch_date or not validate_dispatch_date(
		new.custom_dispatch_date
	).get("valid"):
		new.custom_dispatch_date = get_default_dispatch_date()["date"]
	new.flags.ignore_permissions = True
	new.insert()

	log_field_change(
		"Sales Order", new.name, _("Created"), sales_order, new.name,
		after_submit=0, action="Duplicated",
		reason=_("Duplicated from {0}").format(sales_order),
	)
	frappe.db.commit()
	return {"sales_order": new.name, "duplicated_from": sales_order, "docstatus": new.docstatus}
