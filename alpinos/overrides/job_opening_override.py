"""Override Job Opening to add Job Requisition skills and languages to the website context."""

import frappe
from hrms.hr.doctype.job_opening.job_opening import JobOpening


class CustomJobOpening(JobOpening):
	"""Job Opening that surfaces Job Requisition skills, languages and salary range on the website."""

	def validate(self):
		super().validate()
		self._sync_salary_range()

	def _sync_salary_range(self):
		"""Inherit the salary range from the linked Job Requisition and publish it on the website."""
		if self.job_requisition:
			jr = frappe.db.get_value(
				"Job Requisition",
				self.job_requisition,
				["expected_compensation", "ctc_upper_range"],
				as_dict=True,
			)
			if jr:
				if not self.lower_range and jr.expected_compensation:
					self.lower_range = jr.expected_compensation
				if not self.upper_range and jr.ctc_upper_range:
					self.upper_range = jr.ctc_upper_range

		if self.lower_range or self.upper_range:
			self.publish_salary_range = 1

	def get_context(self, context):
		"""Add skills and languages from the linked Job Requisition to the website context."""
		super().get_context(context)

		if self.job_requisition:
			try:
				job_requisition = frappe.get_doc("Job Requisition", self.job_requisition)
				
				skills = []
				if hasattr(job_requisition, "skills") and job_requisition.skills:
					for skill_row in job_requisition.skills:
						if skill_row.skill:
							# Skill autoname is field:skill_name, so the id usually is the label; look it up, fall back to the id.
							try:
								skill_name = frappe.db.get_value("Skill", skill_row.skill, "skill_name")
								if not skill_name:
									skill_name = skill_row.skill  # Fallback to name if skill_name is empty
							except:
								skill_name = skill_row.skill  # Fallback to name if Skill doesn't exist
							skills.append(skill_name)
				
				context.skills = skills
				
				languages = []
				if hasattr(job_requisition, "languages") and job_requisition.languages:
					for lang_row in job_requisition.languages:
						if lang_row.language_name:
							lang_info = {
								"name": lang_row.language_name,
								"read": lang_row.read or False,
								"write": lang_row.write or False,
								"speak": lang_row.speak or False
							}
							languages.append(lang_info)
				
				context.languages = languages
				
			except frappe.DoesNotExistError:
				context.skills = []
				context.languages = []
			except Exception as e:
				frappe.log_error(
					f"Error fetching skills/languages from Job Requisition {self.job_requisition}: {str(e)}",
					"Job Opening Website Context Error"
				)
				context.skills = []
				context.languages = []
		else:
			context.skills = []
			context.languages = []
		
		return context

