"""Applicable MRPs of an Item: the "Internal MRP Table" of the sales-side Multiple MRP FRD.

Item > MRPs (child table Item MRP) lists every MRP the SKU is sold at. It is the only
source of a Sales Order line's MRP for an Item that has rows here (FRD 2.2):

- Multiple MRP (Item.custom_multiple_mrp) is set when more than one row is Active. The
  Sales Order then asks for the MRP (blank by default); with one active MRP it is filled
  in and locked.
- A row is added, or a retired one made Active again, when stock with that MRP is received
  into a usable warehouse: a GRN after QC, a Stock Entry receipt or transfer (a quarantine
  release lands here), or a Stock Reconciliation. The Batch / MRP lot on the stock ledger
  row (alpinos.mrp_batch) carries the MRP. Quarantine and rejected warehouses never add one.
- A row is retired by clearing Active on the Item; it stays for history.
- An Item with no rows at all is not tracked yet: its orders keep the old behaviour, so a
  SKU nobody has set up is never blocked.

Rows are written straight to the database (register / refresh_flag) so that a receipt
never runs the whole Item validation, which may refuse for unrelated reasons.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, fmt_money, nowdate

from alpinos import mrp_batch as MB

CHILD = "Item MRP"
TABLE = "custom_mrps"
FLAG = "custom_multiple_mrp"

SOURCES = {
	"Purchase Receipt": "GRN",
	"Stock Entry": "Stock Entry",
	"Stock Reconciliation": "Stock Reconciliation",
}


def q(value):
	"""MRPs are compared to the paisa."""
	return flt(value, 2)


def money(value):
	return fmt_money(q(value), precision=2, currency="INR")


# ----------------------------------------------------------------- setup


def setup():
	"""after_migrate: the MRPs tab on Item."""
	if not frappe.db.exists("DocType", CHILD):
		return
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	meta = frappe.get_meta("Item")
	anchor = None
	if not meta.has_field("custom_mrp_tab"):
		fields = [f.fieldname for f in meta.fields]
		anchor = fields[-1] if fields else None
	tab = dict(fieldname="custom_mrp_tab", label="MRPs", fieldtype="Tab Break")
	if anchor:
		tab["insert_after"] = anchor
	create_custom_fields(
		{
			"Item": [
				tab,
				dict(
					fieldname=FLAG,
					label="Multiple MRP",
					fieldtype="Check",
					read_only=1,
					insert_after="custom_mrp_tab",
					description="Set when more than one MRP below is active. The Sales Order then asks which MRP.",
				),
				dict(
					fieldname=TABLE,
					label="Applicable MRPs",
					fieldtype="Table",
					options=CHILD,
					insert_after=FLAG,
					description=(
						"The MRPs this SKU is sold at. Added automatically when stock with a new MRP is received "
						"after QC; untick Active when an MRP no longer applies. Empty = not tracked yet."
					),
				),
			]
		},
		update=True,
	)


# ----------------------------------------------------------------- reading


def _rows(item_code):
	if not item_code:
		return []
	return frappe.get_all(
		CHILD,
		filters={"parent": item_code, "parenttype": "Item", "parentfield": TABLE},
		fields=["name", "mrp", "active", "idx"],
		order_by="idx asc",
	)


def applicable(item_code):
	"""{tracked, multiple, mrps (active, ascending)} for an Item."""
	rows = _rows(item_code)
	mrps = sorted({q(r.mrp) for r in rows if cint(r.active) and q(r.mrp) > 0})
	return frappe._dict(tracked=bool(rows), multiple=len(mrps) > 1, mrps=mrps)


def stock_by_mrp(item_code, warehouse=None):
	"""{mrp: qty} of the Item's lot stock in usable warehouses (or in `warehouse`)."""
	held = held_warehouses()
	cond, values = "", {"item_code": item_code}
	if warehouse:
		cond += " AND sle.warehouse = %(warehouse)s"
		values["warehouse"] = warehouse
	if held:
		cond += " AND sle.warehouse NOT IN %(held)s"
		values["held"] = tuple(held)
	rows = frappe.db.sql(
		f"""
		SELECT mb.mrp, SUM(sle.actual_qty) AS qty
		FROM `tabStock Ledger Entry` sle
		JOIN `tab{MB.DOCTYPE}` mb ON mb.name = sle.`{MB.FIELD}`
		WHERE sle.item_code = %(item_code)s AND sle.is_cancelled = 0{cond}
		GROUP BY mb.mrp
		""",
		values,
		as_dict=True,
	)
	out = {}
	for r in rows:
		out[q(r.mrp)] = flt(out.get(q(r.mrp))) + flt(r.qty)
	return out


