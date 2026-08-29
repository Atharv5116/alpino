"""E-Com Sales Order custom fields + Channel setup."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

CHANNEL_OFFLINE = "Offline"
CHANNEL_ECOM = "E-com"

# The offline customer type that also gets the e-com extra fields.
MODERN_TRADE_TYPE = "MODERN TRADE"

ECOM_ROLES = ("E-Commerce Coordinator", "E-Commerce Manager", "E-Commerce Admin")

# Section shows for E-com orders or any order carrying the e-com flags (MT + Offline).
_ECOM_SECTION_DEPENDS = (
	"eval:doc.custom_channel=='E-com'"
	" || doc.custom_appointment_required || doc.custom_grn_available"
	" || doc.custom_partial_order_allowed || doc.custom_gst_exclusive_buyer"
)


def is_modern_trade(customer_type) -> bool:
	return (customer_type or "").strip().lower() == MODERN_TRADE_TYPE.lower()


def setup_ecom_sales_order_fields():
	_seed_channels()
	_seed_ecom_roles()

	custom_fields = {
		"Sales Order": [
			# Channel discriminator (Offline / E-com)
			dict(
				fieldname="custom_channel",
				label="Channel",
				fieldtype="Link",
				options="Channel",
				insert_after="naming_series",
				read_only=1,
				in_standard_filter=1,
				# Default so raw-form / API / import orders are never channel-less.
				default="Offline",
				description="Offline or E-com. Set automatically by the entry page used.",
			),
			# E-Commerce / MT classification (flags mirror Buyer Master)
			dict(
				fieldname="custom_ecom_section",
				label="E-Commerce Details",
				fieldtype="Section Break",
				insert_after="custom_offline_buyer_customer_type",
				depends_on=_ECOM_SECTION_DEPENDS,
				collapsible=0,
			),
			dict(
				fieldname="custom_appointment_required",
				label="Appointment Required",
				fieldtype="Check",
				insert_after="custom_ecom_section",
				description="Auto-filled from Buyer Master; controls Post Dispatch visibility.",
			),
			dict(
				fieldname="custom_grn_available",
				label="GRN Available",
				fieldtype="Check",
				insert_after="custom_appointment_required",
				description="Auto-filled from Buyer Master; controls GRN section visibility.",
			),
			dict(
				fieldname="custom_ecom_col_1",
				fieldtype="Column Break",
				insert_after="custom_grn_available",
			),
			dict(
				fieldname="custom_partial_order_allowed",
				label="Partial Order Allowed",
				fieldtype="Check",
				insert_after="custom_ecom_col_1",
				description="Auto-filled from Buyer Master; enables the Partial option at PL submission.",
			),
			dict(
				fieldname="custom_gst_exclusive_buyer",
				label="GST-Exclusive Buyer",
				fieldtype="Check",
				insert_after="custom_partial_order_allowed",
				description="Auto-filled from Buyer Master. If Yes: Final = PO Price + GST.",
			),
			# PO details
			dict(
				fieldname="custom_po_number",
				label="PO Number",
				fieldtype="Data",
				insert_after="custom_po_expiry_date",
				description="Customer PO number. Unique per customer (e-com / MT).",
			),
			dict(
				fieldname="custom_po_date",
				label="PO Date",
				fieldtype="Date",
				insert_after="custom_po_number",
				description="Customer PO date. Cannot be a future date.",
			),
			dict(
				fieldname="custom_delivery_by_date",
				label="Delivery By Date",
				fieldtype="Date",
				insert_after="custom_po_date",
				description="Target delivery / GRN date.",
			),
			# Address / GSTIN (e-com)
			dict(
				fieldname="custom_billing_gstin",
				label="Billing GSTIN",
				fieldtype="Data",
				insert_after="custom_site_name",
				length=15,
			),
			dict(
				fieldname="custom_shipping_gstin",
				label="Shipping GSTIN",
				fieldtype="Data",
				insert_after="custom_billing_gstin",
				length=15,
			),
			dict(
				fieldname="custom_billing_address_text",
				label="Billing Address",
				fieldtype="Small Text",
				insert_after="custom_shipping_gstin",
			),
			dict(
				fieldname="custom_shipping_address_text",
				label="Shipping Address",
				fieldtype="Small Text",
				insert_after="custom_billing_address_text",
			),
			# Freebies (entire PO free)
			dict(
				fieldname="custom_is_freebie_po",
				label="Freebies (Entire PO Free)",
				fieldtype="Check",
				insert_after="custom_additional_units_damage_items",
				description="If checked, the whole PO is a freebie order; Order Items table is hidden and free items go in Marketing Freebies.",
			),
			# Sticker attachments (E-com & MT orders)
			dict(
				fieldname="custom_sticker_attachments",
				label="Sticker Attachments",
				fieldtype="Table",
				options="Sales Order Sticker Attachment",
				insert_after="custom_is_freebie_po",
				depends_on=_ECOM_SECTION_DEPENDS,
				description="Sticker artwork/files for this E-com or Modern Trade order; shown on the Pick List.",
			),
		],
		"Sales Order Item": [
			dict(
				fieldname="custom_margin_percent",
				label="Margin %",
				fieldtype="Percent",
				insert_after="custom_customer_mrp",
				description="0–90. Selling Price = MRP × (1 − Margin%/100).",
			),
		],
	}

	create_custom_fields(custom_fields, update=True)
	print("✅ E-Com Sales Order custom fields created")

	_backfill_offline_channel()
	print("✅ E-Com Sales Order setup complete")


def _seed_ecom_roles():
	for role in ECOM_ROLES:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({
				"doctype": "Role",
				"role_name": role,
				"desk_access": 1,
			}).insert(ignore_permissions=True)
	frappe.db.commit()
	print("✅ E-Commerce roles ensured: " + ", ".join(ECOM_ROLES))


def _seed_channels():
	for name in (CHANNEL_OFFLINE, CHANNEL_ECOM):
		if not frappe.db.exists("Channel", name):
			frappe.get_doc({"doctype": "Channel", "channel_name": name}).insert(
				ignore_permissions=True
			)
	frappe.db.commit()
	print("✅ Channel records ensured: Offline, E-com")


def _backfill_offline_channel():
	# Pre-existing Sales Orders belong to the offline channel.
	frappe.db.sql(
		"UPDATE `tabSales Order` SET custom_channel=%s WHERE IFNULL(custom_channel,'')=''",
		(CHANNEL_OFFLINE,),
	)
	frappe.db.commit()
	print("✅ Existing Sales Orders backfilled to channel = Offline")
