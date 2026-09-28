"""Custom fields for Material Management on ERPNext's Material Request and Stock Entry.

Created in code, like work_order_fields, and re-applied on every migrate. Nothing here
changes an existing field: the naming series options are only ever APPENDED to, and the
Work Order planning fields are only made editable after submit (see
_allow_planning_after_submit for why).
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

from alpinos.production import material_constants as M


def _select(values, blank=False):
	return ("\n" if blank else "") + "\n".join(values)


def _custom_fields():
	return {
		"Material Request": [
			{
				"fieldname": "custom_production_section",
				"label": "Production",
				"fieldtype": "Section Break",
				"insert_after": "set_warehouse",
				"collapsible": 0,
			},
			{
				"fieldname": "custom_sub_production_order",
				"label": "Sub Production Order",
				"fieldtype": "Link",
				"options": "Work Order",
				"insert_after": "custom_production_section",
				"in_standard_filter": 1,
				"no_copy": 1,
				"description": "The sub order these materials are requested for.",
			},
			{
				"fieldname": "custom_parent_production_order",
				"label": "Parent Production Order",
				"fieldtype": "Link",
				"options": "Production Order",
				"insert_after": "custom_sub_production_order",
				"read_only": 1,
				"in_standard_filter": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "custom_target_fg_item",
				"label": "Target FG Item",
				"fieldtype": "Link",
				"options": "Item",
				"insert_after": "custom_parent_production_order",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "custom_production_col",
				"fieldtype": "Column Break",
				"insert_after": "custom_target_fg_item",
			},
			{
				"fieldname": "custom_production_type",
				"label": "Production Type",
				"fieldtype": "Data",
				"insert_after": "custom_production_col",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "custom_mr_source",
				"label": "MR Source",
				"fieldtype": "Select",
				# No default: an MR raised anywhere else on the site is not ours and must
				# not be stamped as if it were.
				"options": _select(M.MR_SOURCES, blank=True),
				"insert_after": "custom_production_type",
				"read_only": 1,
				"no_copy": 1,
				"in_standard_filter": 1,
			},
			{
				"fieldname": "custom_mr_status",
				"label": "MR Status",
				"fieldtype": "Select",
				"options": _select(M.MR_STATUSES, blank=True),
				"insert_after": "custom_mr_source",
				"read_only": 1,
				"allow_on_submit": 1,
				"no_copy": 1,
				"in_standard_filter": 1,
			},
			{
				"fieldname": "custom_remarks",
				"label": "Remarks",
				"fieldtype": "Small Text",
				"insert_after": "custom_mr_status",
				"no_copy": 1,
			},
		],
		"Material Request Item": [
			{
				"fieldname": "custom_material_type",
				"label": "Material Type",
				"fieldtype": "Data",
				"insert_after": "item_name",
				"read_only": 1,
			},
			{
				"fieldname": "custom_standard_qty",
				"label": "Standard Qty",
				"fieldtype": "Float",
				"insert_after": "custom_material_type",
				"read_only": 1,
			},
			{
				"fieldname": "custom_available_qty",
				"label": "Available Stock",
				"fieldtype": "Float",
				"insert_after": "custom_standard_qty",
				"read_only": 1,
			},
			{
				"fieldname": "custom_shortage_qty",
				"label": "Shortage",
				"fieldtype": "Float",
				"insert_after": "custom_available_qty",
				"read_only": 1,
			},
			{
				"fieldname": "custom_issued_qty",
				"label": "Issued Qty",
				"fieldtype": "Float",
				"insert_after": "custom_shortage_qty",
				"read_only": 1,
				"allow_on_submit": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "custom_pending_qty",
				"label": "Pending Qty",
				"fieldtype": "Float",
				"insert_after": "custom_issued_qty",
				"read_only": 1,
				"allow_on_submit": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "custom_line_remarks",
				"label": "Remarks",
				"fieldtype": "Data",
				"insert_after": "custom_pending_qty",
			},
		],
		"Stock Entry": [
			{
				"fieldname": "custom_material_section",
				"label": "Production Material",
				"fieldtype": "Section Break",
				"insert_after": "stock_entry_type",
			},
			{
				"fieldname": "custom_entry_kind",
				"label": "Entry Kind",
				"fieldtype": "Select",
				"options": _select(M.ENTRY_KINDS, blank=True),
				"insert_after": "custom_material_section",
				"read_only": 1,
				"no_copy": 1,
				"in_standard_filter": 1,
			},
			{
				"fieldname": "custom_material_request",
				"label": "Material Request",
				"fieldtype": "Link",
				"options": "Material Request",
				"insert_after": "custom_entry_kind",
				"read_only": 1,
				"no_copy": 1,
				"in_standard_filter": 1,
			},
			{
				"fieldname": "custom_material_issue",
				"label": "Material Issue",
				"fieldtype": "Link",
				"options": "Stock Entry",
				"insert_after": "custom_material_request",
				"read_only": 1,
				"no_copy": 1,
				"description": "Set on a Material Return: the issue it returns against.",
			},
			{
				"fieldname": "custom_sub_production_order",
				"label": "Sub Production Order",
				"fieldtype": "Link",
				"options": "Work Order",
				"insert_after": "custom_material_issue",
				"read_only": 1,
				"no_copy": 1,
				"in_standard_filter": 1,
			},
			{
				"fieldname": "custom_material_col",
				"fieldtype": "Column Break",
				"insert_after": "custom_sub_production_order",
			},
			{
				"fieldname": "custom_parent_production_order",
				"label": "Parent Production Order",
				"fieldtype": "Link",
				"options": "Production Order",
				"insert_after": "custom_material_col",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "custom_target_fg_item",
				"label": "Target FG Item",
				"fieldtype": "Link",
				"options": "Item",
				"insert_after": "custom_parent_production_order",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "custom_production_type",
				"label": "Production Type",
				"fieldtype": "Data",
				"insert_after": "custom_target_fg_item",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "custom_return_reason_all",
				"label": "Set Reason For All Rows",
				"fieldtype": "Select",
				"options": _select(M.RETURN_REASONS, blank=True),
				"insert_after": "custom_production_type",
				"no_copy": 1,
				"depends_on": "eval:doc.custom_entry_kind=='Material Return'",
			},
		],
		"Stock Entry Detail": [
			{
				"fieldname": "custom_material_type",
				"label": "Material Type",
				"fieldtype": "Data",
				"insert_after": "item_name",
				"read_only": 1,
			},
			{
				"fieldname": "custom_required_qty",
				"label": "Total Required Qty",
				"fieldtype": "Float",
				"insert_after": "custom_material_type",
				"read_only": 1,
			},
			{
				"fieldname": "custom_available_qty",
				"label": "Available Qty",
				"fieldtype": "Float",
				"insert_after": "custom_required_qty",
				"read_only": 1,
			},
			{
				"fieldname": "custom_mr_item",
				"label": "MR Row",
				"fieldtype": "Data",
				"insert_after": "custom_available_qty",
				"read_only": 1,
				"hidden": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "custom_mi_detail",
				"label": "MI Row",
				"fieldtype": "Data",
				"insert_after": "custom_mr_item",
				"read_only": 1,
				"hidden": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "custom_previously_returned",
				"label": "Previously Returned",
				"fieldtype": "Float",
				"insert_after": "custom_mi_detail",
				"read_only": 1,
			},
			{
				"fieldname": "custom_balance_return",
				"label": "Balance",
				"fieldtype": "Float",
				"insert_after": "custom_previously_returned",
				"read_only": 1,
			},
			{
				"fieldname": "custom_return_reason",
				"label": "Return Reason",
				"fieldtype": "Select",
				"options": _select(M.RETURN_REASONS, blank=True),
				"insert_after": "custom_balance_return",
			},
			{
				"fieldname": "custom_line_remarks",
				"label": "Line Remarks",
				"fieldtype": "Data",
				"insert_after": "custom_return_reason",
			},
		],
	}


def _append_naming_series(doctype, series):
	"""Add these series to the doctype's naming_series options, keeping every existing one
	and the existing default (the first option) exactly where they are."""
	meta = frappe.get_meta(doctype)
	df = meta.get_field("naming_series")
	if not df:
		return
	options = (df.options or "").split("\n")
	missing = [s for s in series if s not in options]
	if not missing:
		return
	while options and not options[-1].strip():
		options.pop()
	make_property_setter(doctype, "naming_series", "options", "\n".join(options + missing),
	                     "Text", validate_fields_for_doctype=False)
	frappe.clear_cache(doctype=doctype)


#: The Work Order fields a submitted Sub PO still has to be able to change.
#:
#: generate_mr SUBMITS the Sub PO. If its MR is then cancelled with nothing issued, the Sub
#: PO goes back to Assigned and may be re-planned -- and re-planning saves these fields on a
#: document that is now submitted. Without allow_on_submit that save is refused.
_WO_PLANNING_FIELDS = (
	"custom_execution_status",
	"custom_assigned_process",
	"custom_assigned_machine",
	"custom_planned_date",
)


def _allow_planning_after_submit():
	for fieldname in _WO_PLANNING_FIELDS:
		name = frappe.db.get_value("Custom Field", {"dt": "Work Order", "fieldname": fieldname})
		if name and not frappe.db.get_value("Custom Field", name, "allow_on_submit"):
			frappe.db.set_value("Custom Field", name, "allow_on_submit", 1, update_modified=False)
	frappe.clear_cache(doctype="Work Order")


def setup_material_fields():
	create_custom_fields(_custom_fields(), ignore_validate=True)
	_append_naming_series("Material Request", [M.MR_NAMING_SERIES])
	_append_naming_series("Stock Entry", [M.MI_NAMING_SERIES, M.MRT_NAMING_SERIES])
	_allow_planning_after_submit()
	frappe.db.commit()


def execute():
	setup_material_fields()
