"""List views of the Offline Sales flow as doc Section 8 lists them (W8).

Opportunity: Opportunity ID, Source, Buyer Order Request Ref., Status (badge), Customer, Customer
Type, Site Name, Total Amount, Linked Quotation; filters on each but Total Amount; newest first.
Quotation: Quotation ID, Source, Buyer Order Request Ref (in place of the Opportunity ID: the
Opportunity is skipped since 20 Nov 2026), Customer, Quotation Status (badge), Payment Term, Payment
Status (badge, a separate column: never merged with the Quotation Status), Grand Total, Sales Order
ID; Force Complete Applied is a filter, never a status. Badges: public/js/opportunity_list.js and
public/js/quotation_list.js. Applied by after_migrate through Property Setters (fields that do not
exist yet are skipped), so ERPNext's own definitions are untouched.
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
	"id_first": True,
}


QUOTATION = {
	# Quotation ID, Customer, Quotation Status (badge), Payment Term, Payment Status (badge), Grand
	# Total, Sales Order ID; Force Complete Applied as a filter. The Opportunity is skipped (20 Nov
	# 2026), so the Opportunity ID column gives way to what the Opportunity list showed of a
	# buyer's request: Source and Buyer Order Request Ref.
	"list": [
		"custom_quotation_source", "custom_buyer_order_request_ref", "customer_name", "custom_payment_term",
		"custom_payment_status", "grand_total", "custom_linked_sales_order",
	],
	"not_list": ["status", "transaction_date", "quotation_to", "party_name", "title", "opportunity"],
	"filters": [
		"custom_quotation_source", "custom_buyer_order_request_ref", "party_name", "custom_quotation_status",
		"custom_payment_term", "custom_payment_status", "custom_linked_sales_order", "custom_force_complete_applied",
	],
	"not_filters": ["status", "opportunity"],
	"labels": {"customer_name": "Customer", "custom_linked_sales_order": "Sales Order ID"},
	"search_fields": "customer_name,party_name,custom_buyer_order_request_ref,custom_linked_sales_order",
	"id_first": True,
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
	# only fields that exist (a field another build adds later joins on the next migrate)
	search = ",".join(f for f in (spec.get("search_fields") or "").split(",") if f and meta.get_field(f))
	if search and meta.search_fields != search:
		make_property_setter(doctype, None, "search_fields", search, "Data", for_doctype=True)
	if spec.get("id_first") and meta.title_field:
		# the list's first column is the document ID (doc: "Opportunity ID" / "Quotation ID"),
		# not ERPNext's Title, which repeats the customer's name
		make_property_setter(doctype, None, "title_field", "", "Data", for_doctype=True)
	if meta.sort_field != "creation" or (meta.sort_order or "").upper() != "DESC":
		make_property_setter(doctype, None, "sort_field", "creation", "Data", for_doctype=True)
		make_property_setter(doctype, None, "sort_order", "DESC", "Data", for_doctype=True)
	frappe.clear_cache(doctype=doctype)


def setup():
	_apply("Opportunity", OPPORTUNITY)
	_apply("Quotation", QUOTATION)
