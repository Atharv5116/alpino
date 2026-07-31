"""Quantity-flow guards across the document chain
Opportunity -> Quotation -> Sales Order -> Pick List -> Delivery Note.

Whenever a downstream document carries LESS quantity of an item than its
upstream source, the row's remark becomes mandatory (Quotation Item /
Sales Order Item `custom_remarks`, Pick List Item / Delivery Note Item
`custom_remark`). The four "X to Y" comparison reports read the same links.
"""

import frappe
from frappe import _
from frappe.utils import flt


def _agg_qty(rows, code_key="item_code", qty_key="qty"):
	out = {}
	for r in rows:
		code = r.get(code_key)
		if code:
			out[code] = out.get(code, 0) + flt(r.get(qty_key))
	return out


def _doc_item_qty(doc, table="items"):
	out = {}
	for r in doc.get(table) or []:
		if r.item_code:
			out[r.item_code] = out.get(r.item_code, 0) + flt(r.qty)
	return out


def _require_remark(row, remark_field, item_code, down_qty, up_qty, up_label):
	if not (row.get(remark_field) or "").strip():
		frappe.throw(
			_(
				"Row #{0} ({1}): quantity is {2} but {3} has {4} — a remark is "
				"mandatory when the quantity is reduced."
			).format(row.idx, item_code, flt(down_qty), up_label, flt(up_qty))
		)


def quotation_qty_remarks(doc, method=None):
	"""Quotation vs its Opportunity: reduced item qty needs custom_remarks."""
	if doc.docstatus > 1 or not frappe.get_meta("Quotation Item").has_field("custom_remarks"):
		return
	opp = doc.get("opportunity") or next(
		(r.get("prevdoc_docname") for r in (doc.get("items") or []) if r.get("prevdoc_docname")),
		None,
	)
	if not opp or not frappe.db.exists("Opportunity", opp):
		return
	up = _agg_qty(
		frappe.get_all("Opportunity Item", filters={"parent": opp}, fields=["item_code", "qty"])
	)
	down = _doc_item_qty(doc)
	flagged = set()
	for row in doc.get("items") or []:
		code = row.item_code
		if code in flagged or code not in up:
			continue
		if flt(down.get(code)) < flt(up[code]):
			_require_remark(row, "custom_remarks", code, down.get(code), up[code], _("Opportunity {0}").format(opp))
			flagged.add(code)


def sales_order_qty_remarks(doc, method=None):
	"""Sales Order vs its Quotation(s): reduced item qty needs custom_remarks."""
	if doc.docstatus > 1 or not frappe.get_meta("Sales Order Item").has_field("custom_remarks"):
		return
	quotations = {r.get("prevdoc_docname") for r in (doc.get("items") or []) if r.get("prevdoc_docname")}
	quotations = {q for q in quotations if q and frappe.db.exists("Quotation", q)}
	if not quotations:
		return
	up = _agg_qty(
		frappe.get_all(
			"Quotation Item",
			filters={"parent": ["in", list(quotations)], "docstatus": ["<", 2]},
			fields=["item_code", "qty"],
		)
	)
	down = _doc_item_qty(doc)
	flagged = set()
	for row in doc.get("items") or []:
		code = row.item_code
		if code in flagged or code not in up:
			continue
		if flt(down.get(code)) < flt(up[code]):
			_require_remark(
				row, "custom_remarks", code, down.get(code), up[code],
				_("Quotation {0}").format(", ".join(sorted(quotations))),
			)
			flagged.add(code)


def pick_list_qty_remarks(doc, method=None):
	"""Pick List vs the Sales Order snapshot (custom_ordered_qty) — checked on
	submit only: draft rows legitimately sit at 0 during picking."""
	if doc.docstatus != 1:
		return
	for row in doc.get("locations") or []:
		ordered = flt(row.get("custom_ordered_qty"))
		if ordered > 0 and flt(row.qty) < ordered and not (row.get("custom_remark") or "").strip():
			frappe.throw(
				_(
					"Row #{0} ({1}): picked qty {2} is less than the ordered qty {3} — "
					"a remark is mandatory for short-picked rows."
				).format(row.idx, row.item_code, flt(row.qty), ordered)
			)


def delivery_note_qty_remarks(doc, method=None):
	"""Delivery Note vs its Pick List rows — checked on submit only."""
	if doc.docstatus != 1 or doc.get("is_return"):
		return
	if not frappe.get_meta("Delivery Note Item").has_field("custom_remark"):
		return
	pli_names = [r.get("pick_list_item") for r in (doc.get("items") or []) if r.get("pick_list_item")]
	if not pli_names:
		return
	pl_qty = {
		r.name: flt(r.qty)
		for r in frappe.get_all(
			"Pick List Item", filters={"name": ["in", pli_names]}, fields=["name", "qty"]
		)
	}
	for row in doc.get("items") or []:
		up = pl_qty.get(row.get("pick_list_item"))
		if up and flt(row.qty) < up and not (row.get("custom_remark") or "").strip():
			frappe.throw(
				_(
					"Row #{0} ({1}): DN qty {2} is less than the Pick List qty {3} — "
					"a remark is mandatory when the quantity is reduced."
				).format(row.idx, row.item_code, flt(row.qty), up)
			)
