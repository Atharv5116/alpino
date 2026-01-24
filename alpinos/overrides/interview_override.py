"""
Override for Interview doctype to fix update_job_applicant_status function
This fixes the TypeError when calling the function with keyword arguments
All changes are kept in the alpinos app only - no modifications to HRMS app
"""

import frappe
from frappe import _


@frappe.whitelist()
def update_job_applicant_status(status: str = None, job_applicant: str = None, **kwargs):
	"""
	Override of hrms.hr.doctype.interview.interview.update_job_applicant_status
	Handles both keyword and positional arguments to fix TypeError
	"""
	# Handle both keyword and positional arguments
	if not status:
		status = kwargs.get('status')
	if not job_applicant:
		job_applicant = kwargs.get('job_applicant')
	
	try:
		if not job_applicant:
			frappe.throw(_("Please specify the job applicant to be updated."))
		if not status:
			frappe.throw(_("Please specify the status to be updated."))

		job_applicant_doc = frappe.get_doc("Job Applicant", job_applicant)
		job_applicant_doc.status = status
		job_applicant_doc.save()

		frappe.msgprint(
			_("Updated the Job Applicant status to {0}").format(job_applicant_doc.status),
			alert=True,
			indicator="green",
		)
	except Exception as e:
		frappe.log_error(f"Failed to update Job Applicant status: {str(e)}", "Update Job Applicant Status Error")
		frappe.msgprint(
			_("Failed to update the Job Applicant status"),
			alert=True,
			indicator="red",
		)


def setup_interview_override(bootinfo=None):
	"""
	Monkey patch the update_job_applicant_status function from HRMS
	This ensures all changes are in the alpinos app only
	This is called during after_migrate hook and boot_session hook
	bootinfo parameter is optional - provided by boot_session hook but not used
	"""
	try:
		# Import the HRMS module
		from hrms.hr.doctype.interview import interview as interview_module
		
		# Replace the function with our override
		interview_module.update_job_applicant_status = update_job_applicant_status
		
		frappe.logger().info("✅ Patched update_job_applicant_status function in Interview module")
		if not bootinfo:  # Only print during migration, not on every boot
			print("✅ Patched update_job_applicant_status function in Interview module")
	except Exception as e:
		frappe.log_error(f"Failed to patch update_job_applicant_status: {str(e)}", "Interview Override Error")
		if not bootinfo:  # Only print during migration, not on every boot
			print(f"⚠️  Could not patch update_job_applicant_status: {str(e)}")


# Patch immediately when module is imported (for immediate availability)
def _patch_on_import():
	"""Patch the function when this module is imported"""
	try:
		from hrms.hr.doctype.interview import interview as interview_module
		interview_module.update_job_applicant_status = update_job_applicant_status
		frappe.logger().info("✅ Patched update_job_applicant_status on import")
	except (ImportError, AttributeError) as e:
		# HRMS might not be installed or module not loaded yet
		# This is fine - setup_interview_override will handle it during migration
		pass
	except Exception as e:
		frappe.log_error(f"Error patching on import: {str(e)}", "Interview Override Import Error")

# Attempt to patch on import (for immediate availability after server restart)
try:
	_patch_on_import()
except:
	pass
