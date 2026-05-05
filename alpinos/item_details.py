"""ERPNext item detail wrappers for Alpinos selling flows."""

import json

import frappe

from erpnext.accounts.party import get_party_details as erpnext_get_party_details
from erpnext.stock.get_item_details import (
	get_item_details as erpnext_get_item_details,
	get_item_tax_template as erpnext_get_item_tax_template,
)


def _as_dict(value):
	if isinstance(value, str):
		return frappe._dict(json.loads(value))
	return frappe._dict(value or {})


def _normalize_obm_quotation_args(args, doc=None):
	"""Resolve Offline Buyer Master quotations to Customer before ERPNext tax/pricing lookup."""

	args = _as_dict(args)
	doc_dict = _as_dict(doc) if doc else frappe._dict()
	doctype = args.get("doctype") or doc_dict.get("doctype")
	quotation_to = args.get("quotation_to") or doc_dict.get("quotation_to")

	if doctype != "Quotation" or quotation_to != "Offline Buyer Master":
		return args, doc

	obm_name = doc_dict.get("party_name") or args.get("customer")
	customer = args.get("custom_resolved_customer") or doc_dict.get("custom_resolved_customer")
	if not customer and obm_name:
		customer = frappe.db.get_value("Offline Buyer Master", obm_name, "customer")

	if not customer:
		return args, doc

	args.customer = customer
	args.quotation_to = "Customer"

	if doc_dict:
		doc_dict.customer = customer
		doc_dict.quotation_to = "Customer"
		doc_dict.party_name = customer
		doc = doc_dict

	return args, doc


@frappe.whitelist()
def get_party_details(
	party=None,
	account=None,
	party_type="Customer",
	company=None,
	posting_date=None,
	bill_date=None,
	price_list=None,
	currency=None,
	doctype=None,
	ignore_permissions=False,
	fetch_payment_terms_template=True,
	party_address=None,
	company_address=None,
	shipping_address=None,
	dispatch_address=None,
	pos_profile=None,
):
	"""Intercept party_type='Offline Buyer Master' and resolve to linked Customer."""
	if party_type == "Offline Buyer Master" and party:
		customer = frappe.db.get_value("Offline Buyer Master", party, "customer")
		if customer:
			party_type = "Customer"
			party = customer
		else:
			return frappe._dict()

	return erpnext_get_party_details(
		party=party,
		account=account,
		party_type=party_type,
		company=company,
		posting_date=posting_date,
		bill_date=bill_date,
		price_list=price_list,
		currency=currency,
		doctype=doctype,
		ignore_permissions=ignore_permissions,
		fetch_payment_terms_template=fetch_payment_terms_template,
		party_address=party_address,
		company_address=company_address,
		shipping_address=shipping_address,
		dispatch_address=dispatch_address,
		pos_profile=pos_profile,
	)


@frappe.whitelist()
def get_item_details(args, doc=None, for_validate=False, overwrite_warehouse=True):
	args, doc = _normalize_obm_quotation_args(args, doc)
	return erpnext_get_item_details(args, doc, for_validate, overwrite_warehouse)


@frappe.whitelist()
def get_item_tax_template(args, item=None, out=None):
	args, _doc = _normalize_obm_quotation_args(args)
	return erpnext_get_item_tax_template(args, item, out)
