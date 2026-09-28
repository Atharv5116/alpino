"""GST on a Purchase Order, from the Item Master (PI-47).

The buyer types the Rate EXCLUDING GST. Each line then takes its GST % from the item
(Item.custom_gst_percent, the one GST field -- see production/item_fields.py) and the
order carries the tax the ERPNext way: one "On Net Total" row per GST account, and on
each line an Item Tax Template for its rate ("GST 5% - AHFPL": Input CGST 2.5, Input
SGST 2.5, Input IGST 5 -- only the accounts that are tax rows on the order are charged).
That is how ERPNext charges different rates on different lines of one document, so net
total, tax, grand total and the per-item tax breakup all come out of ERPNext's own
arithmetic. ERPNext rebuilds every line's item_tax_rate from its template on each
calculation, which is why a template and not a hand-written map. A template is created
the first time a rate is seen; the Item records themselves are never written.

Which accounts: Input CGST + Input SGST (half the rate each) for a supplier in the
company's state, Input IGST for anyone else -- the INPUT accounts, never the CGST / SGST /
IGST output accounts under Liability (see purchase_gst.py for why). The state comes from
the two GSTINs (purchase_gst.gst_tax_category); with either GSTIN missing the order is
treated as in-state, which is the common case here.

Runs as a `validate` hook, after ERPNext's own validate has fetched item details and
computed totals, and then recomputes them with the GST in place.

Only rows this module owns (the CGST / SGST / IGST accounts) are rebuilt on each save;
any other tax row somebody adds by hand is left alone.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import flt

ITEM_GST_FIELD = "custom_gst_percent"

LINE_GST_FIELD = "custom_gst_percent"
LINE_FINAL_RATE_FIELD = "custom_rate_incl_gst"
LINE_FINAL_AMOUNT_FIELD = "custom_amount_incl_gst"

from alpinos.purchase import purchase_gst as G

_HEADS = {"CGST": "Input CGST", "SGST": "Input SGST", "IGST": "Input IGST"}


def setup_po_gst_fields():
	create_custom_fields(
		{
			"Purchase Order Item": [
				dict(
					fieldname=LINE_GST_FIELD,
					label="GST %",
					fieldtype="Percent",
					insert_after="rate",
					read_only=1,
					description="From the Item Master.",
				),
				dict(
					fieldname=LINE_FINAL_RATE_FIELD,
					label="Rate (Incl. GST)",
					fieldtype="Currency",
					options="currency",
					insert_after=LINE_GST_FIELD,
					read_only=1,
				),
				dict(
					fieldname=LINE_FINAL_AMOUNT_FIELD,
					label="Amount (Incl. GST)",
					fieldtype="Currency",
					options="currency",
					insert_after="amount",
					read_only=1,
				),
			]
		},
		ignore_validate=True,
		update=True,
	)
	frappe.db.commit()


def setup_input_gst_accounts():
	"""Input CGST / SGST / IGST for every company that has the output set.

	New accounts only, beside the output ones under the same parent; nothing existing is
	touched. A company without a CGST account is left alone.
	"""
	for company, abbr in frappe.get_all("Company", fields=["name", "abbr"], as_list=True):
		parent = frappe.db.get_value("Account", f"CGST - {abbr}", "parent_account")
		if not parent:
			continue
		for name in _HEADS.values():
			G._ensure_input_account(company, name, parent)
	frappe.db.commit()


def _accounts(company):
	"""{"CGST": "Input CGST - X", ...} for the company, only those that exist."""
	out = {}
	for head, account_name in _HEADS.items():
		acc = frappe.db.get_value(
			"Account", {"company": company, "account_name": account_name, "is_group": 0}, "name"
		)
		if acc:
			out[head] = acc
	return out


def _is_inter_state(doc):
	supplier_gstin, company_gstin = G._resolve_gstins(doc)
	return G.gst_tax_category(supplier_gstin, company_gstin) == G.TAX_CATEGORY_OUT_STATE


TEMPLATE_PREFIX = "GST "


def _gst_template(company, pct, accounts):
	"""The Item Tax Template for this GST rate, created on first use."""
	abbr = frappe.get_cached_value("Company", company, "abbr")
	title = f"{TEMPLATE_PREFIX}{pct:g}%"
	name = f"{title} - {abbr}"
	if frappe.db.exists("Item Tax Template", name):
		return name
	tpl = frappe.get_doc(
		{
			"doctype": "Item Tax Template",
			"title": title,
			"company": company,
			"taxes": [
				{"tax_type": accounts["CGST"], "tax_rate": pct / 2},
				{"tax_type": accounts["SGST"], "tax_rate": pct / 2},
				{"tax_type": accounts["IGST"], "tax_rate": pct},
			],
		}
	)
	tpl.insert(ignore_permissions=True)
	return tpl.name


def item_gst_rates(item_codes):
	codes = list({c for c in item_codes if c})
	if not codes:
		return {}
	return {
		r.name: flt(r.get(ITEM_GST_FIELD))
		for r in frappe.get_all("Item", filters={"name": ("in", codes)}, fields=["name", ITEM_GST_FIELD])
	}


def apply_item_gst(doc, method=None):
	accounts = _accounts(doc.company) if doc.get("company") else {}
	# ERPNext resets every line's item_tax_rate on each save, the approval's submit
	# included, so the rows must be re-applied then as well. But an order the Approver
	# reviewed WITHOUT GST (raised before this existed) keeps the total that was
	# reviewed: an approval transition only re-applies GST that is already on it.
	if doc.flags.get("po_approval_action") and not any(
		t.account_head in set(accounts.values()) for t in doc.get("taxes") or []
	):
		return
	inter = _is_inter_state(doc)
	heads = ("IGST",) if inter else ("CGST", "SGST")
	usable = all(h in accounts for h in _HEADS)

	rates = item_gst_rates(row.item_code for row in doc.get("items") or [])
	for row in doc.get("items") or []:
		row.set(LINE_GST_FIELD, rates.get(row.item_code, 0))

	# Our rows go, whatever mode they were built in; everything else stays.
	ours = set(accounts.values())
	kept = [t for t in doc.get("taxes") or [] if t.account_head not in ours]

	if usable:
		any_gst = False
		for row in doc.get("items") or []:
			pct = flt(row.get(LINE_GST_FIELD))
			any_gst = any_gst or pct > 0
			if pct > 0:
				row.item_tax_template = _gst_template(doc.company, pct, accounts)
			elif (row.get("item_tax_template") or "").startswith(TEMPLATE_PREFIX):
				row.item_tax_template = None

		doc.set("taxes", [])
		for t in kept:
			doc.append("taxes", t)
		if any_gst:
			cost_center = frappe.get_cached_value("Company", doc.company, "cost_center")
			for head in heads:
				doc.append(
					"taxes",
					{
						"charge_type": "On Net Total",
						"account_head": accounts[head],
						"description": _HEADS[head],
						"rate": 0,
						"category": "Total",
						"add_deduct_tax": "Add",
						"cost_center": cost_center,
					},
				)
		for i, t in enumerate(doc.get("taxes"), 1):
			t.idx = i
		doc.calculate_taxes_and_totals()

	for row in doc.get("items") or []:
		pct = flt(row.get(LINE_GST_FIELD))
		row.set(LINE_FINAL_RATE_FIELD, flt(flt(row.rate) * (1 + pct / 100), row.precision("rate")))
		row.set(LINE_FINAL_AMOUNT_FIELD, flt(flt(row.amount) * (1 + pct / 100), row.precision("amount")))
