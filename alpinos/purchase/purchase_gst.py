"""GST on the Purchase Order — the GSTIN on the document, and the tax template that follows it.

WHY THIS MODULE EXISTS
----------------------
"GST not fetching automatically in PO." It was not a fetch that broke: there was
nothing on the purchase side to fetch. As found on 2026-09-12:

    Sales                                   Purchase
    2 Sales Taxes and Charges Templates     0 Purchase Taxes and Charges Templates
    2 Tax Rules (tax_type = Sales)          0 Tax Rules (tax_type = Purchase)
    Tax Categories In-State / Out-State     -- same two, usable as-is
    CGST / SGST / IGST accounts             -- output tax, Liability
    --                                      0 of 559 Suppliers carry a tax_id
    --                                      all 1756 Purchase Orders: taxes_and_charges blank

`india_compliance` is not installed on this site, so there is no `gstin` field
anywhere. ERPNext's own `tax_id` on Supplier and Company is where a GSTIN lives, and
that is what this reads -- no parallel field to keep in step.

Note also that GST appears NOWHERE in the BRD "Purchase Inward Part -1". Nothing here
implements a stated requirement; it is a separate ask, which is why it is a module of
its own rather than more fields in `purchase_order_fields`.

WHAT IS AUTOMATED, AND WHAT IS DELIBERATELY NOT
-----------------------------------------------
Automated:
  * the two GSTINs are shown on the order, fetched from Supplier and Company;
  * In-State vs Out-State is derived by comparing the two GSTIN state codes, which is
    the one piece of real logic `india_compliance` would otherwise provide;
  * the Purchase tax template is then applied through ERPNext's OWN Tax Rule lookup
    (`party.set_taxes`), so a rate lives in exactly one place -- the template -- and
    this module never computes tax.

NOT automated, on purpose: the templates, the Tax Rules and the input-GST accounts are
not created on migrate. Which accounts input GST posts to, and at what rate, is an
accounting decision -- the existing CGST/SGST/IGST accounts are OUTPUT tax under
Liability, and posting purchase input tax to them would misstate the liability.
`create_purchase_gst_masters` builds the whole set when someone who owns that decision
asks for it, and is a no-op until then. Until it is run, `set_gst_tax_category` sets the
category and finds no template, which is inert rather than wrong.
"""

from __future__ import annotations

import re

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import cint, flt, nowdate

PO = "Purchase Order"

# The two Tax Categories the sales side already uses; reused rather than duplicated so
# one category means the same thing on both sides of the ledger.
TAX_CATEGORY_IN_STATE = "In-State GST"
TAX_CATEGORY_OUT_STATE = "Out-State GST"

# 22AAAAA0000A1Z5 -- state code, PAN, entity number, 'Z', checksum.
GSTIN_PATTERN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")

_GSTIN_DESCRIPTION = (
	"Read from the Supplier's Tax ID. Blank means the Supplier has no GSTIN recorded, "
	"in which case the GST tax category cannot be derived and no tax template is applied."
)


# ----------------------------------------------------------------- field surface


def _custom_fields():
	"""The GSTIN pair, sitting with the other tax fields rather than in a block of its own."""
	return {
		PO: [
			dict(
				fieldname="custom_gst_section",
				label="GST",
				fieldtype="Section Break",
				insert_after="tax_category",
				collapsible=0,
			),
			dict(
				fieldname="custom_supplier_gstin",
				label="Supplier GSTIN",
				fieldtype="Data",
				insert_after="custom_gst_section",
				fetch_from="supplier.tax_id",
				fetch_if_empty=0,
				read_only=1,
				no_copy=0,
				description=_GSTIN_DESCRIPTION,
			),
			dict(
				fieldname="custom_gst_col_1",
				fieldtype="Column Break",
				insert_after="custom_supplier_gstin",
			),
			dict(
				fieldname="custom_company_gstin",
				label="Company GSTIN",
				fieldtype="Data",
				insert_after="custom_gst_col_1",
				fetch_from="company.tax_id",
				fetch_if_empty=0,
				read_only=1,
			),
		]
	}


