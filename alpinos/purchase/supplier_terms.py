"""Vendor-wise instructions / terms and conditions (purchase notes 26 Nov 2026, point 3).

A table on the Supplier master, one row per instruction. The Purchase Order print lists the
supplier's own rows under the company's terms, so each vendor's PO carries its instructions.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def setup_supplier_terms_fields():
	create_custom_fields(
		{
			"Supplier": [
				dict(
					fieldname="custom_instructions_section",
					label="Instructions / Terms & Conditions",
					fieldtype="Section Break",
					insert_after="supplier_details",
					collapsible=1,
				),
				dict(
					fieldname="custom_supplier_instructions",
					label="Instructions / Terms & Conditions",
					fieldtype="Table",
					options="Supplier Instruction",
					insert_after="custom_instructions_section",
					description="Printed on every Purchase Order for this supplier, under the company's terms.",
				),
			]
		},
		ignore_validate=True,
		update=True,
	)
	frappe.db.commit()


def supplier_instructions(supplier):
	"""The supplier's instructions in their order, for the PO print."""
	if not supplier:
		return []
	return frappe.get_all(
		"Supplier Instruction",
		filters={"parenttype": "Supplier", "parent": supplier, "parentfield": "custom_supplier_instructions"},
		pluck="instruction",
		order_by="idx asc",
	)
