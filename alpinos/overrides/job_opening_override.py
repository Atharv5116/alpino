"""
Override for Job Opening to add skills and languages from Job Requisition to website context
"""

import frappe
from hrms.hr.doctype.job_opening.job_opening import JobOpening


class CustomJobOpening(JobOpening):
	"""Custom Job Opening class that adds skills and languages from Job Requisition"""
	
	def get_context(self, context):
		"""Override get_context to add skills and languages from Job Requisition"""
		# Call parent method first
		super().get_context(context)
		
		# Fetch skills and languages from Job Requisition if linked
		if self.job_requisition:
			try:
				job_requisition = frappe.get_doc("Job Requisition", self.job_requisition)
				
				# Fetch skills from Job Requisition
				skills = []
				if hasattr(job_requisition, "skills") and job_requisition.skills:
					for skill_row in job_requisition.skills:
						if skill_row.skill:
							# Skill name is stored in skill_name field, but since autoname is field:skill_name,
							# the name itself is the skill name. Try to get skill_name field, otherwise use name
							try:
								skill_name = frappe.db.get_value("Skill", skill_row.skill, "skill_name")
								if not skill_name:
									skill_name = skill_row.skill  # Fallback to name if skill_name is empty
							except:
								skill_name = skill_row.skill  # Fallback to name if Skill doesn't exist
							skills.append(skill_name)
				
				context.skills = skills
				
				# Fetch languages from Job Requisition
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
				# Job Requisition doesn't exist, set empty lists
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
			# No Job Requisition linked
			context.skills = []
			context.languages = []
		
		return context

