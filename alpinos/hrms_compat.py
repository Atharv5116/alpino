"""HRMS differences between v15 and v16 that more than one module has to step around."""

import frappe


def interview_round_meta():
	"""(doctype, name field, Interview link field) of an interview round on this HRMS.

	v16 folded Interview Round into Interview Type: the round's designation, skill set and
	interviewers now live on Interview Type, named by interview_type_name, and Interview
	links to it through interview_type. The Interview Round table can outlive the upgrade,
	so the test is whether Interview still has the field, not whether the table exists.
	"""
	if frappe.get_meta("Interview").has_field("interview_round"):
		return "Interview Round", "round_name", "interview_round"
	return "Interview Type", "interview_type_name", "interview_type"


def ensure_round_as_interview_type(round_name, description=None):
	"""On v16, the Interview Type that stands in for an alpinos interview round.

	Returns the stored name; MariaDB matches names case-insensitively, so a
	"Pre-Onboarding" type made on v15 is reused for the "pre-onboarding" round.
	"""
	existing = frappe.db.get_value("Interview Type", round_name, "name")
	if existing:
		return existing
	doc = frappe.get_doc({
		"doctype": "Interview Type",
		"interview_type_name": round_name,
		"description": description or round_name,
	})
	doc.flags.ignore_mandatory = True
	doc.insert(ignore_permissions=True)
	return doc.name


def _assignment_lookup():
	"""HRMS v16's Holiday List Assignment lookups, or None on v15 (which has neither)."""
	import hrms.utils.holiday_list as hl

	if hasattr(hl, "get_holiday_list_for_employee") and hasattr(hl, "get_assigned_holiday_list"):
		return hl
	return None


def employee_holiday_list(employee, on_date, v15_holiday_list):
	"""The employee's holiday list on `on_date`.

	HRMS v16 resolves it from Holiday List Assignments (the employee's own, else the
	company's) and no longer reads Employee.holiday_list, which HR stops maintaining. On v15
	this returns `v15_holiday_list` untouched, so each caller keeps the rule it had.
	"""
	hl = _assignment_lookup()
	if not hl:
		return v15_holiday_list
	return hl.get_holiday_list_for_employee(employee, raise_exception=False, as_on=on_date)


def company_holiday_list(company, on_date, v15_holiday_list):
	"""The company's holiday list on `on_date`; on v16 its assignment, else the old field."""
	hl = _assignment_lookup()
	if not hl:
		return v15_holiday_list
	return hl.get_assigned_holiday_list(company, as_on=on_date) or v15_holiday_list
