"""Quotation customization for Alpinos."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

# Offline Sales, Section 5 ("Opportunity to Sales Order v1.0.0", W5). Every value below is set by
# the server (alpinos.offline_sales.quotation / quotation_payments) except Quotation Remarks,
# Responsible Sales Officer (Sales Manager / Sales Admin), Payment Term and Credit Days (before
# Finalize) and the Payment Schedule rows (before Finalize). no_copy: a duplicated or amended
# Quotation starts its own status and payment record (21.3: payments are never carried over).
_STAMP = dict(read_only=1, no_copy=1, allow_on_submit=1)

OFFLINE_HEADER_FIELDS = [
	dict(
		fieldname="custom_quotation_status",
		label="Quotation Status",
		fieldtype="Select",
		options="Draft\nNegotiation\nFinalized\nSales Order Created\nCancelled",
		default="Draft",
		insert_after="naming_series",
		search_index=1,
		in_standard_filter=1,
		**_STAMP,
	),
	dict(
		fieldname="custom_billing_gstin",
		label="Billing GSTIN",
		fieldtype="Data",
		insert_after="custom_site_name",
		read_only=1,
		no_copy=1,
	),
	dict(
		fieldname="custom_quotation_remarks",
		label="Quotation Remarks",
		fieldtype="Small Text",
		insert_after="custom_opportunity_remark",
	),
	dict(
		fieldname="custom_responsible_sales_officer",
		label="Responsible Sales Officer",
		fieldtype="Link",
		options="User",
		insert_after="valid_till",
		no_copy=1,
		allow_on_submit=1,
		ignore_user_permissions=1,
	),
	dict(
		fieldname="custom_finalized_by",
		label="Finalized By",
		fieldtype="Link",
		options="User",
		insert_after="custom_responsible_sales_officer",
		depends_on="eval:doc.custom_finalized_by",
		ignore_user_permissions=1,
		**_STAMP,
	),
	dict(
		fieldname="custom_finalized_on",
		label="Finalized On",
		fieldtype="Datetime",
		insert_after="custom_finalized_by",
		depends_on="eval:doc.custom_finalized_on",
		**_STAMP,
	),
	dict(
		fieldname="custom_linked_sales_order",
		label="Sales Order ID",
		fieldtype="Link",
		options="Sales Order",
		insert_after="custom_finalized_on",
		depends_on="eval:doc.custom_linked_sales_order",
		ignore_user_permissions=1,
		**_STAMP,
	),
	dict(
		fieldname="custom_cancellation_reason",
		label="Cancellation Reason",
		fieldtype="Small Text",
		insert_after="custom_linked_sales_order",
		depends_on="eval:doc.custom_quotation_status=='Cancelled'",
		**_STAMP,
	),
	dict(
		fieldname="custom_cancelled_by",
		label="Cancelled By",
		fieldtype="Link",
		options="User",
		insert_after="custom_cancellation_reason",
		depends_on="eval:doc.custom_quotation_status=='Cancelled'",
		ignore_user_permissions=1,
		**_STAMP,
	),
	dict(
		fieldname="custom_cancelled_by_role",
		label="Cancelled By Role",
		fieldtype="Data",
		insert_after="custom_cancelled_by",
		depends_on="eval:doc.custom_quotation_status=='Cancelled'",
		**_STAMP,
	),
	dict(
		fieldname="custom_cancelled_on",
		label="Cancelled On",
		fieldtype="Datetime",
		insert_after="custom_cancelled_by_role",
		depends_on="eval:doc.custom_quotation_status=='Cancelled'",
		**_STAMP,
	),
]

#: The Opportunity is skipped (Hetvi, 20 Nov 2026): a Buyer Order Request Form submission is a
#: Draft Quotation, so the Quotation carries what the Opportunity carried for it (Section 2, 5.1):
#: the source, the BOR reference, the buyer's contact person and "Buyer Portal - name".
SOURCE_DIRECT = "Direct Quotation"
SOURCE_PORTAL = "Buyer Order Request Form"

REQUEST_FIELDS = [
	dict(
		fieldname="custom_quotation_source",
		label="Source",
		fieldtype="Select",
		options=f"{SOURCE_DIRECT}\n{SOURCE_PORTAL}",
		default=SOURCE_DIRECT,
		insert_after="custom_quotation_status",
		in_standard_filter=1,
		read_only=1,
		no_copy=1,
	),
	dict(
		fieldname="custom_buyer_order_request_ref",
		label="Buyer Order Request Ref",
		fieldtype="Data",
		insert_after="custom_quotation_source",
		depends_on="eval:doc.custom_buyer_order_request_ref",
		search_index=1,
		read_only=1,
		no_copy=1,
	),
	dict(
		fieldname="custom_request_contact_person",
		label="Request Contact Person",
		fieldtype="Data",
		insert_after="custom_buyer_order_request_ref",
		depends_on=f"eval:doc.custom_quotation_source=='{SOURCE_PORTAL}'",
		read_only=1,
		no_copy=1,
	),
	dict(
		fieldname="custom_source_display",
		label="Submitted Through",
		fieldtype="Data",
		insert_after="custom_request_contact_person",
		depends_on=f"eval:doc.custom_quotation_source=='{SOURCE_PORTAL}'",
		read_only=1,
		no_copy=1,
	),
]

#: Tabs like the Opportunity's: Details | Items | Payment | Activity (Hetvi, 20 Nov 2026). The
#: order inside each is set by _setup_offline_field_order.
TAB_FIELDS = [
	dict(fieldname="custom_items_tab", label="Items", fieldtype="Tab Break", insert_after="ignore_pricing_rule"),
	dict(fieldname="custom_payment_tab", label="Payment", fieldtype="Tab Break", insert_after="referral_sales_partner"),
]

#: One dynamic Payment Section after the totals (doc 5, 8): Payment Term, then the term's fields
#: (Credit Days + Expected Payment Date, or the Payment Schedule), the submitted payments, and
#: the Payment Summary. Written after Finalize only through the payment actions.
PAYMENT_FIELDS = [
	dict(
		fieldname="custom_payment_section",
		label="Payment",
		fieldtype="Section Break",
		insert_after="referral_sales_partner",
	),
	dict(
		fieldname="custom_payment_term",
		label="Payment Term",
		fieldtype="Select",
		options="\nAdvance\nCredit\nPartial",
		insert_after="custom_payment_section",
		no_copy=1,
		allow_on_submit=1,
		in_standard_filter=1,
	),
	dict(
		fieldname="custom_payment_term_col",
		fieldtype="Column Break",
		insert_after="custom_payment_term",
	),
	dict(
		fieldname="custom_credit_days",
		label="Credit Days",
		fieldtype="Int",
		insert_after="custom_payment_term_col",
		depends_on="eval:doc.custom_payment_term=='Credit'",
		no_copy=1,
		allow_on_submit=1,
	),
	dict(
		fieldname="custom_expected_payment_date",
		label="Expected Payment Date",
		fieldtype="Date",
		insert_after="custom_credit_days",
		depends_on="eval:doc.custom_payment_term=='Credit'",
		description="Finalized date + Credit Days, set at Finalize.",
		reqd=0,
		mandatory_depends_on="",
		read_only=1,
		no_copy=1,
		allow_on_submit=1,
	),
	dict(
		fieldname="custom_schedule_section",
		label="Payment Schedule",
		fieldtype="Section Break",
		insert_after="custom_expected_payment_date",
		depends_on="eval:doc.custom_payment_term=='Partial'",
	),
	dict(
		fieldname="custom_payment_schedule",
		label="Payment Schedule",
		fieldtype="Table",
		options="Quotation Payment Schedule",
		insert_after="custom_schedule_section",
		no_copy=1,
		allow_on_submit=1,
	),
	dict(
		fieldname="custom_receipts_section",
		label="Payments Received",
		fieldtype="Section Break",
		insert_after="custom_payment_schedule",
		depends_on="eval:(doc.custom_payment_receipts || []).length",
	),
	dict(
		fieldname="custom_payment_receipts",
		label="Payments",
		fieldtype="Table",
		options="Quotation Payment Receipt",
		insert_after="custom_receipts_section",
		**_STAMP,
	),
	dict(
		fieldname="custom_payment_summary_section",
		label="Payment Summary",
		fieldtype="Section Break",
		insert_after="custom_payment_receipts",
	),
	dict(
		fieldname="custom_payment_grand_total",
		label="Quotation Grand Total",
		fieldtype="Currency",
		options="currency",
		insert_after="custom_payment_summary_section",
		**_STAMP,
	),
	dict(
		fieldname="custom_total_received",
		label="Total Received",
		fieldtype="Currency",
		options="currency",
		insert_after="custom_payment_summary_section",
		**_STAMP,
	),
	dict(
		fieldname="custom_total_pending",
		label="Total Pending",
		fieldtype="Currency",
		options="currency",
		insert_after="custom_total_received",
		**_STAMP,
	),
	dict(
		fieldname="custom_payment_summary_col",
		fieldtype="Column Break",
		insert_after="custom_total_pending",
	),
	dict(
		fieldname="custom_payment_status",
		label="Payment Status",
		fieldtype="Select",
		options="Pending\nPartially Received\nFully Received",
		default="Pending",
		insert_after="custom_payment_summary_col",
		in_standard_filter=1,
		**_STAMP,
	),
	dict(
		fieldname="custom_so_eligibility",
		label="SO Eligibility",
		fieldtype="Select",
		options="Allowed\nBlocked",
		default="Blocked",
		insert_after="custom_payment_status",
		**_STAMP,
	),
	dict(
		fieldname="custom_payment_process",
		label="Payment Process",
		fieldtype="Data",
		default="Open",
		insert_after="custom_so_eligibility",
		**_STAMP,
	),
	dict(
		fieldname="custom_force_complete_col",
		fieldtype="Column Break",
		insert_after="custom_payment_process",
	),
	dict(
		fieldname="custom_force_complete_applied",
		label="Force Complete Applied",
		fieldtype="Check",
		default="0",
		insert_after="custom_force_complete_col",
		in_standard_filter=1,
		**_STAMP,
	),
	dict(
		fieldname="custom_force_complete_unpaid",
		label="Unpaid at Force Complete",
		fieldtype="Currency",
		options="currency",
		insert_after="custom_force_complete_applied",
		depends_on="eval:doc.custom_force_complete_applied",
		**_STAMP,
	),
	dict(
		fieldname="custom_force_complete_reason",
		label="Force Complete Reason",
		fieldtype="Small Text",
		insert_after="custom_force_complete_unpaid",
		depends_on="eval:doc.custom_force_complete_applied",
		**_STAMP,
	),
	dict(
		fieldname="custom_force_completed_by",
		label="Force Completed By",
		fieldtype="Link",
		options="User",
		insert_after="custom_force_complete_reason",
		depends_on="eval:doc.custom_force_complete_applied",
		ignore_user_permissions=1,
		**_STAMP,
	),
	dict(
		fieldname="custom_force_completed_role",
		label="Force Completed By Role",
		fieldtype="Data",
		insert_after="custom_force_completed_by",
		depends_on="eval:doc.custom_force_complete_applied",
		**_STAMP,
	),
	dict(
		fieldname="custom_force_completed_on",
		label="Force Completed On",
		fieldtype="Datetime",
		insert_after="custom_force_completed_role",
		depends_on="eval:doc.custom_force_complete_applied",
		**_STAMP,
	),
]

#: The single-payment fields used before Section 5 (Payment Mode Advance / Debit / Partial, one
#: advance amount and one proof). Kept read only for the Quotations that carry them; the patch
#: quotation_payment_v2 moved their Payment Mode to Payment Term. No receipt is made from them.
LEGACY_PAYMENT_FIELDS = [
	dict(
		fieldname="custom_legacy_payment_section",
		label="Earlier Payment Details",
		fieldtype="Section Break",
		insert_after="custom_force_completed_on",
		collapsible=1,
		depends_on="eval:doc.custom_payment_mode || doc.custom_attachment_proof || doc.custom_advance_amount",
	),
	dict(
		fieldname="custom_payment_mode",
		label="Payment Mode (earlier)",
		fieldtype="Select",
		options="\nAdvance\nDebit\nPartial",
		insert_after="custom_legacy_payment_section",
		reqd=0,
		read_only=1,
		no_copy=1,
	),
	dict(
		fieldname="custom_advance_amount",
		label="Advance Amount (earlier)",
		fieldtype="Currency",
		insert_after="custom_payment_mode",
		reqd=0,
		read_only=1,
		no_copy=1,
		depends_on="eval:doc.custom_advance_amount",
		mandatory_depends_on="",
	),
	dict(
		fieldname="custom_attachment_proof",
		label="Attachment (Proof) (earlier)",
		fieldtype="Attach",
		insert_after="custom_advance_amount",
		reqd=0,
		read_only=1,
		no_copy=1,
		depends_on="eval:doc.custom_attachment_proof",
		mandatory_depends_on="",
	),
	dict(
		fieldname="custom_transaction_id",
		label="Transaction ID (earlier)",
		fieldtype="Data",
		insert_after="custom_attachment_proof",
		read_only=1,
		no_copy=1,
		depends_on="eval:doc.custom_transaction_id",
	),
	dict(
		fieldname="custom_remaining_amount",
		label="Remaining Amount (earlier)",
		fieldtype="Currency",
		insert_after="custom_transaction_id",
		read_only=1,
		hidden=1,
		no_copy=1,
	),
]


def setup_quotation_custom_fields():
	_force_quotation_fieldtype_sync()
	_delete_obsolete_quotation_custom_fields()
	# Apply property setters before creating/updating custom fields, otherwise doctype
	# validation can fail (e.g. Quotation.order_type default still being ERPNext's "Sales").
	_setup_quotation_property_setters()

	custom_fields = {
		"Quotation": [
			dict(
				fieldname="custom_resolved_customer",
				label="Resolved Customer",
				fieldtype="Link",
				options="Customer",
				insert_after="party_name",
				hidden=1,
				read_only=1,
			),
			# Offline Sales (alpinos.offline_sales): the Buyer this Quotation belongs to, whichever
			# party type it was raised against, so Buyer assignment can scope it; and that
			# Buyer's Secondary POC, which a Sales Admin's list view filters on.
			dict(
				fieldname="custom_buyer_master",
				label="Buyer Master",
				fieldtype="Link",
				options="Buyer Master",
				insert_after="custom_resolved_customer",
				read_only=1,
				no_copy=1,
				search_index=1,
				ignore_user_permissions=1,
				# the Customer field already names the Buyer on screen
				hidden=1,
			),
			dict(
				fieldname="custom_secondary_poc",
				label="Secondary POC",
				fieldtype="Link",
				options="Employee",
				insert_after="custom_buyer_master",
				hidden=1,
				read_only=1,
				no_copy=1,
				ignore_user_permissions=1,
			),
			# Offline Sales, Section 5, 2.1 (S5-R5, S5-R9): what Convert to Quotation carries over
			# from the Opportunity (alpinos.offline_sales.opportunity.convert_to_quotation).
			dict(
				fieldname="custom_site_name",
				label="Site Name",
				# the Buyer's sites, set on the form (public/js/quotation_offline.js), as on the Opportunity
				fieldtype="Select",
				insert_after="custom_secondary_poc",
				no_copy=1,
			),
			dict(
				fieldname="custom_opportunity_remark",
				label="Opportunity Remark",
				fieldtype="Small Text",
				insert_after="custom_site_name",
				read_only=1,
				no_copy=1,
				depends_on="eval:doc.opportunity && doc.custom_opportunity_remark",
				hidden=1,
			),
			dict(
				fieldname="custom_order_no",
				label="Order No.",
				fieldtype="Data",
				insert_after="order_type",
				read_only=1,
				hidden=1,
				fetch_from="name",
			),
			*OFFLINE_HEADER_FIELDS,
			*REQUEST_FIELDS,
			*TAB_FIELDS,
			dict(
				fieldname="custom_other_details_section",
				label="Other Details",
				fieldtype="Section Break",
				insert_after="items",
			),
			dict(
				fieldname="custom_marketing_freebies",
				label="Marketing Freebies",
				fieldtype="Table",
				options="Sales Order Marketing Freebie",
				insert_after="custom_other_details_section",
			),
			dict(
				fieldname="custom_scheme_item_table",
				label="Scheme Item Table",
				fieldtype="Table",
				options="Sales Order Scheme Item",
				insert_after="custom_marketing_freebies",
				depends_on=None,
				mandatory_depends_on=None,
			),
			dict(
				fieldname="custom_additional_units_damage",
				label="Additional Units - Damage",
				fieldtype="Check",
				insert_after="custom_scheme_item_table",
			),
			dict(
				fieldname="custom_additional_units_damage_items",
				label="Additional Units - Damage Items",
				fieldtype="Table",
				options="Sales Order Additional Units Item",
				insert_after="custom_additional_units_damage",
				depends_on="eval:doc.custom_additional_units_damage",
				mandatory_depends_on="eval:doc.custom_additional_units_damage",
			),
			# Offline Sales, Section 5, 5: the totals after the item tables, in the doc's order
			# (Total, Net Total, Cash Discount %, Cash Discount Amount, Taxes, Grand Total). The
			# figures are the Sales Order engine's (alpinos.offline_sales.quotation.price).
			dict(
				fieldname="custom_total_section",
				label="Cash Discount",
				fieldtype="Section Break",
				insert_after="net_total",
			),
			dict(
				fieldname="custom_cash_discount",
				label="Cash Discount %",
				fieldtype="Percent",
				insert_after="custom_total_section",
				default="0",
			),
			dict(
				fieldname="custom_cash_discount_amount",
				label="Cash Discount Amount",
				fieldtype="Currency",
				options="currency",
				insert_after="custom_cash_discount",
				read_only=1,
			),
			# the breakdown of the old Quotation maths: kept (old print formats read it), hidden
			dict(
				fieldname="custom_sub_total",
				label="Sub Total",
				fieldtype="Currency",
				insert_after="custom_cash_discount_amount",
				read_only=1,
				hidden=1,
			),
			dict(
				fieldname="custom_over_discount",
				label="Over Discount",
				fieldtype="Currency",
				insert_after="custom_sub_total",
				read_only=1,
				hidden=1,
			),
			dict(
				fieldname="custom_additional_discount_total",
				label="Additional Discount",
				fieldtype="Currency",
				insert_after="custom_over_discount",
				read_only=1,
				hidden=1,
			),
			dict(
				fieldname="custom_gst_total",
				label="GST",
				fieldtype="Currency",
				insert_after="custom_additional_discount_total",
				read_only=1,
				hidden=1,
			),
			dict(
				fieldname="custom_total_payable",
				label="Total",
				fieldtype="Currency",
				insert_after="custom_gst_total",
				read_only=1,
				hidden=1,
			),
			*PAYMENT_FIELDS,
			*LEGACY_PAYMENT_FIELDS,
			dict(
				fieldname="custom_activity_tab",
				label="Activity",
				fieldtype="Tab Break",
				insert_after="supplier_quotation",
			),
			dict(
				fieldname="custom_activity_html",
				label="Activity / Audit Trail",
				fieldtype="HTML",
				insert_after="custom_activity_tab",
			),
		],
		"Quotation Item": [
			dict(
				fieldname="custom_remarks",
				label="Remarks",
				fieldtype="Data",
				insert_after="qty",
				description="Mandatory when this quotation qty is less than the Opportunity qty.",
			),
			# Box from Quantity by the Customer Type's rounding (as the Sales Order): may be decimal
			dict(
				fieldname="custom_boxes",
				label="Box",
				fieldtype="Float",
				insert_after="qty",
				reqd=1,
				read_only=1,
				in_list_view=1,
				columns=1,
			),
			# MRP: the Item's applicable MRP; picked from the list when the SKU has several (A-26)
			dict(
				fieldname="custom_mrp",
				label="MRP",
				fieldtype="Currency",
				insert_after="rate",
				reqd=1,
				read_only=1,
				in_list_view=1,
				columns=1,
			),
			# Selling Price (GST included, as on the Sales Order): Buyer Catalog, else MRP less the
			# Flat and Offer Discount; changed by a Sales Manager / Sales Admin only (S5-R23)
			dict(
				fieldname="custom_selling_price",
				label="Selling Price",
				fieldtype="Currency",
				insert_after="custom_mrp",
				in_list_view=1,
				columns=1,
			),
			dict(
				fieldname="custom_buyer_margin_percent",
				label="Buyer Margin %",
				fieldtype="Percent",
				insert_after="custom_selling_price",
				hidden=1,
				description="Buyer margin applied before Flat / Offer / Additional Discount (same logic as Opportunity).",
			),
			dict(
				fieldname="custom_discount_type",
				label="Discount Type",
				fieldtype="Select",
				options="\nPercentage\nAmount",
				insert_after="custom_buyer_margin_percent",
				default="Percentage",
				reqd=1,
				hidden=1,
			),
			dict(
				fieldname="custom_flat_discount",
				label="Flat Discount %",
				fieldtype="Float",
				insert_after="custom_discount_type",
				reqd=1,
				in_list_view=1,
				columns=1,
			),
			dict(
				fieldname="custom_offer",
				label="Offer Discount %",
				fieldtype="Float",
				insert_after="custom_flat_discount",
				in_list_view=1,
				columns=1,
			),
			dict(
				fieldname="custom_additional_discount_type",
				label="Additional Discount Type",
				fieldtype="Select",
				options="\nPercentage\nAmount",
				insert_after="custom_offer",
				default="Percentage",
				reqd=1,
			),
			dict(
				fieldname="custom_additional_discount",
				label="Additional Discount %",
				fieldtype="Percent",
				insert_after="custom_additional_discount_type",
			),
			dict(
				fieldname="custom_item_tax_percent",
				label="Tax %",
				fieldtype="Percent",
				insert_after="custom_additional_discount",
				fetch_from="item_code.custom_gst_percent",
				reqd=1,
			),
			dict(
				fieldname="custom_item_tax",
				label="Tax",
				fieldtype="Currency",
				insert_after="custom_item_tax_percent",
				read_only=1,
			),
		],
	}

	create_custom_fields(custom_fields, update=True)
	_ensure_quotation_partial_payment_fields_not_always_mandatory()
	_fix_quotation_table_layout()
	frappe.clear_cache(doctype="Quotation")
	frappe.clear_cache(doctype="Quotation Item")
	_setup_offline_field_order()
	_setup_offline_visibility()
	frappe.clear_cache(doctype="Quotation")


def _setup_quotation_property_setters():
	property_setters = [
		dict(
			doctype_or_field="DocField",
			doc_type="Quotation",
			field_name="items",
			property="label",
			value="Order Items",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Quotation",
			field_name="order_type",
			property="label",
			value="Customer Type",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Quotation",
			field_name="party_name",
			property="label",
			value="Customer",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Quotation",
			field_name="customer_address",
			property="label",
			# ERPNext's customer_address is the billing address; Convert to Quotation puts the
			# Opportunity's Billing Address there (Section 5, 2.1 S5-R7)
			value="Billing Address",
			property_type="Data",
		),
		# Section 5, 2.1: set by the system, never typed (Customer Type from the Buyer, the
		# Quotation Date is the creation date, the Opportunity is set by Convert to Quotation)
		*[
			dict(
				doctype_or_field="DocField",
				doc_type="Quotation",
				field_name=fieldname,
				property="read_only",
				value="1",
				property_type="Check",
			)
			for fieldname in ("order_type", "transaction_date", "opportunity")
		],
		# Order Items grid: the commercial columns of 2.2 (SKU, Quantity, Box, MRP, Selling Price,
		# the three discounts, Line Amount); ERPNext's own Rate leaves the grid
		*[
			dict(
				doctype_or_field="DocField",
				doc_type="Quotation Item",
				field_name=fieldname,
				property=prop,
				value=value,
				property_type="Check" if prop == "in_list_view" else "Int",
			)
			for fieldname, prop, value in (
				("item_code", "columns", "1"),
				("item_name", "columns", "1"),
				("qty", "columns", "1"),
				("amount", "columns", "1"),
				("rate", "in_list_view", "0"),
			)
		],
		dict(
			doctype_or_field="DocField",
			doc_type="Quotation",
			field_name="order_type",
			property="options",
			value="Alpino Customer Type",
			property_type="Text",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Quotation",
			field_name="order_type",
			property="fieldtype",
			value="Link",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Quotation",
			field_name="order_type",
			property="reqd",
			value="1",
			property_type="Check",
		),
		# Clear ERPNext's default ("Sales") because it won't exist after we override options.
		dict(
			doctype_or_field="DocField",
			doc_type="Quotation",
			field_name="order_type",
			property="default",
			value="",
			property_type="Text",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Quotation Item",
			field_name="item_code",
			property="label",
			value="SKU",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Quotation Item",
			field_name="item_name",
			property="label",
			value="SKU Name",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Quotation Item",
			field_name="item_name",
			property="in_list_view",
			value="1",
			property_type="Check",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Quotation Item",
			field_name="qty",
			property="label",
			value="Quantity (Units)",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Quotation Item",
			field_name="qty",
			property="precision",
			value="0",
			property_type="Select",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Quotation Item",
			field_name="qty",
			property="non_negative",
			value="1",
			property_type="Check",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Quotation Item",
			field_name="custom_additional_discount_type",
			property="hidden",
			value="1",
			property_type="Check",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Quotation",
			field_name="naming_series",
			property="options",
			value="QTN-2627-.#####",
			property_type="Text",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Quotation",
			field_name="naming_series",
			property="default",
			value="QTN-2627-.#####",
			property_type="Text",
		),

	]

	for ps_data in property_setters:
		existing = frappe.db.exists(
			"Property Setter",
			{
				"doc_type": ps_data["doc_type"],
				"field_name": ps_data.get("field_name"),
				"property": ps_data["property"],
			},
		)
		if existing:
			doc = frappe.get_doc("Property Setter", existing)
			doc.value = ps_data["value"]
			doc.property_type = ps_data["property_type"]
			doc.save(ignore_permissions=True)
		else:
			frappe.get_doc({"doctype": "Property Setter", **ps_data}).insert(ignore_permissions=True)

	frappe.db.commit()


def _ensure_quotation_partial_payment_fields_not_always_mandatory():
	"""mandatory_depends_on is client-side; server only sees Custom Field reqd — keep it 0."""
	for fieldname in ("custom_advance_amount", "custom_attachment_proof"):
		name = frappe.db.get_value("Custom Field", {"dt": "Quotation", "fieldname": fieldname}, "name")
		if not name:
			continue
		if frappe.db.get_value("Custom Field", name, "reqd"):
			frappe.db.set_value("Custom Field", name, "reqd", 0)


def _fix_quotation_table_layout():
	"""Force existing Custom Field rows into the Sales Order Entry sequence."""

	updates = {
		"custom_marketing_freebies": {
			"insert_after": "custom_other_details_section",
			"depends_on": None,
			"mandatory_depends_on": None,
		},
		"custom_scheme_item_table": {
			"insert_after": "custom_marketing_freebies",
			"depends_on": None,
			"mandatory_depends_on": None,
			"options": "Sales Order Scheme Item",
		},
		"custom_additional_units_damage": {
			"insert_after": "custom_scheme_item_table",
			"depends_on": None,
			"mandatory_depends_on": None,
		},
		"custom_additional_units_damage_items": {
			"insert_after": "custom_additional_units_damage",
			"depends_on": "eval:doc.custom_additional_units_damage",
			"mandatory_depends_on": "eval:doc.custom_additional_units_damage",
			"options": "Sales Order Additional Units Item",
		},
		# Section 5, 8: the Payment Section comes after the totals and taxes
		"custom_payment_section": {
			"insert_after": "referral_sales_partner",
			"depends_on": None,
			"mandatory_depends_on": None,
		},
	}

	for fieldname, values in updates.items():
		name = frappe.db.get_value("Custom Field", {"dt": "Quotation", "fieldname": fieldname}, "name")
		if not name:
			continue
		for key, value in values.items():
			frappe.db.set_value("Custom Field", name, key, value)
	frappe.db.commit()


def _delete_obsolete_quotation_custom_fields():
	"""Drop legacy fields that duplicated standard behaviour (safe if missing)."""
	obsolete = [
		("Quotation", "custom_order_type"),
		("Quotation Item", "custom_sku_with_name"),
		("Quotation Item", "custom_item_mrp"),
	]
	for doctype, fieldname in obsolete:
		name = frappe.db.get_value("Custom Field", {"dt": doctype, "fieldname": fieldname}, "name")
		if name:
			frappe.delete_doc("Custom Field", name, force=1, ignore_permissions=True)
	frappe.db.commit()
	print("✅ Quotation: obsolete fields deleted")


def _force_quotation_fieldtype_sync():
	"""Manually sync field types in the database for Quotation to bypass Frappe validation errors."""
	# Box was Int; the Sales Order's rule (Customer Type rounding) can give a decimal Box, and
	# Frappe refuses an Int -> Float change through the Custom Field form.
	# Site Name was Data; a pick-list of the Buyer's sites since the Opportunity is skipped
	site = frappe.db.get_value("Custom Field", {"dt": "Quotation", "fieldname": "custom_site_name"}, ["name", "fieldtype"], as_dict=True)
	if site and site.fieldtype == "Data":
		frappe.db.set_value("Custom Field", site.name, "fieldtype", "Select", update_modified=False)
		frappe.clear_cache(doctype="Quotation")
	boxes = frappe.db.get_value("Custom Field", {"dt": "Quotation Item", "fieldname": "custom_boxes"}, ["name", "fieldtype"], as_dict=True)
	if boxes and boxes.fieldtype == "Int":
		frappe.db.set_value("Custom Field", boxes.name, "fieldtype", "Float", update_modified=False)
		frappe.clear_cache(doctype="Quotation Item")
		frappe.db.updatedb("Quotation Item")
	# Standard field order_type on Quotation (via Property Setter)
	ps_name = frappe.db.get_value("Property Setter", {
		"doc_type": "Quotation",
		"field_name": "order_type",
		"property": "fieldtype"
	}, "name")
	if ps_name:
		frappe.db.set_value("Property Setter", ps_name, "value", "Link", update_modified=False)

	ps_opts = frappe.db.get_value("Property Setter", {
		"doc_type": "Quotation",
		"field_name": "order_type",
		"property": "options"
	}, "name")
	if ps_opts:
		frappe.db.set_value("Property Setter", ps_opts, "value", "Alpino Customer Type", update_modified=False)

	frappe.db.commit()


#: The Quotation shows the document's fields only (Hetvi, 20 Nov 2026: "the fields mentioned in
#: the document has to be the only fields visible"), in tabs like the Opportunity's.
#: Details = Section 5, 5 (header) + the Buyer Order Request fields; Items = 6.1-6.5 (the item
#: tables and the Sales Order-style summary); Payment = 8-16; Activity = 20.
_DETAILS_ORDER = [
	"customer_section",
	"custom_quotation_status", "custom_quotation_source", "custom_buyer_order_request_ref",
	"custom_request_contact_person", "custom_source_display", "party_name", "order_type", "custom_site_name",
	"column_break_7",
	"customer_address", "custom_billing_gstin", "shipping_address_name", "custom_quotation_remarks",
	"column_break1",
	"transaction_date", "custom_responsible_sales_officer", "custom_finalized_by", "custom_finalized_on",
	"custom_linked_sales_order", "custom_cancellation_reason", "custom_cancelled_by", "custom_cancelled_by_role",
	"custom_cancelled_on",
]

#: ERPNext fields (and earlier custom ones) that are not in the document. Hidden only: ERPNext
#: still fills the mandatory ones (Series, Quotation To, Company, currency and price list).
_HIDDEN = [
	"naming_series", "quotation_to", "valid_till", "company", "is_export_with_gst", "amended_from",
	"currency_and_price_list", "scan_barcode", "last_scanned_warehouse", "total_qty", "total_net_weight", "base_total", "base_net_total",
	"taxes_section", "section_break_36", "base_total_taxes_and_charges", "base_grand_total",
	"base_rounding_adjustment", "base_rounded_total", "base_in_words", "rounding_adjustment", "rounded_total",
	"disable_rounded_total", "in_words", "section_break_44", "sec_tax_breakup", "section_gst_breakup",
	"bundle_items_section", "pricing_rule_details", "address_and_contact_tab", "terms_tab", "more_info_tab",
	"custom_legacy_payment_section",
]

#: Section 5 names (5, 6.5, 6.1)
_LABELS = {
	("Quotation", "transaction_date"): "Quotation Date",
	("Quotation", "total"): "Total",
	("Quotation", "net_total"): "Net Total",
	("Quotation", "total_taxes_and_charges"): "Taxes & Charges",
	("Quotation", "grand_total"): "Grand Total",
	("Quotation Item", "amount"): "Line Amount",
	("Quotation", "custom_scheme_item_table"): "Scheme Items",
}

#: 6.1: SKU Code, SKU Name, Quantity, Box, MRP, Selling Price, Flat / Offer / Additional Discount %,
#: Line Amount. Ten columns of one unit each fit the grid.
_GRID = ["item_code", "item_name", "qty", "custom_boxes", "custom_mrp", "custom_selling_price",
	"custom_flat_discount", "custom_offer", "custom_additional_discount", "amount"]


def _setup_offline_visibility():
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	def ps(doctype, fieldname, prop, value, ptype):
		current = frappe.db.get_value(
			"Property Setter", {"doc_type": doctype, "field_name": fieldname, "property": prop}, "value"
		)
		if current != str(value):
			make_property_setter(doctype, fieldname, prop, value, ptype, validate_fields_for_doctype=False)

	meta = frappe.get_meta("Quotation", cached=False)
	for fieldname in _HIDDEN:
		if meta.get_field(fieldname):
			ps("Quotation", fieldname, "hidden", "1", "Check")
	# a new Quotation is always for a Buyer Master (the field is hidden)
	ps("Quotation", "quotation_to", "default", "Buyer Master", "Text")
	for (doctype, fieldname), label in _LABELS.items():
		ps(doctype, fieldname, "label", label, "Data")
	item_meta = frappe.get_meta("Quotation Item", cached=False)
	for fieldname in _GRID:
		if item_meta.get_field(fieldname):
			ps("Quotation Item", fieldname, "in_list_view", "1", "Check")
			ps("Quotation Item", fieldname, "columns", "1", "Int")
	# committed here: a later after_migrate step that rolls back must not take these with it
	frappe.db.commit()
	frappe.clear_cache(doctype="Quotation")


def _setup_offline_field_order():
	"""Details (the header), then Items (from the item section to the Payment tab), Payment,
	ERPNext's hidden tabs, and the Activity tab before Connections."""
	import json

	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	frappe.db.delete("Property Setter", {"doc_type": "Quotation", "property": "field_order", "field_name": ("is", "not set")})
	frappe.clear_cache(doctype="Quotation")
	current = [df.fieldname for df in frappe.get_meta("Quotation", cached=False).fields]
	head = [f for f in _DETAILS_ORDER if f in current]
	end_of_header = current.index("currency_and_price_list")
	# header fields not named above stay in the header, after it (they are hidden or system)
	head += [f for f in current[:end_of_header] if f not in head]
	rest = [f for f in current[end_of_header:] if f not in head]
	for tab, before in (("custom_items_tab", "items_section"), ("custom_payment_tab", "custom_payment_section")):
		if tab in rest and before in rest:
			rest.remove(tab)
			rest.insert(rest.index(before), tab)
	tail = [f for f in ("custom_activity_tab", "custom_activity_html") if f in rest]
	rest = [f for f in rest if f not in tail]
	at = rest.index("connections_tab") if "connections_tab" in rest else len(rest)
	rest[at:at] = tail
	make_property_setter(
		"Quotation", None, "field_order", json.dumps(head + rest), "Data", for_doctype=True, validate_fields_for_doctype=False
	)
	frappe.db.commit()
