/**
 * User Impersonation UI
 * Adds impersonation controls to the navbar using Frappe's built-in approach
 */

frappe.provide('alpinos.impersonate');

alpinos.impersonate = {
	init: function() {
		// Check if user has Impersonate role
		const has_impersonate_role = frappe.user_roles && frappe.user_roles.includes('Impersonate');
		
		if (!has_impersonate_role) {
			return;
		}
		
		// Check impersonation status on page load
		this.check_status();
		
		// Add impersonate option to toolbar
		this.setup_toolbar();
	},
	
	setup_toolbar: function() {
		// Wait for toolbar to be ready
		frappe.after_ajax(() => {
			if (frappe.ui.toolbar && frappe.ui.toolbar.setup_session_defaults) {
				// Hook into the session defaults setup to add our menu item
				const original_setup = frappe.ui.toolbar.setup_session_defaults;
				frappe.ui.toolbar.setup_session_defaults = function() {
					original_setup.call(this);
					alpinos.impersonate.add_to_user_menu();
				};
				
				// If already setup, add directly
				if ($('.navbar').length > 0) {
					this.add_to_user_menu();
				}
			}
		});
	},
	
	add_to_user_menu: function() {
		// Check if already added
		if ($('#impersonate-user-link').length > 0) {
			return;
		}
		
		// Find the user dropdown - look for the one with "My Settings" or "Log out"
		const user_dropdown = $('.dropdown-menu:contains("My Settings"), .dropdown-menu:contains("Log out")').first();
		
		if (user_dropdown.length > 0) {
			// Add the menu item at the top
			const menu_item = $(`
				<li>
					<a id="impersonate-user-link" class="dropdown-item" href="#">
						<svg class="icon icon-sm"><use href="#icon-shuffle"></use></svg>
						<span class="menu-item-label">${__('Switch to User')}</span>
					</a>
				</li>
			`);
			
			menu_item.find('a').on('click', (e) => {
				e.preventDefault();
				alpinos.impersonate.show_dialog();
			});
			
			user_dropdown.prepend(menu_item);
			console.log('Impersonate: Menu item added');
		}
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
	
	show_dialog: function() {
		const d = new frappe.ui.Dialog({
			title: __('Switch to User'),
			fields: [
				{
					fieldname: 'user',
					label: __('User'),
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
			primary_action_label: __('Switch'),
			primary_action: (values) => {
				this.start_impersonation(values.user);
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
