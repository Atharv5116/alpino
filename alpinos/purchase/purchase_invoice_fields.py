"""Custom fields on Purchase Invoice — BRD 6 "Purchase Invoice & Payment".

WHY CUSTOM FIELDS ON ERPNEXT'S PURCHASE INVOICE, NOT A NEW DOCTYPE
------------------------------------------------------------------
BRD 6 describes a "unified Invoice document" carrying the supplier bill, the item lines,
an optional logistics bill and the payment history. All of that except the last two is
already Purchase Invoice: supplier, items, amounts, taxes, the accounting entry, and the
`items[].purchase_receipt` link back to the GRN. Rebuilding it as a bespoke doctype would
mean re-implementing tax handling and the GL posting, and would leave Accounts with a
document Tally reconciliation and every standard report cannot see.

So the BRD's sections map on as:

    6.1.1 Header            -> the standard header + the link/attachment fields here
    6.1.3 Item Details      -> the standard `items` table, mapped from the GRN
    6.1.4 Logistics bill    -> the logistics block here (optional, gated on a checkbox)
    6.1.5 Payment reference -> `custom_payment_references`, a Purchase Payment Reference table
    6.4   BR-UNF-04         -> the two derived pending amounts here

WHY A SEPARATE STATUS FIELD
---------------------------
ERPNext's own `status` on Purchase Invoice is Draft / Unpaid / Overdue / Paid / Return /
Cancelled, derived from `outstanding_amount` on the ledger. BRD 6.2 wants Draft / Pending
Payment / Partially Paid / Completed / Cancelled, derived from what Accounts has recorded
in Tally -- which is a different fact from what the ledger says, and deliberately so: the
BRD's flow records payments made OUTSIDE this system. Overloading the standard field
would put two incompatible meanings on one column, exactly the collision the Purchase
Order approval block avoided by keeping `custom_approval_status` separate.
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

from alpinos.purchase import constants as C

PI = "Purchase Invoice"

STATUS_FIELD = "custom_unified_status"
TYPE_FIELD = "custom_invoice_type"

_STATUS_OPTIONS = "\n".join(C.UNF_STATUSES)
_TYPE_OPTIONS = "\n".join(C.UNF_TYPES)

_DIRECT_DESCRIPTION = (
	"BRD 6.0. A Direct Purchase Invoice is raised straight from an approved Purchase "
	"Order and skips Purchase Inward, QC and GRN, so it carries no GRN or Inward link."
)


def _custom_fields():
	return {
		PI: [
			# ---------------------------------------------------- 6.1.1 header
			dict(
				fieldname="custom_purchase_chain_section",
				label="Purchase Inward Chain",
				fieldtype="Section Break",
				insert_after="supplier_name",
				collapsible=0,
			),
			dict(
				fieldname=TYPE_FIELD,
				label="Invoice Type",
				fieldtype="Select",
				options=_TYPE_OPTIONS,
				default=C.UNF_TYPE_NORMAL,
				insert_after="custom_purchase_chain_section",
				read_only=1,
				no_copy=1,
				in_standard_filter=1,
				description=_DIRECT_DESCRIPTION,
			),
			dict(
				fieldname="custom_purchase_inward",
				label="Purchase Inward",
				fieldtype="Link",
				options="Purchase Inward",
				insert_after=TYPE_FIELD,
				read_only=1,
				no_copy=1,
				in_standard_filter=1,
			),
			dict(
				fieldname="custom_grn",
				label="GRN",
				fieldtype="Link",
				options="Purchase Receipt",
				insert_after="custom_purchase_inward",
				read_only=1,
				no_copy=1,
			),
			dict(
				fieldname="custom_chain_col_1",
				fieldtype="Column Break",
				insert_after="custom_grn",
			),
			dict(
				fieldname=STATUS_FIELD,
				label="Invoice & Payment Status",
				fieldtype="Select",
				options=_STATUS_OPTIONS,
				default=C.UNF_DRAFT,
				insert_after="custom_chain_col_1",
				read_only=1,
				allow_on_submit=1,
				no_copy=1,
				in_list_view=1,
				in_standard_filter=1,
				description=(
					"BRD 6.2. Derived from the payments Accounts has recorded, which is a "
					"different fact from the ledger status ERPNext maintains alongside it."
				),
			),
			dict(
				fieldname="custom_payment_due_date",
				label="Payment Due Date",
				fieldtype="Date",
				insert_after=STATUS_FIELD,
				allow_on_submit=1,
				in_standard_filter=1,
				description=(
					"Invoice Date + the supplier's Payment Terms where they are set; "
					"entered by hand on a Direct Purchase Invoice (BRD 6.1.2)."
				),
			),
			dict(
				fieldname="custom_invoice_attachment",
				label="Supplier Invoice Attachment",
				fieldtype="Attach",
				insert_after="custom_payment_due_date",
				description="VAL-UNF-02: the physical supplier invoice copy, required to submit.",
			),
			dict(
				fieldname="custom_invoice_remarks",
				label="Invoice Remarks",
				fieldtype="Small Text",
				insert_after="custom_invoice_attachment",
			),
			# ------------------------------------------------ 6.1.4 logistics
			dict(
				fieldname="custom_logistics_section",
				label="Logistics / Transport Bill",
				fieldtype="Section Break",
				insert_after="custom_invoice_remarks",
				collapsible=1,
				description=(
					"BRD 6.1.4, optional. Fill this only when a separate transporter bill "
					"has to be paid; door delivery means no logistics payment at all."
				),
			),
			dict(
				fieldname="custom_include_logistics",
				label="Include Logistics?",
				fieldtype="Check",
				default="0",
				insert_after="custom_logistics_section",
			),
			dict(
				fieldname="custom_logistics_vendor",
				label="Logistics Vendor",
				fieldtype="Link",
				options="Supplier",
				insert_after="custom_include_logistics",
				depends_on="eval:doc.custom_include_logistics",
				mandatory_depends_on="eval:doc.custom_include_logistics",
			),
			dict(
				fieldname="custom_transport_invoice_no",
				label="Transport Invoice / LR No.",
				fieldtype="Data",
				insert_after="custom_logistics_vendor",
				depends_on="eval:doc.custom_include_logistics",
				mandatory_depends_on="eval:doc.custom_include_logistics",
			),
			dict(
				fieldname="custom_logistics_col_1",
				fieldtype="Column Break",
				insert_after="custom_transport_invoice_no",
			),
			dict(
				fieldname="custom_freight_amount",
				label="Freight Amount",
				fieldtype="Currency",
				insert_after="custom_logistics_col_1",
				depends_on="eval:doc.custom_include_logistics",
				mandatory_depends_on="eval:doc.custom_include_logistics",
			),
			dict(
				fieldname="custom_transport_attachment",
				label="Transport Bill Attachment",
				fieldtype="Attach",
				insert_after="custom_freight_amount",
				depends_on="eval:doc.custom_include_logistics",
			),
			# --------------------------------------- 6.1.5 payments + BR-UNF-04
			dict(
				fieldname="custom_payment_section",
				label="Payment & Logistics Reference",
				fieldtype="Section Break",
				insert_after="custom_transport_attachment",
				collapsible=0,
				description=(
					"BRD 6.1.5, filled by Accounts. BR-UNF-05 allows as many rows as the "
					"payment actually took -- a supplier advance today, logistics tomorrow."
				),
			),
			dict(
				fieldname="custom_payment_references",
				label="Payment References",
				fieldtype="Table",
				options="Purchase Payment Reference",
				insert_after="custom_payment_section",
				allow_on_submit=1,
			),
			dict(
				fieldname="custom_supplier_pending_amount",
				label="Supplier Pending Amount",
				fieldtype="Currency",
				insert_after="custom_payment_references",
				read_only=1,
				allow_on_submit=1,
				no_copy=1,
				description="BR-UNF-04. Total invoice amount less the Supplier Payments recorded.",
			),
			dict(
				fieldname="custom_payment_col_1",
				fieldtype="Column Break",
				insert_after="custom_supplier_pending_amount",
			),
			dict(
				fieldname="custom_logistics_pending_amount",
				label="Logistics Pending Amount",
				fieldtype="Currency",
				insert_after="custom_payment_col_1",
				read_only=1,
				allow_on_submit=1,
				no_copy=1,
				description="BR-UNF-04. Freight amount less the Logistics Payments recorded.",
			),
			dict(
				fieldname="custom_total_paid_amount",
				label="Total Paid",
				fieldtype="Currency",
				insert_after="custom_logistics_pending_amount",
				read_only=1,
				allow_on_submit=1,
				no_copy=1,
			),
		]
	}


#: The Purchase-Team sections BR-UNF-03 freezes once the invoice is submitted. Held here
#: rather than in the controller so the field list and the guard cannot drift.
PURCHASE_OWNED_FIELDS = (
	"custom_payment_due_date",
	"custom_invoice_attachment",
	"custom_invoice_remarks",
	"custom_include_logistics",
	"custom_logistics_vendor",
	"custom_transport_invoice_no",
	"custom_freight_amount",
	"custom_transport_attachment",
)


def apply_purchase_invoice_form_layout():
	"""Show the chain and payment status in the list view without opening each invoice."""
	make_property_setter(
		PI, None, "search_fields", "supplier,custom_unified_status,bill_no", "Data", for_doctype=True
	)


def setup_purchase_invoice_fields():
	create_custom_fields(_custom_fields(), ignore_validate=True, update=True)
	apply_purchase_invoice_form_layout()
	frappe.db.commit()


def execute():
	setup_purchase_invoice_fields()
