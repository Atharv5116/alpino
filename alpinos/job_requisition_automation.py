"""
Automation scripts for Job Requisition
- Auto-populate approved_on and approved_by on approval
- Auto-create Job Opening when status becomes Approved
- Sync status with Job Opening
"""

import frappe
from frappe import _
from frappe.utils import now


def set_requested_by(doc, method=None):
	"""
	Auto-populate custom_requested_by field and fetch requestor's employee record
	"""
	if not doc.custom_requested_by:
		doc.custom_requested_by = frappe.session.user
	
	# Fetch the employee record of the requestor
	if doc.custom_requested_by and not doc.requested_by_employee:
		employee = frappe.db.get_value("Employee", {"user_id": doc.custom_requested_by}, "name")
		if employee:
			doc.requested_by_employee = employee
			
			# Fetch the requestor's reporting manager
			reports_to = frappe.db.get_value("Employee", employee, "reports_to")
			if reports_to:
				doc.requestor_reporting_manager = reports_to
				
				# Fetch the User ID of the reporting manager for workflow
				manager_user_id = frappe.db.get_value("Employee", reports_to, "user_id")
				if manager_user_id:
					doc.requestor_manager_user = manager_user_id


def fetch_reporting_manager(doc, method=None):
	"""
	Auto-fetch reporting managers:
	1. Requestor's manager (always, for primary workflow)
	2. Linked employee's manager (if replacement position)
	"""
	# Always fetch requestor's manager if requestor is set
	if doc.custom_requested_by:
		requestor_employee = frappe.db.get_value("Employee", {"user_id": doc.custom_requested_by}, "name")
		if requestor_employee:
			doc.requested_by_employee = requestor_employee
			
			# Fetch requestor's reporting manager
			requestor_manager = frappe.db.get_value("Employee", requestor_employee, "reports_to")
			if requestor_manager:
				doc.requestor_reporting_manager = requestor_manager
				
				# Fetch User ID for workflow
				manager_user_id = frappe.db.get_value("Employee", requestor_manager, "user_id")
				if manager_user_id:
					doc.requestor_manager_user = manager_user_id
	
	# If there's a linked employee (replacement position), fetch their manager too
	if doc.linked_employee:
		linked_emp_manager = frappe.db.get_value("Employee", doc.linked_employee, "reports_to")
		if linked_emp_manager:
			doc.reporting_manager = linked_emp_manager
			
			# Fetch User ID
			user_id = frappe.db.get_value("Employee", linked_emp_manager, "user_id")
			if user_id:
				doc.reporting_manager_user = user_id


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


def create_published_job_opening_on_live(doc, method=None):
	"""
	Auto-create PUBLISHED Job Opening when Job Requisition status becomes Live
	"""
	# Check if status changed to Live
	if doc.status == "Live":
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
				
				# Set to published
				job_opening.publish = 1
				job_opening.status = "Open"
				
				# Save Job Opening (job_application_route will be set by before_save hook)
				job_opening.insert(ignore_permissions=True)
				frappe.db.commit()
				
				frappe.msgprint(
					_("Published Job Opening {0} created successfully").format(
						frappe.bold(job_opening.name)
					),
					indicator="green"
				)
				
			except Exception as e:
				frappe.log_error(
					f"Error creating Job Opening for Job Requisition {doc.name}: {str(e)}",
					"Job Requisition Automation"
				)


def update_job_requisition_on_publish(doc, method=None):
	"""
	Update Job Requisition to Live when Job Opening is published
	This is called from Job Opening doc_events
	"""
	if doc.publish == 1 and doc.job_requisition:
		try:
			# Get the Job Requisition
			job_req = frappe.get_doc("Job Requisition", doc.job_requisition)
			
			# Only update if it's currently Approved (not already Live)
			if job_req.status == "Approved":
				job_req.status = "Live"
				job_req.save(ignore_permissions=True)
				frappe.db.commit()
				
				frappe.msgprint(
					_("Job Requisition {0} has been set to Live").format(
						frappe.bold(doc.job_requisition)
					),
					indicator="green"
				)
				
		except Exception as e:
			frappe.log_error(
				f"Error updating Job Requisition {doc.job_requisition} to Live: {str(e)}",
				"Job Opening Publish Automation"
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
