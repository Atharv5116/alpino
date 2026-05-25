/**
 * Override User form to show Impersonate button for users with Impersonate role
 * (not just Administrator)
 */

frappe.ui.form.on('User', {
	refresh: function(frm) {
		// Check if current user has Impersonate role or is Administrator
		const can_impersonate = frappe.user_roles.includes('Impersonate') || frappe.session.user === 'Administrator';
		
		// Only show button if:
		// 1. User has Impersonate role or is Administrator
		// 2. Not viewing own profile
		// 3. Not viewing Administrator profile
		if (can_impersonate && frm.doc.name !== frappe.session.user && frm.doc.name !== 'Administrator') {
			// Remove existing button if any
			frm.remove_custom_button(__('Impersonate'));
			
			// Add Impersonate button
			frm.add_custom_button(__('Impersonate'), () => {
				if (frm.doc.restrict_ip) {
					frappe.msgprint({
						message: __("There's IP restriction for this user, you cannot impersonate as this user."),
						title: __("IP restriction is enabled"),
					});
					return;
				}
				
				frappe.prompt(
					[
						{
							fieldtype: "Small Text",
							label: __("Reason for impersonation"),
							fieldname: "reason",
							reqd: 1,
						},
					],
					(values) => {
						frappe
							.xcall("alpinos.overrides.user_override.impersonate", {
								user: frm.doc.name,
								reason: values.reason,
							})
							.then(() => window.location.reload());
					},
					__("Impersonate as {0}", [frm.doc.name]),
					__("Confirm")
				);
			});
		}
	}
});
