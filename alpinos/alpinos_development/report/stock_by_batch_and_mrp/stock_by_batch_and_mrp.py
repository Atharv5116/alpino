"""Stock by Batch and MRP -- stock by Item, Batch, MRP and Location (MRP draft, section 8).

One row per item, warehouse and Batch / MRP (alpinos.mrp_batch), straight from the stock
ledger, so it always agrees with Stock Balance: the same item at MRP 199 and MRP 210 is two
rows, and stock that came in before lots existed shows as "No Batch / MRP".

Location tells usable stock from stock that is not: the Quarantine and Rejected warehouses
of Purchase Inward Settings hold goods QC has not released or has refused. Picked is what open
Pick Lists have already chosen and not shipped, so Free is what a new order can still take.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, today

from alpinos import mrp_batch as MB
from alpinos.purchase import constants as C
from alpinos.purchase.settings import warehouse as settings_warehouse

NO_LOT = _("No Batch / MRP")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return _columns(), _rows(filters)


def _columns():
	return [
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 150},
		{"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 190},
		{"label": _("Warehouse"), "fieldname": "warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 170},
		{"label": _("Location"), "fieldname": "location_kind", "fieldtype": "Data", "width": 95},
		{"label": _("Batch No."), "fieldname": "batch_no", "fieldtype": "Data", "width": 120},
		{"label": _("MRP"), "fieldname": "mrp", "fieldtype": "Currency", "width": 85},
		{"label": _("Mfg Date"), "fieldname": "manufacturing_date", "fieldtype": "Date", "width": 95},
		{"label": _("Expiry Date"), "fieldname": "expiry_date", "fieldtype": "Date", "width": 95},
		{"label": _("Qty"), "fieldname": "qty", "fieldtype": "Float", "width": 90},
		{"label": _("Picked"), "fieldname": "picked_qty", "fieldtype": "Float", "width": 80},
		{"label": _("Free"), "fieldname": "free_qty", "fieldtype": "Float", "width": 90},
		{"label": _("UOM"), "fieldname": "stock_uom", "fieldtype": "Link", "options": "UOM", "width": 65},
		{"label": _("Value"), "fieldname": "value", "fieldtype": "Currency", "width": 110},
		{"label": _("Purchase Rate"), "fieldname": "purchase_rate", "fieldtype": "Currency", "width": 100},
		{"label": _("Batch / MRP"), "fieldname": "mrp_batch", "fieldtype": "Link", "options": "MRP Batch", "width": 180},
		{"label": _("Purchase Inward"), "fieldname": "purchase_inward", "fieldtype": "Link", "options": "Purchase Inward", "width": 140},
	]


def _rows(filters):
	if not frappe.get_meta("Stock Ledger Entry").has_field(MB.FIELD):
		frappe.msgprint(_("The Batch / MRP dimension is not set up yet. Run bench migrate first."))
		return []

	conditions = ["sle.is_cancelled = 0", "sle.posting_date <= %(to_date)s"]
	values = {"to_date": getdate(filters.get("to_date") or today())}
	for key, column in (("company", "sle.company"), ("warehouse", "sle.warehouse"), ("item_code", "sle.item_code")):
		if filters.get(key):
			conditions.append(f"{column} = %({key})s")
			values[key] = filters.get(key)
	if filters.get("item_group"):
		conditions.append("item.item_group = %(item_group)s")
		values["item_group"] = filters.item_group
	if filters.get("batch_no"):
		conditions.append("lot.batch_no LIKE %(batch_no)s")
		values["batch_no"] = "%{0}%".format(filters.batch_no.strip())
	if filters.get("mrp"):
		conditions.append("lot.mrp = %(mrp)s")
		values["mrp"] = flt(filters.mrp, 2)
	if filters.get("only_unassigned"):
		conditions.append(f"IFNULL(sle.`{MB.FIELD}`, '') = ''")

	rows = frappe.db.sql(
		f"""
		SELECT sle.item_code, item.item_name, item.stock_uom, sle.warehouse, sle.company,
			sle.`{MB.FIELD}` AS mrp_batch, lot.batch_no, lot.mrp, lot.manufacturing_date,
			lot.expiry_date, lot.purchase_rate, lot.purchase_inward,
			SUM(sle.actual_qty) AS qty, SUM(sle.stock_value_difference) AS value
		FROM `tabStock Ledger Entry` sle
		JOIN `tabItem` item ON item.name = sle.item_code
		LEFT JOIN `tabMRP Batch` lot ON lot.name = sle.`{MB.FIELD}`
		WHERE {" AND ".join(conditions)}
		GROUP BY sle.item_code, sle.warehouse, sle.`{MB.FIELD}`
		HAVING ABS(SUM(sle.actual_qty)) > 0.000001
		ORDER BY sle.item_code, sle.warehouse, lot.expiry_date IS NULL, lot.expiry_date, lot.mrp
		""",
		values,
		as_dict=True,
	)

	holds = _pick_list_holds(rows)
	kinds = {}
	out = []
	for row in rows:
		if row.company not in kinds:
			kinds[row.company] = {
				settings_warehouse(C.WH_QUARANTINE, row.company): _("Quarantine"),
				settings_warehouse(C.WH_REJECTED, row.company): _("Rejected"),
			}
		row.location_kind = kinds[row.company].get(row.warehouse) or _("Usable")
		row.picked_qty = flt(holds.get((row.item_code, row.warehouse, row.mrp_batch or "")))
		row.free_qty = flt(row.qty) - row.picked_qty
		if not row.mrp_batch:
			row.batch_no = NO_LOT
		out.append(row)
	return out


def _pick_list_holds(rows):
	"""{(item, warehouse, lot): qty} chosen on open Pick Lists and not yet delivered."""
	items = list({r.item_code for r in rows})
	if not items or not frappe.get_meta("Pick List Item").has_field(MB.FIELD):
		return {}
	out = {}
	for row in frappe.db.sql(
		f"""
		SELECT pli.item_code, pli.warehouse, IFNULL(pli.`{MB.FIELD}`, '') AS lot,
			SUM(GREATEST(IFNULL(pli.stock_qty, pli.qty) - IFNULL(pli.delivered_qty, 0), 0)) AS qty
		FROM `tabPick List Item` pli
		JOIN `tabPick List` pl ON pl.name = pli.parent
		WHERE pli.item_code IN %(items)s AND pl.docstatus < 2
			AND IFNULL(pl.status, '') NOT IN ('Completed', 'Cancelled')
		GROUP BY pli.item_code, pli.warehouse, IFNULL(pli.`{MB.FIELD}`, '')
		""",
		{"items": tuple(items)},
		as_dict=True,
	):
		out[(row.item_code, row.warehouse, row.lot)] = flt(row.qty)
	return out