def held_warehouses():
	"""Quarantine and rejected warehouses: stock there is not approved for sale."""
	try:
		from alpinos.purchase.settings import get_settings

		s = get_settings()
	except Exception:
		return []
	return [w for w in (s.get("quarantine_warehouse"), s.get("rejected_warehouse")) if w]


@frappe.whitelist()
def get_sales_mrp_options(item_code):
	"""MRP choices for a Sales Order line (offline and e-com entry screens).

	tracked = 0: the Item has no MRP table yet, the screen keeps its old pricing.
	multiple = 0: one active MRP, filled in and locked (`default`).
	multiple = 1: the user picks one of `mrps`; each carries the stock held at that MRP."""
	if not (frappe.has_permission("Sales Order", "create") or frappe.has_permission("Sales Order", "write")):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	info = applicable(item_code)
	stock = stock_by_mrp(item_code) if info.tracked else {}
	return {
		"tracked": int(info.tracked),
		"multiple": int(info.multiple),
		"mrps": [{"mrp": m, "stock_qty": flt(stock.get(m))} for m in info.mrps],
		"default": info.mrps[0] if len(info.mrps) == 1 else None,
	}


def line_mrp_error(item_code, mrp, imported=False):
	"""Why `mrp` cannot be a Sales Order line's MRP for `item_code`, or None when it can."""
	info = applicable(item_code)
	if not info.tracked:
		return None
	mrp = q(mrp)
	if not info.mrps:
		return _("SKU {0} has no active MRP in its Item MRP table. Activate or add one on the Item first.").format(item_code)
	if mrp <= 0:
		if info.multiple:
			return _("Select the MRP for SKU {0}. Applicable MRPs: {1}.").format(
				item_code, ", ".join(money(m) for m in info.mrps)
			)
		return _("MRP is blank for SKU {0}. Applicable MRP: {1}.").format(item_code, money(info.mrps[0]))
	if mrp in info.mrps:
		return None
	if info.multiple:
		return _("MRP {0} is not an applicable MRP for SKU {1}. Applicable MRPs: {2}.").format(
			money(mrp), item_code, ", ".join(money(m) for m in info.mrps)
		)
	if imported:
		return _("MRP mismatch for SKU {0}. Imported MRP: {1}. Applicable MRP: {2}. Please correct the import sheet.").format(
			item_code, money(mrp), money(info.mrps[0])
		)
	return _("MRP mismatch for SKU {0}. Order MRP: {1}. Applicable MRP: {2}.").format(
		item_code, money(mrp), money(info.mrps[0])
	)


# ----------------------------------------------------------------- writing


def register(item_code, mrp, source="Manual", reference_doctype=None, reference_name=None, on=None):
	"""Make `mrp` an active MRP of `item_code`. True when the table changed."""
	mrp = q(mrp)
	if not item_code or mrp <= 0 or not frappe.db.exists("DocType", CHILD):
		return False
	if not frappe.get_meta("Item").has_field(TABLE):
		return False
	rows = _rows(item_code)
	row = next((r for r in rows if q(r.mrp) == mrp), None)
	if row:
		if cint(row.active):
			return False
		# Stock arrived again at an MRP that had been retired.
		frappe.db.set_value(CHILD, row.name, "active", 1, update_modified=False)
	else:
		child = frappe.get_doc(
			{
				"doctype": CHILD,
				"parent": item_code,
				"parenttype": "Item",
				"parentfield": TABLE,
				"idx": max([cint(r.idx) for r in rows] or [0]) + 1,
				"mrp": mrp,
				"active": 1,
				"source": source,
				"first_received_on": on or nowdate(),
				"reference_doctype": reference_doctype,
				"reference_name": reference_name,
			}
		)
		child.db_insert()
	refresh_flag(item_code)
	return True


def refresh_flag(item_code):
	multiple = 1 if applicable(item_code).multiple else 0
	if cint(frappe.db.get_value("Item", item_code, FLAG)) != multiple:
		frappe.db.set_value("Item", item_code, FLAG, multiple, update_modified=False)
	frappe.clear_document_cache("Item", item_code)


def item_validate(doc, method=None):
	"""Item validate: one row per MRP, MRP above 0, and the Multiple MRP flag in step."""
	if not doc.meta.has_field(TABLE):
		return
	seen = set()
	for row in doc.get(TABLE) or []:
		mrp = q(row.mrp)
		if mrp <= 0:
			frappe.throw(_("Row #{0} of Applicable MRPs: MRP must be greater than 0.").format(row.idx))
		if mrp in seen:
			frappe.throw(_("MRP {0} appears more than once in Applicable MRPs.").format(money(mrp)))
		seen.add(mrp)
		row.mrp = mrp
		if not row.source:
			row.source = "Manual"
	active = [r for r in doc.get(TABLE) or [] if cint(r.active)]
	doc.set(FLAG, 1 if len({q(r.mrp) for r in active}) > 1 else 0)


