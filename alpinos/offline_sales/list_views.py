"""List views of the Offline Sales flow as doc Section 8 lists them (W8).

Opportunity: Opportunity ID, Source, Buyer Order Request Ref., Status (badge), Customer, Customer
Type, Site Name, Total Amount, Linked Quotation; filters on each but Total Amount; newest first.
The status badge colours are in public/js/opportunity_list.js. Applied by after_migrate through
Property Setters, so ERPNext's own Opportunity definition is untouched.
"""

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

OPPORTUNITY = {
	"list": [
		"custom_opportunity_source", "custom_buyer_order_request_ref", "customer_name", "custom_order_type",
		"custom_site_name", "total", "custom_linked_quotation",
	],
	"not_list": ["naming_series", "opportunity_from", "status", "opportunity_type"],
	"filters": [
		"custom_opportunity_source", "custom_buyer_order_request_ref", "custom_opportunity_status", "party_name",
		"custom_order_type", "custom_site_name", "custom_linked_quotation",
	],
	"not_filters": ["opportunity_from", "status"],
	"labels": {"total": "Total Amount", "customer_name": "Customer"},
	"search_fields": "customer_name,party_name,custom_buyer_order_request_ref,custom_site_name,custom_linked_quotation",
}


def _field(doctype, fieldname, prop, value, ptype="Check"):
	meta = frappe.get_meta(doctype)
	df = meta.get_field(fieldname)
	if not df or str(df.get(prop) or "") == str(value or ""):
		return
	if df.get("is_custom_field"):
		name = frappe.db.get_value("Custom Field", {"dt": doctype, "fieldname": fieldname})
		if name:
			frappe.db.set_value("Custom Field", name, prop, value, update_modified=False)
			return
	make_property_setter(doctype, fieldname, prop, value, ptype, validate_fields_for_doctype=False)


def _apply(doctype, spec):
	if not frappe.db.exists("DocType", doctype):
		return
	for f in spec.get("list", []):
		_field(doctype, f, "in_list_view", 1)
	for f in spec.get("not_list", []):
		_field(doctype, f, "in_list_view", 0)
	for f in spec.get("filters", []):
		_field(doctype, f, "in_standard_filter", 1)
	for f in spec.get("not_filters", []):
		_field(doctype, f, "in_standard_filter", 0)
	for f, label in spec.get("labels", {}).items():
		_field(doctype, f, "label", label, "Data")
	meta = frappe.get_meta(doctype)
	if spec.get("search_fields") and meta.search_fields != spec["search_fields"]:
		make_property_setter(doctype, None, "search_fields", spec["search_fields"], "Data", for_doctype=True)
	if meta.sort_field != "creation" or (meta.sort_order or "").upper() != "DESC":
		make_property_setter(doctype, None, "sort_field", "creation", "Data", for_doctype=True)
		make_property_setter(doctype, None, "sort_order", "DESC", "Data", for_doctype=True)
	frappe.clear_cache(doctype=doctype)


def setup():
	_apply("Opportunity", OPPORTUNITY)
