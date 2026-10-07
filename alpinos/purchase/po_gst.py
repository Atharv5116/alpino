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
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import flt

ITEM_GST_FIELD = "custom_gst_percent"

LINE_GST_FIELD = "custom_gst_percent"
LINE_FINAL_RATE_FIELD = "custom_rate_incl_gst"
LINE_FINAL_AMOUNT_FIELD = "custom_amount_incl_gst"
LINE_HSN_FIELD = "custom_hsn_code"
ITEM_HSN_FIELD = "custom_hsn_code"

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
					read_only=0,
					description="Filled from the Item Master; the buyer may change it on the order.",
				),
				dict(
					fieldname=LINE_HSN_FIELD,
					label="HSN/SAC",
					fieldtype="Data",
					insert_after="item_name",
					description="Filled from the Item Master; the buyer may change it on the order.",
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
			],
			# GRN and Purchase Invoice lines carry the same two, under the SAME fieldnames:
			# ERPNext's GRN -> Invoice mapper copies child fields that share a name, so a new
			# invoice takes the GRN's values without code of its own. The GRN takes them from
			# the Purchase Inward line (grn._apply_row). Editable on both.
			"Purchase Receipt Item": [
				dict(fieldname=LINE_GST_FIELD, label="GST %", fieldtype="Percent", insert_after="custom_mrp",
				     description="From the Purchase Inward; may be changed on the GRN."),
				dict(fieldname=LINE_HSN_FIELD, label="HSN/SAC", fieldtype="Data", insert_after=LINE_GST_FIELD,
				     description="From the Purchase Inward; may be changed on the GRN."),
			],
			"Purchase Invoice Item": [
				dict(fieldname=LINE_GST_FIELD, label="GST %", fieldtype="Percent", insert_after="rate",
				     description="From the GRN / Purchase Inward; may be changed on the invoice."),
				dict(fieldname=LINE_HSN_FIELD, label="HSN/SAC", fieldtype="Data", insert_after=LINE_GST_FIELD,
				     description="From the GRN / Purchase Inward; may be changed on the invoice."),
			],
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
	for company, _abbr in frappe.get_all("Company", fields=["name", "abbr"], as_list=True):
		ensure_input_accounts(company)
	frappe.db.commit()


def _tax_parent(company):
	"""The group the GST accounts sit in, whatever this chart of accounts calls them.

	Only "CGST - <abbr>" was looked for, so a site whose chart names it otherwise (UAT)
	never got the Input accounts and every PO saved with its GST silently dropped.
	"""
	abbr = frappe.get_cached_value("Company", company, "abbr")
	parent = frappe.db.get_value("Account", f"CGST - {abbr}", "parent_account")
	if parent:
		return parent
	for pattern in ("%CGST%", "%SGST%", "%IGST%", "%GST%"):
		parent = frappe.db.get_value(
			"Account",
			{"company": company, "is_group": 0, "account_name": ("like", pattern)},
			"parent_account",
		)
		if parent:
			return parent
	parent = frappe.db.get_value(
		"Account", {"company": company, "is_group": 1, "account_name": "Duties and Taxes"}, "name"
	)
	if parent:
		return parent
	return frappe.db.get_value(
		"Account", {"company": company, "is_group": 1, "account_type": "Tax"}, "name"
	)


def ensure_input_accounts(company):
	"""Input CGST / SGST / IGST for `company` (created when missing). {head: account}."""
	accounts = _accounts(company)
	if all(h in accounts for h in _HEADS):
		return accounts
	parent = _tax_parent(company)
	if not parent:
		return accounts
	for name in _HEADS.values():
		G._ensure_input_account(company, name, parent)
	return _accounts(company)


def _gst_unavailable_message(company):
	return _(
		"GST could not be calculated: the Input CGST / Input SGST / Input IGST accounts do not "
		"exist for {0}, and no GST or Duties and Taxes account group was found to create "
		"them in. Please ask Accounts to create them."
	).format(company)


