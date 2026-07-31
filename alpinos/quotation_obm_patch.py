"""Patch ERPNext Quotation._make_customer for Buyer Master party_type."""

import frappe


def apply_quotation_obm_customer_patch() -> None:
	import erpnext.selling.doctype.quotation.quotation as qmod

	if getattr(qmod._make_customer, "_alpinos_obm_patch", False):
		return

	_orig = qmod._make_customer

	def _make_customer(source_name, ignore_permissions=False):
		q = frappe.db.get_value(
			"Quotation",
			source_name,
			["quotation_to", "party_name"],
			as_dict=1,
		)
		if q and q.quotation_to == "Buyer Master" and q.party_name:
			cust = frappe.db.get_value("Buyer Master", q.party_name, "customer")
			if cust:
				return frappe.get_doc("Customer", cust)
		return _orig(source_name, ignore_permissions=ignore_permissions)

	_make_customer._alpinos_obm_patch = True
	qmod._make_customer = _make_customer
