"""Buyer assignment decides what a Sales Officer sees.

Buyer Master & Sales Order - Required Changes (03-10-2026), sections 5, 14 and 15.

    14. "A Sales Officer can only see Buyers where the Sales Officer is included in
         Buyer Master > Sales Officer(s). They must not have unrestricted access to
         unrelated Buyers."
    15. "A Sales Officer can see Sales Orders related to Buyers assigned to that Sales
         Officer... even when the Sales Order itself was created by another permitted user."

So the scope is the Buyer, not authorship. A Sales Officer sees every Sales Order of a Buyer
they are assigned to, including ones a manager raised; and loses sight of a Buyer the moment
they are unassigned, including orders they raised themselves. There is deliberately no
"but I created it" fallback -- that would keep an unassigned officer looking at the account
after the handover, which is the opposite of what the rule is for.

Only Sales Officers are narrowed by default. The approved "Opportunity to Sales Order v1.0.0"
(Section 1, 4.1) narrows a Sales Manager to the Buyers they are Primary POC of too; that ships
behind Offline Sales Settings > "Buyer assignment decides what Sales Managers and Sales Admins
see", OFF until the Buyers carry their POCs (on 13 Nov one UAT Buyer had a Primary POC). A Sales
Admin keeps organisation-wide Offline Buyer access either way: Show All governs list scope
only (alpinos.offline_sales.access), never permission.

Section 1, 4.1-4.2 also carries the scope downstream: a scoped user sees the Opportunities and
Quotations of their Buyers, and the Pick Lists and Delivery Notes of their Buyers' Sales Orders, read only
for a Sales Officer.
"""

import frappe

from alpinos.permission_compat import NO_OBJECTION

from alpinos.buyer_assignment import SALES_OFFICER_ROLE

#: Holding any of these means the assignment narrowing does not apply.
UNRESTRICTED_ROLES = {
	"Sales Admin",
	"Sales Master Manager",
	"System Manager",
	"Administrator",
}

#: Narrowed only while Offline Sales Settings switches manager scoping on.
SWITCHED_ROLE = "Sales Manager"

#: Roles that work Pick Lists and Delivery Notes for every order: assignment never narrows
#: those two documents for them.
OPERATIONS_ROLES = {
	"Warehouse Admin",
	"Warehouse Manager",
	"Accounts User",
	"Accounts Manager",
	"PL User",
	"DN User",
	"Alpinos Full Access",
}

#: A Sales Officer only reads Pick Lists and Delivery Notes (Section 1, 4.2).
_WRITE_PTYPES = {"write", "create", "submit", "cancel", "delete", "amend"}

#: The Sales Order field that points at the Buyer Master.
SO_BUYER_FIELD = "custom_offline_buyer_master"


def _employee_for(user):
	return frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name", order_by="name asc")


def _scope_managers():
	from alpinos.offline_sales.settings import scope_managers

	return scope_managers()


def is_assignment_scoped(user=None):
	"""True when this user may only see the Buyers they are assigned to."""
	user = user or frappe.session.user
	if not user or user == "Administrator":
		return False
	roles = set(frappe.get_roles(user))
	if roles & UNRESTRICTED_ROLES:
		return False
	if SWITCHED_ROLE in roles:
		return _scope_managers()
	return SALES_OFFICER_ROLE in roles


def _is_officer_only(user):
	roles = set(frappe.get_roles(user))
	return SALES_OFFICER_ROLE in roles and not (roles & (UNRESTRICTED_ROLES | {SWITCHED_ROLE}))


def _assigned_buyers_sql(employee):
	"""SQL selecting the Buyer Master names this employee is assigned to.

	All three assignment fields count, because section 5 makes all three access-control
	fields. For a Sales-Officer-only user the POC branches can never match -- those fields
	refuse anyone without Sales Manager or Sales Admin -- but scoping on all three keeps the
	rule correct if somebody's roles change later.
	"""
	e = frappe.db.escape(employee)
	return (
		"SELECT bso.parent FROM `tabBuyer Sales Officer` bso "
		f"WHERE bso.parenttype = 'Buyer Master' AND bso.employee = {e} "
		"UNION "
		"SELECT bpp.parent FROM `tabBuyer Primary POC` bpp "
		f"WHERE bpp.parenttype = 'Buyer Master' AND bpp.employee = {e} "
		"UNION "
		f"SELECT bm.name FROM `tabBuyer Master` bm WHERE bm.secondary_poc = {e}"
	)


