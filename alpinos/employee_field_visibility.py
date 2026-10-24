"""Make the Employee 'Personal Email', 'IFSC Code' and 'Relieving Date' fields visible.

They were hidden by site-level Customize-Form Property Setters:
  - personal_email  -> hidden = 1
  - ifsc_code       -> only shown when salary_mode == "Bank" (depends_on)
  - relieving_date  -> sits in the Exit tab, which is hidden; it is moved to the Salary tab,
                       below Increment Cycle, and the Exit tab stays hidden

This overrides those so the fields are visible on the Employee form. Idempotent —
runs on every migrate via after_migrate.
"""

import json

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

	_move_relieving_date(meta)

	frappe.clear_cache(doctype="Employee")
	frappe.logger("alpinos").info("Made Employee personal_email + ifsc_code + relieving_date visible.")


def _move_relieving_date(meta):
	"""Put Relieving Date straight after Increment Cycle (Salary tab, left column).

	Works on the order the form already has (the site's field_order plus any custom
	fields), so nothing else moves. Frappe keeps that order in a DocType-level
	field_order Property Setter, which is updated here or created when there is none.
	"""
	if not (meta.has_field("relieving_date") and meta.has_field("increment_cycle")):
		return

	order = [d.fieldname for d in meta.fields if d.fieldname]
	if order.index("relieving_date") == order.index("increment_cycle") + 1:
		return
	order.remove("relieving_date")
	order.insert(order.index("increment_cycle") + 1, "relieving_date")

	name = frappe.db.get_value(
		"Property Setter",
		{"doc_type": "Employee", "property": "field_order", "doctype_or_field": "DocType"},
	)
	if name:
		frappe.db.set_value("Property Setter", name, "value", json.dumps(order))
	else:
		make_property_setter(
			"Employee", None, "field_order", json.dumps(order), "Data",
			for_doctype=True, validate_fields_for_doctype=False,
		)
