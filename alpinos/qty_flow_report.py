"""Shared engine for the four quantity-flow comparison reports:

Opportunity to Quotation / Quotation to Sales Order /
Sales Order to Pick List / Pick List to Delivery Note.

Each report lists document pairs with one row per SKU: upstream qty,
downstream qty, difference and the downstream row remarks. The report JS
highlights the lesser of the two quantities. The remark-compulsory rule for
reduced quantities lives in alpinos.qty_flow (validate hooks).
"""

import frappe
from frappe.utils import flt

STAGES = {
	"opp_quo": {
		"up_doctype": "Opportunity",
		"down_doctype": "Quotation",
		"up_qty_label": "Opp Qty",
		"down_qty_label": "Quotation Qty",
	},
	"quo_so": {
		"up_doctype": "Quotation",
		"down_doctype": "Sales Order",
		"up_qty_label": "Quotation Qty",
		"down_qty_label": "Order Qty",
	},
	"so_pl": {
		"up_doctype": "Sales Order",
		"down_doctype": "Pick List",
		"up_qty_label": "Order Qty",
		"down_qty_label": "Picked Qty",
	},
	"pl_dn": {
		"up_doctype": "Pick List",
		"down_doctype": "Delivery Note",
		"up_qty_label": "Picked Qty",
		"down_qty_label": "DN Qty",
	},
}


def _agg(rows, qty_key="qty"):
	"""{item_code: total_qty} from child rows."""
	out = {}
	for r in rows:
		if r.get("item_code"):
			out[r.item_code] = out.get(r.item_code, 0) + flt(r.get(qty_key))
	return out


def _remarks(rows, field):
	"""{item_code: 'joined remarks'} from downstream child rows."""
	out = {}
	for r in rows:
		txt = (r.get(field) or "").strip()
		if r.get("item_code") and txt:
			out.setdefault(r.item_code, [])
			if txt not in out[r.item_code]:
				out[r.item_code].append(txt)
	return {k: "; ".join(v) for k, v in out.items()}


def _date_conditions(filters, fieldname):
	out = []
	if filters.get("from_date"):
		out.append([fieldname, ">=", filters["from_date"]])
	if filters.get("to_date"):
		out.append([fieldname, "<=", filters["to_date"]])
	return out


def _pairs_opp_quo(filters):
	conds = [["docstatus", "<", 2]] + _date_conditions(filters, "transaction_date")
	if filters.get("down_id"):
		conds.append(["name", "=", filters["down_id"]])
	for quo in frappe.get_all(
		"Quotation", filters=conds, fields=["name", "opportunity"],
		order_by="transaction_date desc, name desc", limit_page_length=0,
	):
		items = frappe.get_all(
			"Quotation Item", filters={"parent": quo.name},
			fields=["item_code", "qty", "custom_remarks", "prevdoc_docname"],
		)
		opp = quo.opportunity or next((r.prevdoc_docname for r in items if r.get("prevdoc_docname")), None)
		if not opp or (filters.get("up_id") and filters["up_id"] != opp):
			continue
		up_rows = frappe.get_all("Opportunity Item", filters={"parent": opp}, fields=["item_code", "qty"])
		yield opp, quo.name, _agg(up_rows), _agg(items), _remarks(items, "custom_remarks")


def _pairs_quo_so(filters):
	conds = [["docstatus", "<", 2]] + _date_conditions(filters, "transaction_date")
	if filters.get("down_id"):
		conds.append(["name", "=", filters["down_id"]])
	for so in frappe.get_all(
		"Sales Order", filters=conds, pluck="name",
		order_by="transaction_date desc, name desc", limit_page_length=0,
	):
		items = frappe.get_all(
			"Sales Order Item", filters={"parent": so},
			fields=["item_code", "qty", "custom_remarks", "prevdoc_docname"],
		)
		for quo in sorted({r.prevdoc_docname for r in items if r.get("prevdoc_docname")}):
			if filters.get("up_id") and filters["up_id"] != quo:
				continue
			linked = [r for r in items if r.get("prevdoc_docname") == quo]
			up_rows = frappe.get_all(
				"Quotation Item", filters={"parent": quo, "docstatus": ["<", 2]},
				fields=["item_code", "qty"],
			)
			yield quo, so, _agg(up_rows), _agg(linked), _remarks(linked, "custom_remarks")