def _assigned_buyer_names(employee):
	if not employee:
		return set()
	rows = frappe.db.sql(_assigned_buyers_sql(employee))
	return {r[0] for r in rows if r and r[0]}


# ---------------------------------------------------------------------------
# Buyer Master
# ---------------------------------------------------------------------------

def buyer_master_query_conditions(user=None):
	user = user or frappe.session.user
	if not is_assignment_scoped(user):
		return ""
	employee = _employee_for(user)
	if not employee:
		# A Sales Officer with no Employee record is assigned to nothing, and an empty
		# condition would hand them every Buyer instead of none.
		return "1 = 0"
	return f"`tabBuyer Master`.name IN ({_assigned_buyers_sql(employee)})"


def buyer_master_has_permission(doc, user=None, permission_type=None):
	"""Deny an unassigned Buyer; otherwise stay out of the way (return NO_OBJECTION)."""
	user = user or frappe.session.user
	if not is_assignment_scoped(user):
		return NO_OBJECTION
	employee = _employee_for(user)
	name = doc.get("name") if hasattr(doc, "get") else None
	if not name:
		return NO_OBJECTION
	if not employee or name not in _assigned_buyer_names(employee):
		return False
	return NO_OBJECTION


# ---------------------------------------------------------------------------
# Sales Order
# ---------------------------------------------------------------------------

def sales_order_query_conditions(user=None):
	user = user or frappe.session.user
	if not is_assignment_scoped(user):
		return ""
	employee = _employee_for(user)
	if not employee:
		return "1 = 0"
	return (
		f"IFNULL(`tabSales Order`.{SO_BUYER_FIELD}, '') <> '' "
		f"AND `tabSales Order`.{SO_BUYER_FIELD} IN ({_assigned_buyers_sql(employee)})"
	)


def sales_order_has_permission(doc, user=None, permission_type=None):
	user = user or frappe.session.user
	if not is_assignment_scoped(user):
		return NO_OBJECTION
	buyer = doc.get(SO_BUYER_FIELD) if hasattr(doc, "get") else None
	if not buyer:
		# Not an offline-buyer order, so no Buyer assignment can grant it.
		return False
	employee = _employee_for(user)
	if not employee or buyer not in _assigned_buyer_names(employee):
		return False
	return NO_OBJECTION


# ---------------------------------------------------------------------------
# Quotation (Section 1, 4.1)
# ---------------------------------------------------------------------------

QUOTATION_BUYER_FIELD = "custom_buyer_master"


def quotation_query_conditions(user=None):
	user = user or frappe.session.user
	if not is_assignment_scoped(user):
		return ""
	employee = _employee_for(user)
	if not employee:
		return "1 = 0"
	return (
		f"IFNULL(`tabQuotation`.{QUOTATION_BUYER_FIELD}, '') <> '' "
		f"AND `tabQuotation`.{QUOTATION_BUYER_FIELD} IN ({_assigned_buyers_sql(employee)})"
	)


def quotation_has_permission(doc, user=None, permission_type=None):
	user = user or frappe.session.user
	if not is_assignment_scoped(user):
		return NO_OBJECTION
	if not doc.get("creation") or (hasattr(doc, "is_new") and doc.is_new()):
		return NO_OBJECTION  # creating one is the role's create right; its Buyer is checked on save
	from alpinos.offline_sales.catalog_gate import quotation_buyer

	buyer = doc.get(QUOTATION_BUYER_FIELD) or quotation_buyer(doc)
	employee = _employee_for(user)
	if not buyer or not employee or buyer not in _assigned_buyer_names(employee):
		return False
	return NO_OBJECTION


# ---------------------------------------------------------------------------
# Opportunity (Section 1, 4.1 and Section 8: the Opportunities of the user's Buyers)
# ---------------------------------------------------------------------------


