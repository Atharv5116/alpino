"""Seed the default Salary Category records (run on migrate)."""

import frappe

# (category_name, attendance_rule_engine, description)
DEFAULT_CATEGORIES = (
	(
		"HO/Admin Staff",
		"HO/Admin",
		"Head Office / Admin staff — percentage-based attendance rules "
		"(97%/50% full/half day, late groups, WFH, comp-off).",
	),
	(
		"WH ESSL Staff",
		"WH ESSL",
		"Warehouse biometric staff — minute-based OT/EL attendance rules.",
	),
	(
		"Offline Sales Officer",
		"Offline Sales",
		"Field sales officers — attendance uploaded monthly by HR via Excel.",
	),
)


def seed_salary_categories():
	"""Create the default categories; backfill the engine on existing ones."""
	if not frappe.db.exists("DocType", "Salary Category"):
		return

	for name, engine, description in DEFAULT_CATEGORIES:
		if frappe.db.exists("Salary Category", name):
			# Keep the engine current (may be blank on pre-existing rows).
			if frappe.db.get_value("Salary Category", name, "attendance_rule_engine") != engine:
				frappe.db.set_value("Salary Category", name, "attendance_rule_engine", engine)
			continue
		frappe.get_doc(
			{
				"doctype": "Salary Category",
				"category_name": name,
				"attendance_rule_engine": engine,
				"description": description,
			}
		).insert(ignore_permissions=True)

	frappe.db.commit()