def _pairs_so_pl(filters):
	conds = [["docstatus", "<", 2], ["custom_sales_order_id", "is", "set"]]
	conds += _date_conditions(filters, "creation")
	if filters.get("down_id"):
		conds.append(["name", "=", filters["down_id"]])
	if filters.get("up_id"):
		conds.append(["custom_sales_order_id", "=", filters["up_id"]])
	for pl in frappe.get_all(
		"Pick List", filters=conds, fields=["name", "custom_sales_order_id"],
		order_by="creation desc", limit_page_length=0,
	):
		so = pl.custom_sales_order_id
		# Only main order lines — freebies / scheme rows have their own source
		# tables and would inflate the picked qty.
		down_rows = [
			r for r in frappe.get_all(
				"Pick List Item", filters={"parent": pl.name},
				fields=["item_code", "qty", "custom_remark", "custom_source_table"],
			)
			if (r.get("custom_source_table") or "Items") == "Items"
		]
		up_rows = frappe.get_all("Sales Order Item", filters={"parent": so}, fields=["item_code", "qty"])
		yield so, pl.name, _agg(up_rows), _agg(down_rows), _remarks(down_rows, "custom_remark")


def _pairs_pl_dn(filters):
	conds = [["docstatus", "<", 2], ["is_return", "=", 0]]
	conds += _date_conditions(filters, "posting_date")
	if filters.get("down_id"):
		conds.append(["name", "=", filters["down_id"]])
	for dn in frappe.get_all(
		"Delivery Note", filters=conds, pluck="name",
		order_by="posting_date desc, name desc", limit_page_length=0,
	):
		items = frappe.get_all(
			"Delivery Note Item", filters={"parent": dn},
			fields=["item_code", "qty", "custom_remark", "against_pick_list"],
		)
		for pl in sorted({r.against_pick_list for r in items if r.get("against_pick_list")}):
			if filters.get("up_id") and filters["up_id"] != pl:
				continue
			linked = [r for r in items if r.get("against_pick_list") == pl]
			up_rows = [
				r for r in frappe.get_all(
					"Pick List Item", filters={"parent": pl},
					fields=["item_code", "qty", "custom_source_table"],
				)
				if (r.get("custom_source_table") or "Items") == "Items"
			]
			yield pl, dn, _agg(up_rows), _agg(linked), _remarks(linked, "custom_remark")


_PAIR_FUNCS = {
	"opp_quo": _pairs_opp_quo,
	"quo_so": _pairs_quo_so,
	"so_pl": _pairs_so_pl,
	"pl_dn": _pairs_pl_dn,
}


def _columns(stage):
	s = STAGES[stage]
	return [
		{"label": frappe._(s["up_doctype"] + " ID"), "fieldname": "up_id", "fieldtype": "Link",
		 "options": s["up_doctype"], "width": 180},
		{"label": frappe._(s["down_doctype"] + " ID"), "fieldname": "down_id", "fieldtype": "Link",
		 "options": s["down_doctype"], "width": 180},
		{"label": frappe._("SKU"), "fieldname": "sku", "fieldtype": "Link", "options": "Item", "width": 150},
		{"label": frappe._(s["up_qty_label"]), "fieldname": "up_qty", "fieldtype": "Float", "width": 110},
		{"label": frappe._(s["down_qty_label"]), "fieldname": "down_qty", "fieldtype": "Float", "width": 120},
		{"label": frappe._("Difference"), "fieldname": "difference", "fieldtype": "Float", "width": 110},
		{"label": frappe._("Remarks"), "fieldname": "remarks", "fieldtype": "Data", "width": 240},
	]


def run(stage, filters=None):
	filters = frappe._dict(filters or {})
	data = []
	for up_name, down_name, up_qty, down_qty, remarks in _PAIR_FUNCS[stage](filters):
		first = True
		for sku in sorted(set(up_qty) | set(down_qty)):
			u, d = flt(up_qty.get(sku)), flt(down_qty.get(sku))
			data.append(
				{
					"up_id": up_name if first else "",
					"down_id": down_name if first else "",
					"sku": sku,
					"up_qty": u,
					"down_qty": d,
					"difference": d - u,
					"remarks": remarks.get(sku) or "",
				}
			)
			first = False
	return _columns(stage), data
