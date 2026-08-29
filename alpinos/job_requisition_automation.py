"""Automation hooks for Job Requisition (approval fields, Job Opening creation, status sync)."""

import frappe
from frappe import _
from frappe.utils import getdate, now


def set_requested_by(doc, method=None):
	"""Set custom_requested_by and fetch the requestor's employee record."""
	if doc.doctype != "Job Requisition":
		return

	if not doc.custom_requested_by or doc.custom_requested_by == "user":
		if frappe.session.user and frappe.session.user != "Guest":
			doc.custom_requested_by = frappe.session.user
		else:
			return

	# skip validation for the literal string "user"
	if doc.custom_requested_by and doc.custom_requested_by != "user":
		if not frappe.db.exists("User", doc.custom_requested_by):
			frappe.throw(
				_("Could not find Requested By: {0}").format(doc.custom_requested_by),
				title=_("Invalid User")
			)
	
	if doc.custom_requested_by and not doc.requested_by_employee:
		employee = frappe.db.get_value("Employee", {"user_id": doc.custom_requested_by}, "name")
		if employee:
			doc.requested_by_employee = employee

			reports_to = frappe.db.get_value("Employee", employee, "reports_to")
			if reports_to:
				doc.requestor_reporting_manager = reports_to

				manager_user_id = frappe.db.get_value("Employee", reports_to, "user_id")
				if manager_user_id:
					doc.requestor_manager_user = manager_user_id


def fetch_reporting_manager(doc, method=None):
	"""Fetch reporting managers: requestor's always, linked employee's for replacements."""
	if doc.custom_requested_by:
		requestor_employee = frappe.db.get_value("Employee", {"user_id": doc.custom_requested_by}, "name")
		if requestor_employee:
			doc.requested_by_employee = requestor_employee

			requestor_manager = frappe.db.get_value("Employee", requestor_employee, "reports_to")
			if requestor_manager:
				doc.requestor_reporting_manager = requestor_manager

				manager_user_id = frappe.db.get_value("Employee", requestor_manager, "user_id")
				if manager_user_id:
					doc.requestor_manager_user = manager_user_id

	# replacement position: fetch the linked employee's manager too
	if doc.linked_employee:
		linked_emp_manager = frappe.db.get_value("Employee", doc.linked_employee, "reports_to")
		if linked_emp_manager:
			doc.reporting_manager = linked_emp_manager

			user_id = frappe.db.get_value("Employee", linked_emp_manager, "user_id")
			if user_id:
				doc.reporting_manager_user = user_id


def fetch_designation_details(doc, method=None):
	"""Fetch description and skills from the selected Designation."""
	if doc.doctype != "Job Requisition":
		return

	if not doc.designation:
		return

	try:
		designation = frappe.get_doc("Designation", doc.designation)

		designation_changed = doc.has_value_changed("designation") if not doc.is_new() else True

		if not doc.description or designation_changed:
			if designation.description:
				doc.description = designation.description

		if not hasattr(doc, "skills"):
			# skills field may not be created yet
			return

		if doc.skills is None:
			doc.skills = []

		current_skills_count = len(doc.skills) if doc.skills else 0

		if current_skills_count == 0 or designation_changed:
			if designation_changed and current_skills_count > 0:
				doc.skills = []

			if hasattr(designation, "skills"):
				designation_skills = designation.get("skills", [])
				if designation_skills:
					skills_added = 0
					for skill_row in designation_skills:
						skill_value = skill_row.get("skill") if isinstance(skill_row, dict) else getattr(skill_row, "skill", None)
						if skill_value:
							doc.append("skills", {
								"skill": skill_value
							})
							skills_added += 1

					if skills_added > 0:
						frappe.logger().info(
							f"Added {skills_added} skills from Designation {doc.designation} to Job Requisition {doc.name if not doc.is_new() else 'NEW'}"
						)

	except frappe.DoesNotExistError:
		frappe.log_error(
			f"Designation {doc.designation} not found for Job Requisition {doc.name}",
			"Job Requisition Automation - Designation Not Found"
		)
	except Exception as e:
		frappe.log_error(
			f"Error fetching designation details for Job Requisition {doc.name}: {str(e)}",
			"Job Requisition Automation"
		)


def validate_salary_range(doc, method=None):
	"""Validate CTC Lower Range is less than CTC Upper Range."""
	if doc.doctype != "Job Requisition":
		return
	lower = doc.get("expected_compensation")
	upper = doc.get("ctc_upper_range")
	if lower is not None and upper is not None and (lower or 0) >= (upper or 0):
		frappe.throw(
			_("CTC Lower Range / Monthly must be less than CTC Upper Range / Monthly."),
			title=_("Invalid Salary Range"),
		)


