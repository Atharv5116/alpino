"""Who may do what to a Sales Order, per Buyer assignment.

"Buyer Master & Sales Order - Required Changes" (03-10-2026), sections 6-11.

    6.  A Sales Order can be created by Sales Officer, Primary POC or Secondary POC.
    7.  An assigned Sales Officer may create, save, edit while Draft, add and remove items,
        change Quantity / Selling Price / Flat Discount % / Margin, cancel while Draft and
        duplicate -- but CANNOT submit.
    11. Only the Primary POC or Secondary POC performs the final submission.

NOTE ON PRECEDENCE. The approved BRD "Opportunity to Sales Order v1.0.0" says the opposite
in its section 6 §2.1 -- "SO cannot create a Sales Order... Backend/API validation must also
block unauthorized creation" -- and gives the refusal wording in exception §11.1. The 03-10
document supersedes it and says so itself ("Change from Current Specification"). This module
implements the newer rule; if that is ever reversed, this file and the role's DocPerms are
the only places to change.

Submission authority is per BUYER, not per role: the question the document asks is whether
*this* person is the Primary or Secondary POC of the buyer the order belongs to. Sales
Manager and Sales Admin keep a blanket authority because they already carry it everywhere
else in the app, and removing it here would strand orders whose POC has left.
"""

import frappe
from frappe import _

from alpinos.buyer_assignment import SALES_OFFICER_ROLE

#: Roles that may submit any Sales Order, regardless of who the buyer's POC is.
SUBMIT_OVERRIDE_ROLES = {"Sales Admin", "Sales Manager", "System Manager", "Administrator"}

#: What a Sales Officer may do to a Sales Order. Submit is deliberately absent.
SALES_OFFICER_SO_PERMS = {
	"read": 1,
	"write": 1,
	"create": 1,
	"report": 1,
	"email": 1,
	"print": 1,
	"share": 1,
	"delete": 0,
	"submit": 0,
	"cancel": 0,
	"amend": 0,
}

#: The Sales Order field pointing at the Buyer Master.
SO_BUYER_FIELD = "custom_offline_buyer_master"


def setup_sales_officer_permissions():
	"""Give the Sales Officer role its Sales Order rights, without submit."""
	if not frappe.db.exists("Role", SALES_OFFICER_ROLE):
		return
	from frappe.permissions import add_permission, update_permission_property

	if not frappe.db.exists(
		"Custom DocPerm", {"parent": "Sales Order", "role": SALES_OFFICER_ROLE, "permlevel": 0}
	):
		add_permission("Sales Order", SALES_OFFICER_ROLE, 0)
	for ptype, value in SALES_OFFICER_SO_PERMS.items():
		update_permission_property(
			"Sales Order", SALES_OFFICER_ROLE, 0, ptype, value, validate=False
		)
	frappe.db.commit()


def _employee_for(user):
	return frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name")


def is_poc_for_buyer(buyer, user=None):
	"""True when this user is the Primary or Secondary POC of that Buyer."""
	user = user or frappe.session.user
	if not buyer:
		return False
	employee = _employee_for(user)
	if not employee:
		return False
	if frappe.db.exists(
		"Buyer Primary POC",
		{"parent": buyer, "parenttype": "Buyer Master", "employee": employee},
	):
		return True
	return frappe.db.get_value("Buyer Master", buyer, "secondary_poc") == employee


def may_submit(sales_order, user=None):
	"""(allowed, reason) for submitting one Sales Order."""
	user = user or frappe.session.user
	roles = set(frappe.get_roles(user))
	if user == "Administrator" or (roles & SUBMIT_OVERRIDE_ROLES):
		return True, ""

	buyer = frappe.db.get_value("Sales Order", sales_order, SO_BUYER_FIELD)
	if is_poc_for_buyer(buyer, user):
		return True, ""

	if SALES_OFFICER_ROLE in roles:
		# The wording the document gives the Sales Officer: they build the order, somebody
		# else signs it off.
		return False, _(
			"A Sales Officer may create and edit a Draft Sales Order but cannot submit it. "
			"The Primary POC or Secondary POC for this Buyer submits it."
		)
	return False, _("Only the Primary POC or Secondary POC for this Buyer may submit this Sales Order.")


def require_submit_authority(sales_order, user=None):
	allowed, reason = may_submit(sales_order, user)
	if not allowed:
		frappe.throw(reason, frappe.PermissionError, title=_("Not Permitted"))


def sales_order_has_permission(doc, user=None, permission_type=None):
	"""Deny submit to anyone who is not a POC of the order's Buyer.

	Only ever denies: returning None leaves the other hooks on this doctype their say, which
	is how frappe.permissions.has_controller_permissions reads a chain.
	"""
	if permission_type not in ("submit", "cancel"):
		return None
	user = user or frappe.session.user
	roles = set(frappe.get_roles(user))
	if user == "Administrator" or (roles & SUBMIT_OVERRIDE_ROLES):
		return None
	name = doc.get("name") if hasattr(doc, "get") else None
	buyer = (doc.get(SO_BUYER_FIELD) if hasattr(doc, "get") else None) or (
		frappe.db.get_value("Sales Order", name, SO_BUYER_FIELD) if name else None
	)
	if is_poc_for_buyer(buyer, user):
		return None
	if SALES_OFFICER_ROLE in roles:
		return False
	return None


@frappe.whitelist()
def submit_authority(sales_order):
	"""What the Sales Order view should show this user. Backs hiding the Submit button."""
	allowed, reason = may_submit(sales_order)
	return {"can_submit": 1 if allowed else 0, "reason": reason}
