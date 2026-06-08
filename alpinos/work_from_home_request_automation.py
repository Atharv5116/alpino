"""
Automation scripts for Work From Home Request
- Auto-populate employee from current user
- Auto-populate leave approver for the employee
"""

import frappe
from frappe import _


@frappe.whitelist()
def get_current_employee_and_approver():
	"""
	Get current user's employee and leave approver
	Used by client script for auto-population
	"""
	current_user = frappe.session.user
	
	if not current_user or current_user == "Guest":
		return None
	
	# Get employee linked to current user - try Active first, then any status
	employee = frappe.db.get_value(
		"Employee",
		{"user_id": current_user, "status": "Active"},
		"name"
	)
	
	# If no active employee found, try without status filter
	if not employee:
		employee = frappe.db.get_value(
			"Employee",
			{"user_id": current_user},
			"name"
		)
	
	if not employee:
		return None
	
	# Get leave approver
	leave_approver = get_leave_approver_for_employee(employee)
	
	return {
		"employee": employee,
		"leave_approver": leave_approver
	}


def enforce_single_day(doc, method=None):
	"""Work From Home is single-day only.

	- Keep `to_date` equal to `date` so the request always covers exactly one day (the To Date
	  field is hidden in the UI; this guards every save path).
	- Require the Half Day Period when Half Day is ticked (mirrors the form's mandatory rule and
	  the Leave Application validation; blocks any path that bypasses the UI).
	"""
	if doc.doctype != "Work From Home Request":
		return

	if doc.get("date"):
		doc.to_date = doc.date

	if doc.get("half_day") and not doc.get("custom_half_day_period"):
		frappe.throw(
			_("Please select the Half Day Period (First Half / Second Half) for a half-day request."),
			title=_("Half Day Period Required"),
		)


def auto_populate_employee_and_approver(doc, method=None):
	"""
	Auto-populate employee and leave approver when creating a new Work From Home Request
	"""
	if doc.doctype != "Work From Home Request":
		return
	
	# Auto-fill employee from current user if not already set
	if not doc.employee:
		current_user = frappe.session.user
		
		# Skip if no valid user session
		if not current_user or current_user == "Guest":
			return
		
		# Get employee linked to current user - try Active first, then any status
		employee = frappe.db.get_value(
			"Employee",
			{"user_id": current_user, "status": "Active"},
			"name"
		)
		
		# If no active employee found, try without status filter
		if not employee:
			employee = frappe.db.get_value(
				"Employee",
				{"user_id": current_user},
				"name"
			)
		
		if employee:
			doc.employee = employee
	
	# Auto-populate leave approver if employee is set
	if doc.employee:
		# Get the previous employee value to check if it changed
		previous_employee = None
		if hasattr(doc, 'get_doc_before_save') and doc.get_doc_before_save():
			previous_employee = doc.get_doc_before_save().employee
		
		# Update leave approver if:
		# 1. Leave approver is not set, OR
		# 2. Employee field was changed
		if not doc.leave_approver or (previous_employee and previous_employee != doc.employee):
			leave_approver = get_leave_approver_for_employee(doc.employee)
			if leave_approver:
				doc.leave_approver = leave_approver


def get_leave_approver_for_employee(employee):
	"""
	Get leave approver for an employee
	First checks employee.leave_approver, then falls back to department approver
	"""
	leave_approver, department = frappe.db.get_value(
		"Employee",
		employee,
		["leave_approver", "department"]
	)
	
	# If no leave approver on employee, check department approvers
	if not leave_approver and department:
		leave_approver = frappe.db.get_value(
			"Department Approver",
			{"parent": department, "parentfield": "leave_approvers", "idx": 1},
			"approver"
		)
	
	return leave_approver


