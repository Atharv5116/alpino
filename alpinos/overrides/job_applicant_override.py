"""Override Job Applicant autoname to HR-JOBAP-##### format instead of email."""

import frappe
from frappe.model.naming import make_autoname
from hrms.hr.doctype.job_applicant.job_applicant import JobApplicant


class CustomJobApplicant(JobApplicant):
	"""Job Applicant named as HR-JOBAP-##### instead of by email."""
	
	def validate(self):
		super().validate()
		self._validate_employment_dates()

	def autoname(self):
		"""Generate name in HR-JOBAP-##### format instead of email."""
		self.name = make_autoname("HR-JOBAP-.#####", "Job Applicant")

	def _validate_employment_dates(self):
		if self.employment_start_date and self.employment_end_date:
			if self.employment_start_date == self.employment_end_date:
				frappe.throw("Start Date and End Date cannot be the same.")

