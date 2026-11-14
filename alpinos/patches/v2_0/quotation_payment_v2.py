"""Offline Sales, Section 5 (W5): Quotations raised before the Quotation workflow get its values.

    Payment Mode (Advance / Debit / Partial)  -> Payment Term (Advance / Credit / Partial);
                                                 blank -> the Buyer Master's term (A-32)
    docstatus 0 / 1 / 2                       -> Draft / Finalized (Sales Order Created when an
                                                 active Sales Order links it) / Cancelled
    Credit                                    -> Credit Days from the Buyer Master; the stored
                                                 Expected Payment Date is kept
    Responsible Sales Officer                 -> by the same default as a new Quotation (A-16)
    payment summary                           -> nothing received (no receipt is invented from the
                                                 old proof or advance fields, which stay readable
                                                 under "Earlier Payment Details")

Finalized By / On stay blank: the old records do not say who submitted them or when.
"""

import frappe
from frappe.utils import cint, flt

MODE_TO_TERM = {"Advance": "Advance", "Debit": "Credit", "Credit": "Credit", "Partial": "Partial"}


def execute():
	if not frappe.db.has_column("Quotation", "custom_quotation_status"):
		from alpinos.quotation_custom_fields import setup_quotation_custom_fields

		setup_quotation_custom_fields()
	# the Sales Order's Linked Quotation (W7) decides "Sales Order Created"; on a site migrating to
	# this build it is created by after_migrate, which runs after the patches
	if not frappe.db.has_column("Sales Order", "custom_quotation"):
		from alpinos.sales_order_custom_fields import setup_sales_order_custom_fields

		setup_sales_order_custom_fields()
	if not frappe.db.has_column("Quotation", "custom_quotation_status"):
		return
	migrate()


def migrate(names=None):
	from alpinos.offline_sales import quotation as Q
	from alpinos.offline_sales import quotation_payments as P

	filters = {"name": ("in", names)} if names else {}
	for name in frappe.get_all("Quotation", filters=filters, pluck="name", order_by="creation asc"):
		_legacy_selling_prices(name)
		doc = frappe.get_doc("Quotation", name)
		buyer = Q.buyer_of(doc)
		row = frappe.db.get_value("Buyer Master", buyer, ["payment_term", "payment_term_days"], as_dict=True) if buyer else None
		term = MODE_TO_TERM.get(doc.get("custom_payment_mode") or "") or doc.get("custom_payment_term")
		if not term and row and row.payment_term in Q.TERMS:
			term = row.payment_term
		doc.custom_payment_term = term or None
		if term == "Credit" and not cint(doc.get("custom_credit_days")) and row:
			doc.custom_credit_days = Q.credit_days_of(row.payment_term_days)
		if doc.docstatus == 2:
			status = Q.CANCELLED
		elif doc.docstatus == 1:
			status = Q.SO_CREATED if Q.active_sales_order_of(doc.name) else Q.FINALIZED
		else:
			status = Q.DRAFT
		doc.custom_quotation_status = status
		if status == Q.SO_CREATED and not doc.get("custom_linked_sales_order"):
			doc.custom_linked_sales_order = Q.active_sales_order_of(doc.name)
		if not doc.get("custom_responsible_sales_officer"):
			frappe.set_user("Administrator")
			doc.custom_responsible_sales_officer = Q.default_responsible_officer(doc)
		if not doc.get("custom_billing_gstin"):
			doc.custom_billing_gstin = Q.billing_gstin(Q.customer_of(doc), doc.get("custom_site_name")) or None
		P.recompute(doc)
		values = {
			f: doc.get(f)
			for f in (
				"custom_payment_term", "custom_credit_days", "custom_quotation_status", "custom_linked_sales_order",
				"custom_responsible_sales_officer", "custom_billing_gstin", "custom_total_received",
				"custom_total_pending", "custom_payment_status", "custom_so_eligibility", "custom_payment_process",
			)
		}
		values["custom_force_complete_applied"] = cint(doc.get("custom_force_complete_applied"))
		values["custom_credit_days"] = cint(values["custom_credit_days"])
		values["custom_total_pending"] = flt(values["custom_total_pending"], 2)
		frappe.db.set_value("Quotation", name, values, update_modified=False)


def _legacy_selling_prices(quotation):
	"""Rows priced before this build carry no Selling Price (the old Quotation priced a line as
	MRP x (1 - Flat %) x (1 - Offer %)); give them that price so the PDF and totals show it."""
	if not frappe.db.has_column("Quotation Item", "custom_selling_price"):
		return
	for row in frappe.get_all(
		"Quotation Item",
		filters={"parent": quotation, "parenttype": "Quotation"},
		fields=["name", "custom_mrp", "custom_flat_discount", "custom_offer", "custom_selling_price"],
	):
		if flt(row.custom_selling_price) > 0 or flt(row.custom_mrp) <= 0:
			continue
		price = flt(row.custom_mrp) * (1 - flt(row.custom_flat_discount) / 100) * (1 - flt(row.custom_offer) / 100)
		frappe.db.set_value("Quotation Item", row.name, "custom_selling_price", flt(price, 2), update_modified=False)

