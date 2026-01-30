"""
Override for Job Applicant to change autoname from email to AHFPL#### format
"""

import frappe
from frappe.model.naming import make_autoname
from hrms.hr.doctype.job_applicant.job_applicant import JobApplicant


class CustomJobApplicant(JobApplicant):
	"""Custom Job Applicant class with AHFPL#### naming"""
	
	def autoname(self):
		"""Generate name in AHFPL#### format instead of email"""
		# Use AHFPL.##### format (AHFPL0001, AHFPL0002, etc.)
		self.name = make_autoname("AHFPL.#####", "Job Applicant")

