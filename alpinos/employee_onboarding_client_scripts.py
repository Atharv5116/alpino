"""
Create Client Scripts for Job Applicant and Interview
to add buttons for creating Employee Onboarding
"""

import frappe


def create_employee_onboarding_client_scripts():
	"""Create client scripts for Job Applicant, Interview, and Employee Onboarding"""
	
	# Client Script for Job Applicant
	job_applicant_script = """
frappe.ui.form.on('Job Applicant', {
	refresh: function(frm) {
		// Add button to create Employee Onboarding
		if (frm.doc.name && !frm.is_new()) {
			frm.add_custom_button(__('Create Employee Onboarding'), function() {
				frappe.call({
					method: 'alpinos.employee_onboarding_automation.create_employee_onboarding_from_job_applicant',
					args: {
						job_applicant_name: frm.doc.name
					},
					callback: function(r) {
						if (r.message && r.message.action === 'open_new_form') {
							// Open new Employee Onboarding form with job_applicant pre-filled
							frappe.model.with_doctype('Employee Onboarding', function() {
								var onboarding_doc = frappe.model.get_new_doc('Employee Onboarding');
								onboarding_doc.job_applicant = r.message.job_applicant;
								onboarding_doc.candidate_id = r.message.job_applicant;  // Link field to Job Applicant
								onboarding_doc.boarding_status = 'Pre-Onboarding Initiated';
								
								// Ensure work experience fields are NOT auto-populated
								// These must be entered manually
								onboarding_doc.work_experience_company_name = '';
								onboarding_doc.work_experience_designation = '';
								onboarding_doc.work_experience_start_date = '';
								onboarding_doc.work_experience_end_date = '';
								onboarding_doc.work_experience_city = '';
								
								frappe.set_route('Form', 'Employee Onboarding', onboarding_doc.name);
								
								// Trigger refresh after route
								setTimeout(function() {
									var frm = frappe.ui.form.get_open_form('Employee Onboarding', onboarding_doc.name);
									if (frm && frm.doc.job_applicant) {
										frm.trigger('job_applicant');
									}
								}, 500);
							});
						} else if (r.message) {
							// Existing onboarding found, route to it
							frappe.set_route('Form', 'Employee Onboarding', r.message);
						}
					},
					error: function(r) {
						frappe.msgprint({
							title: __('Error'),
							message: r.message || __('Failed to create Employee Onboarding'),
							indicator: 'red'
						});
					}
				});
			}, __('Actions'));
		}
	}
});
"""
	
	# Client Script for Interview
	interview_script = """
frappe.ui.form.on('Interview', {
	refresh: function(frm) {
		// Add button to create Employee Onboarding
		if (frm.doc.name && !frm.is_new() && frm.doc.job_applicant) {
			frm.add_custom_button(__('Create Employee Onboarding'), function() {
				frappe.call({
					method: 'alpinos.employee_onboarding_automation.create_employee_onboarding_from_job_applicant',
					args: {
						job_applicant_name: frm.doc.job_applicant
					},
					callback: function(r) {
						if (r.message && r.message.action === 'open_new_form') {
							// Open new Employee Onboarding form with job_applicant pre-filled
							frappe.model.with_doctype('Employee Onboarding', function() {
								var onboarding_doc = frappe.model.get_new_doc('Employee Onboarding');
								onboarding_doc.job_applicant = r.message.job_applicant;
								onboarding_doc.candidate_id = r.message.job_applicant;  // Link field to Job Applicant
								onboarding_doc.boarding_status = 'Pre-Onboarding Initiated';
								
								// Ensure work experience fields are NOT auto-populated
								// These must be entered manually
								onboarding_doc.work_experience_company_name = '';
								onboarding_doc.work_experience_designation = '';
								onboarding_doc.work_experience_start_date = '';
								onboarding_doc.work_experience_end_date = '';
								onboarding_doc.work_experience_city = '';
								
								frappe.set_route('Form', 'Employee Onboarding', onboarding_doc.name);
								
								// Trigger refresh after route
								setTimeout(function() {
									var frm = frappe.ui.form.get_open_form('Employee Onboarding', onboarding_doc.name);
									if (frm && frm.doc.job_applicant) {
										frm.trigger('job_applicant');
									}
								}, 500);
							});
						} else if (r.message) {
							// Existing onboarding found, route to it
							frappe.set_route('Form', 'Employee Onboarding', r.message);
						}
					},
					error: function(r) {
						frappe.msgprint({
							title: __('Error'),
							message: r.message || __('Failed to create Employee Onboarding'),
							indicator: 'red'
						});
					}
				});
			}, __('Actions'));
		}
	}
});
"""
	
	# Create or update Job Applicant client script
	create_or_update_client_script(
		"Job Applicant - Create Employee Onboarding",
		"Job Applicant",
		job_applicant_script
	)
	
	# Create or update Interview client script
	create_or_update_client_script(
		"Interview - Create Employee Onboarding",
		"Interview",
		interview_script
	)
	
	# Client Script for Employee Onboarding
	employee_onboarding_script = """
frappe.ui.form.on('Employee Onboarding', {
	setup: function(frm) {
		// Remove status filter - show all job applicants
		frm.set_query("job_applicant", function() {
			return {
				filters: {}  // No filters - show all job applicants
			};
		});

		frm.set_query("job_offer", function() {
			return {
				filters: {
					job_applicant: frm.doc.job_applicant,
					docstatus: 1,
				},
			};
		});
	},
	
	refresh: function(frm) {
		// Auto-populate fields when form loads if job_applicant is set
		if (frm.doc.job_applicant) {
			// Set candidate_id to job_applicant (Link field)
			if (!frm.doc.candidate_id) {
				frm.set_value("candidate_id", frm.doc.job_applicant);
			}
			
			// Always trigger auto-population
			auto_populate_from_job_applicant(frm);
			
			// Ensure work experience fields are NOT auto-populated when form is new
			// Only clear them if form is new (created from button)
			if (frm.is_new()) {
				frm.set_value("work_experience_company_name", "");
				frm.set_value("work_experience_designation", "");
				frm.set_value("work_experience_start_date", "");
				frm.set_value("work_experience_end_date", "");
				frm.set_value("work_experience_city", "");
			}
		}
		
		// Check if pre-onboarding interview was created and redirect
		if (frm.doc.boarding_status === 'Pre-Onboarding Initiated' && frm.doc.job_applicant) {
			// Check if interview exists
			frappe.db.get_value('Interview', {
				'job_applicant': frm.doc.job_applicant,
				'interview_round': 'pre-onboarding'
			}, 'name', (r) => {
				if (r && r.name) {
					// Show message and add button to open interview
					frappe.show_alert({
						message: __('Pre-Onboarding Interview created. Click to open.'),
						indicator: 'blue'
					}, 5);
					
					frm.add_custom_button(__('Open Pre-Onboarding Interview'), function() {
						frappe.set_route('Form', 'Interview', r.name);
					});
				}
			});
		}
	},
	
	after_save: function(frm) {
		// After save, check if pre-onboarding interview was created
		if (frm.doc.boarding_status === 'Pre-Onboarding Initiated' && frm.doc.job_applicant) {
			// Wait a moment for the interview to be created
			setTimeout(function() {
				frappe.db.get_value('Interview', {
					'job_applicant': frm.doc.job_applicant,
					'interview_round': 'pre-onboarding'
				}, 'name', (r) => {
					if (r && r.name) {
						// Show message and redirect to interview
						frappe.show_alert({
							message: __('Pre-Onboarding Interview created. Redirecting...'),
							indicator: 'blue'
						}, 3);
						
						// Redirect to interview after a short delay
						setTimeout(function() {
							frappe.set_route('Form', 'Interview', r.name);
						}, 500);
					}
				});
			}, 1500);
		}
	},
	
	job_applicant: function(frm) {
		// Auto-populate fields when job_applicant is selected or changed
		if (frm.doc.job_applicant) {
			// Check for existing Employee
			frappe.db.get_value(
				"Employee",
				{ job_applicant: frm.doc.job_applicant },
				"name",
				(r) => {
					if (r.name) {
						frm.set_value("employee", r.name);
					} else {
						frm.set_value("employee", "");
					}
				},
			);
			
			// Set candidate_id to job_applicant (Link field)
			frm.set_value("candidate_id", frm.doc.job_applicant);
			
			// Always trigger auto-population when job_applicant changes
			auto_populate_from_job_applicant(frm);
		} else {
			// Clear dependent fields when job_applicant is cleared
			frm.set_value("employee", "");
			frm.set_value("candidate_id", "");
		}
	}
});

function auto_populate_from_job_applicant(frm) {
	// Get Job Applicant data and populate fields
	if (!frm.doc.job_applicant) return;
	
	// Set candidate_id to job_applicant (Link field)
	frm.set_value("candidate_id", frm.doc.job_applicant);
	
	frappe.call({
		method: 'frappe.client.get',
		args: {
			doctype: 'Job Applicant',
			name: frm.doc.job_applicant
		},
		callback: function(r) {
			if (r.message) {
				var job_applicant = r.message;
				
				// EXPLICITLY DO NOT populate work experience fields
				// These fields must be entered manually by the user
				// Do not auto-populate from job_applicant employment fields
				// Only clear them if form is new (to prevent auto-population from button)
				if (frm.is_new()) {
					frm.set_value("work_experience_company_name", "");
					frm.set_value("work_experience_designation", "");
					frm.set_value("work_experience_start_date", "");
					frm.set_value("work_experience_end_date", "");
					frm.set_value("work_experience_city", "");
				}
				
				// Full Name - split into first, middle, last
				if (job_applicant.applicant_name) {
					var name_parts = job_applicant.applicant_name.trim().split(/\\s+/);
					if (name_parts.length >= 1) {
						frm.set_value("first_name", name_parts[0]);
					}
					if (name_parts.length >= 2) {
						frm.set_value("middle_name", name_parts.length > 2 ? name_parts[1] : "");
					}
					if (name_parts.length >= 3) {
						frm.set_value("last_name", name_parts.slice(2).join(" "));
					} else if (name_parts.length > 1) {
						frm.set_value("last_name", name_parts[name_parts.length - 1]);
					}
					frm.set_value("full_name_display", job_applicant.applicant_name);
				}
				
				// Personal Mobile Number
				if (job_applicant.phone_number) {
					frm.set_value("personal_mobile_number", job_applicant.phone_number);
				}
				
				// Personal Email
				if (job_applicant.email_id) {
					frm.set_value("personal_email", job_applicant.email_id);
				}
				
				// Marital Status
				if (job_applicant.marital_status) {
					frm.set_value("marital_status_onboarding", job_applicant.marital_status);
				}
				
				// Degree
				if (job_applicant.degree) {
					frm.set_value("degree", job_applicant.degree);
				}
				
				// City/State combined field
				if (job_applicant.city_state) {
					frm.set_value("city_state_combined", job_applicant.city_state);
				}
				
				// Notice Period
				
				// Designation
				if (job_applicant.designation) {
					frm.set_value("onboarding_designation", job_applicant.designation);
				}
				
				// Get Job Opening data for Company, Location, Department
				if (job_applicant.job_requisition) {
					frappe.call({
						method: 'frappe.client.get',
						args: {
							doctype: 'Job Opening',
							name: job_applicant.job_requisition
						},
						callback: function(job_r) {
							if (job_r.message) {
								var job_opening = job_r.message;
								
								// Company
								if (job_opening.company) {
									frm.set_value("company", job_opening.company);
								}
								
								// Location
								if (job_opening.location) {
									frm.set_value("location", job_opening.location);
								}
								
								// Department
								if (job_opening.department) {
									frm.set_value("department", job_opening.department);
									
									// Get Department for HOD and Reporting Manager
									frappe.call({
										method: 'frappe.client.get',
										args: {
											doctype: 'Department',
											name: job_opening.department
										},
										callback: function(dept_r) {
											if (dept_r.message) {
												var department = dept_r.message;
												if (department.hod) {
													frm.set_value("hod", department.hod);
												}
												if (department.reports_to) {
													frm.set_value("reporting_manager", department.reports_to);
												}
											}
										}
									});
								}
							}
						}
					});
				}
			}
		}
	});
}
"""
	
	# Create or update Employee Onboarding client script
	create_or_update_client_script(
		"Employee Onboarding - Auto-populate and Link Unique ID",
		"Employee Onboarding",
		employee_onboarding_script
	)
	
	print("✅ Client Scripts created for Job Applicant, Interview, and Employee Onboarding")


def create_or_update_client_script(name, doctype, script):
	"""Create or update a client script"""
	try:
		# Check if client script already exists
		if frappe.db.exists("Client Script", name):
			client_script = frappe.get_doc("Client Script", name)
			client_script.script = script
			client_script.enabled = 1
			client_script.save(ignore_permissions=True)
			frappe.db.commit()
		else:
			# Create new client script
			client_script = frappe.get_doc({
				"doctype": "Client Script",
				"name": name,
				"dt": doctype,
				"view": "Form",
				"enabled": 1,
				"script": script
			})
			client_script.insert(ignore_permissions=True)
			frappe.db.commit()
	except Exception as e:
		frappe.log_error(f"Error creating client script {name}: {str(e)}", "Client Script Creation Error")
		print(f"⚠️  Could not create client script {name}: {str(e)}")