def setup_purchase_gst_fields():
	create_custom_fields(_custom_fields(), ignore_validate=True, update=True)


def execute():
	setup_purchase_gst_fields()


# --------------------------------------------------------------------- the logic


def _state_code(gstin):
	"""The first two digits of a GSTIN are the state. None when there is nothing usable."""
	gstin = (gstin or "").strip().upper()
	if len(gstin) < 2 or not gstin[:2].isdigit():
		return None
	return gstin[:2]


def is_valid_gstin(gstin):
	return bool(GSTIN_PATTERN.match((gstin or "").strip().upper()))


def gst_tax_category(supplier_gstin, company_gstin):
	"""In-State when both GSTINs are in the same state, Out-State when they differ.

	None when either side is missing: guessing a category from one GSTIN would pick a
	tax rate, and a wrong rate is worse than no rate.
	"""
	supplier_state = _state_code(supplier_gstin)
	company_state = _state_code(company_gstin)
	if not supplier_state or not company_state:
		return None
	return TAX_CATEGORY_IN_STATE if supplier_state == company_state else TAX_CATEGORY_OUT_STATE


def _resolve_gstins(doc):
	"""The two GSTINs, preferring what is already on the document over a fresh read."""
	supplier_gstin = (doc.get("custom_supplier_gstin") or "").strip()
	if not supplier_gstin and doc.get("supplier"):
		supplier_gstin = frappe.db.get_value("Supplier", doc.supplier, "tax_id") or ""
	company_gstin = (doc.get("custom_company_gstin") or "").strip()
	if not company_gstin and doc.get("company"):
		company_gstin = frappe.db.get_value("Company", doc.company, "tax_id") or ""
	return supplier_gstin.strip(), company_gstin.strip()


def set_gst_tax_category(doc, method=None):
	"""Stamp the GSTINs and the derived tax category, then let ERPNext pick the template.

	Runs on validate so it works for a scripted order and a data import too, not only
	for someone picking a supplier on the form.

	A tax category the user chose by hand is never overwritten -- an order to a
	registered dealer in the same state may still legitimately carry a different
	category, and this is a convenience, not a rule the BRD imposes.
	"""
	if cint(doc.get("docstatus")) != 0:
		return

	supplier_gstin, company_gstin = _resolve_gstins(doc)
	# Keep the document honest about what it was priced against, even when the Supplier
	# master is edited later.
	if supplier_gstin and not (doc.get("custom_supplier_gstin") or "").strip():
		doc.custom_supplier_gstin = supplier_gstin
	if company_gstin and not (doc.get("custom_company_gstin") or "").strip():
		doc.custom_company_gstin = company_gstin

	if (doc.get("tax_category") or "").strip():
		_apply_purchase_tax_template(doc)
		return

	category = gst_tax_category(supplier_gstin, company_gstin)
	if not category or not frappe.db.exists("Tax Category", category):
		return
	doc.tax_category = category
	_apply_purchase_tax_template(doc)


def _apply_purchase_tax_template(doc):
	"""Apply the Purchase tax template ERPNext's own Tax Rule picks for this order.

	Only when the order carries no taxes at all. Re-deriving over rows someone already
	has would silently rewrite a manually corrected tax block, and an amended order
	would lose the correction it was amended to make.
	"""
	if (doc.get("taxes_and_charges") or "").strip() or doc.get("taxes"):
		return
	if not (doc.get("supplier") and doc.get("company")):
		return

	from erpnext.accounts.party import set_taxes
	from erpnext.controllers.accounts_controller import get_taxes_and_charges

	try:
		template = set_taxes(
			doc.supplier,
			"Supplier",
			doc.get("transaction_date") or nowdate(),
			doc.company,
			tax_category=doc.get("tax_category"),
		)
	except Exception:
		# A misconfigured Tax Rule must not stop an order being saved; the tax block
		# stays empty and visibly so, which is recoverable.
		frappe.log_error(
			title="Purchase GST: tax template lookup failed",
			message=frappe.get_traceback(),
		)
		return

	if not template:
		return

	doc.taxes_and_charges = template
	for row in get_taxes_and_charges("Purchase Taxes and Charges Template", template) or []:
		doc.append("taxes", row)


