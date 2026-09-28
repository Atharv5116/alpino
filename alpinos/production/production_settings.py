"""Reading Production Settings (the store warehouses and the planning switches).

The one place that answers "which warehouses count as available stock", so the Store
Planning board, the Material Request screen and the Parent PO stock check can never
disagree about it.
"""

import frappe
from frappe import _
from frappe.utils import cint

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


def main_warehouse():
	"""The RM Store: default source for Material Requests and Material Issues."""
	warehouse = _value("main_warehouse")
	if not warehouse:
		frappe.throw(_("Set the Main warehouse in Production Settings."),
		             title=_("Main Warehouse Not Set"))
	return warehouse


def wip_warehouse():
	"""The shop floor: where Material Issues deliver and Material Returns collect from."""
	warehouse = _value("wip_warehouse")
	if not warehouse:
		frappe.throw(_("Set the WIP warehouse in Production Settings."),
		             title=_("WIP Warehouse Not Set"))
	return warehouse


def excluded_warehouses():
	if not _installed():
		return []
	return [row.warehouse for row in (get_settings().get("excluded_warehouses") or [])
	        if row.warehouse]


def capacity_check_enabled():
	return bool(cint(_value("merge_capacity_check")))


def _default_company():
	return (frappe.defaults.get_user_default("Company")
	        or frappe.db.get_single_value("Global Defaults", "default_company"))


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
	wip = _value("wip_warehouse")
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
