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
