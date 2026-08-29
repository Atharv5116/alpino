// Copyright (c) 2026, Hetvi Patel and contributors
// For license information, please see license.txt

frappe.ui.form.on("Work From Home Request", {
	setup: function(frm) {
		if (frm.is_new() && !frm.doc.employee) {
			auto_populate_employee_and_approver(frm);
		}
	},
	
	onload: function(frm) {
		if (frm.is_new() && !frm.doc.employee) {
			auto_populate_employee_and_approver(frm);
		}
	},
	
	refresh: function(frm) {
		if (frm.is_new() && !frm.doc.employee) {
			auto_populate_employee_and_approver(frm);
		}
	},
	
	employee: function(frm) {
		if (frm.doc.employee) {
			frappe.call({
				method: 'alpinos.work_from_home_request_automation.get_leave_approver_for_employee_api',
				args: {
					employee: frm.doc.employee
				},
				callback: function(r) {
					if (r.message) {
						frm.set_value('leave_approver', r.message);
					} else {
						frm.set_value('leave_approver', '');
					}
				}
			});
		} else {
			frm.set_value('leave_approver', '');
		}
	}
});

function auto_populate_employee_and_approver(frm) {
	frappe.call({
		method: 'alpinos.work_from_home_request_automation.get_current_employee_and_approver',
		callback: function(r) {
			if (r.message && r.message.employee) {
				// also triggers the employee() handler above
				frm.set_value('employee', r.message.employee);

				if (r.message.leave_approver) {
					frm.set_value('leave_approver', r.message.leave_approver);
				} else {
					// backup fetch in case the employee trigger doesn't cover it
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