def opportunity_query_conditions(user=None):
	user = user or frappe.session.user
	if not is_assignment_scoped(user):
		return ""
	employee = _employee_for(user)
	if not employee:
		return "1 = 0"
	return (
		"`tabOpportunity`.opportunity_from = 'Buyer Master' "
		f"AND `tabOpportunity`.party_name IN ({_assigned_buyers_sql(employee)})"
	)


def opportunity_has_permission(doc, user=None, permission_type=None):
	user = user or frappe.session.user
	if not is_assignment_scoped(user):
		return NO_OBJECTION
	if not doc.get("creation") or (hasattr(doc, "is_new") and doc.is_new()):
		return NO_OBJECTION  # creating one is the role's create right; its Buyer is checked on save
	buyer = doc.get("party_name") if doc.get("opportunity_from") == "Buyer Master" else None
	employee = _employee_for(user)
	if not buyer or not employee or buyer not in _assigned_buyer_names(employee):
		return False
	return NO_OBJECTION


# ---------------------------------------------------------------------------
# Pick List / Delivery Note: through their Sales Order's Buyer (Section 1, 4.2)
# ---------------------------------------------------------------------------


def is_downstream_scoped(user=None):
	user = user or frappe.session.user
	if not is_assignment_scoped(user):
		return False
	return not (set(frappe.get_roles(user)) & OPERATIONS_ROLES)


def _downstream_condition(doctype, user):
	user = user or frappe.session.user
	if not is_downstream_scoped(user):
		return ""
	employee = _employee_for(user)
	if not employee:
		return "1 = 0"
	return (
		f"`tab{doctype}`.custom_sales_order_id IN (SELECT so.name FROM `tabSales Order` so "
		f"WHERE so.{SO_BUYER_FIELD} IN ({_assigned_buyers_sql(employee)}))"
	)


def _downstream_permission(doc, user, permission_type):
	user = user or frappe.session.user
	if not is_downstream_scoped(user):
		return NO_OBJECTION
	if permission_type in _WRITE_PTYPES and _is_officer_only(user):
		return False
	if not doc.get("creation") or (hasattr(doc, "is_new") and doc.is_new()):
		return NO_OBJECTION
	so = doc.get("custom_sales_order_id")
	buyer = frappe.db.get_value("Sales Order", so, SO_BUYER_FIELD) if so else None
	employee = _employee_for(user)
	if not buyer or not employee or buyer not in _assigned_buyer_names(employee):
		return False
	return NO_OBJECTION


def pick_list_query_conditions(user=None):
	return _downstream_condition("Pick List", user)


def delivery_note_query_conditions(user=None):
	return _downstream_condition("Delivery Note", user)


def pick_list_has_permission(doc, user=None, permission_type=None):
	return _downstream_permission(doc, user, permission_type)


def delivery_note_has_permission(doc, user=None, permission_type=None):
	return _downstream_permission(doc, user, permission_type)


@frappe.whitelist()
def explain(user=None):
	"""What this user is scoped to, and why. For a 'why can't I see it' complaint.

	  bench --site SITE execute alpinos.buyer_assignment_visibility.explain --kwargs "{'user':'x@y.com'}"
	"""
	# company-scope: n/a (debug tool: one user's own Buyer assignment; another user's needs System Manager)
	if user and user != frappe.session.user:
		frappe.only_for(("System Manager", "Administrator"))
	user = user or frappe.session.user
	roles = sorted(set(frappe.get_roles(user)))
	employee = _employee_for(user)
	scoped = is_assignment_scoped(user)
	buyers = sorted(_assigned_buyer_names(employee)) if scoped else None
	return {
		"user": user,
		"employee": employee,
		"roles": roles,
		"assignment_scoped": scoped,
		"reason": (
			"not scoped: holds " + ", ".join(sorted(set(roles) & UNRESTRICTED_ROLES))
			if set(roles) & UNRESTRICTED_ROLES
			else "scoped to assigned Buyers"
			if scoped
			else f"not scoped: {SWITCHED_ROLE} with manager scoping switched off"
			if SWITCHED_ROLE in roles
			else f"not scoped: does not hold {SALES_OFFICER_ROLE}"
		),
		"manager_scoping_on": _scope_managers(),
		"pick_list_and_delivery_note_scoped": is_downstream_scoped(user),
		"assigned_buyers": buyers,
		"assigned_buyer_count": len(buyers) if buyers is not None else None,
	}
