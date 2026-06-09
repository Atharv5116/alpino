"""Keep employee salary confidential from the reporting hierarchy.

Two parts:

  1. Salary Slip is limited to the owning employee — managers (HOD / RM) never see a
     subordinate's slip via the team/subordinate visibility. HR Manager and HR User (the
     payroll roles) still see everything. Enforced through permission_query_conditions
     (list views) + has_permission (single document).

  2. The Employee salary section fields are moved to permission level 1, and only the HR
     roles are granted that level — so a manager who can open a subordinate's Employee record
     (via User Permissions) still cannot see the compensation fields.

setup_employee_salary_field_permissions runs on every migrate (after_migrate hook).
"""

import frappe


# Roles allowed to see all salary (slips + Employee salary fields). Everyone else is limited
# to their own employee record.
SALARY_ADMIN_ROLES = ("HR Manager", "HR User")

# Core Employee compensation fields always kept behind permission level 1. The full set is
# discovered dynamically (every field under the "Salary" tab) so custom salary fields are
# covered too — see _employee_salary_fields().
EMPLOYEE_SALARY_FIELDS = (
	"ctc",
	"salary_mode",
	"salary_currency",
	"payroll_cost_center",
	"salary_category",
)


def _is_salary_admin(user):
	return user == "Administrator" or bool(set(SALARY_ADMIN_ROLES) & set(frappe.get_roles(user)))


def _employee_for_user(user):
	return frappe.db.get_value("Employee", {"user_id": user}, "name")


# --------------------------------------------------------------------------- Salary Slip


def salary_slip_query_conditions(user=None):
	"""permission_query_conditions hook: restrict Salary Slip lists to the user's own employee."""
	user = user or frappe.session.user
	if _is_salary_admin(user):
		return ""
	employee = _employee_for_user(user)
	if employee:
		return f"`tabSalary Slip`.`employee` = {frappe.db.escape(employee)}"
	# No linked employee -> see nothing (a condition that never matches).
	return "1=0"


def salary_slip_has_permission(doc, user=None, permission_type=None):
	"""has_permission hook: a non-admin user may only access their own salary slip."""
	user = user or frappe.session.user
	if _is_salary_admin(user):
		return True
	employee = _employee_for_user(user)
	return bool(employee) and doc.get("employee") == employee


# --------------------------------------------------------------- Employee salary field perms


def _employee_salary_fields(meta):
	"""Every field under the Employee "Salary" tab, plus the core compensation fields.

	Discovered dynamically so the custom salary fields on this site (CTC Monthly, Pay Frequency,
	bank details, etc.) are covered without hard-coding their names. Walks the doctype's field
	order: once inside a Tab Break labelled "Salary", every data field belongs to the section
	until the next Tab Break.
	"""
	names = set(EMPLOYEE_SALARY_FIELDS)
	in_salary = False
	skip = {"Column Break", "Section Break", "Tab Break", "HTML", "Heading"}
	for f in meta.fields:
		if f.fieldtype == "Tab Break":
			in_salary = "salary" in (f.label or f.fieldname or "").lower()
			continue
		if in_salary and f.fieldtype not in skip:
			names.add(f.fieldname)
	return {n for n in names if meta.has_field(n)}


def setup_employee_salary_field_permissions():
	"""Move all Employee Salary-tab fields to permlevel 1 and grant that level to the HR roles."""
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter
	from frappe.permissions import add_permission, update_permission_property

	try:
		meta = frappe.get_meta("Employee")
		fields = _employee_salary_fields(meta)
		for fieldname in fields:
			make_property_setter(
				"Employee", fieldname, "permlevel", 1, "Int",
				validate_fields_for_doctype=False,
			)

		# Grant permission level 1 (read + write) to the HR roles so they keep salary access.
		for role in SALARY_ADMIN_ROLES:
			add_permission("Employee", role, 1)
			update_permission_property("Employee", role, 1, "read", 1)
			update_permission_property("Employee", role, 1, "write", 1)

		frappe.clear_cache(doctype="Employee")
		frappe.db.commit()
		print(f"✅ Restricted {len(fields)} Employee salary fields to permlevel 1 (HR roles only)")
	except Exception as e:
		print(f"⚠️  Could not set up Employee salary field permissions: {str(e)}")
		frappe.log_error(frappe.get_traceback(), "Employee salary field permissions")