def create_work_from_home_client_script():
	"""Create client script to auto-populate employee and leave approver"""
	
	script = """
frappe.ui.form.on('Work From Home Request', {
	setup: function(frm) {
		// Auto-populate employee and leave approver immediately when form is set up (for new documents)
		if (frm.is_new() && !frm.doc.employee) {
			auto_populate_employee_and_approver(frm);
		}
	},
	
	onload: function(frm) {
		// Auto-populate employee and leave approver on form load if new document
		if (frm.is_new() && !frm.doc.employee) {
			auto_populate_employee_and_approver(frm);
		}
	},
	
	refresh: function(frm) {
		// Also populate on refresh if still empty (for new documents)
		if (frm.is_new() && !frm.doc.employee) {
			auto_populate_employee_and_approver(frm);
		}
	},
	
	employee: function(frm) {
		// Auto-populate leave approver when employee changes (manually or programmatically)
		if (frm.doc.employee) {
			// Always update leave approver when employee changes
			frappe.call({
				method: 'alpinos.work_from_home_request_automation.get_leave_approver_for_employee_api',
				args: {
					employee: frm.doc.employee
				},
				callback: function(r) {
					if (r.message) {
						frm.set_value('leave_approver', r.message);
					} else {
						// Clear if no approver found
						frm.set_value('leave_approver', '');
					}
				}
			});
		} else {
			// Clear leave approver if employee is cleared
			frm.set_value('leave_approver', '');
		}
	}
});

function auto_populate_employee_and_approver(frm) {
	// Get current user's employee and leave approver
	frappe.call({
		method: 'alpinos.work_from_home_request_automation.get_current_employee_and_approver',
		callback: function(r) {
			if (r.message && r.message.employee) {
				// Set employee first
				frm.set_value('employee', r.message.employee);
				
				// Set leave approver - use value from response or fetch separately
				if (r.message.leave_approver) {
					frm.set_value('leave_approver', r.message.leave_approver);
				} else {
					// Fetch leave approver separately if not in response
					setTimeout(function() {
						frappe.call({
							method: 'alpinos.work_from_home_request_automation.get_leave_approver_for_employee_api',
							args: {
								employee: r.message.employee
							},
							callback: function(r2) {
								if (r2.message) {
									frm.set_value('leave_approver', r2.message);
								}
							}
						});
					}, 100);
				}
			}
		}
	});
}
"""
	
	try:
		script_name = "Work From Home Request - Auto Populate Employee"
		script_doc = frappe.db.exists("Client Script", {"name": script_name})
		
		if script_doc:
			# Update existing script
			doc = frappe.get_doc("Client Script", script_name)
			doc.script = script
			doc.save(ignore_permissions=True)
		else:
			# Create new script
			doc = frappe.get_doc({
				"doctype": "Client Script",
				"name": script_name,
				"dt": "Work From Home Request",
				"script": script,
				"view": "Form"
			})
			doc.insert(ignore_permissions=True)
		
		frappe.db.commit()
	except Exception as e:
		frappe.log_error(f"Error creating Work From Home Request client script: {str(e)}")


@frappe.whitelist()
def get_leave_approver_for_employee_api(employee):
	"""API wrapper for get_leave_approver_for_employee"""
	return get_leave_approver_for_employee(employee)


@frappe.whitelist()
def save_wfh_tasks(wfh_request_name, tasks):
	"""
	Save tasks to Work From Home Request
	Args:
		wfh_request_name: Name of the Work From Home Request document
		tasks: List of task dictionaries with task_name and status
	"""
	if not wfh_request_name:
		frappe.throw(_("Work From Home Request name is required"))
	
	if not tasks or len(tasks) == 0:
		frappe.throw(_("At least one task is required"))
	
	# Get the WFH Request document
	wfh_request = frappe.get_doc("Work From Home Request", wfh_request_name)
	
	# Clear existing tasks (optional - you can remove this if you want to append)
	# wfh_request.tasks = []
	
	# Add new tasks
	for task in tasks:
		if task.get("task_name") and task.get("status"):
			wfh_request.append("tasks", {
				"task_name": task.get("task_name"),
				"status": task.get("status")
			})
	
	# Save the document
	wfh_request.save(ignore_permissions=True)
	frappe.db.commit()
	
	return {
		"message": "Tasks saved successfully",
		"tasks_count": len(tasks)
	}
