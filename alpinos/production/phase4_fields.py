"""Phase 4+ groundwork setup (Execution / QC / Filling / Inventory).

setup_phase4_fields   -- Work Order fields (custom_completed_processes, custom_current_run,
                         custom_wip_qty), Item custom_pack_size_kg, and the default values of
                         the new Production Settings rules.
run_builder_setups    -- calls each builder's own setup (execution_setup.setup_execution,
                         filling_setup.setup_filling, inventory_setup.setup_inventory) if
                         that module exists; a missing module is skipped, a failing one is
                         logged and never stops the migrate.
setup_phase4_access   -- workspace shortcuts + page access for the new screens (in
                         alpinos.production.workspace); re-run every migrate, so pages that
                         do not exist yet are picked up later.
"""

import importlib

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

PACK_SIZE_FIELD = "custom_pack_size_kg"

#: (module, function) of each builder's setup, in run order.
BUILDER_SETUPS = (
	("alpinos.production.execution_setup", "setup_execution"),
	("alpinos.production.filling_setup", "setup_filling"),
	("alpinos.production.inventory_setup", "setup_inventory"),
)


def _item_fields():
	from alpinos.production.item_fields import ALLOWED_CATEGORIES_FIELD, MATERIAL_TYPE_FIELD

	return {
		"Item": [
			{
				"fieldname": PACK_SIZE_FIELD,
				"label": "Pack Size (KG)",
				"fieldtype": "Float",
				"precision": "3",
				"insert_after": ALLOWED_CATEGORIES_FIELD,
				"depends_on": f"eval:doc.{MATERIAL_TYPE_FIELD}=='FG'",
				# default pending BA confirmation: pack size kept on the FG Item in KG.
				"description": "Net weight of one pack in KG, e.g. 0.4 for 400 g. FG items only.",
			},
		],
	}


def _settings_defaults():
	"""Fill the rule defaults once, only where the Single has never stored a value."""
	if not frappe.db.exists("DocType", "Production Settings"):
		return
	for fieldname, default in (("filling_wastage_tolerance_pct", 5),
	                           ("adjustment_approval_kg", 500),
	                           ("standard_batch_size_kg", 50)):
		# tabSingles has no `modified` column, so get_value's default ORDER BY fails on it.
		stored = frappe.db.sql(
			"select value from tabSingles where doctype=%s and field=%s",
			("Production Settings", fieldname))
		stored = stored[0][0] if stored else None
		if stored in (None, ""):
			frappe.db.set_single_value("Production Settings", fieldname, default)


def setup_phase4_fields():
	from alpinos.production.work_order_fields import phase4_custom_fields

	steps = (
		("Work Order fields", lambda: create_custom_fields(
			phase4_custom_fields(
				include_current_run=bool(frappe.db.exists("DocType", "Production Run"))),
			ignore_validate=True, update=True)),
		("Item fields", lambda: create_custom_fields(
			_item_fields(), ignore_validate=True, update=True)),
		("Production Settings defaults", _settings_defaults),
	)
	for label, step in steps:
		try:
			step()
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"Phase 4 setup: {label}")
	frappe.db.commit()


def run_builder_setups():
	for module_name, function_name in BUILDER_SETUPS:
		try:
			module = importlib.import_module(module_name)
		except ModuleNotFoundError as e:
			if e.name == module_name:
				continue  # that builder has not shipped its setup yet
			frappe.log_error(frappe.get_traceback(), f"Phase 4 setup: import {module_name}")
			continue
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"Phase 4 setup: import {module_name}")
			continue
		fn = getattr(module, function_name, None)
		if not callable(fn):
			continue
		try:
			fn()
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(frappe.get_traceback(), f"Phase 4 setup: {module_name}.{function_name}")


def setup_phase4_access():
	from alpinos.production import workspace

	for label, fn in (("page access", workspace.setup_phase4_page_access),
	                  ("workspace", workspace.setup_production_workspace)):
		try:
			fn()
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"Phase 4 setup: {label}")
	frappe.db.commit()
