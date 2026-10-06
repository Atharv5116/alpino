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

Only Sales Officers are narrowed. Sales Managers and Sales Admins keep the scope they have
today: the approved BRD gives SA organisation-wide Offline Buyer access and says Show All
governs list scope only, so inventing a restriction for them here would contradict it.
"""

import frappe

from alpinos.buyer_assignment import SALES_OFFICER_ROLE

#: Holding any of these means the Sales Officer narrowing does not apply.
UNRESTRICTED_ROLES = {
	"Sales Admin",
	"Sales Manager",
	"Sales Master Manager",
	"System Manager",
	"Administrator",
}

#: The Sales Order field that points at the Buyer Master.
SO_BUYER_FIELD = "custom_offline_buyer_master"


def _employee_for(user):
	return frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name")


def is_assignment_scoped(user=None):
	"""True when this user may only see the Buyers they are assigned to."""
	user = user or frappe.session.user
	if not user or user == "Administrator":
		return False
	roles = set(frappe.get_roles(user))
	if roles & UNRESTRICTED_ROLES:
		return False
	return SALES_OFFICER_ROLE in roles


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
	"""Deny an unassigned Buyer; otherwise stay out of the way (return None)."""
	user = user or frappe.session.user
	if not is_assignment_scoped(user):
		return None
	employee = _employee_for(user)
	name = doc.get("name") if hasattr(doc, "get") else None
	if not name:
		return None
	if not employee or name not in _assigned_buyer_names(employee):
		return False
	return None


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
		return None
	buyer = doc.get(SO_BUYER_FIELD) if hasattr(doc, "get") else None
	if not buyer:
		# Not an offline-buyer order, so no Buyer assignment can grant it.
		return False
	employee = _employee_for(user)
	if not employee or buyer not in _assigned_buyer_names(employee):
		return False
	return None


@frappe.whitelist()
def explain(user=None):
	"""What this user is scoped to, and why. For a 'why can't I see it' complaint.

	  bench --site SITE execute alpinos.buyer_assignment_visibility.explain --kwargs "{'user':'x@y.com'}"
	"""
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
			else f"not scoped: does not hold {SALES_OFFICER_ROLE}"
		),
		"assigned_buyers": buyers,
		"assigned_buyer_count": len(buyers) if buyers is not None else None,
	}
