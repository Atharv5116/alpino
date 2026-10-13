"""Fill Total Invoice Value on orders picked or dispatched before it was maintained.

Changes(HP) #42: the Order Fulfilment Report showed Invoice Amount 0 on those orders.
The report now reads submitted Delivery Notes live, but the stored value is still what
the Sales Order screens and a not-yet-dispatched order show, so it is filled once here
with the same rule the hooks use (alpinos.so_invoice_value.backfill). Only that derived
field is written, without touching the order's modified time.

Patches run before after_migrate creates the Sales Order custom fields, so on a site that
never had Total Invoice Value the field is created here first; after_migrate then keeps it
in step with alpinos.sales_order_custom_fields as usual.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from alpinos.so_invoice_value import backfill


def execute():
	if not frappe.db.has_column("Sales Order", "custom_total_invoice_value"):
		create_custom_fields(
			{
				"Sales Order": [
					dict(
						fieldname="custom_total_invoice_value",
						label="Total Invoice Value",
						fieldtype="Currency",
						insert_after="custom_invoice_no",
						read_only=1,
						description="Total of the dispatched (picked) products including GST — the sum of this order's Delivery Notes. Blank until something is dispatched.",
					)
				]
			},
			update=True,
		)
	backfill(apply=1)
