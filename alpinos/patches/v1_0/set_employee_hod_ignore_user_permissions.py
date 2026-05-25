import frappe


def execute():
    """Ensure Employee.hod custom field ignores user permissions.

    This prevents User Permission rules on Employee from hiding Employee
    records just because the HOD link points to a different employee.
    """
    cf_name = frappe.db.get_value(
        "Custom Field",
        {"dt": "Employee", "fieldname": "hod"},
        "name",
    )

    if not cf_name:
        return

    cf = frappe.get_doc("Custom Field", cf_name)
    if not getattr(cf, "ignore_user_permissions", 0):
        cf.ignore_user_permissions = 1
        cf.save(ignore_permissions=True)

