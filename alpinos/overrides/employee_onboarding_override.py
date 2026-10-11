"""Override Employee Onboarding to skip holiday_list validation, and to key an onboarding on its
Job Applicant when it has no Job Offer (how alpinos onboards)."""

import frappe
from frappe import _
from hrms.hr.doctype.employee_onboarding.employee_onboarding import EmployeeOnboarding
from erpnext.setup.doctype.employee.employee import get_holiday_list_for_employee

from alpinos.query_compat import IS_V16


class CustomEmployeeOnboarding(EmployeeOnboarding):
	def get_holiday_list(self):
		"""Return the holiday list, or None instead of throwing when none is set."""
		if self.doctype == "Employee Separation":
			return get_holiday_list_for_employee(self.employee)
		else:
			if self.employee:
				return get_holiday_list_for_employee(self.employee)
			else:
				return self.holiday_list if self.holiday_list else None

	# HRMS 16 looks the employee up, and refuses a duplicate onboarding, by Job Offer (HRMS 15
	# used the Job Applicant). alpinos onboards straight from the Job Applicant with no Job Offer,
	# so with job_offer empty the lookup matched any employee without one (linking the onboarding
	# to an unrelated employee) and every onboarding after the first was refused as a duplicate
	# "for Job Offer: None". Use the Job Offer when there is one, else the Job Applicant.
	def _onboarding_key(self):
		if self.job_offer:
			return "job_offer", self.job_offer, _("Job Offer")
		return "job_applicant", self.job_applicant, _("Job Applicant")

	def set_employee(self):
		if not IS_V16:
			return super().set_employee()
		if self.employee:
			return
		field, value, _label = self._onboarding_key()
		if value:
			self.employee = frappe.db.get_value("Employee", {field: value}, "name")

	def validate_duplicate_employee_onboarding(self):
		if not IS_V16:
			return super().validate_duplicate_employee_onboarding()
		field, value, label = self._onboarding_key()
		if not value:
			return
		existing = frappe.db.exists("Employee Onboarding", {field: value, "docstatus": ("!=", 2)})
		if existing and existing != self.name:
			frappe.throw(
				_("Employee Onboarding: {0} already exists for {1}: {2}").format(
					frappe.bold(existing), label, frappe.bold(value)
				)
			)
