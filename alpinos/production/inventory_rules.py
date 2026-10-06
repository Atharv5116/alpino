"""Stock Entry validate hook for the Inventory module (FRD 10.4).

Registered by Groundwork as Stock Entry "validate". It touches ONLY entries this module
owns -- custom_entry_kind "Production Transfer" / "Inventory Adjustment", or an entry
flagged alpinos_inventory by inventory_api -- and returns at once for everything else, so
Material Issues / Returns, Manufacture entries and ordinary stock entries are untouched.

10.4.1  Hard block: stock may never go below zero at the source ("Insufficient stock in
        source location."), checked per item + batch + warehouse, adding up rows that draw
        on the same stock. ERPNext's own negative-stock setting is a second line of defence.
10.4.2  Moving FG-Hold / QC-Rejected stock is allowed and its status is NOT changed here --
        nothing in this hook writes Batch.custom_fg_status; dispatch_rules keeps it blocked.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

from alpinos.production import inventory_common as IC


def _owned(doc):
	return doc.get("custom_entry_kind") in IC.OWN_KINDS or bool(doc.flags.get("alpinos_inventory"))


def validate_negative_and_status(doc, method=None):
	if not _owned(doc):
		return
	if cint(doc.docstatus) == 2:
		return
	need = {}
	for row in doc.get("items") or []:
		if not row.get("s_warehouse") or not row.get("item_code"):
			continue
		qty = flt(row.get("transfer_qty")) or flt(row.get("qty")) * (flt(row.get("conversion_factor")) or 1)
		key = (row.item_code, row.s_warehouse, row.get("batch_no") or "")
		entry = need.setdefault(key, {"qty": 0.0, "idx": row.idx})
		entry["qty"] += qty
	for (item_code, warehouse, batch_no), entry in need.items():
		available = IC.available_qty(item_code, warehouse, batch_no or None)
		if entry["qty"] > available + 0.0000001:
			frappe.throw(
				_("Row {0}: {1}{2} needs {3} but only {4} is available at {5}. {6}").format(
					entry["idx"], item_code, (" / " + batch_no) if batch_no else "",
					flt(entry["qty"], 3), flt(available, 3), warehouse, _(IC.MSG_INSUFFICIENT)),
				title=_("Insufficient Stock"))