def validate_job_requisition(doc, method=None):
	"""Field validations for Job Requisition (positions, deadline, experience, replacement)."""
	if doc.doctype != "Job Requisition":
		return

	no_of_positions = doc.get("no_of_positions")
	if no_of_positions is not None and (no_of_positions or 0) <= 0:
		frappe.throw(
			_("Number of Positions must be greater than 0."),
			title=_("Invalid Number of Positions"),
		)

	hiring_deadline = doc.get("hiring_deadline")
	if hiring_deadline:
		if getdate(hiring_deadline) < getdate():
			frappe.throw(
				_("Hiring Deadline cannot be in the past."),
				title=_("Invalid Hiring Deadline"),
			)

	min_exp = doc.get("min_experience")
	if min_exp is not None:
		try:
			val = int(min_exp)
			if val < 0:
				frappe.throw(
					_("Min. Experience (Years) cannot be negative."),
					title=_("Invalid Min. Experience"),
				)
			if val > 50:
				frappe.throw(
					_("Min. Experience (Years) cannot exceed 50."),
					title=_("Invalid Min. Experience"),
				)
		except (TypeError, ValueError):
			pass  # let the doctype/UI handle non-numeric input

	if doc.get("vacancy_type") == "Replace" and not doc.get("linked_employee"):
		frappe.throw(
			_("Linked Employee is required when Vacancy Type is Replace."),
			title=_("Missing Linked Employee"),
		)


def update_approval_fields(doc, method=None):
	"""Populate approved_on / approved_by when status becomes Approved."""
	if doc.status == "Approved":
		if not doc.approved_on:
			doc.approved_on = now()

		if not doc.approved_by:
			doc.approved_by = frappe.session.user


def create_published_job_opening_on_live(doc, method=None):
	"""Create a published Job Opening when Job Requisition status becomes Live."""
	if doc.status == "Live":
		existing_opening = frappe.db.exists("Job Opening", {"job_requisition": doc.name})

		if not existing_opening:
			try:
				from hrms.hr.doctype.job_requisition.job_requisition import make_job_opening

				job_opening = make_job_opening(doc.name)

				if hasattr(doc, "location") and doc.location:
					job_opening.location = doc.location

				if hasattr(doc, "min_experience") and doc.min_experience:
					# Job Opening has no min_experience field; nothing to map
					pass

				if hasattr(doc, "ctc_upper_range") and doc.ctc_upper_range:
					job_opening.upper_range = doc.ctc_upper_range

				if hasattr(doc, "hiring_deadline") and doc.hiring_deadline:
					job_opening.closes_on = doc.hiring_deadline

				job_opening.publish = 1
				job_opening.status = "Open"

				# job_application_route is set by the before_save hook
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
	"""Set Job Requisition to Live when its Job Opening is published (Job Opening doc_event)."""
	if doc.publish == 1 and doc.job_requisition:
		try:
			job_req = frappe.get_doc("Job Requisition", doc.job_requisition)

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
	"""Sync status between Job Requisition and Job Opening."""
	job_opening = frappe.db.get_value("Job Opening", {"job_requisition": doc.name}, "name")

	if job_opening:
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


def create_job_requisition_client_script():
	"""Create the Job Requisition client script (fetch skills, set custom_requested_by)."""

	script = """
frappe.ui.form.on('Job Requisition', {
	onload: function(frm) {
		// Set custom_requested_by field immediately on form load if empty or set to "user"
		if ((!frm.doc.custom_requested_by || frm.doc.custom_requested_by === 'user') && frappe.session.user && frappe.session.user !== 'Guest') {
			frm.set_value('custom_requested_by', frappe.session.user);
		}
	},
	
	refresh: function(frm) {
		// Also set on refresh if still empty or invalid
		if ((!frm.doc.custom_requested_by || frm.doc.custom_requested_by === 'user') && frappe.session.user && frappe.session.user !== 'Guest') {
			frm.set_value('custom_requested_by', frappe.session.user);
		}
	},
	
	designation: function(frm) {
		if (frm.doc.designation) {
			// Clear existing skills first
			frm.clear_table('skills');
			
			// Fetch designation and populate skills
			frappe.db.get_doc('Designation', frm.doc.designation).then(function(designation) {
				if (designation.skills && designation.skills.length > 0) {
					designation.skills.forEach(function(designation_skill) {
						if (designation_skill.skill) {
							var row = frm.add_child('skills');
							row.skill = designation_skill.skill;
						}
					});
					frm.refresh_field('skills');
				}
			}).catch(function(error) {
				console.error('Error fetching designation skills:', error);
			});
		} else {
			// Clear skills if designation is cleared
			frm.clear_table('skills');
			frm.refresh_field('skills');
		}
	}
});
"""
	
	try:
		script_name = "Job Requisition - Fetch Skills from Designation"
		if frappe.db.exists("Client Script", script_name):
			client_script = frappe.get_doc("Client Script", script_name)
			client_script.script = script
			client_script.enabled = 1
			client_script.save(ignore_permissions=True)
			frappe.db.commit()
			print(f"✅ Updated client script: {script_name}")
		else:
			client_script = frappe.get_doc({
				"doctype": "Client Script",
				"name": script_name,
				"dt": "Job Requisition",
				"view": "Form",
				"enabled": 1,
				"script": script
			})
			client_script.insert(ignore_permissions=True)
			frappe.db.commit()
			print(f"✅ Created client script: {script_name}")
	except Exception as e:
		frappe.log_error(
			f"Error creating client script for Job Requisition: {str(e)}",
			"Job Requisition Client Script Error"
		)
		print(f"⚠️  Could not create client script: {str(e)}")
