"""Custom fields on Employee.

  - salary_category : Link to the Salary Category master. Mapped 1:1 from the
    Employee Onboarding field of the same name when the Employee is created.

  - custom_confirmation_leaves_allocated : internal guard Check, set once the
    confirmation leave allocation (Casual/Bereavement/Restricted) has run for this
    employee so it never double-allocates. See
    alpinos.confirmation_leave_allocation.allocate_confirmation_leaves and
    alpinos.employee_confirmation.on_employee_update.

Created on every migrate via the after_migrate hook (setup_employee_custom_fields).
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def setup_employee_custom_fields():
	custom_fields = {
		"Employee": [
			dict(
				fieldname="salary_category",
				label="Salary Category",
				fieldtype="Link",
				options="Salary Category",
				insert_after="employment_type",
				description="Salary category for this employee (from the Salary Category master).",
			),
			dict(
				fieldname="custom_confirmation_leaves_allocated",
				label="Confirmation Leaves Allocated",
				fieldtype="Check",
				insert_after="salary_category",
				read_only=1,
				no_copy=1,
				print_hide=1,
				description="Set automatically once Casual/Bereavement/Restricted leave was allocated on confirmation. Prevents double allocation.",
			),
		]
	}

	try:
		create_custom_fields(custom_fields, update=True)
		frappe.db.commit()
		print("✅ Added Employee custom fields (salary_category, confirmation guard)")
	except Exception as e:
		print(f"⚠️  Could not add Employee custom fields: {str(e)}")
		frappe.log_error(
			f"Error adding Employee custom fields: {str(e)}\nTraceback: {frappe.get_traceback()}",
			"Add Employee Custom Fields",
		)
