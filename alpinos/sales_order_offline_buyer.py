# Copyright (c) 2026, Alpinos and contributors
# License: MIT

import frappe
from frappe import _
from frappe.utils import flt


def _customers_with_offline_buyer_master_query(txt, start, page_len):
	"""Customers that have a row in Offline Buyer Master (same pool for Sales Order + Catalog)."""
	txt = txt or ""
	return frappe.db.sql(
		"""
		SELECT c.name, c.customer_name
		FROM `tabCustomer` c
		INNER JOIN `tabOffline Buyer Master` m ON m.customer = c.name
		WHERE IFNULL(c.disabled, 0) = 0
			AND (c.name LIKE %(txt)s OR c.customer_name LIKE %(txt)s)
		ORDER BY c.name ASC
		LIMIT %(page_len)s OFFSET %(start)s
		""",
		{"txt": f"%{txt}%", "start": int(start), "page_len": int(page_len)},
	)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def sales_order_customer_query(doctype, txt, searchfield, start, page_len, filters):
	"""Limit Sales Order Customer link to customers that have an Offline Buyer Master."""
	return _customers_with_offline_buyer_master_query(txt, start, page_len)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def catalog_customer_query(doctype, txt, searchfield, start, page_len, filters):
	"""Same customer list as Sales Order — only customers linked in Offline Buyer Master."""
	return _customers_with_offline_buyer_master_query(txt, start, page_len)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def offline_buyer_master_item_query(doctype, txt, searchfield, start, page_len, filters):
	"""Item link for Sales Order Entry: only SKUs that have a margin row on the customer's Offline Buyer Master."""
	doctype = "Item"
	txt = txt or ""
	if isinstance(filters, str):
		filters = frappe.parse_json(filters)
	filters = filters or {}
	customer = (filters.get("customer") or "").strip()
	if not customer:
		return []

	obm = frappe.db.get_value("Offline Buyer Master", {"customer": customer}, "name")
	if not obm:
		return []

	return frappe.db.sql(
		"""
		SELECT i.name, i.item_name
		FROM `tabItem` i
		INNER JOIN `tabOffline Buyer Margin` m
			ON m.sku = i.name AND m.parent = %(obm)s AND m.parenttype = 'Offline Buyer Master'
		WHERE IFNULL(i.disabled, 0) = 0
			AND (i.name LIKE %(txt)s OR IFNULL(i.item_name, '') LIKE %(txt)s)
		ORDER BY i.name ASC
		LIMIT %(page_len)s OFFSET %(start)s
		""",
		{"txt": f"%{txt}%", "obm": obm, "start": int(start), "page_len": int(page_len)},
	)


@frappe.whitelist()
def get_offline_buyer_item_rate(customer, item_code):
	"""Return selling rate from Offline Buyer Master margins (same formula as offline buyer catalog)."""
	if not customer or not item_code:
		return None

	obm_name = frappe.db.get_value(
		"Offline Buyer Master",
		{"customer": customer},
		"name",
		order_by="modified desc",
	)
	if not obm_name:
		return None

	margin_pct = frappe.db.get_value(
		"Offline Buyer Margin",
		{"parent": obm_name, "parenttype": "Offline Buyer Master", "sku": item_code},
		"margin_percent",
	)
	if margin_pct is None:
		return None

	mrp = flt(frappe.db.get_value("Item", item_code, "standard_rate") or 0)
	pct = flt(margin_pct)
	rate = flt(mrp * (1 - pct / 100), 2) if mrp else 0.0

	return {"rate": rate, "margin_percent": pct, "mrp": mrp, "offline_buyer_master": obm_name}


@frappe.whitelist()
def get_offline_buyer_for_customer(customer):
	"""Return Offline Buyer Master name and trade customer_type for a linked ERPNext Customer."""
	if not customer:
		return {"offline_buyer_master": None, "customer_type": None}

	row = frappe.db.get_value(
		"Offline Buyer Master",
		{"customer": customer},
		["name", "customer_type"],
		as_dict=True,
	)
	if not row:
		return {"offline_buyer_master": None, "customer_type": None}

	return {
		"offline_buyer_master": row.get("name"),
		"customer_type": row.get("customer_type"),
	}


def sync_sales_order_offline_buyer_fields(doc, method=None):
	"""Keep OBM link and trade Customer Type on Sales Order in sync with Customer (save/API/import)."""
	if doc.docstatus != 0:
		return
	try:
		meta = frappe.get_meta("Sales Order")
	except Exception:
		return
	if not meta.has_field("custom_offline_buyer_master"):
		return

	if not doc.customer:
		doc.custom_offline_buyer_master = None
		doc.custom_offline_buyer_customer_type = None
		return

	row = frappe.db.get_value(
		"Offline Buyer Master",
		{"customer": doc.customer},
		["name", "customer_type"],
		as_dict=True,
	)
	if row:
		doc.custom_offline_buyer_master = row.get("name")
		doc.custom_offline_buyer_customer_type = row.get("customer_type")
	else:
		doc.custom_offline_buyer_master = None
		doc.custom_offline_buyer_customer_type = None


def validate_sales_order_offline_buyer_customer(doc, method=None):
	"""Ensure Sales Order customer is linked to an Offline Buyer Master (UI also restricts the link)."""
	if doc.docstatus != 0:
		return
	if getattr(doc.flags, "ignore_offline_buyer_customer_check", False):
		return
	if not doc.customer:
		return
	if frappe.db.exists("DocType", "Offline Buyer Master") and not frappe.db.exists(
		"Offline Buyer Master", {"customer": doc.customer}
	):
		frappe.throw(
			_("Customer {0} is not linked to an Offline Buyer Master. Only offline-buyer customers can be selected.").format(
				frappe.bold(doc.customer)
			),
			title=_("Invalid Customer"),
		)
