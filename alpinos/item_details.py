"""ERPNext item detail wrappers for Alpinos selling flows."""

import json

import frappe

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
def get_item_details(args, doc=None, for_validate=False, overwrite_warehouse=True):
	args, doc = _normalize_obm_quotation_args(args, doc)
	return erpnext_get_item_details(args, doc, for_validate, overwrite_warehouse)


@frappe.whitelist()
def get_item_tax_template(args, item=None, out=None):
	args, _doc = _normalize_obm_quotation_args(args)
	return erpnext_get_item_tax_template(args, item, out)
