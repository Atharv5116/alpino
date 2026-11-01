"""Reading Production Settings (the store warehouses and the planning switches).

The one place that answers "which warehouses count as available stock", so the Store
Planning board, the Material Request screen and the Parent PO stock check can never
disagree about it.

Warehouses are per company: a company's row in "Warehouses by Company" decides its
warehouses; the Single's own warehouse fields count only for the company they belong to.
Every warehouse accessor takes the company (the document's); without one it is the
company the user works in (company_scope.helpers.current_company).
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

SETTINGS = "Production Settings"

#: Warehouses whose stock is never usable for production, whatever the settings say. Matched
#: case-insensitively against the warehouse name. Many of these also carry
#: is_rejected_warehouse, but not all of them, so the name is checked as well.
NON_USABLE_NAME_PARTS = ("quarantine", "rejected", "qc sample", "control sample", "qc hold")


def _installed():
	return bool(frappe.db.exists("DocType", SETTINGS))


def get_settings():
	return frappe.get_cached_doc(SETTINGS)


def _value(fieldname):
	if not _installed():
		return None
	return get_settings().get(fieldname)


def _company(company=None):
	if company:
		return company
	from alpinos.company_scope.helpers import current_company

	return current_company()


def warehouse_for(fieldname, company=None):
	"""A warehouse setting for `company`: its Warehouses by Company row, else the Single's
	value when that warehouse belongs to the company. None when neither is set."""
	if not _installed():
		return None
	company = _company(company)
	if company:
		for row in get_settings().get("company_warehouses") or []:
			if row.company == company and row.get(fieldname):
				return row.get(fieldname)
	value = _value(fieldname)
	if value and company and frappe.db.get_value("Warehouse", value, "company") != company:
		return None
	return value


def _missing(label, company):
	company = _company(company)
	where = _(" for {0}").format(company) if company else ""
	frappe.throw(_("Set the {0}{1} in Production Settings.").format(_(label), where),
	             title=_("{0} Not Set").format(_(label)))


def main_warehouse(company=None):
	"""The RM Store: default source for Material Requests and Material Issues."""
	warehouse = warehouse_for("main_warehouse", company)
	if not warehouse:
		_missing("Main warehouse", company)
	return warehouse


def wip_warehouse(company=None):
	"""The shop floor: where Material Issues deliver and Material Returns collect from."""
	warehouse = warehouse_for("wip_warehouse", company)
	if not warehouse:
		_missing("WIP warehouse", company)
	return warehouse


def excluded_warehouses():
	if not _installed():
		return []
	return [row.warehouse for row in (get_settings().get("excluded_warehouses") or [])
	        if row.warehouse]


def capacity_check_enabled():
	return bool(cint(_value("merge_capacity_check")))


def _default_company():
	return _company()


def usable_warehouses(company=None):
	"""Leaf, enabled warehouses of the company whose stock may be used for production.

	Left out: the excluded warehouses in Production Settings, rejected warehouses, anything
	named Quarantine / Rejected / QC Sample / Control Sample / QC Hold, and the WIP warehouse
	(stock there has already been issued to a sub order).
	"""
	company = company or _default_company()
	filters = {"is_group": 0, "disabled": 0}
	if company:
		filters["company"] = company
	fields = ["name", "warehouse_name"]
	has_rejected = frappe.get_meta("Warehouse").has_field("is_rejected_warehouse")
	if has_rejected:
		fields.append("is_rejected_warehouse")

	skip = set(excluded_warehouses())
	wip = warehouse_for("wip_warehouse", company)
	if wip:
		skip.add(wip)

	out = []
	for row in frappe.get_all("Warehouse", filters=filters, fields=fields, order_by="name asc"):
		if row.name in skip:
			continue
		if has_rejected and cint(row.get("is_rejected_warehouse")):
			continue
		label = f"{row.name} {row.warehouse_name or ''}".lower()
		if any(part in label for part in NON_USABLE_NAME_PARTS):
			continue
		out.append(row.name)
	return out


# --- Phase 4+ (Execution / Filling / Inventory), appended ----------------------------

DEFAULT_WASTAGE_TOLERANCE_PCT = 5.0
DEFAULT_ADJUSTMENT_APPROVAL_KG = 500.0


def _required(fieldname, label, company=None):
	warehouse = warehouse_for(fieldname, company)
	if not warehouse:
		_missing(label, company)
	return warehouse


def baked_wip_warehouse(company=None):
	"""Where approved baked bulk waits for Filling. Falls back to the WIP warehouse."""
	return warehouse_for("baked_wip_warehouse", company) or wip_warehouse(company)


def fg_hold_warehouse(company=None):
	"""Filled FG before Final QC clears it."""
	return _required("fg_hold_warehouse", "FG Hold Warehouse", company)


def fg_warehouse(company=None):
	"""FG-Cleared stock (available for dispatch)."""
	return _required("fg_warehouse", "FG Warehouse", company)


def rejected_warehouse(company=None):
	"""QC-rejected baked bulk and FG."""
	return _required("rejected_warehouse", "Rejected Warehouse", company)


def wastage_tolerance_pct():
	"""Filling wastage above this % of the run weight needs approval. Blank = 5."""
	value = _value("filling_wastage_tolerance_pct")
	return flt(value) if value not in (None, "") else DEFAULT_WASTAGE_TOLERANCE_PCT


#: BA answer (2026-10-05): one batch = 50 KG of finished product.
DEFAULT_STANDARD_BATCH_SIZE_KG = 50.0


def standard_batch_size_kg():
	"""KG one BOM batch makes. Blank = 50."""
	if not _installed():
		return DEFAULT_STANDARD_BATCH_SIZE_KG
	value = _value("standard_batch_size_kg")
	return flt(value) if value not in (None, "") and flt(value) > 0 else DEFAULT_STANDARD_BATCH_SIZE_KG


def adjustment_approval_kg():
	"""Deduct adjustments above this many KG need Plant Head approval. Blank = 500."""
	value = _value("adjustment_approval_kg")
	return flt(value) if value not in (None, "") else DEFAULT_ADJUSTMENT_APPROVAL_KG
