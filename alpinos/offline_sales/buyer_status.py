"""Buyer Master status actions ("Opportunity to Sales Order v1.0.0", Section 4, 4.1-4.2 and 7).

    Approve Buyer        Pending Approval, On Hold   -> Approved     confirmation
    Put Buyer On Hold    Pending Approval            -> On Hold      mandatory reason
    Make Buyer Inactive  Approved                    -> Inactive     mandatory reason
    Reactivate Buyer     Inactive                    -> Approved     confirmation
    Cancel Buyer         any status but Cancelled    -> Cancelled    mandatory reason

Only a Sales Manager or Sales Admin acts (System Manager too, as everywhere in the app). A
single decision is enough; there is no second level (4.2). Cancelled is final (8.5).

This is the only way buyer_status changes: buyer_rules refuses it on a plain save or import.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime

from alpinos.alpinos_development.doctype.field_change_log.field_change_log import acting_role
from alpinos.offline_sales import (
	APPROVED,
	CANCELLED,
	INACTIVE,
	ON_HOLD,
	PENDING,
	is_manager,
	is_offline,
)
from alpinos.offline_sales import audit
from alpinos.offline_sales.buyer_rules import _cancelled_message, status_of

#: action -> (from statuses, to status, reason required, trail action, verb for messages)
ACTIONS = {
	"approve": ((PENDING, ON_HOLD), APPROVED, False, "Buyer Master Approved", "approved"),
	"hold": ((PENDING,), ON_HOLD, True, "Buyer Master Put On Hold", "put on hold"),
	"inactive": ((APPROVED,), INACTIVE, True, "Buyer Master Made Inactive", "made inactive"),
	"reactivate": ((INACTIVE,), APPROVED, False, "Buyer Master Reactivated", "reactivated"),
	"cancel": ((PENDING, ON_HOLD, APPROVED, INACTIVE), CANCELLED, True, "Buyer Master Cancelled", "cancelled"),
}


def available_actions(doc, user=None):
	"""The actions this user may take on this buyer now (drives the form buttons)."""
	if not is_manager(user) or not is_offline(doc.get("channel")):
		return []
	status = status_of(doc)
	return [a for a, spec in ACTIONS.items() if status in spec[0]]


@frappe.whitelist()
def buyer_action(buyer, action, reason=None):
	# company-scope: n/a (Buyer Master has no company; access is the read check below)
	if action not in ACTIONS:
		frappe.throw(_("Unknown action {0}.").format(action))
	doc = frappe.get_doc("Buyer Master", buyer)
	doc.check_permission("read")
	from_statuses, to_status, needs_reason, trail_action, verb = ACTIONS[action]

	if not is_manager():
		frappe.throw(
			_("Only a Sales Manager or Sales Admin can approve, hold, inactivate, reactivate or cancel a Buyer."),
			frappe.PermissionError,
			title=_("Not Permitted"),
		)
	if not is_offline(doc.get("channel")):
		frappe.throw(_("Approval statuses apply to Offline buyers only."))

	current = status_of(doc)
	if current == CANCELLED:
		frappe.throw(_cancelled_message(), title=_("Not Permitted"))
	if current not in from_statuses:
		frappe.throw(_("A Buyer that is {0} cannot be {1}.").format(_(current), _(verb)), title=_("Not Permitted"))

	reason = (reason or "").strip()
	if needs_reason and not reason:
		frappe.throw(_("Enter the reason."), title=_("Reason Required"))

	if action == "approve":
		missing = [doc.meta.get_label(f) for f in ("level", "payment_term", "customer_type") if not doc.get(f)]
		if missing:
			frappe.throw(_("Set {0} before approving this Buyer.").format(", ".join(missing)))

	doc.flags.alpinos_buyer_status_action = True
	doc.buyer_status = to_status
	doc.status_reason = reason or None
	if action == "approve":
		doc.approved_by = frappe.session.user
		doc.approver_role = acting_role() or None
		doc.approved_on = now_datetime()
	if to_status != PENDING:
		doc.escalated_on = None
	# an old buyer may lack a field made mandatory since; a status change is not the place
	# to stop on that (approval checked what it needs above)
	doc.flags.ignore_mandatory = action != "approve"
	doc.save(ignore_permissions=True)

	audit.status_change("Buyer Master", doc.name, trail_action, current, to_status, reason=reason or None)
	return {"buyer_status": to_status, "message": _("Buyer {0}.").format(_(verb))}
