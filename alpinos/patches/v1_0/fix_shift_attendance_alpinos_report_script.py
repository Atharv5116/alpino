import frappe


def execute():
	"""
	Ensure `Alpinos Shift Attendance` Report has a valid `report_script`.

	Some installations end up with `report_type = Script Report` but `report_script = NULL`,
	which causes RestrictedPython safe_exec to fail with:
		TypeError: Not allowed source type: "NoneType".
	"""
	report_name = "Alpinos Shift Attendance"
	report = frappe.db.exists("Report", {"name": report_name})
	if not report:
		return

	current = frappe.db.get_value("Report", report_name, "report_script")
	if current:
		return

	# Wrapper kept intentionally small; it imports and delegates to our module implementation.
	# (Imports are allowed in Frappe script reports' RestrictedPython environment.)
	report_script = """def execute(filters=None):
\tfrom alpinos.alpinos_development.report.shift_attendance_alpinos.shift_attendance_alpinos import execute as _execute
\treturn _execute(filters)
"""
	# Use db_set to avoid triggering any additional validations.
	frappe.db.set_value("Report", report_name, "report_script", report_script, update_modified=True)
	frappe.db.commit()

