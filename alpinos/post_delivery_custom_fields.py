"""
Post Delivery — reflect fields on Delivery Note + Sales Order.

The Post Delivery doc (one per DN) mirrors its status onto the linked Delivery Note
and Sales Order via these read-only fields (written with db.set_value since both are
submitted). Run on after_migrate, after the e-com and DN custom-field setups.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def setup_post_delivery_fields():
	custom_fields = {
		"Delivery Note": [
			dict(
				fieldname="custom_post_delivery_section",
				label="Post Delivery",
				fieldtype="Section Break",
				insert_after="custom_lr_gr_no",
				collapsible=1,
				depends_on="eval:doc.custom_post_delivery",
			),
			dict(
				fieldname="custom_post_delivery",
				label="Post Delivery",
				fieldtype="Link",
				options="Post Delivery",
				insert_after="custom_post_delivery_section",
				read_only=1,
				allow_on_submit=1,
			),
			dict(
				fieldname="custom_post_delivery_status",
				label="Post Delivery Status",
				fieldtype="Data",
				insert_after="custom_post_delivery",
				read_only=1,
				allow_on_submit=1,
			),
			dict(
				fieldname="custom_pd_col",
				fieldtype="Column Break",
				insert_after="custom_post_delivery_status",
			),
			dict(
				fieldname="custom_asn_status",
				label="ASN Status",
				fieldtype="Data",
				insert_after="custom_pd_col",
				read_only=1,
				allow_on_submit=1,
			),
			dict(
				fieldname="custom_grn_status",
				label="GRN Status",
				fieldtype="Data",
				insert_after="custom_asn_status",
				read_only=1,
				allow_on_submit=1,
			),
			dict(
				fieldname="custom_appointment_status",
				label="Appointment Status",
				fieldtype="Data",
				insert_after="custom_grn_status",
				read_only=1,
				allow_on_submit=1,
			),
		],
		"Sales Order": [
			dict(
				fieldname="custom_post_delivery_section",
				label="Post Delivery",
				fieldtype="Section Break",
				insert_after="custom_gst_exclusive_buyer",
				collapsible=1,
				depends_on="eval:doc.custom_appointment_required || doc.custom_post_delivery_status",
			),
			dict(
				fieldname="custom_post_delivery_status",
				label="Post Delivery Status",
				fieldtype="Select",
				options="\nNot Started\nIn Progress\nCompleted",
				insert_after="custom_post_delivery_section",
				read_only=1,
				allow_on_submit=1,
				in_standard_filter=1,
			),
			dict(
				fieldname="custom_asn_status",
				label="ASN Status",
				fieldtype="Data",
				insert_after="custom_post_delivery_status",
				read_only=1,
				allow_on_submit=1,
			),
			dict(
				fieldname="custom_pd_col",
				fieldtype="Column Break",
				insert_after="custom_asn_status",
			),
			dict(
				fieldname="custom_grn_status",
				label="GRN Status",
				fieldtype="Data",
				insert_after="custom_pd_col",
				read_only=1,
				allow_on_submit=1,
			),
			dict(
				fieldname="custom_fill_rate",
				label="Fill Rate (%)",
				fieldtype="Percent",
				insert_after="custom_grn_status",
				read_only=1,
				allow_on_submit=1,
			),
		],
	}
	create_custom_fields(custom_fields, update=True)
	print("✅ Post Delivery reflect fields created on Delivery Note + Sales Order")

	_grant_post_delivery_role_perms()


def _grant_post_delivery_role_perms():
	"""Grant the E-Commerce roles access to Post Delivery in code (the roles are
	seeded in after_migrate, so they can't be referenced in the doctype JSON perms
	which sync earlier). Idempotent."""
	from frappe.permissions import add_permission, update_permission_property

	if not frappe.db.exists("DocType", "Post Delivery"):
		return

	grants = {
		"E-Commerce Admin": {"read": 1, "write": 1, "create": 1, "delete": 1, "report": 1, "print": 1, "share": 1, "email": 1, "export": 1},
		"E-Commerce Manager": {"read": 1, "write": 1, "create": 1, "delete": 1, "report": 1, "print": 1, "share": 1},
		"E-Commerce Coordinator": {"read": 1, "write": 1, "create": 1, "report": 1, "print": 1},
	}
	for role, props in grants.items():
		if not frappe.db.exists("Role", role):
			continue
		if not frappe.db.exists("Custom DocPerm", {"parent": "Post Delivery", "role": role, "permlevel": 0}):
			add_permission("Post Delivery", role, 0)
		for prop, val in props.items():
			update_permission_property("Post Delivery", role, 0, prop, val, validate=False)
	frappe.db.commit()
	print("✅ Post Delivery permissions granted to E-Commerce roles")
