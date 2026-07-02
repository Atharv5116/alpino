"""Move the 'No Biometric' preference from Company to Employee.

Employees of the same company can have different biometric preferences, so the flag now
lives on Employee. This one-time patch carries the old company-level setting onto each of
that company's employees, then removes the now-unused Company custom field.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field


def execute():
	# 1. Ensure the per-employee field exists (after_migrate creates it too, but the backfill
	#    below needs the column to exist now).
	if not frappe.db.exists("Custom Field", {"dt": "Employee", "fieldname": "custom_no_biometric"}):
		create_custom_field(
			"Employee",
			dict(
				fieldname="custom_no_biometric",
				label="No Biometric",
				fieldtype="Check",
				insert_after="category",
				default=0,
			),
		)

	# 2. Carry the old company-level value onto employees (don't clobber any already set).
	company_cols = [c.get("Field") for c in frappe.db.sql("SHOW COLUMNS FROM `tabCompany`", as_dict=True)]
	if "custom_no_biometric" in company_cols:
		companies = [
			r[0]
			for r in frappe.db.sql(
				"SELECT name FROM `tabCompany` WHERE IFNULL(custom_no_biometric, 0) = 1"
			)
		]
		if companies:
			frappe.db.sql(
				"""
				UPDATE `tabEmployee` SET custom_no_biometric = 1
				WHERE company IN %(c)s AND IFNULL(custom_no_biometric, 0) = 0
				""",
				{"c": companies},
			)

	# 3. Remove the now-unused Company-level custom field.
	cf = frappe.db.get_value("Custom Field", {"dt": "Company", "fieldname": "custom_no_biometric"}, "name")
	if cf:
		frappe.delete_doc("Custom Field", cf, force=1, ignore_permissions=True)

	frappe.db.commit()
	print("✅ Moved 'No Biometric' from Company to Employee")