def _accounts(company):
	"""{"CGST": <account>, "SGST": ..., "IGST": ...} for the company's PURCHASE (input) GST.

	In order, the first that gives an account:
	    1. India Compliance's GST Settings -> GST Accounts, the company's "Input" row
	       (UAT: "Input Tax CGST - AHFPL" ...). Its accounts are the ones India Compliance
	       validates transactions against, so they must win.
	    2. An account named "Input Tax CGST" (India Compliance's naming) or "Input CGST"
	       (what setup_input_gst_accounts creates where India Compliance is absent).
	Only "Input CGST" was looked for, so on UAT every PO saved with its GST dropped.
	"""
	out = {}
	if frappe.db.exists("DocType", "GST Account"):
		try:
			row = frappe.get_all(
				"GST Account",
				filters={"parent": "GST Settings", "company": company, "account_type": "Input"},
				fields=["cgst_account", "sgst_account", "igst_account"],
				limit=1,
			)
		except Exception:
			row = []
		if row:
			for head, field in (("CGST", "cgst_account"), ("SGST", "sgst_account"), ("IGST", "igst_account")):
				if row[0].get(field):
					out[head] = row[0][field]
	for head, account_name in _HEADS.items():
		if head in out:
			continue
		for name in ("Input Tax " + head, account_name):
			acc = frappe.db.get_value(
				"Account", {"company": company, "account_name": name, "is_group": 0}, "name"
			)
			if acc:
				out[head] = acc
				break
	return out


def _input_gst_accounts(company):
	"""Every purchase-GST account of the company, under either naming."""
	names = [p + h for p in ("Input ", "Input Tax ") for h in _HEADS]
	return set(
		frappe.get_all(
			"Account", filters={"company": company, "account_name": ("in", names), "is_group": 0}, pluck="name"
		)
	)


def _is_inter_state(doc):
	supplier_gstin, company_gstin = G._resolve_gstins(doc)
	return G.gst_tax_category(supplier_gstin, company_gstin) == G.TAX_CATEGORY_OUT_STATE


TEMPLATE_PREFIX = "GST "


def _template_fits(name, pct, accounts):
	"""Does this Item Tax Template carry the purchase GST accounts at this rate?"""
	rates = {
		r.tax_type: flt(r.tax_rate)
		for r in frappe.get_all(
			"Item Tax Template Detail", filters={"parent": name}, fields=["tax_type", "tax_rate"]
		)
	}
	return (
		abs(rates.get(accounts["CGST"], -1) - pct / 2) < 0.001
		and abs(rates.get(accounts["SGST"], -1) - pct / 2) < 0.001
		and abs(rates.get(accounts["IGST"], -1) - pct) < 0.001
	)


def _gst_template(company, pct, accounts):
	"""The Item Tax Template for this GST rate: an existing one that already carries the
	purchase GST accounts (India Compliance ships "GST 5% - <abbr>" and the like), else our
	own, created on first use. An existing template is never edited."""
	abbr = frappe.get_cached_value("Company", company, "abbr")
	title = f"{TEMPLATE_PREFIX}{pct:g}%"
	name = f"{title} - {abbr}"
	if frappe.db.exists("Item Tax Template", name) and _template_fits(name, pct, accounts):
		return name
	if frappe.db.exists("Item Tax Template", name):
		# Taken by a template without these accounts (India Compliance's own, say).
		title = f"{title} Purchase"
		name = f"{title} - {abbr}"
		if frappe.db.exists("Item Tax Template", name):
			return name
	values = {
		"doctype": "Item Tax Template",
		"title": title,
		"company": company,
		"taxes": [
			{"tax_type": accounts["CGST"], "tax_rate": pct / 2},
			{"tax_type": accounts["SGST"], "tax_rate": pct / 2},
			{"tax_type": accounts["IGST"], "tax_rate": pct},
		],
	}
	meta = frappe.get_meta("Item Tax Template")
	# India Compliance's mandatory fields on the template, when it is installed.
	if meta.has_field("gst_treatment"):
		values["gst_treatment"] = "Taxable"
	if meta.has_field("gst_rate"):
		values["gst_rate"] = pct
	tpl = frappe.get_doc(values)
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
	if not usable and doc.get("company"):
		accounts = ensure_input_accounts(doc.company)
		usable = all(h in accounts for h in _HEADS)

	# The line's own GST % is the buyer's to set (the screen fills it from the Item when the
	# item is picked). A NEW line that arrives with none -- Frappe starts a Percent at 0, so
	# 0 -- takes the Item Master's rate; a line already saved keeps whatever it holds, a
	# deliberate 0 included.
	before = doc.get_doc_before_save() if not doc.is_new() else None
	saved = {r.name for r in (before.get("items") if before else []) or []}
	rates = item_gst_rates(row.item_code for row in doc.get("items") or [])
	for row in doc.get("items") or []:
		if not flt(row.get(LINE_GST_FIELD)) and row.name not in saved:
			row.set(LINE_GST_FIELD, rates.get(row.item_code, 0))

	if usable:
		_apply_gst_rows(doc, accounts, heads)
	elif any(flt(row.get(LINE_GST_FIELD)) for row in doc.get("items") or []):
		# Never silently: the line shows GST but the total would not include it.
		frappe.msgprint(_gst_unavailable_message(doc.company), indicator="orange", alert=True)

	for row in doc.get("items") or []:
		pct = flt(row.get(LINE_GST_FIELD))
		row.set(LINE_FINAL_RATE_FIELD, flt(flt(row.rate) * (1 + pct / 100), row.precision("rate")))
		row.set(LINE_FINAL_AMOUNT_FIELD, flt(flt(row.amount) * (1 + pct / 100), row.precision("amount")))


