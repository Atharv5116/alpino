"""Sales Order side of the Quotation hand-off (doc Section 6, W7), for Offline orders.

- Offline Sales Settings "Offline Sales Orders must come from a Finalized Quotation" (OFF at
  deploy, client decision 13 Nov 2026): when ON, an Offline Sales Order without a Linked
  Quotation is refused and only Sales Manager / Sales Admin create orders. When OFF, direct
  orders work as before (the 3 Oct amendment lets a Sales Officer draft one).
- A Sales Officer never creates an order from a Quotation (doc 2.1).
- One active Sales Order per Quotation (doc 3): Draft or submitted, not Cancelled / Rejected.
- A Quotation-sourced order keeps its Customer and links, and a Registered Business buyer
  needs its Billing GSTIN, on creation and on submission (doc 6).
- Buyer Catalog sync stays on submission only (sales_mrp.update_buyer_catalog_on_submit);
  here each synced row also records the Last Order Date and the Linked Sales Order (doc 8.3).

The Quotation Status / SO Eligibility checks and the Create Sales Order action belong with
the Quotation build (W5 / W7) and read their own fields.
"""

import frappe
from frappe import _
from frappe.utils import flt

from alpinos.offline_sales import is_offline, is_sales_officer_only

MSG_DUPLICATE = "Sales Order [{0}] is already linked to Quotation [{1}]. Duplicate Sales Order creation is blocked."
MSG_GSTIN = "Billing GSTIN is missing on selected Billing Address [{0}]. Please update GSTIN in Buyer Master before proceeding with the Sales Order."
MSG_SO_CANNOT_CREATE = "Permission Denied: Sales Officers are not authorized to create Sales Orders."
MSG_QUOTATION_ONLY = "Offline Sales Orders are created from a Finalized Quotation. Open the Quotation and click Create Sales Order."
INACTIVE = ("Cancelled", "Rejected")


def quotation_required():
	return bool(frappe.db.get_single_value("Offline Sales Settings", "quotation_required_for_sales_order"))


def _offline(doc):
	return (doc.get("custom_channel") or "").strip() != "E-com" and is_offline(doc.get("custom_channel"))


def active_sales_order(quotation, exclude=None):
	"""The active Sales Order of a Quotation: Draft or submitted, not Cancelled / Rejected."""
	if not quotation:
		return None
	rows = frappe.db.sql(
		"""
		SELECT name FROM `tabSales Order`
		WHERE custom_quotation = %(q)s AND docstatus < 2 AND name != %(me)s
			AND IFNULL(custom_workflow_status, '') NOT IN %(inactive)s
		ORDER BY creation LIMIT 1
		""",
		{"q": quotation, "me": exclude or "", "inactive": INACTIVE},
	)
	return rows[0][0] if rows else None


def sales_order_validate(doc, method=None):
	# company-scope: n/a (checks the order being saved and its own Quotation)
	if not _offline(doc):
		return
	if doc.is_new():
		_creation_rules(doc)
	else:
		_keep_links(doc)
	if doc.get("custom_quotation") and (doc.is_new() or doc.get("_action") == "submit"):
		_billing_gstin(doc)


def _creation_rules(doc):
	if not doc.get("custom_quotation"):
		if quotation_required():
			frappe.throw(_(MSG_QUOTATION_ONLY), title=_("Quotation required"))
		return
	if is_sales_officer_only():
		frappe.throw(_(MSG_SO_CANNOT_CREATE), frappe.PermissionError)
	# a row lock on the Quotation: two people creating at the same moment get one order
	frappe.db.sql("SELECT name FROM `tabQuotation` WHERE name = %s FOR UPDATE", doc.custom_quotation)
	other = active_sales_order(doc.custom_quotation, exclude=doc.name)
	if other:
		frappe.throw(_(MSG_DUPLICATE).format(other, doc.custom_quotation), title=_("Duplicate Sales Order"))
	if not doc.get("custom_opportunity"):
		doc.custom_opportunity = frappe.db.get_value("Quotation", doc.custom_quotation, "opportunity")


def _keep_links(doc):
	before = doc.get_doc_before_save()
	if not before or not before.get("custom_quotation"):
		return
	for field in ("custom_quotation", "custom_opportunity", "customer"):
		if (before.get(field) or "") != (doc.get(field) or ""):
			frappe.throw(
				_("This Sales Order was created from Quotation {0}, so its {1} cannot be changed.").format(
					before.custom_quotation, doc.meta.get_label(field)
				)
			)


def _billing_gstin(doc):
	if (doc.get("custom_billing_gstin") or "").strip():
		return
	gst_type = frappe.db.get_value("Buyer Master", {"customer": doc.customer}, "gst_type")
	if gst_type != "Registered Business":
		return
	where = doc.get("custom_site_name") or doc.get("customer_address") or ""
	frappe.throw(_(MSG_GSTIN).format(where), title=_("Billing GSTIN missing"))


def stamp_catalog_on_submit(doc, method=None):
	"""Last Order Date + Linked Sales Order on every Buyer Catalog row this order synced."""
	# company-scope: n/a (writes the order's own buyer's catalogue rows)
	if (doc.get("custom_channel") or "").strip() == "E-com" or not doc.get("customer"):
		return
	if not frappe.db.has_column("Buyer Item", "last_sales_order"):
		return
	from alpinos import item_mrp as IM

	for row in doc.get("items") or []:
		if not row.item_code or flt(row.get("custom_selling_price")) <= 0:
			continue
		mrp = flt(row.get("custom_customer_mrp"))
		by_mrp = bool(mrp > 0 and IM.applicable(row.item_code).tracked)
		frappe.db.sql(
			f"""
			UPDATE `tabBuyer Item` bil
			INNER JOIN `tabBuyer Items` bi ON bi.name = bil.parent AND bil.parenttype = 'Buyer Items'
			SET bil.last_order_date = %(date)s, bil.last_sales_order = %(so)s
			WHERE bi.buyer = %(customer)s AND IFNULL(bi.docstatus, 0) < 2 AND bil.item_code = %(item)s
				{"AND ROUND(IFNULL(bil.mrp, 0), 2) = %(mrp)s" if by_mrp else ""}
			""",
			{"date": doc.transaction_date, "so": doc.name, "customer": doc.customer, "item": row.item_code, "mrp": IM.q(mrp) if by_mrp else 0},
		)
