/**
 * User Impersonation UI
 * Adds impersonation controls to the navbar
 */

frappe.provide('alpinos.impersonate');

alpinos.impersonate = {
	init: function() {
		// Wait for user roles to be loaded
		frappe.after_ajax(() => {
			// Check if user has Impersonate role
			// Use frappe.user_roles array which is more reliable
			const has_impersonate_role = frappe.user_roles && frappe.user_roles.includes('Impersonate');
			
			if (!has_impersonate_role) {
				console.log('Impersonate: User does not have Impersonate role');
				return;
			}
			
			console.log('Impersonate: User has Impersonate role, initializing...');
			
			// Check impersonation status on page load
			this.check_status();
			
			// Add impersonate button to navbar
			this.add_navbar_button();
		});
	},
	
	check_status: function() {
		frappe.call({
			method: 'alpinos.impersonate.get_impersonation_status',
			callback: (r) => {
				if (r.message && r.message.impersonating) {
					this.show_impersonation_banner(r.message);
				}
			}
		});
	},
	
	add_navbar_button: function() {
		// Add to navbar dropdown
		const navbar = $('.navbar-right');
		
		// Check if button already exists
		if ($('#impersonate-menu-item').length > 0) {
			console.log('Impersonate: Menu item already exists');
			return;
		}
		
		// Add impersonate menu item to user dropdown
		// Use multiple attempts to ensure DOM is ready
		let attempts = 0;
		const max_attempts = 10;
		
		const add_menu_item = () => {
			attempts++;
			const user_menu = $('#toolbar-user');
			
			if (user_menu.length > 0) {
				const dropdown = user_menu.find('.dropdown-menu');
				if (dropdown.length > 0) {
					// Check again if already added
					if ($('#impersonate-menu-item').length === 0) {
						dropdown.prepend(`
							<li>
								<a id="impersonate-menu-item" href="#" onclick="alpinos.impersonate.show_dialog(); return false;">
									<i class="fa fa-user-secret"></i> ${__('Impersonate User')}
								</a>
							</li>
							<li class="divider"></li>
						`);
						console.log('Impersonate: Menu item added successfully');
					}
					return;
				}
			}
			
			// Retry if not found and haven't exceeded max attempts
			if (attempts < max_attempts) {
				setTimeout(add_menu_item, 500);
			} else {
				console.log('Impersonate: Could not find user menu after', max_attempts, 'attempts');
			}
		};
		
		// Start trying to add menu item
		setTimeout(add_menu_item, 500);
	},
	
	show_dialog: function() {
		// Get list of users
		frappe.call({
			method: 'alpinos.impersonate.get_users_for_impersonation',
			callback: (r) => {
				if (r.message) {
					this.create_impersonate_dialog(r.message);
				}
			}
		});
	},
	
	create_impersonate_dialog: function(users) {
		const d = new frappe.ui.Dialog({
			title: __('Impersonate User'),
			fields: [
				{
					fieldtype: 'HTML',
					options: `
						<div class="alert alert-warning">
							<strong>${__('Warning:')}</strong> ${__('You are about to impersonate another user. All actions will be performed as that user.')}
						</div>
					`
				},
				{
					fieldname: 'target_user',
					label: __('Select User to Impersonate'),
					fieldtype: 'Link',
					options: 'User',
					reqd: 1,
					get_query: function() {
						return {
							filters: {
								enabled: 1,
								name: ['not in', [frappe.session.user, 'Administrator', 'Guest']]
							}
						};
					}
				}
			],
			primary_action_label: __('Start Impersonation'),
			primary_action: (values) => {
				this.start_impersonation(values.target_user);
				d.hide();
			}
		});
		
		d.show();
	},
	
	start_impersonation: function(target_user) {
		frappe.call({
			method: 'alpinos.impersonate.start_impersonation',
			args: {
				target_user: target_user
			},
			callback: (r) => {
				if (r.message && r.message.success) {
					frappe.show_alert({
						message: r.message.message,
						indicator: 'green'
					});
					
					// Show impersonation banner
					this.show_impersonation_banner({
						impersonating: true,
						original_user: r.message.original_user,
						impersonated_user: r.message.impersonated_user
					});
					
					// Reload page to apply new user context
					setTimeout(() => {
						window.location.reload();
					}, 1000);
				}
			}
		});
	},
	
	stop_impersonation: function() {
		frappe.call({
			method: 'alpinos.impersonate.stop_impersonation',
			callback: (r) => {
				if (r.message && r.message.success) {
					frappe.show_alert({
						message: r.message.message,
						indicator: 'blue'
					});
					
					// Remove banner
					$('#impersonation-banner').remove();
					
					// Reload page to restore original user context
					setTimeout(() => {
						window.location.reload();
					}, 1000);
				}
			}
		});
	},
	
	show_impersonation_banner: function(status) {
		// Remove existing banner if any
		$('#impersonation-banner').remove();
		
		// Add banner at top of page
		const banner = $(`
			<div id="impersonation-banner" style="
				position: fixed;
				top: 0;
				left: 0;
				right: 0;
				background: #ff6b6b;
				color: white;
				padding: 10px 20px;
				text-align: center;
				z-index: 10000;
				font-weight: bold;
				box-shadow: 0 2px 5px rgba(0,0,0,0.2);
			">
				<i class="fa fa-user-secret"></i>
				${__('IMPERSONATING:')} ${status.impersonated_user || frappe.session.user}
				<span style="margin: 0 10px;">|</span>
				${__('Original User:')} ${status.original_user}
				<button class="btn btn-xs btn-warning" style="margin-left: 20px;" onclick="alpinos.impersonate.stop_impersonation()">
					${__('Stop Impersonation')}
				</button>
			</div>
		`);
		
		$('body').prepend(banner);
		
		// Adjust page content to account for banner
		$('.page-head').css('margin-top', '50px');
	}
};

// Initialize on page load
$(document).ready(function() {
	alpinos.impersonate.init();
});

// Re-initialize on page change
$(document).on('page-change', function() {
	alpinos.impersonate.init();
});
