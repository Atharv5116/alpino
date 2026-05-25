"""
Patch to remove unused custom bank fields from Employee:
- bank_name_salary
- micr_code
- bank_cb
"""

import frappe


def execute():
    """Delete unused custom Employee bank fields and their DB columns."""
    custom_field_names = [
        "Employee-bank_name_salary",
        "Employee-micr_code",
        "Employee-bank_cb",
    ]

    # 1. Delete Custom Field records
    for cf_name in custom_field_names:
        if frappe.db.exists("Custom Field", cf_name):
            frappe.delete_doc("Custom Field", cf_name, force=True, ignore_permissions=True)

    # 2. Delete related Property Setter records on Employee
    fieldnames = ["bank_name_salary", "micr_code", "bank_cb"]
    prop_setter_names = frappe.get_all(
        "Property Setter",
        filters={"doc_type": "Employee", "field_name": ["in", fieldnames]},
        pluck="name",
    )

    for ps_name in prop_setter_names:
        frappe.delete_doc("Property Setter", ps_name, force=True, ignore_permissions=True)

    # 3. Drop columns from tabEmployee if they exist
    for fieldname in fieldnames:
        try:
            if frappe.db.has_column("Employee", fieldname):
                frappe.db.sql(f"ALTER TABLE `tabEmployee` DROP COLUMN `{fieldname}`")
        except Exception:
            # Don't break migrate if column is missing or DB backend differs
            frappe.log_error(
                title="Employee bank field drop failed",
                message=f"Could not drop column '{fieldname}' from tabEmployee",
            )

    frappe.clear_cache(doctype="Employee")