# ------------------------------------------------------- the masters, on request

#: Account name -> (abbreviated suffix is added per company) for the input side of GST.
_INPUT_ACCOUNTS = ("Input CGST", "Input SGST", "Input IGST")


def _ensure_input_account(company, account_name, parent):
	"""One input-GST account under the same parent the output accounts use."""
	abbr = frappe.get_cached_value("Company", company, "abbr")
	full = f"{account_name} - {abbr}"
	if frappe.db.exists("Account", full):
		return full
	doc = frappe.get_doc(
		{
			"doctype": "Account",
			"account_name": account_name,
			"parent_account": parent,
			"company": company,
			"account_type": "Tax",
			"is_group": 0,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def create_purchase_gst_masters(rate=None, company=None, commit=False):
	"""Create the input-GST accounts, the two Purchase templates and their Tax Rules.

	NOT called on migrate. `rate` is the total GST percentage for the template (split
	half/half across CGST and SGST for the in-state one, charged whole as IGST for the
	other) and has no default, because a default rate here would be an invented
	accounting decision.

	Idempotent: re-running adopts what already exists rather than duplicating it.

	    bench --site <site> execute alpinos.purchase.purchase_gst.create_purchase_gst_masters \
	        --kwargs "{'rate': 18, 'commit': True}"
	"""
	rate = flt(rate)
	if rate <= 0:
		frappe.throw(
			_(
				"Please pass the total GST rate, for example rate=18. There is no default: "
				"the rate and the accounts it posts to are an accounting decision."
			)
		)

	company = company or frappe.defaults.get_user_default("Company") or frappe.get_all(
		"Company", pluck="name", limit=1
	)[0]
	abbr = frappe.get_cached_value("Company", company, "abbr")

	# Sit the input accounts beside the output ones rather than inventing a tree.
	sample = frappe.db.get_value("Account", f"CGST - {abbr}", "parent_account")
	parent = sample or f"Duties and Taxes - {abbr}"
	accounts = {name: _ensure_input_account(company, name, parent) for name in _INPUT_ACCOUNTS}

	created = {"accounts": accounts, "templates": [], "tax_rules": []}

	plans = (
		(
			TAX_CATEGORY_IN_STATE,
			f"GST {rate:g}% Purchase In-State (CGST+SGST)",
			[(accounts["Input CGST"], rate / 2.0), (accounts["Input SGST"], rate / 2.0)],
		),
		(
			TAX_CATEGORY_OUT_STATE,
			f"GST {rate:g}% Purchase Out-State (IGST)",
			[(accounts["Input IGST"], rate)],
		),
	)

	for category, title, rows in plans:
		name = f"{title} - {abbr}"
		if not frappe.db.exists("Purchase Taxes and Charges Template", name):
			tpl = frappe.get_doc(
				{
					"doctype": "Purchase Taxes and Charges Template",
					"title": title,
					"company": company,
					"tax_category": category,
					"taxes": [
						{
							"category": "Total",
							"add_deduct_tax": "Add",
							"charge_type": "On Net Total",
							"account_head": head,
							"rate": pct,
							"description": head.rsplit(" - ", 1)[0],
						}
						for head, pct in rows
					],
				}
			)
			tpl.insert(ignore_permissions=True)
			name = tpl.name
		created["templates"].append(name)

		existing = frappe.db.exists(
			"Tax Rule",
			{"tax_type": "Purchase", "tax_category": category, "company": company},
		)
		if not existing:
			rule = frappe.get_doc(
				{
					"doctype": "Tax Rule",
					"tax_type": "Purchase",
					"tax_category": category,
					"company": company,
					"purchase_tax_template": name,
					"use_for_shopping_cart": 0,
				}
			)
			rule.insert(ignore_permissions=True)
			existing = rule.name
		created["tax_rules"].append(existing)

	if commit:
		frappe.db.commit()
	return created
