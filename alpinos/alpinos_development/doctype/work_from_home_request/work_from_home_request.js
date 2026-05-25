// Copyright (c) 2026, Hetvi Patel and contributors
// For license information, please see license.txt

frappe.ui.form.on("Work From Home Request", {
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
				// Set employee first - this will trigger the employee() function
				frm.set_value('employee', r.message.employee);
				
				// Also set leave approver directly from response if available
				if (r.message.leave_approver) {
					frm.set_value('leave_approver', r.message.leave_approver);
				} else {
					// If not in response, the employee trigger will fetch it
					// But let's also fetch it here as backup
					setTimeout(function() {
						if (!frm.doc.leave_approver) {
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
						}
					}, 200);
				}
			}
		},
		error: function(r) {
			console.error('Error fetching employee and approver:', r);
		}
	});
}
