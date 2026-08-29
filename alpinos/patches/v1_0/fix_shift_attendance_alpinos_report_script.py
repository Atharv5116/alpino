import frappe


def execute():
	"""Give the Alpinos Shift Attendance report a report_script when it's missing.

	Some installs end up with report_type = Script Report but report_script = NULL,
	which makes safe_exec fail with: Not allowed source type: "NoneType".
	"""
	report_name = "Alpinos Shift Attendance"
	report = frappe.db.exists("Report", {"name": report_name})
	if not report:
		return

	current = frappe.db.get_value("Report", report_name, "report_script")
	if current:
		return

	# RestrictedPython blocks names starting with "_", so no _execute alias here.
	report_script = """def execute(filters=None):
\timport alpinos.alpinos_development.report.shift_attendance_alpinos.shift_attendance_alpinos as rpt
\treturn rpt.execute(filters)
"""
	# db_set to skip the usual validations.
	frappe.db.set_value("Report", report_name, "report_script", report_script, update_modified=True)
	frappe.db.commit()

