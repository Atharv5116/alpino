"""
Override for Interview doctype to fix update_job_applicant_status function
This fixes the TypeError when calling the function with keyword arguments
All changes are kept in the alpinos app only - no modifications to HRMS app
"""

import frappe
from frappe import _
from hrms.hr.doctype.interview.interview import Interview as HRMSInterview

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


class CustomInterview(HRMSInterview):
	"""
	Override Interview to allow submission for any status.
	"""

	def before_submit(self):
		if getattr(self, "status", None) not in ["Cleared", "Rejected"]:
			self._alpinos_original_status = self.status
			self.status = "Rejected"

	def on_submit(self):
		original_status = getattr(self, "_alpinos_original_status", None)
		if original_status:
			self.db_set("status", original_status, update_modified=False)
		self.show_job_applicant_update_dialog()


def allow_submit_any_status_before_submit(doc, method=None):
	"""
	Temporarily set status to Rejected so HRMS validation passes.
	Original status is restored in on_submit hook.
	"""
	if getattr(doc, "status", None) not in ["Cleared", "Rejected"]:
		frappe.logger().info(
			f"[alpinos] Interview before_submit override: {doc.name} status "
			f"{doc.status} -> Rejected"
		)
		doc._alpinos_original_status = doc.status
		doc.status = "Rejected"


def restore_status_after_submit(doc, method=None):
	"""
	Restore original status after successful submit.
	"""
	original_status = getattr(doc, "_alpinos_original_status", None)
	if original_status:
		frappe.logger().info(
			f"[alpinos] Interview on_submit restore: {doc.name} status "
			f"Rejected -> {original_status}"
		)
		doc.db_set("status", original_status, update_modified=False)


@frappe.whitelist()
def debug_interview_controller(name: str) -> dict:
	"""Return controller class info for debugging."""
	doc = frappe.get_doc("Interview", name)
	return {
		"class": f"{doc.__class__.__module__}.{doc.__class__.__name__}",
		"status": doc.status,
		"docstatus": doc.docstatus,
	}


@frappe.whitelist()
def debug_interview_on_submit_handler() -> dict:
	"""Return the active Interview.on_submit handler."""
	from hrms.hr.doctype.interview import interview as interview_module

	handler = interview_module.Interview.on_submit
	return {"on_submit": f"{handler.__module__}.{handler.__qualname__}"}


@frappe.whitelist()
def debug_call_on_submit(name: str) -> dict:
	"""Call on_submit directly to see if it throws."""
	doc = frappe.get_doc("Interview", name)
	try:
		doc.on_submit()
		return {"ok": True}
	except Exception as exc:
		return {"ok": False, "error": str(exc)}


@frappe.whitelist()
def debug_interview_doc_events() -> dict:
	"""Return doc_events hooks for Interview."""
	hooks = frappe.get_hooks("doc_events") or {}
	return {"Interview": hooks.get("Interview")}


@frappe.whitelist()
def debug_submit_interview(name: str) -> dict:
	"""Attempt to submit an Interview and return any error."""
	doc = frappe.get_doc("Interview", name)
	try:
		doc.submit()
		return {"ok": True, "status": doc.status}
	except Exception:
		return {
			"ok": False,
			"status": doc.status,
			"traceback": frappe.get_traceback(),
		}


@frappe.whitelist()
def debug_submit_via_savedocs(name: str) -> dict:
	"""Submit Interview through savedocs to mirror UI submit."""
	from frappe.desk.form.save import savedocs

	doc = frappe.get_doc("Interview", name)
	doc_dict = doc.as_dict()
	doc_dict["docstatus"] = 1
	try:
		out = savedocs(doc=frappe.as_json(doc_dict), action="Submit")
		return {"ok": True, "out": out}
	except Exception:
		return {"ok": False, "traceback": frappe.get_traceback()}


@frappe.whitelist()
def debug_find_interview_custom_scripts() -> list[dict]:
	"""List Client Scripts for Interview."""
	return frappe.get_all(
		"Client Script",
		filters={"dt": "Interview"},
		fields=["name", "enabled", "script"],
	)


@frappe.whitelist()
def debug_find_server_scripts_with_message() -> list[dict]:
	"""Find Server Scripts containing the submit validation message."""
	return frappe.db.get_all(
		"Server Script",
		filters={"script": ["like", "%Cleared or Rejected%"]},
		fields=["name", "script_type", "script"],
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
		if hasattr(interview_module, "Interview"):
			interview_module.Interview.on_submit = CustomInterview.on_submit
		
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
		if hasattr(interview_module, "Interview"):
			interview_module.Interview.on_submit = CustomInterview.on_submit
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
