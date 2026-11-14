"""Opportunity customization for Alpinos: Property Setters for existing fields, Custom Fields for new ones."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


#: Offline Sales, Section 3 ("Opportunity to Sales Order v1.0.0"): the header fields of 3.1 and
#: the status model of 6.1. Every value here is set by the server (alpinos.offline_sales.
#: opportunity) except Site Name and Common Remark; the Buyer Order Request portal
#: (alpinos.offline_sales.order_link) fills Source, the BOR reference and the contact.
OFFLINE_HEADER_FIELDS = [
	dict(
		fieldname="custom_opportunity_status",
		label="Opportunity Status",
		fieldtype="Select",
		options="Pending (Draft)\nPending (Submitted)\nConverted to Quotation\nWon\nPartial\nHold\nLost\nCancelled",
		default="Pending (Draft)",
		insert_after="naming_series",
		read_only=1,
		no_copy=1,
		in_standard_filter=1,
		search_index=1,
	),
	dict(
		fieldname="custom_opportunity_source",
		label="Opportunity Source",
		fieldtype="Select",
		options="Direct Opportunity\nBuyer Order Request Form",
		default="Direct Opportunity",
		insert_after="custom_opportunity_status",
		read_only=1,
		no_copy=1,
		in_standard_filter=1,
	),
	dict(
		fieldname="custom_buyer_order_request_ref",
		label="Buyer Order Request Ref",
		fieldtype="Data",
		insert_after="custom_opportunity_source",
		read_only=1,
		no_copy=1,
		search_index=1,
		depends_on="eval:doc.custom_buyer_order_request_ref",
	),
	dict(
		fieldname="custom_request_contact_person",
		label="Request Contact Person",
		fieldtype="Data",
		insert_after="custom_buyer_order_request_ref",
		read_only=1,
		no_copy=1,
		depends_on="eval:doc.custom_request_contact_person",
	),
	dict(
		fieldname="custom_source_display",
		label="Submitted Through",
		fieldtype="Data",
		insert_after="custom_request_contact_person",
		read_only=1,
		no_copy=1,
		depends_on="eval:doc.custom_source_display",
	),
	dict(
		fieldname="custom_site_name",
		label="Site Name",
		# a Select whose choices are the Buyer's sites, filled on the form (Dynamic Select, 3.1 #6)
		fieldtype="Select",
		options="",
		insert_after="custom_order_type",
	),
	dict(
		fieldname="custom_common_remark",
		label="Common Remark",
		fieldtype="Small Text",
		insert_after="customer_address",
	),
	dict(
		fieldname="custom_status_reason",
		label="Status Reason",
		fieldtype="Small Text",
		insert_after="custom_common_remark",
		read_only=1,
		no_copy=1,
		depends_on="eval:doc.custom_status_reason",
	),
	dict(
		fieldname="custom_status_before_hold",
		label="Status Before Hold",
		fieldtype="Data",
		insert_after="custom_status_reason",
		read_only=1,
		hidden=1,
		no_copy=1,
	),
	dict(
		fieldname="custom_created_by",
		label="Created By",
		fieldtype="Link",
		options="User",
		insert_after="column_break_10",
		read_only=1,
		no_copy=1,
		ignore_user_permissions=1,
	),
	dict(
		fieldname="custom_created_on",
		label="Created On",
		fieldtype="Datetime",
		insert_after="custom_created_by",
		read_only=1,
		no_copy=1,
	),
	dict(
		fieldname="custom_submitted_by",
		label="Submitted By",
		fieldtype="Link",
		options="User",
		insert_after="custom_created_on",
		read_only=1,
		no_copy=1,
		ignore_user_permissions=1,
	),
	dict(
		fieldname="custom_submitted_on",
		label="Submitted On",
		fieldtype="Datetime",
		insert_after="custom_submitted_by",
		read_only=1,
		no_copy=1,
	),
	dict(
		fieldname="custom_linked_quotation",
		label="Linked Quotation ID",
		fieldtype="Link",
		options="Quotation",
		insert_after="custom_submitted_on",
		read_only=1,
		no_copy=1,
		ignore_user_permissions=1,
	),
	# the Buyer's Secondary POC, for a Sales Admin's list default (as on the Quotation)
	dict(
		fieldname="custom_secondary_poc",
		label="Secondary POC",
		fieldtype="Link",
		options="Employee",
		insert_after="custom_linked_quotation",
		read_only=1,
		hidden=1,
		no_copy=1,
		ignore_user_permissions=1,
	),
	dict(
		fieldname="custom_buyer_section",
		label="Buyer Status & Assignments",
		fieldtype="Section Break",
		insert_after="custom_secondary_poc",
		depends_on="eval:doc.opportunity_from === 'Buyer Master' && doc.party_name",
		collapsible=0,
	),
	dict(
		fieldname="custom_buyer_info_html",
		label="Buyer",
		fieldtype="HTML",
		insert_after="custom_buyer_section",
	),
	dict(
		fieldname="custom_activity_tab",
		label="Activity",
		fieldtype="Tab Break",
		insert_after="notes",
	),
	dict(
		fieldname="custom_activity_html",
		label="Activity / Audit Trail",
		fieldtype="HTML",
		insert_after="custom_activity_tab",
	),
]

#: The header as Section 3, 3.1 lists it. ERPNext places customer_address (relabelled Shipping
#: Address) in its Contacts tab, which is hidden for a Buyer Master Opportunity, and a property
#: setter's insert_after does not move a standard field, so the order is set with field_order.
_HEADER_ORDER = [
	"naming_series",
	"custom_opportunity_status",
	"custom_opportunity_source",
	"custom_buyer_order_request_ref",
	"custom_request_contact_person",
	"custom_source_display",
	"opportunity_from",
	"party_name",
	"custom_order_type",
	"custom_site_name",
	"customer_name",
	"status",
	"column_break0",
	"custom_billing_address",
	"customer_address",
	"custom_common_remark",
	"custom_status_reason",
	"custom_status_before_hold",
	"column_break_10",
	"custom_created_by",
	"custom_created_on",
	"custom_submitted_by",
	"custom_submitted_on",
	"custom_linked_quotation",
	"custom_secondary_poc",
	"opportunity_type",
	"opportunity_owner",
	"sales_stage",
	"expected_closing",
	"probability",
	"custom_buyer_section",
	"custom_buyer_info_html",
]


def _setup_offline_field_order():
	import json

	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	frappe.clear_cache(doctype="Opportunity")
	current = [df.fieldname for df in frappe.get_meta("Opportunity", cached=False).fields]
	head = [f for f in _HEADER_ORDER if f in current]
	order = head + [f for f in current if f not in head]
	# the Activity tab goes last, after ERPNext's Comments / Connections tabs
	tail = [f for f in ("custom_activity_tab", "custom_activity_html") if f in order]
	order = [f for f in order if f not in tail] + tail
	existing = frappe.db.get_value(
		"Property Setter", {"doc_type": "Opportunity", "property": "field_order", "field_name": ("is", "not set")}, "value"
	)
	if existing and json.loads(existing) == order:
		return
	make_property_setter(
		"Opportunity", None, "field_order", json.dumps(order), "Data", for_doctype=True, validate_fields_for_doctype=False
	)


def setup_opportunity_custom_fields():
	_force_opportunity_fieldtype_sync()
	_delete_obsolete_opportunity_custom_fields()
	_cleanup_opportunity_from_property_setters()

	custom_fields = {
		"Opportunity": [
			*OFFLINE_HEADER_FIELDS,
			dict(
				fieldname="custom_order_type",
				label="Customer Type",
				fieldtype="Link",
				options="Alpino Customer Type",
				insert_after="party_name",
				reqd=1,
				# Offline Sales, Section 3, 3.1: auto-fetched from the Buyer, never typed
				read_only=1,
			),
		dict(
			fieldname="custom_billing_address",
			label="Billing Address",
			fieldtype="Link",
			options="Address",
			insert_after="custom_order_type",
			depends_on="eval:doc.opportunity_from === 'Buyer Master'",
			mandatory_depends_on="eval:doc.opportunity_from === 'Buyer Master'",
		),
		dict(
			fieldname="custom_other_details_section",
			label="Other Details",
			fieldtype="Section Break",
			insert_after="items",
		),
		dict(
			fieldname="custom_details_tab",
			label="Details",
			fieldtype="Tab Break",
			insert_after="transaction_date",
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
			label="Scheme Items",
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
			label="Additional Unit / Damage Items",
			fieldtype="Table",
			options="Sales Order Additional Units Item",
			insert_after="custom_additional_units_damage",
			depends_on="eval:doc.custom_additional_units_damage",
			mandatory_depends_on="eval:doc.custom_additional_units_damage",
		),
		# Section 3 has no cash discount on the Opportunity (it starts on the Quotation): kept
		# at 0 and out of sight
		dict(
			fieldname="custom_cash_discount",
			label="Cash Discount (%)",
			fieldtype="Percent",
			insert_after="total",
			default="0",
			hidden=1,
			read_only=1,
		),
		dict(
			fieldname="custom_over_discount",
			label="Over Discount",
			fieldtype="Currency",
			insert_after="custom_cash_discount",
			read_only=1,
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
		),
		],
		"Opportunity Item": [
			# Section 3, 3.2: the commercial values are the Buyer Catalog's, recomputed on the
			# server on every Draft save (alpinos.offline_sales.opportunity); only SKU, Quantity
			# and Row Remark are typed.
			dict(
				fieldname="custom_boxes",
				label="Box",
				fieldtype="Float",
				insert_after="qty",
				read_only=1,
				in_list_view=1,
				columns=1,
			),
			dict(
				fieldname="custom_mrp",
				label="MRP",
				fieldtype="Currency",
				insert_after="rate",
				read_only=1,
				in_list_view=1,
				columns=1,
			),
			dict(
				fieldname="custom_selling_price",
				label="Selling Price",
				fieldtype="Currency",
				insert_after="custom_mrp",
				read_only=1,
				in_list_view=1,
				columns=1,
			),
			dict(
				fieldname="custom_buyer_margin_percent",
				label="Buyer Margin %",
				fieldtype="Percent",
				insert_after="custom_selling_price",
				read_only=1,
				hidden=1,
				description="From Buyer Master / catalog when applicable; applied before Flat % / Offer / Additional Discount.",
			),
			dict(
				fieldname="custom_flat_discount",
				label="Flat Discount %",
				fieldtype="Percent",
				insert_after="custom_buyer_margin_percent",
				read_only=1,
				in_list_view=1,
				columns=1,
			),
			dict(
				fieldname="custom_offer",
				label="Offer Discount %",
				fieldtype="Data",
				insert_after="custom_flat_discount",
				read_only=1,
			),
			dict(
				fieldname="custom_additional_discount",
				label="Additional Disc.%",
				fieldtype="Percent",
				insert_after="custom_offer",
				read_only=1,
			),
			dict(
				fieldname="custom_line_amount",
				label="Line Amount",
				fieldtype="Currency",
				insert_after="custom_additional_discount",
				read_only=1,
				in_list_view=1,
				columns=1,
			),
			dict(
				fieldname="custom_row_remark",
				label="Row Remark",
				fieldtype="Data",
				insert_after="custom_line_amount",
			),
			dict(
				fieldname="custom_item_tax",
				label="Tax",
				fieldtype="Currency",
				insert_after="custom_row_remark",
				read_only=1,
			),
		],
	}

	create_custom_fields(custom_fields, update=True)
	_clear_opportunity_stale_defaults()
	_setup_opportunity_property_setters()
	frappe.clear_cache(doctype="Opportunity")
	frappe.clear_cache(doctype="Opportunity Item")
	_setup_offline_field_order()
	frappe.clear_cache(doctype="Opportunity")


def _cleanup_opportunity_from_property_setters():
	"""Remove bad overrides: opportunity_from is Link -> DocType; options must stay 'DocType'."""
	for prop in ("options", "default"):
		frappe.db.delete(
			"Property Setter",
			{
				"doc_type": "Opportunity",
				"field_name": "opportunity_from",
				"property": prop,
			},
		)


def _clear_opportunity_stale_defaults():
	"""Clear defaults that used to have wrong values."""
	frappe.db.set_value(
		"Custom Field",
		{"dt": "Opportunity", "fieldname": "custom_cash_discount"},
		"default",
		"0",
	)


def _setup_opportunity_property_setters():
	property_setters = [
		# Existing fields adjusted via property setter
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity",
			field_name="party_name",
			property="label",
			value="Customer",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity",
			field_name="party_name",
			property="reqd",
			value="1",
			property_type="Check",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity",
			field_name="job_title",
			property="hidden",
			value="1",
			property_type="Check",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity",
			field_name="items_section",
			property="insert_after",
			value="custom_details_tab",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity",
			field_name="more_info",
			property="insert_after",
			value="items",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity",
			field_name="transaction_date",
			property="label",
			value="Date",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity",
			field_name="customer_address",
			property="label",
			value="Shipping Address",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity",
			field_name="customer_address",
			property="hidden",
			value="0",
			property_type="Check",
		),
		# Move Shipping Address to header (before items tab) - visible only for OBM
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity",
			field_name="customer_address",
			property="insert_after",
			value="custom_billing_address",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity",
			field_name="customer_address",
			property="depends_on",
			value="eval:doc.opportunity_from === 'Buyer Master'",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity",
			field_name="more_info",
			property="insert_after",
			value="items",
			property_type="Data",
		),
		# Hide the empty 'Details' tab when OBM is selected
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity",
			field_name="custom_details_tab",
			property="depends_on",
			value="eval:doc.opportunity_from !== 'Buyer Master'",
			property_type="Data",
		),
		# Hide the 'Contacts' tab when OBM is selected
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity",
			field_name="contact_info",
			property="depends_on",
			value="eval:doc.opportunity_from !== 'Buyer Master'",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity Item",
			field_name="item_code",
			property="label",
			value="SKU",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity Item",
			field_name="item_name",
			property="label",
			value="SKU Name",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity Item",
			field_name="item_name",
			property="in_list_view",
			value="1",
			property_type="Check",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity Item",
			field_name="qty",
			property="label",
			value="Quantity (Units)",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity Item",
			field_name="qty",
			property="precision",
			value="0",
			property_type="Select",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity Item",
			field_name="qty",
			property="non_negative",
			value="1",
			property_type="Check",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity",
			field_name="naming_series",
			property="options",
			value="OPP-2627-.#####",
			property_type="Text",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity",
			field_name="naming_series",
			property="default",
			value="OPP-2627-.#####",
			property_type="Text",
		),
		# Offline Sales, Section 3: the party is always a Buyer Master ("Customer"); an old
		# Customer / Lead Opportunity keeps what it has.
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity",
			field_name="opportunity_from",
			property="default",
			value="Buyer Master",
			property_type="Data",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity",
			field_name="opportunity_from",
			property="read_only",
			value="1",
			property_type="Check",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity",
			field_name="customer_address",
			property="mandatory_depends_on",
			value="eval:doc.opportunity_from === 'Buyer Master'",
			property_type="Data",
		),
		# ERPNext's own status (Open / Quotation / Lost ...) is replaced by Opportunity Status
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity",
			field_name="status",
			property="hidden",
			value="1",
			property_type="Check",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity",
			field_name="total",
			property="label",
			value="Total Amount",
			property_type="Data",
		),
		# 3.2: Line Amount (Quantity x Selling Price) replaces ERPNext's ex-GST Rate / Amount on
		# the grid; they stay filled for ERPNext, out of sight
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity Item",
			field_name="rate",
			property="in_list_view",
			value="0",
			property_type="Check",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity Item",
			field_name="rate",
			property="reqd",
			value="0",
			property_type="Check",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity Item",
			field_name="rate",
			property="read_only",
			value="1",
			property_type="Check",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity Item",
			field_name="rate",
			property="hidden",
			value="1",
			property_type="Check",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity Item",
			field_name="amount",
			property="in_list_view",
			value="0",
			property_type="Check",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity Item",
			field_name="amount",
			property="hidden",
			value="1",
			property_type="Check",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity Item",
			field_name="item_name",
			property="read_only",
			value="1",
			property_type="Check",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity Item",
			field_name="item_code",
			property="columns",
			value="2",
			property_type="Int",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity Item",
			field_name="item_name",
			property="columns",
			value="2",
			property_type="Int",
		),
		dict(
			doctype_or_field="DocField",
			doc_type="Opportunity Item",
			field_name="qty",
			property="columns",
			value="1",
			property_type="Int",
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


def _delete_obsolete_opportunity_custom_fields():
	"""Drop legacy fields that duplicated standard behaviour (safe if missing)."""
	obsolete = [
		("Opportunity Item", "custom_sku_with_name"),
		("Opportunity Item", "custom_item_mrp"),
	]
	for doctype, fieldname in obsolete:
		name = frappe.db.get_value("Custom Field", {"dt": doctype, "fieldname": fieldname}, "name")
		if name:
			frappe.delete_doc("Custom Field", name, force=1, ignore_permissions=True)
	frappe.db.commit()
	print("✅ Opportunity: obsolete fields deleted")


def _force_opportunity_fieldtype_sync():
	"""Manually sync field types in the database for Opportunity to bypass Frappe validation errors."""
	# Custom field custom_order_type on Opportunity
	cf_name = frappe.db.get_value("Custom Field", {"dt": "Opportunity", "fieldname": "custom_order_type"}, "name")
	if cf_name:
		frappe.db.set_value("Custom Field", cf_name, {
			"fieldtype": "Link",
			"options": "Alpino Customer Type"
		}, update_modified=False)
	frappe.db.commit()

