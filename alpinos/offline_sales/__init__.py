"""Offline Sales workflow ("Opportunity to Sales Order v1.0.0", approved 14 Sep 2026), without
the Opportunity module (Hetvi, 13 Nov 2026: "everything except the opportunity part").

Build 1 is the document's Section 1 (roles, record access, Show All, the common audit trail) and
Section 4 (buyer creation, approval statuses, the 48-hour escalation, the Buyer Catalog gate).

The roles are the ones the 3 Oct amendment already put on Buyer Master:
    SO  Sales Officer        assigned through Buyer Master > Sales Officer(s)
    SM  Sales Manager        Primary POC(s)
    SA  Sales Admin          Secondary POC (single)
"""

import frappe

SALES_OFFICER = "Sales Officer"
SALES_MANAGER = "Sales Manager"
SALES_ADMIN = "Sales Admin"
SYSTEM_MANAGER = "System Manager"

#: Roles that review, approve and price buyers (document section 3.2 / 3.3, plus the
#: technical System Manager, which the app already treats as able to do anything).
MANAGER_ROLES = (SALES_MANAGER, SALES_ADMIN, SYSTEM_MANAGER)

SETTINGS = "Offline Sales Settings"

# Buyer statuses (document Section 4, 4.1). "Needs Correction" is deliberately absent.
PENDING = "Pending Approval"
APPROVED = "Approved"
ON_HOLD = "On Hold"
INACTIVE = "Inactive"
CANCELLED = "Cancelled"
STATUSES = (PENDING, APPROVED, ON_HOLD, INACTIVE, CANCELLED)

#: Statuses in which a Sales Officer may still correct the buyer (4.1).
CORRECTABLE = (PENDING, ON_HOLD)

CATALOG_PENDING = "Pending"
CATALOG_COMPLETED = "Completed"

#: The one channel the workflow does not govern ("E-Commerce workflow excluded", 3.1).
ECOM_CHANNEL = "E-com"


def is_offline(channel):
	"""Every buyer outside E-com is an Offline buyer (a blank channel is an old Offline one)."""
	return (channel or "") != ECOM_CHANNEL


def user_roles(user=None):
	return set(frappe.get_roles(user or frappe.session.user))


def is_manager(user=None):
	"""Sales Manager, Sales Admin, System Manager or Administrator."""
	user = user or frappe.session.user
	return user == "Administrator" or bool(user_roles(user) & set(MANAGER_ROLES))


def is_sales_officer_only(user=None):
	"""A Sales Officer who holds none of the manager roles: the person the document limits."""
	user = user or frappe.session.user
	if user == "Administrator":
		return False
	roles = user_roles(user)
	return SALES_OFFICER in roles and not (roles & set(MANAGER_ROLES))
