"""
Map Opportunity → Quotation with Alpinos line fields and correct opportunity link.

Replaces ERPNext `make_quotation` via hooks.override_whitelisted_methods.
"""

import frappe
from frappe.model.mapper import get_mapped_doc
from frappe.utils import flt

from erpnext.setup.utils import get_exchange_rate

from alpinos.quotation_line_calc import (
	infer_line_tax_percent,
	quotation_line_taxable_net,
	recalculate_quotation_item_row,
)


def _map_opportunity_item_to_quotation_child(source, target, source_parent):
	"""Populate Quotation Item custom fields when mapping from Opportunity Item."""

	def _gv(obj, fname):
		if hasattr(obj, "get"):
			v = obj.get(fname)
			if v is None:
				return getattr(obj, fname, None)
			return v
		return getattr(obj, fname, None)

	target.custom_boxes = _gv(source, "custom_boxes")

	target.custom_buyer_margin_percent = flt(_gv(source, "custom_buyer_margin_percent"))
	target.custom_mrp = flt(_gv(source, "custom_mrp"))
	target.custom_discount_type = "Percentage"
	target.custom_flat_discount = flt(_gv(source, "custom_flat_discount") or _gv(source, "custom_buyer_margin_percent"))
	target.custom_offer = flt(_gv(source, "custom_offer") or 0)
	target.custom_additional_discount_type = "Percentage"
	target.custom_additional_discount = flt(_gv(source, "custom_additional_discount"))

	opp_tax = flt(_gv(source, "custom_item_tax"))
	amt_pre_tax = flt(_gv(source, "amount"))
	if amt_pre_tax > 0 and opp_tax >= 0:
		target.custom_item_tax_percent = infer_line_tax_percent(amt_pre_tax, opp_tax)
	else:
		merged = frappe._dict(
			{
				"qty": target.qty,
				"custom_mrp": target.custom_mrp,
				"custom_buyer_margin_percent": target.custom_buyer_margin_percent,
				"custom_discount_type": target.custom_discount_type,
				"custom_flat_discount": target.custom_flat_discount,
				"custom_offer": target.custom_offer,
				"custom_additional_discount_type": target.custom_additional_discount_type,
				"custom_additional_discount": target.custom_additional_discount,
			}
		)
		tnet = quotation_line_taxable_net(merged)
		if tnet > 0 and opp_tax >= 0:
			target.custom_item_tax_percent = infer_line_tax_percent(tnet, opp_tax)


@frappe.whitelist()
def make_quotation(source_name, target_doc=None):
	def set_missing_values(source, target):
		from erpnext.controllers.accounts_controller import get_default_taxes_and_charges

		quotation = frappe.get_doc(target)

		quotation.opportunity = source.name

		obm_party = source.party_name if source.get("opportunity_from") == "Offline Buyer Master" else None
		resolved_customer = None
		obm_customer_name = None
		payment_term = None
		if obm_party:
			row = frappe.db.get_value(
				"Offline Buyer Master",
				obm_party,
				["customer", "customer_business_name", "payment_term"],
				as_dict=True,
			)
			if row:
				resolved_customer = row.get("customer")
				obm_customer_name = row.get("customer_business_name")
				payment_term = row.get("payment_term")
			if not resolved_customer:
				frappe.throw(
					"Offline Buyer Master {0} has no linked Customer. Please save the Offline Buyer Master first.".format(
						frappe.bold(obm_party)
					)
				)

		order_type_src = source.get("custom_order_type")
		if order_type_src:
			quotation.order_type = order_type_src
		if obm_party and payment_term:
			quotation.custom_payment_mode = {
				"Credit": "Debit",
				"Partial": "Partial",
				"Advance": "Advance",
			}.get(payment_term, "Advance")

		company_currency = frappe.get_cached_value("Company", quotation.company, "default_currency")

		if company_currency == quotation.currency:
			exchange_rate = 1
		else:
			exchange_rate = get_exchange_rate(
				quotation.currency, company_currency, quotation.transaction_date, args="for_selling"
			)

		quotation.conversion_rate = exchange_rate

		taxes = get_default_taxes_and_charges("Sales Taxes and Charges Template", company=quotation.company)
		if taxes.get("taxes"):
			quotation.update(taxes)

		quotation.ignore_pricing_rule = 1
		if obm_party:
			# ERPNext's set_missing_values/get_party_details only understands standard
			# selling parties for tax rules. Use the linked Customer internally, then
			# restore the visible Quotation party back to Offline Buyer Master.
			quotation.quotation_to = "Customer"
			quotation.party_name = resolved_customer
		quotation.run_method("set_missing_values")
		if obm_party:
			quotation.quotation_to = "Offline Buyer Master"
			quotation.party_name = obm_party
			quotation.customer_name = obm_customer_name or source.get("customer_name") or obm_party
			quotation.custom_resolved_customer = resolved_customer
			try:
				from alpinos.sales_order_offline_buyer import _offline_buyer_address_sync

				addresses = _offline_buyer_address_sync(resolved_customer)
				if addresses.get("default_billing"):
					quotation.customer_address = addresses.get("default_billing")
				if addresses.get("default_shipping"):
					quotation.shipping_address_name = addresses.get("default_shipping")
			except Exception:
				# Address sync is helpful but must not block quotation creation.
				frappe.log_error(frappe.get_traceback(), "OBM address sync failed while making quotation")

		for row in quotation.get("items") or []:
			recalculate_quotation_item_row(quotation, row)

		quotation.run_method("calculate_taxes_and_totals")

	doclist = get_mapped_doc(
		"Opportunity",
		source_name,
		{
			"Opportunity": {
				"doctype": "Quotation",
				"field_map": {"opportunity_from": "quotation_to"},
			},
			"Opportunity Item": {
				"doctype": "Quotation Item",
				"field_map": {
					"parent": "prevdoc_docname",
					"parenttype": "prevdoc_doctype",
					"uom": "stock_uom",
				},
				"postprocess": _map_opportunity_item_to_quotation_child,
				"add_if_empty": True,
			},
		},
		target_doc,
		set_missing_values,
	)

	return doclist
