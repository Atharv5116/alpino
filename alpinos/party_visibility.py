"""Changes(HP) #50: why a party does or does not appear in the customer search.

"A Sales Admin cannot find U.S Supplements" has five possible causes, and the screen says
none of them. The Sales Order customer dropdown does not list Customers: it lists customers
that have a Buyer Master row, in the user's channel, at the ROOT of their family
(sales_order_offline_buyer._customers_with_offline_buyer_master_query). A party goes missing
when any one of those is not true, or when its Buyer Master points at a Customer that was
renamed out from under it.

	bench --site SITE execute alpinos.party_visibility.explain --kwargs "{'term':'Supplement'}"
	bench --site SITE execute alpinos.party_visibility.explain --kwargs "{'term':'U.S','user':'x@y.com'}"

Read-only: it reports, it never repairs.
"""

import frappe
from frappe.utils import cint

# The dropdown a Sales role uses; E-com roles get the e-com one, which differs only by channel.
_OFFLINE_CHANNELS = ("", "Offline")


def _buyer_rows(term):
	like = f"%{term}%"
	return frappe.db.sql(
		"""
		SELECT m.name, m.customer_business_name, m.site_name, m.channel, m.customer,
		       IFNULL(m.is_parent, 0) AS is_parent, IFNULL(m.parent_buyer, '') AS parent_buyer
		FROM `tabBuyer Master` m
		WHERE m.customer_business_name LIKE %(like)s OR m.name LIKE %(like)s
		   OR IFNULL(m.customer, '') LIKE %(like)s OR IFNULL(m.tally_buyer_name, '') LIKE %(like)s
		ORDER BY m.customer_business_name
		""",
		{"like": like},
		as_dict=True,
	)


def _customer_rows(term):
	like = f"%{term}%"
	return frappe.db.sql(
		"""
		SELECT c.name, c.customer_name, IFNULL(c.disabled, 0) AS disabled,
		       (SELECT COUNT(*) FROM `tabBuyer Master` b WHERE b.customer = c.name) AS buyer_rows
		FROM `tabCustomer` c
		WHERE c.customer_name LIKE %(like)s OR c.name LIKE %(like)s
		ORDER BY c.customer_name
		""",
		{"like": like},
		as_dict=True,
	)


def _why_hidden(buyer):
	"""Every reason this buyer is not offered in the offline Sales Order dropdown."""
	reasons = []
	if not (buyer.customer or "").strip():
		reasons.append("the Buyer Master has no Customer linked")
	elif not frappe.db.exists("Customer", buyer.customer):
		reasons.append(
			f"its Customer {buyer.customer!r} no longer exists -- the Customer was renamed and "
			"the Buyer Master still points at the old id"
		)
	elif cint(frappe.db.get_value("Customer", buyer.customer, "disabled")):
		reasons.append(f"its Customer {buyer.customer!r} is disabled")

	if (buyer.channel or "") not in _OFFLINE_CHANNELS:
		reasons.append(
			f"its channel is {buyer.channel!r}: Sales roles are limited to Offline and General "
			"Trade (Changes(HP) #22), so only an E-Commerce role sees it"
		)
	if not cint(buyer.is_parent) and buyer.parent_buyer:
		reasons.append(
			f"it is a CHILD site of {buyer.parent_buyer}: the dropdown offers the family root, "
			"and the Site Name field then narrows to this site"
		)
	return reasons


@frappe.whitelist()
def explain(term, user=None):
	"""Report what the customer search can and cannot see for `term`, and why."""
	frappe.only_for(("System Manager", "Sales Admin", "Sales Manager", "E-Commerce Admin", "Administrator"))
	term = (term or "").strip()
	if not term:
		frappe.throw("A search term is required.")

	buyers = _buyer_rows(term)
	customers = _customer_rows(term)

	# What the page itself would offer, run as the user in question.
	from alpinos.sales_order_offline_buyer import _customers_with_offline_buyer_master_query

	original = frappe.session.user
	try:
		if user:
			frappe.set_user(user)
		offered = [
			row[0]
			for row in _customers_with_offline_buyer_master_query(term, 0, 50, channel="Offline", parents_only=True)
		]
	finally:
		frappe.set_user(original)

	findings = []
	for b in buyers:
		reasons = _why_hidden(b)
		findings.append({
			"buyer": b.name,
			"business_name": b.customer_business_name,
			"site": b.site_name,
			"channel": b.channel,
			"customer": b.customer,
			"in_offline_dropdown": b.customer in offered,
			"hidden_because": reasons,
		})

	# A Customer nobody made a Buyer Master for is invisible to the dropdown by design:
	# the pool is Buyer Masters, not the Customer list.
	orphan_customers = [
		{"customer": c.name, "customer_name": c.customer_name,
		 "hidden_because": ["no Buyer Master row points at this Customer"]}
		for c in customers if not cint(c.buyer_rows)
	]

	return {
		"term": term,
		"as_user": user or original,
		"buyer_masters": findings,
		"customers_without_a_buyer_master": orphan_customers,
		"offered_by_the_offline_dropdown": offered,
	}


@frappe.whitelist()
def broken_customer_links(limit=50):
	"""Buyer Masters whose Customer is gone -- renamed away, or deleted. Read-only."""
	frappe.only_for(("System Manager", "Administrator"))
	rows = frappe.db.sql(
		"""
		SELECT m.name AS buyer, m.customer_business_name, m.customer AS missing_customer
		FROM `tabBuyer Master` m
		WHERE IFNULL(m.customer, '') <> ''
		  AND NOT EXISTS (SELECT 1 FROM `tabCustomer` c WHERE c.name = m.customer)
		ORDER BY m.name
		""",
		as_dict=True,
	)
	return {"count": len(rows), "sample": rows[: cint(limit)] if cint(limit) else rows}
