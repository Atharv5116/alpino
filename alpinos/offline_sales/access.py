"""Show All and assignment coverage (document Section 1, 3.3, 4.1 and 7).

Show All is list scope, never permission: "Applicable List Views default to Buyers where the
current SA is the Secondary POC. Show All = ON expands the List View to all permitted Offline
Buyers. Show All controls display scope and does not grant the underlying business permission."

So it is a list filter, applied only while Offline Sales Settings switches manager scoping on:
  * Buyer Master list   secondary_poc = the Sales Admin's Employee
  * Quotation list      custom_secondary_poc = the same (kept current from the Buyer)
  * Sales Order Entry   the page's own Show All lifts it (alpinos.sales_order_api)
Link fields, reports and the documents themselves stay as the user's permissions allow.
"""

import frappe

from alpinos.offline_sales import ECOM_CHANNEL, SALES_ADMIN, CANCELLED
from alpinos.offline_sales.settings import scope_managers


def _employee(user=None):
	from alpinos.buyer_assignment import employee_for_user

	return employee_for_user(user)


def sa_default_employee(user=None):
	"""The Sales Admin's Employee when their lists should open on their own Buyers, else None."""
	user = user or frappe.session.user
	if user == "Administrator" or not scope_managers():
		return None
	if SALES_ADMIN not in frappe.get_roles(user):
		return None
	return _employee(user)


def sa_default_buyers(user=None):
	"""Buyer Master names a Sales Admin's lists default to, or None for no default filter."""
	employee = sa_default_employee(user)
	if not employee:
		return None
	return frappe.get_all("Buyer Master", filters={"secondary_poc": employee}, pluck="name")


@frappe.whitelist()
def list_scope():
	"""What the Buyer Master / Quotation list views should default to for this user."""
	# company-scope: n/a (the user's own Employee and a settings flag)
	employee = sa_default_employee()
	return {"secondary_poc_default": 1 if employee else 0, "employee": employee}


@frappe.whitelist()
def coverage_report():
	"""Offline buyers (not Cancelled) missing each assignment: what to fill before the switch."""
	# company-scope: n/a (Buyer Master has no company; System Manager / Sales roles read settings)
	frappe.has_permission("Offline Sales Settings", "read", throw=True)
	row = frappe.db.sql(
		"""
		SELECT
			COUNT(*) AS buyers,
			SUM(NOT EXISTS (SELECT 1 FROM `tabBuyer Sales Officer` s WHERE s.parent = bm.name AND s.parenttype = 'Buyer Master')) AS without_sales_officer,
			SUM(NOT EXISTS (SELECT 1 FROM `tabBuyer Primary POC` p WHERE p.parent = bm.name AND p.parenttype = 'Buyer Master')) AS without_primary_poc,
			SUM(IFNULL(bm.secondary_poc, '') = '') AS without_secondary_poc,
			SUM(
				NOT EXISTS (SELECT 1 FROM `tabBuyer Sales Officer` s WHERE s.parent = bm.name AND s.parenttype = 'Buyer Master')
				AND NOT EXISTS (SELECT 1 FROM `tabBuyer Primary POC` p WHERE p.parent = bm.name AND p.parenttype = 'Buyer Master')
				AND IFNULL(bm.secondary_poc, '') = ''
			) AS without_any
		FROM `tabBuyer Master` bm
		WHERE IFNULL(bm.channel, '') != %(ecom)s AND IFNULL(bm.buyer_status, '') != %(cancelled)s
		""",
		{"ecom": ECOM_CHANNEL, "cancelled": CANCELLED},
		as_dict=True,
	)[0]
	return {k: int(v or 0) for k, v in row.items()}


def refresh_quotation_secondary_poc(buyer, secondary_poc):
	"""A Buyer's new Secondary POC follows onto its Quotations (their list filter reads it)."""
	if frappe.db.has_column("Quotation", "custom_secondary_poc") and frappe.db.has_column("Quotation", "custom_buyer_master"):
		frappe.db.sql(
			"UPDATE `tabQuotation` SET custom_secondary_poc = %s WHERE custom_buyer_master = %s",
			(secondary_poc or None, buyer),
		)
