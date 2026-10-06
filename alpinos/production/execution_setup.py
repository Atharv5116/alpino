"""after_migrate setup for Production Execution + Production QC (Builder 1).

Registered in hooks.py as "alpinos.production.execution_setup.setup_execution".

    * Stock Entry custom_process_inward / custom_production_qc -- the read-only links that
      tie a stock entry posted by an Inward Entry / a Production QC back to it.
    * Print format "Production Order Print".

Naming of Production Run / Process Inward / Production QC is the doctype autoname
(PRUN- / PINW- / PQCP-.YYYY.-.#####), so no naming series has to be appended anywhere.
Permissions are in alpinos.production.phase4_permissions.EXECUTION_PERMS.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from alpinos.production.execution_common import SE_INWARD_FIELD, SE_QC_FIELD


def _stock_entry_fields():
	meta = frappe.get_meta("Stock Entry")
	anchor = next((f for f in ("custom_material_issue", "custom_sub_production_order", "custom_entry_kind")
	               if meta.has_field(f)), "stock_entry_type")
	return {
		"Stock Entry": [
			{
				"fieldname": SE_INWARD_FIELD,
				"label": "Process Inward",
				"fieldtype": "Link",
				"options": "Process Inward",
				"insert_after": anchor,
				"read_only": 1,
				"no_copy": 1,
				"allow_on_submit": 1,
				"description": "Set on the stock entry an Inward Entry posted.",
			},
			{
				"fieldname": SE_QC_FIELD,
				"label": "Production QC",
				"fieldtype": "Link",
				"options": "Production QC",
				"insert_after": SE_INWARD_FIELD,
				"read_only": 1,
				"no_copy": 1,
				"allow_on_submit": 1,
				"description": "Set on the rejection transfer a Production QC posted.",
			},
		],
	}


def setup_execution():
	try:
		create_custom_fields(_stock_entry_fields(), ignore_validate=True)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Execution setup: Stock Entry fields")
	try:
		from alpinos.production.execution_print import setup_production_order_print

		setup_production_order_print()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Execution setup: Production Order Print")
	frappe.db.commit()
