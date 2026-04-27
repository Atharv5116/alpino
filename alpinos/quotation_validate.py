"""Server-side rules for Quotation (mandatory_depends_on is not enforced on save)."""

import frappe
from frappe import _
from frappe.utils import flt


def validate_partial_payment_fields(doc, method=None):
	if doc.get("custom_payment_mode") != "Partial":
		return
	if flt(doc.get("custom_advance_amount")) <= 0:
		frappe.throw(_("Advance Amount is required when Payment Mode is Partial"))
	if not doc.get("custom_attachment_proof"):
		frappe.throw(_("Attachment (Proof) is required when Payment Mode is Partial"))