def stock_ledger_on_submit(doc, method=None):
	"""Stock Ledger Entry on_submit: stock received with a Batch / MRP adds that MRP."""
	if cint(doc.get("is_cancelled")) or flt(doc.get("actual_qty")) <= 0:
		return
	lot = doc.get(MB.FIELD)
	source = SOURCES.get(doc.get("voucher_type"))
	if not lot or not source or doc.get("warehouse") in held_warehouses():
		return
	details = frappe.db.get_value(MB.DOCTYPE, lot, ["item_code", "mrp"], as_dict=True)
	if details and q(details.mrp) > 0:
		register(details.item_code, details.mrp, source, doc.voucher_type, doc.voucher_no, doc.get("posting_date"))


# ----------------------------------------------------------------- opening data


def seed(dry_run=False):
	"""Fill the table once for Items that have none.

	An Item with Batch / MRP stock in usable warehouses gets those MRPs. Any other Item gets
	the MRP it is sold at today, its Item valuation rate (what the Sales Order fell back to),
	marked "Opening" so the team can review it. Items with neither are left untracked."""
	if not frappe.get_meta("Item").has_field(TABLE):
		return {}
	have = set(frappe.get_all(CHILD, filters={"parenttype": "Item", "parentfield": TABLE}, pluck="parent", distinct=True))
	held = held_warehouses()
	cond, values = "", {}
	if held:
		cond = " AND sle.warehouse NOT IN %(held)s"
		values["held"] = tuple(held)
	lot_mrps = {}
	for r in frappe.db.sql(
		f"""
		SELECT mb.item_code, mb.mrp, SUM(sle.actual_qty) AS qty
		FROM `tabStock Ledger Entry` sle
		JOIN `tab{MB.DOCTYPE}` mb ON mb.name = sle.`{MB.FIELD}`
		WHERE sle.is_cancelled = 0{cond}
		GROUP BY mb.item_code, mb.mrp
		HAVING SUM(sle.actual_qty) > 0
		""",
		values,
		as_dict=True,
	):
		if q(r.mrp) > 0:
			lot_mrps.setdefault(r.item_code, set()).add(q(r.mrp))
	stats = {"from_stock": 0, "from_valuation_rate": 0, "untracked": 0, "multiple": 0}
	sold = _sold_items()
	for item in frappe.get_all("Item", fields=["name", "valuation_rate"]):
		if item.name in have or (item.name not in sold and item.name not in lot_mrps):
			continue
		mrps = sorted(lot_mrps.get(item.name) or [])
		source = "Opening"
		if mrps:
			stats["from_stock"] += 1
		elif q(item.valuation_rate) > 0:
			mrps = [q(item.valuation_rate)]
			stats["from_valuation_rate"] += 1
		else:
			stats["untracked"] += 1
			continue
		if len(mrps) > 1:
			stats["multiple"] += 1
		if dry_run:
			continue
		for i, mrp in enumerate(mrps, 1):
			frappe.get_doc(
				{
					"doctype": CHILD,
					"parent": item.name,
					"parenttype": "Item",
					"parentfield": TABLE,
					"idx": i,
					"mrp": mrp,
					"active": 1,
					"source": source,
					"first_received_on": nowdate(),
					"remarks": "From stock" if item.name in lot_mrps else "From Item valuation rate",
				}
			).db_insert()
		if len(mrps) > 1:
			frappe.db.set_value("Item", item.name, FLAG, 1, update_modified=False)
	return stats


def _sold_items():
	"""Items that are sold: finished goods, bundles, anything already on a Sales Order or a
	Buyer Catalog. Raw and packing materials keep a cost, not an MRP, in valuation rate."""
	names = set(frappe.db.sql_list("SELECT DISTINCT item_code FROM `tabSales Order Item`"))
	if frappe.db.exists("DocType", "Buyer Item"):
		names |= set(frappe.db.sql_list("SELECT DISTINCT item_code FROM `tabBuyer Item` WHERE IFNULL(item_code, '') != ''"))
	if frappe.get_meta("Item").has_field("custom_is_bundle"):
		names |= set(frappe.get_all("Item", filters={"custom_is_bundle": 1}, pluck="name"))
	try:
		from alpinos.production import material_type as MT

		groups = MT.groups_of_type("FG")
		if groups:
			names |= set(frappe.get_all("Item", filters={"item_group": ("in", groups)}, pluck="name"))
	except Exception:
		pass
	return names