def _apply_gst_rows(doc, accounts, heads):
	"""Tax rows from each line's GST %: an Item Tax Template per rate on the line, one
	"On Net Total" row per GST account, then ERPNext's own recalculation. Shared by the
	Purchase Order and the Purchase Invoice."""
	# Our rows go, whatever mode they were built in; everything else stays. "Ours" includes
	# the other purchase-GST account names too (Input CGST / Input Tax CGST ...), so a row
	# built before the company's GST accounts changed does not linger at 0 on the order.
	ours = set(accounts.values()) | _input_gst_accounts(doc.company)
	kept = [t for t in doc.get("taxes") or [] if t.account_head not in ours]

	if True:
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


def apply_invoice_gst(doc, method=None):
	"""GST on a Purchase Invoice raised by the module, from each line's GST % column.

	The GRN carries no tax rows, and the invoice is mapped from the GRN, so it came out
	with Taxes & Charges 0. The lines' GST % (fetched from the GRN / Purchase Inward and
	editable on the invoice) now builds the tax exactly as it does on the Purchase Order.
	A line with no GST % carries no tax: nothing is filled in from the order or the Item.

	Left alone: debit notes (returns), invoices Accounts keys in outside the module, and
	anything already submitted.
	"""
	if doc.get("is_return") or doc.docstatus == 2:
		return
	if not (doc.get("custom_purchase_inward") or doc.get("custom_invoice_type") or doc.get("custom_grn")):
		return
	accounts = _accounts(doc.company) if doc.get("company") else {}
	if not all(h in accounts for h in _HEADS):
		accounts = ensure_input_accounts(doc.company)
	if not all(h in accounts for h in _HEADS):
		frappe.msgprint(_gst_unavailable_message(doc.company), indicator="orange", alert=True)
		return

	# The lines' GST % is used exactly as it stands. A normal invoice's comes from its GRN,
	# which took it from the Purchase Inward where Store entered it (then editable on the
	# GRN and here); nothing is read from the Purchase Order or the Item master, because the
	# rate on the inward can legitimately differ from the order's. A Direct Purchase Invoice
	# has no inward: its lines carry the order's GST, copied by ERPNext's PO -> invoice map.
	grand_before = flt(doc.get("grand_total"))
	heads = ("IGST",) if _is_inter_state(doc) else ("CGST", "SGST")
	_apply_gst_rows(doc, accounts, heads)
	_resync_payment_schedule(doc, grand_before)


