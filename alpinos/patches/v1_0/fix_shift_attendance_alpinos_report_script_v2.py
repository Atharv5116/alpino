import frappe


def execute():
	"""
	Fix report_script for `Alpinos Shift Attendance`.

	v1 used `_execute` as an import alias which RestrictedPython blocks
	(variable names starting with `_` are not allowed in safe_exec).
	This patch replaces it with a module-import wrapper that uses `rpt.execute`.
	"""
	report_name = "Alpinos Shift Attendance"
	if not frappe.db.exists("Report", {"name": report_name}):
		return

	# RestrictedPython disallows names starting with "_".
	# Use module-level import + attribute access instead of aliasing to _execute.
	report_script = (
		"def execute(filters=None):\n"
		"\timport alpinos.alpinos_development.report.shift_attendance_alpinos.shift_attendance_alpinos as rpt\n"
		"\treturn rpt.execute(filters)\n"
	)

	frappe.db.set_value("Report", report_name, "report_script", report_script, update_modified=True)
	frappe.db.commit()
