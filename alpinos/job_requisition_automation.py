"""
Automation scripts for Job Requisition
- Auto-populate approved_on and approved_by on approval
- Auto-create Job Opening when status becomes Approved
- Sync status with Job Opening
"""

import frappe
from frappe import _
from frappe.utils import now


def update_approval_fields(doc, method=None):
	"""
	Auto-populate approved_on and approved_by when status changes to Approved
	"""
	# Check if status changed to Approved
	if doc.status == "Approved":
		# Only update if not already set
		if not doc.approved_on:
			doc.approved_on = now()
		
		if not doc.approved_by:
			# Get current user
			doc.approved_by = frappe.session.user


def create_job_opening_on_approval(doc, method=None):
	"""
	Auto-create Job Opening when Job Requisition status becomes Approved
	"""
	# Check if status changed to Approved
	if doc.status == "Approved":
		# Check if Job Opening already exists for this requisition
		existing_opening = frappe.db.exists("Job Opening", {"job_requisition": doc.name})
		
		if not existing_opening:
			try:
				# Import the make_job_opening function from HRMS
				from hrms.hr.doctype.job_requisition.job_requisition import make_job_opening
				
				# Create Job Opening
				job_opening = make_job_opening(doc.name)
				
				# Map additional fields
				if hasattr(doc, "location") and doc.location:
					job_opening.location = doc.location
				
				if hasattr(doc, "min_experience") and doc.min_experience:
					# Store min_experience in description or custom field
					# Note: Job Opening doesn't have min_experience field by default
					# We can add it to description or create a custom field
					pass
				
				if hasattr(doc, "ctc_upper_range") and doc.ctc_upper_range:
					job_opening.upper_range = doc.ctc_upper_range
				
				if hasattr(doc, "hiring_deadline") and doc.hiring_deadline:
					job_opening.closes_on = doc.hiring_deadline
				
				# Save Job Opening
				job_opening.insert(ignore_permissions=True)
				frappe.db.commit()
				
				frappe.msgprint(
					_("Job Opening {0} created successfully").format(
						frappe.bold(job_opening.name)
					),
					indicator="green"
				)
				
			except Exception as e:
				frappe.log_error(
					f"Error creating Job Opening for Job Requisition {doc.name}: {str(e)}",
					"Job Requisition Automation"
				)


def publish_job_opening_on_live(doc, method=None):
	"""
	Auto-publish Job Opening when Job Requisition status becomes Live
	"""
	if doc.status == "Live":
		# Find associated Job Opening
		job_opening = frappe.db.get_value("Job Opening", {"job_requisition": doc.name}, "name")
		
		if job_opening:
			try:
				# Update Job Opening to published
				frappe.db.set_value("Job Opening", job_opening, {
					"publish": 1,
					"status": "Open"
				})
				frappe.db.commit()
				
				frappe.msgprint(
					_("Job Opening {0} has been published on website").format(
						frappe.bold(job_opening)
					),
					indicator="green"
				)
				
			except Exception as e:
				frappe.log_error(
					f"Error publishing Job Opening {job_opening}: {str(e)}",
					"Job Requisition Automation"
				)


def sync_status_with_job_opening(doc, method=None):
	"""
	Sync status between Job Requisition and Job Opening
	"""
	# Find associated Job Opening
	job_opening = frappe.db.get_value("Job Opening", {"job_requisition": doc.name}, "name")
	
	if job_opening:
		# Map status values
		status_mapping = {
			"Approved": "Open",
			"Live": "Open",
			"Rejected": "Closed",
			"On Hold": "Open"
		}
		
		if doc.status in status_mapping:
			try:
				frappe.db.set_value("Job Opening", job_opening, {
					"status": status_mapping[doc.status]
				})
				frappe.db.commit()
			except Exception as e:
				frappe.log_error(
					f"Error syncing status for Job Opening {job_opening}: {str(e)}",
					"Job Requisition Automation"
				)
