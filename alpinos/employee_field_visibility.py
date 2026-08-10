"""Make the Employee 'Personal Email' and 'IFSC Code' fields visible.

Both were hidden by site-level Customize-Form Property Setters:
  - personal_email  -> hidden = 1
  - ifsc_code       -> only shown when salary_mode == "Bank" (depends_on)

This overrides those so the fields are visible on the Employee form. Idempotent —
runs on every migrate via after_migrate.
"""

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def execute():
	meta = frappe.get_meta("Employee")

	# Personal Email: unhide.
	if meta.has_field("personal_email"):
		make_property_setter(
			"Employee", "personal_email", "hidden", 0, "Check",
			validate_fields_for_doctype=False,
		)

	# IFSC Code: always visible (drop the "salary_mode == Bank" condition).
	if meta.has_field("ifsc_code"):
		make_property_setter(
			"Employee", "ifsc_code", "depends_on", "", "Data",
			validate_fields_for_doctype=False,
		)

	frappe.clear_cache(doctype="Employee")
	frappe.logger("alpinos").info("Made Employee personal_email + ifsc_code visible.")
