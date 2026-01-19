"""
Override for Job Applicant to change autoname from email to CAND-#### format
"""

import frappe
from frappe.model.naming import make_autoname
from hrms.hr.doctype.job_applicant.job_applicant import JobApplicant


class CustomJobApplicant(JobApplicant):
	"""Custom Job Applicant class with CAND-#### naming"""
	
	def autoname(self):
		"""Generate name in CAND-#### format instead of email"""
		# Use CAND-.##### format (CAND-0001, CAND-0002, etc.)
		self.name = make_autoname("CAND-.#####", "Job Applicant")

