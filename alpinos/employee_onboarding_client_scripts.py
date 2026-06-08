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
								onboarding_doc.boarding_status = 'Draft';
								
								// Work experience fields will be auto-populated by the client script
								
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
	},

	// Auto-fill Applied Position immediately when Job Opening changes
	job_requisition: function(frm) {
		if (!frm.doc.job_requisition) return;
		frappe.db.get_value('Job Opening', frm.doc.job_requisition, 'designation')
			.then((r) => {
				const designation = r && r.message ? r.message.designation : null;
				if (designation) {
					frm.set_value('applied_position', designation);
					// Keep designation in sync as well, if present on the form
					if (frm.doc.designation !== undefined) {
						frm.set_value('designation', designation);
					}
				}
			})
			.catch(() => {});
	},

	// If job_title is used to carry Job Opening in some flows, sync from it too
	job_title: function(frm) {
		if (!frm.doc.job_title || frm.doc.job_requisition) return;
		frm.set_value('job_requisition', frm.doc.job_title);
		frm.trigger('job_requisition');
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
								onboarding_doc.boarding_status = 'Draft';
								
								// Work experience fields will be auto-populated by the client script
								
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
// Allow saving Employee Onboarding in Draft state without client-side mandatory checks
if (!frappe.ui.form._employee_onboarding_check_mandatory_patched) {
	frappe.ui.form._employee_onboarding_check_mandatory_patched = true;
	const original_check_mandatory = frappe.ui.form.check_mandatory;
	frappe.ui.form.check_mandatory = function (frm) {
		if (frm && frm.doctype === 'Employee Onboarding') {
			// Skip mandatory check when in Draft or Email Sent state
			var state = frm.doc.boarding_status || frm.doc.workflow_state || '';
			if (frm.is_new() || state === 'Draft' || state === 'Email Sent') {
				return true;
			}
		}
		return original_check_mandatory(frm);
	};
}

// Helper: Remove or restore mandatory asterisks based on workflow state
function toggle_mandatory_indicators(frm) {
	var state = frm.doc.boarding_status || frm.doc.workflow_state || '';
	var skip_mandatory = frm.is_new() || state === 'Draft' || state === 'Email Sent';

	if (skip_mandatory) {
		// Store original reqd values and remove mandatory from ALL fields
		if (!frm._original_reqd_map) {
			frm._original_reqd_map = {};
		}
		frm.meta.fields.forEach(function(df) {
			if (df.reqd) {
				frm._original_reqd_map[df.fieldname] = 1;
				frm.set_df_property(df.fieldname, 'reqd', 0);
			}
		});
	} else {
		// Restore original mandatory values
		if (frm._original_reqd_map) {
			Object.keys(frm._original_reqd_map).forEach(function(fieldname) {
				frm.set_df_property(fieldname, 'reqd', 1);
			});
			frm._original_reqd_map = null;
		}
	}
}

function alp_calc_probation_end(frm) {
	// Probation End Date = Date of Joining (DOJ) + Probation Period (days). The field is
	// read-only; this gives a live preview as the days / DOJ are edited.
	if (!frm.doc.date_of_joining_onboarding) return;
	var days = parseInt(frm.doc.probation_period) || 0;
	var end = frappe.datetime.add_days(frm.doc.date_of_joining_onboarding, days);
	if (frm.doc.probation_end_date !== end) {
		frm.set_value('probation_end_date', end);
	}
}

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

	probation_period: function(frm) { alp_calc_probation_end(frm); },
	date_of_joining_onboarding: function(frm) { alp_calc_probation_end(frm); },

	refresh: function(frm) {
		// Ensure status / boarding_status fields are visible
		try {
			frm.set_df_property('status', 'hidden', 0);
		} catch (e) {
			// ignore if status not present as a visible field
		}
		try {
			frm.set_df_property('boarding_status', 'hidden', 0);
		} catch (e) {
			// ignore if boarding_status is not defined
		}

		// Toggle mandatory asterisks based on workflow state
		toggle_mandatory_indicators(frm);

		// Auto-populate fields when form loads if job_applicant is set
		if (frm.doc.job_applicant) {
			// Set candidate_id to job_applicant (Link field)
			if (!frm.doc.candidate_id) {
				frm.set_value("candidate_id", frm.doc.job_applicant);
			}
			
			// Always trigger auto-population
			auto_populate_from_job_applicant(frm);
		}
		
		// Add Create Employee button when in 'Employee Created' workflow state
		// or when no workflow state is set (backward compat)
		if (!frm.is_new() && !frm.doc.employee) {
			if (frm.doc.boarding_status === 'Employee Created' || !frm.doc.boarding_status) {
				frm.add_custom_button(__('Create Employee'), function() {
					frappe.model.open_mapped_doc({
						method: 'alpinos.employee_onboarding_to_employee.make_employee_with_details',
						frm: frm
					});
				}, __('Actions'));
			}
		}
	},
	
	after_save: function(frm) {
		// When workflow transitions to 'Employee Created', open the Employee creation form
		if (frm.doc.boarding_status === 'Employee Created' && !frm.doc.employee) {
			setTimeout(function() {
				frappe.model.open_mapped_doc({
					method: 'alpinos.employee_onboarding_to_employee.make_employee_with_details',
					frm: frm
				});
			}, 1000);
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
	},
	
	designation_company_profile: function(frm) {
		// Auto-populate hidden standard 'designation' field (Link) when designation_company_profile changes
		if (frm.doc.designation_company_profile && !frm.doc.designation) {
			// Try to find matching Designation record using client-side API
			frappe.db.get_value('Designation', frm.doc.designation_company_profile, 'name', (r) => {
				if (r && r.name) {
					frm.set_value("designation", r.name);
				} else {
					// If no exact match, try to find by name (case-insensitive)
					// Use frappe.call with a server-side method for LIKE queries
					frappe.call({
						method: 'frappe.client.get_list',
						args: {
							doctype: 'Designation',
							filters: {
								name: ['like', '%' + frm.doc.designation_company_profile + '%']
							},
							fields: ['name'],
							limit: 1
						},
						callback: function(r2) {
							if (r2.message && r2.message.length > 0) {
								frm.set_value("designation", r2.message[0].name);
							}
						}
					});
				}
			});
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
				
				// Work Experience fields - Auto-populate from Job Applicant employment fields
				// Only populate if fields are empty (don't overwrite user-entered data)
				if (job_applicant.employment_company_name && !frm.doc.work_experience_company_name) {
					frm.set_value("work_experience_company_name", job_applicant.employment_company_name);
				}
				
				if (job_applicant.employment_designation && !frm.doc.work_experience_designation) {
					frm.set_value("work_experience_designation", job_applicant.employment_designation);
				}
				
				if (job_applicant.employment_start_date && !frm.doc.work_experience_start_date) {
					frm.set_value("work_experience_start_date", job_applicant.employment_start_date);
				}
				
				if (job_applicant.employment_end_date && !frm.doc.work_experience_end_date) {
					frm.set_value("work_experience_end_date", job_applicant.employment_end_date);
				}
				
				// City - try to get from employment_city or city_state
				if (!frm.doc.work_experience_city) {
					if (job_applicant.employment_city) {
						frm.set_value("work_experience_city", job_applicant.employment_city);
					} else if (job_applicant.city_state) {
						// Extract city from city_state (format: "City/State")
						var city_state_parts = job_applicant.city_state.split("/");
						if (city_state_parts.length >= 1) {
							frm.set_value("work_experience_city", city_state_parts[0].trim());
						}
					}
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
				
				// Auto-populate hidden standard 'designation' field (Link) from designation_company_profile
				// This ensures the hidden field is populated for Employee creation
				if (frm.doc.designation_company_profile && !frm.doc.designation) {
					// Try to find matching Designation record using client-side API
					frappe.db.get_value('Designation', frm.doc.designation_company_profile, 'name', (r) => {
						if (r && r.name) {
							frm.set_value("designation", r.name);
						} else {
							// If no exact match, try to find by name (case-insensitive)
							// Use frappe.call with a server-side method for LIKE queries
							frappe.call({
								method: 'frappe.client.get_list',
								args: {
									doctype: 'Designation',
									filters: {
										name: ['like', '%' + frm.doc.designation_company_profile + '%']
									},
									fields: ['name'],
									limit: 1
								},
								callback: function(r2) {
									if (r2.message && r2.message.length > 0) {
										frm.set_value("designation", r2.message[0].name);
									}
								}
							});
						}
					});
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

