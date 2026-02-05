"""
Override for Job Applicant to change autoname from email to AHFPL#### format
"""

import frappe
from frappe.model.naming import make_autoname
from hrms.hr.doctype.job_applicant.job_applicant import JobApplicant


class CustomJobApplicant(JobApplicant):
	"""Custom Job Applicant class with AHFPL#### naming"""
	
	def validate(self):
		super().validate()
		self._validate_employment_dates()

	def autoname(self):
		"""Generate name in HR-JOBAP-##### format instead of email"""
		# Use HR-JOBAP-.##### format (HR-JOBAP-00001, HR-JOBAP-00002, etc.)
		self.name = make_autoname("HR-JOBAP-.#####", "Job Applicant")

	def _validate_employment_dates(self):
		if self.employment_start_date and self.employment_end_date:
			if self.employment_start_date == self.employment_end_date:
				frappe.throw("Start Date and End Date cannot be the same.")