def _resync_payment_schedule(doc, grand_before):
	"""ERPNext built the payment schedule against the total BEFORE the GST was added; left
	as it is, the invoice would fail "Total Payment Amount in Payment Schedule must be
	equal to Grand Total". One instalment takes the new total; several are rebuilt."""
	schedule = doc.get("payment_schedule") or []
	if not schedule:
		return
	total = flt(doc.get("rounded_total") or doc.get("grand_total"), doc.precision("grand_total"))
	if abs(sum(flt(r.payment_amount) for r in schedule) - total) < 0.01:
		return
	if len(schedule) == 1:
		row = schedule[0]
		row.payment_amount = total
		row.outstanding = total
		if row.meta.has_field("base_payment_amount"):
			row.base_payment_amount = flt(total * flt(doc.get("conversion_rate") or 1), row.precision("base_payment_amount"))
		return
	doc.set("payment_schedule", [])
	doc.set_payment_schedule()


def fill_line_hsn(doc, method=None):
	"""A PO line without an HSN takes the Item Master's; a typed one is kept."""
	rows = [r for r in doc.get("items") or [] if r.item_code and not (r.get(LINE_HSN_FIELD) or "").strip()]
	if not rows:
		return
	hsn = {
		i.name: i.get(ITEM_HSN_FIELD)
		for i in frappe.get_all(
			"Item", filters={"name": ("in", list({r.item_code for r in rows}))}, fields=["name", ITEM_HSN_FIELD]
		)
	}
	for r in rows:
		if hsn.get(r.item_code):
			r.set(LINE_HSN_FIELD, hsn[r.item_code])


def items_without_gst(doc):
	"""The order's items whose Item Master has no GST % (stored as 0 -- the field has no
	separate "not set" state)."""
	codes = list({r.item_code for r in doc.get("items") or [] if r.item_code})
	if not codes:
		return []
	# Plain SQL: a frappe ("in", (0, None)) filter matches nothing once None is in the list.
	return frappe.db.sql(
		f"""select name, item_name from `tabItem`
		where name in %(codes)s and ifnull(`{ITEM_GST_FIELD}`, 0) <= 0 order by name""",
		{"codes": tuple(codes)},
		as_dict=True,
	)


def assert_items_have_gst(doc, method=None):
	"""An order cannot be submitted (for approval, or approved) while any of its items has
	no GST % in the Item Master. A popup names them so they can be fixed there."""
	missing = items_without_gst(doc)
	if not missing:
		# The order's own lines too: a GST % of 0 typed (or left) on a line is refused even
		# when the Item master has a rate.
		zero = [r for r in doc.get("items") or [] if r.item_code and flt(r.get(LINE_GST_FIELD)) <= 0]
		if zero:
			lines = "".join(
				"<li>Row {0}: {1}{2}</li>".format(
					r.idx,
					frappe.utils.escape_html(r.item_code),
					" &mdash; " + frappe.utils.escape_html(r.item_name) if r.get("item_name") and r.item_name != r.item_code else "",
				)
				for r in zero
			)
			frappe.throw(
				frappe._(
					"GST % cannot be 0. Enter the GST percentage on these lines, then submit the "
					"Purchase Order again:<ul style=\"margin-top:6px;\">{0}</ul>"
				).format(lines),
				title=frappe._("GST % Missing on Lines"),
			)
		# Lines carry GST but the order's total does not: the GST accounts are missing.
		accounts = set(_accounts(doc.company).values()) if doc.get("company") else set()
		if not any(t.account_head in accounts and flt(t.tax_amount) for t in doc.get("taxes") or []):
			frappe.throw(_gst_unavailable_message(doc.company), title=frappe._("GST Not Calculated"))
		return
	rows = "".join(
		"<li>{0}{1}</li>".format(
			frappe.utils.get_link_to_form("Item", m.name),
			" &mdash; " + frappe.utils.escape_html(m.item_name) if m.item_name and m.item_name != m.name else "",
		)
		for m in missing
	)
	frappe.throw(
		frappe._(
			"Add the GST percentage in the Item master for these items, then submit the "
			"Purchase Order again:<ul style=\"margin-top:6px;\">{0}</ul>"
		).format(rows),
		title=frappe._("GST % Missing on Items"),
	)
