"""
Customize Expense Claim DocType
- Hide non-required fields in main Expense Claim doctype
- Make hidden fields non-mandatory
"""

import frappe
from frappe.model.workflow import get_workflow_name
from frappe.utils import cstr
from frappe import _
from hrms.hr.doctype.expense_claim.expense_claim import ExpenseClaim as OriginalExpenseClaim


def update_property_setter(doctype, fieldname, property_name, value, property_type="Data"):
	"""Create or update a property setter"""
	try:
		existing = frappe.db.exists(
			"Property Setter",
			{
				"doc_type": doctype,
				"field_name": fieldname,
				"property": property_name,
			}
		)
		
		if existing:
			ps = frappe.get_doc("Property Setter", existing)
			ps.value = value
			ps.property_type = property_type
			ps.save(ignore_permissions=True)
		else:
			ps = frappe.get_doc({
				"doctype": "Property Setter",
				"doctype_or_field": "DocField",
				"doc_type": doctype,
				"field_name": fieldname,
				"property": property_name,
				"value": value,
				"property_type": property_type,
			})
			ps.insert(ignore_permissions=True)
		
		frappe.db.commit()
	except Exception as e:
		frappe.log_error(f"Error updating property setter for {doctype}.{fieldname}.{property_name}: {str(e)}", "Property Setter Error")
		print(f"⚠️  Could not update property setter: {str(e)}")


def hide_field_and_make_non_mandatory(doctype, fieldname):
	"""Hide a field and make it non-mandatory"""
	update_property_setter(doctype, fieldname, "hidden", "1", "Check")
	update_property_setter(doctype, fieldname, "reqd", "0", "Check")
	print(f"✅ Hidden and made non-mandatory: {doctype}.{fieldname}")


def delete_reporting_manager_field():
	"""Delete Reporting Manager custom field from Expense Claim (if it exists)"""
	try:
		custom_field = frappe.db.get_value(
			"Custom Field",
			{"dt": "Expense Claim", "fieldname": "reporting_manager"},
			"name",
		)
		if custom_field:
			frappe.delete_doc("Custom Field", custom_field, force=True, ignore_permissions=True)
			frappe.db.commit()
			print("✅ Deleted Reporting Manager custom field from Expense Claim")
	except Exception as e:
		frappe.log_error(
			f"Error deleting Reporting Manager field: {str(e)}",
			"Expense Claim Field Cleanup Error",
		)
		print(f"⚠️  Could not delete Reporting Manager field: {str(e)}")


def make_expense_claim_detail_fields_non_mandatory():
	"""Make all fields in Expense Claim Detail table non-mandatory"""
	print("\n🔧 Making Expense Claim Detail fields non-mandatory...")
	
	doctype = "Expense Claim Detail"
	
	# Get all fields from the doctype
	try:
		doc = frappe.get_doc("DocType", doctype)
		fields_updated = 0
		
		for field in doc.fields:
			# Skip system fields and layout fields
			if field.fieldtype in ["Section Break", "Column Break", "Tab Break", "HTML", "Button"]:
				continue
			
			# Make field non-mandatory
			update_property_setter(doctype, field.fieldname, "reqd", "0", "Check")
			fields_updated += 1
		
		print(f"✅ Made {fields_updated} fields non-mandatory in Expense Claim Detail")
		
	except Exception as e:
		frappe.log_error(f"Error making Expense Claim Detail fields non-mandatory: {str(e)}", "Expense Claim Detail Error")
		print(f"⚠️  Error: {str(e)}")


def add_reimbursement_child_table():
	"""Add Reimbursement child table to Expense Claim"""
	print("\n🔧 Adding Reimbursement child table to Expense Claim...")
	
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
	
	custom_fields = {
		"Expense Claim": [
			# Reimbursement section - insert after column_break_5 to ensure it's after the column break
			dict(
				fieldname="reimbursement_section",
				label="Reimbursement",
				fieldtype="Section Break",
				insert_after="column_break_5",
				module="Alpinos Development",
			),
			# Reimbursement child table (inside reimbursement section)
			dict(
				fieldname="reimbursement",
				label="Reimbursement",
				fieldtype="Table",
				options="Reimbursement child table",
				insert_after="reimbursement_section",
				module="Alpinos Development",
			),
		]
	}
	
	try:
		# Hide column_break_5 FIRST to ensure it doesn't affect the reimbursement section
		update_property_setter("Expense Claim", "column_break_5", "hidden", "1", "Check")
		print("✅ Hidden column_break_5 to ensure full width reimbursement section")
		
		create_custom_fields(custom_fields, update=True)
		print("✅ Added Reimbursement section and child table to Expense Claim")
		
		# Verify fields were created
		section_exists = frappe.db.exists("Custom Field", {
			"dt": "Expense Claim",
			"fieldname": "reimbursement_section"
		})
		table_exists = frappe.db.exists("Custom Field", {
			"dt": "Expense Claim",
			"fieldname": "reimbursement"
		})
		if section_exists and table_exists:
			print("   ✓ Verified: reimbursement_section and reimbursement fields exist")
		else:
			print("   ⚠️  Warning: Some fields not found after creation")
		
		# Ensure section break and table are full width by setting column property
		# Section breaks should naturally be full width, but ensure no column breaks affect it
		# Check if there are any column breaks after reimbursement_section and hide them
		try:
			# Get the doctype to check field order
			doc = frappe.get_doc("DocType", "Expense Claim")
			reimbursement_section_idx = None
			for idx, field in enumerate(doc.fields):
				if field.fieldname == "reimbursement_section":
					reimbursement_section_idx = idx
					break
			
			# Check for column breaks after reimbursement_section
			if reimbursement_section_idx is not None:
				for field in doc.fields[reimbursement_section_idx + 1:]:
					if field.fieldtype == "Column Break" and field.fieldname != "column_break_5":
						update_property_setter("Expense Claim", field.fieldname, "hidden", "1", "Check")
						print(f"   ✓ Hidden column break: {field.fieldname}")
					# Stop checking after we hit the reimbursement table or another section
					if field.fieldname == "reimbursement" or (field.fieldtype == "Section Break" and field.fieldname != "reimbursement_section"):
						break
		except Exception as e:
			print(f"   ⚠️  Could not check for additional column breaks: {str(e)}")
		
		# Reload doctype to ensure field is visible
		frappe.clear_cache(doctype="Expense Claim")
		frappe.reload_doc("HR", "DocType", "Expense Claim", force=True)
		print("✅ Reloaded Expense Claim doctype")
		
	except Exception as e:
		frappe.log_error(f"Error adding Reimbursement child table: {str(e)}", "Reimbursement Table Error")
		print(f"⚠️  Error adding Reimbursement child table: {str(e)}")
		raise


def set_reimbursement_child_defaults():
	"""Set default values for Reimbursement child table fields"""
	print("\n🔧 Setting defaults for Reimbursement child table...")
	try:
		# Default Payment Type to "Outside Payroll"
		update_property_setter("Reimbursement child table", "payment_type", "default", "Outside Payroll", "Data")
		print("✅ Set default Payment Type to Outside Payroll")

		# Payment Mode visibility and mandatory settings are now handled by client script
		# For Outside Payroll: visible and required
		# For Inside Payroll: hidden and non-required
		update_property_setter("Reimbursement child table", "payment_mode", "reqd", "0", "Check")
		print("✅ Payment Mode visibility and mandatory state controlled by client script based on Payment Type")
	except Exception as e:
		frappe.log_error(f"Error setting defaults for Reimbursement child table: {str(e)}", "Reimbursement Defaults Error")
		print(f"⚠️  Error setting defaults: {str(e)}")
		raise


def create_reimbursement_add_row_script():
	"""Create client script to show Add Row button only when Expense Type is Business"""
	print("\n🔧 Creating client script for Reimbursement Add Row button...")
	
	script = """
frappe.ui.form.on('Expense Claim', {
	onload: function(frm) {
		setTimeout(function() {
			setup_reimbursement_add_row_control(frm);
			toggle_reimbursement_add_row(frm);

			// Toggle payment_mode visibility for all rows on load after grid is ready
			setTimeout(function() {
				if (frm.doc.reimbursement && frm.doc.reimbursement.length > 0) {
					frm.doc.reimbursement.forEach(function(row) {
						if (row.name) {
							toggle_payment_mode_required(frm, 'Reimbursement child table', row.name);
						}
					});
				}
			}, 300);
		}, 500);
	},

	employee: function(frm) {
		// Auto-fill Expense Approver based on employee.reports_to.user_id (if field exists)
		if (!frm.fields_dict.expense_approver) {
			return;
		}

		if (frm.doc.employee) {
			frappe.db.get_value('Employee', frm.doc.employee, 'reports_to', function(data) {
				if (data && data.reports_to) {
					frappe.db.get_value('Employee', data.reports_to, 'user_id', function(manager) {
						frm.set_value('expense_approver', (manager && manager.user_id) ? manager.user_id : '');
					});
				} else {
					frm.set_value('expense_approver', '');
				}
			});
		} else {
			frm.set_value('expense_approver', '');
		}
	},
	
	refresh: function(frm) {
		setup_reimbursement_add_row_control(frm);
		toggle_reimbursement_add_row(frm);
		
		// Toggle payment_mode visibility for all rows after a delay to ensure grid is ready
		setTimeout(function() {
			if (frm.doc.reimbursement && frm.doc.reimbursement.length > 0) {
				frm.doc.reimbursement.forEach(function(row) {
					if (row.name) {
						toggle_payment_mode_required(frm, 'Reimbursement child table', row.name);
					}
				});
			}
		}, 300);
		
		// Set up continuous monitoring (less frequent to avoid interference)
		if (frm._reimbursement_check_interval) {
			clearInterval(frm._reimbursement_check_interval);
		}
		frm._reimbursement_check_interval = setInterval(function() {
			toggle_reimbursement_add_row(frm);
		}, 1000);
	},
	
	reimbursement_add: function(frm, cdt, cdn) {
		// Reset handler setup flags when a row is added, so handler can be re-attached after grid refresh
		var grid_field = frm.get_field('reimbursement');
		if (grid_field && grid_field.grid && grid_field.grid._add_row_state) {
			grid_field.grid._add_row_state.handler_setup = false;
			grid_field.grid._add_row_state.setup_in_progress = false;
		}
		setTimeout(function() {
			toggle_reimbursement_add_row(frm);
			// Toggle payment_mode visibility for the newly added row
			toggle_payment_mode_required(frm, cdt, cdn);
		}, 200);
	},
	
	reimbursement_remove: function(frm, cdt, cdn) {
		setTimeout(function() {
			toggle_reimbursement_add_row(frm);
		}, 100);
	}
});

frappe.ui.form.on('Reimbursement child table', {
	expense_type: function(frm, cdt, cdn) {
		// Get the child doc to check the current value immediately
		var child_doc = frappe.get_doc(cdt, cdn);
		// Use a timeout to ensure form data is synced, but also check immediately
		setTimeout(function() {
			toggle_reimbursement_add_row(frm);
		}, 300);
	},
	
	payment_type: function(frm, cdt, cdn) {
		// Toggle payment_mode required state based on payment_type
		toggle_payment_mode_required(frm, cdt, cdn);
	},
	
	form_render: function(frm, cdt, cdn) {
		setTimeout(function() {
			toggle_reimbursement_add_row(frm);
			toggle_payment_mode_required(frm, cdt, cdn);
		}, 100);
	}
});

function setup_reimbursement_add_row_control(frm) {
	var grid_field = frm.get_field('reimbursement');
	if (!grid_field || !grid_field.grid) {
		setTimeout(function() {
			setup_reimbursement_add_row_control(frm);
		}, 200);
		return;
	}
	
	var grid = grid_field.grid;
	
	// Hook into grid refresh to ensure button is hidden after refresh
	if (!grid._add_row_control_hooked) {
		var original_refresh = grid.refresh;
		grid.refresh = function() {
			var result = original_refresh.apply(this, arguments);
			setTimeout(function() {
				toggle_reimbursement_add_row(frm);
			}, 50);
			return result;
		};
		grid._add_row_control_hooked = true;
	}
}

function toggle_reimbursement_add_row(frm) {
	var grid_field = frm.get_field('reimbursement');
	if (!grid_field || !grid_field.grid) {
		return;
	}
	
	var grid = grid_field.grid;
	
	// Track the current state to avoid unnecessary re-setup
	if (!grid._add_row_state) {
		grid._add_row_state = {
			should_show: false,
			handler_setup: false,
			setup_in_progress: false
		};
	}
	
	// Get rows - try grid rows first (most up-to-date), then fallback to frm.doc
	var reimbursement_rows = [];
	
	// Method 1: Get from grid rows if available
	if (grid.rows && grid.rows.length > 0) {
		reimbursement_rows = grid.rows.map(function(grid_row) {
			return grid_row.doc || grid_row;
		});
	}
	
	// Method 2: Get from grid data_rows if available
	if (reimbursement_rows.length === 0 && grid.data_rows && grid.data_rows.length > 0) {
		reimbursement_rows = grid.data_rows.map(function(row) {
			return row.doc || row;
		});
	}
	
	// Method 3: Fallback to frm.doc
	if (reimbursement_rows.length === 0) {
		reimbursement_rows = frm.doc.reimbursement || [];
	}
	
	// If no rows exist, allow adding the first row (show button)
	if (reimbursement_rows.length === 0) {
		// Only update if state changed
		if (grid._add_row_state.should_show !== true) {
		frm.set_df_property('reimbursement', 'cannot_add_rows', 0);
		grid.cannot_add_rows = false;
		if (grid.wrapper) {
			$(grid.wrapper).find('.grid-add-row').show();
			}
			grid._add_row_state.should_show = true;
			grid._add_row_state.handler_setup = false; // Reset so handler gets set up
			grid._add_row_state.setup_in_progress = false; // Reset setup flag
		}
		return;
	}
	
	// Check if any row has expense_type = "Business"
	var has_business = false;
	for (var i = 0; i < reimbursement_rows.length; i++) {
		var row = reimbursement_rows[i];
		var expense_type = row.expense_type;
		
		// If expense_type is not directly available, try to get from grid row
		if (!expense_type && row.name && grid.get_row) {
			try {
				var grid_row = grid.get_row(row.name);
				if (grid_row && grid_row.doc && grid_row.doc.expense_type) {
					expense_type = grid_row.doc.expense_type;
				}
			} catch(e) {
				// Ignore errors
			}
		}
		
		// Check the value (case-insensitive to be safe)
		if (expense_type && expense_type.trim() === 'Business') {
			has_business = true;
			break; // Found one, no need to continue
		}
	}
	
	// Only proceed if state actually changed
	var state_changed = (grid._add_row_state.should_show !== has_business);
	
	if (has_business) {
		// Show Add Row button if at least one row has Expense Type = "Business"
		// First, ensure cannot_add_rows is false at all levels
		frm.set_df_property('reimbursement', 'cannot_add_rows', 0);
		grid.cannot_add_rows = false;
		if (grid.df) {
			grid.df.cannot_add_rows = false;
		}
		
		// Only manipulate button if state changed or handler not set up
		if (state_changed || !grid._add_row_state.handler_setup) {
			// Show the button first
		if (grid.wrapper) {
			var $add_btn = $(grid.wrapper).find('.grid-add-row');
			
			// If not found, try finding by text
			if ($add_btn.length === 0) {
				$(grid.wrapper).find('button').each(function() {
					var btn_text = $(this).text().trim();
					if (btn_text === 'Add Row' || btn_text.indexOf('Add Row') !== -1) {
						$add_btn = $add_btn.add($(this));
					}
				});
			}
			
			if ($add_btn.length > 0) {
					// CRITICAL: Remove ALL click handlers first (including the prevention handler we added when hiding)
					$add_btn.off('click');
					
				// Remove all hiding styles and show the button
				$add_btn.removeClass('hidden');
					$add_btn.removeAttr('style');
				$add_btn.css({
						'display': '',
						'visibility': '',
						'pointer-events': 'auto'
				});
				$add_btn.prop('disabled', false);
				$add_btn.removeAttr('disabled');
				$add_btn.show();
				
					// Setup the add row button handler ONLY ONCE
					// Use flags to prevent multiple handler attachments
					if (!grid._add_row_state.handler_setup && !grid._add_row_state.setup_in_progress) {
						// Clear any pending timeouts to prevent multiple setups
						if (grid._add_row_setup_timeout) {
							clearTimeout(grid._add_row_setup_timeout);
						}
						
						// Mark as in progress to prevent concurrent calls
						grid._add_row_state.setup_in_progress = true;
						
						grid._add_row_setup_timeout = setTimeout(function() {
							if (grid.setup_add_row && grid.wrapper) {
								// Remove any existing handlers first to prevent duplicates
								var $add_btn = $(grid.wrapper).find('.grid-add-row');
								if ($add_btn.length > 0) {
									$add_btn.off('click');
								}
								// Now setup the handler
								grid.setup_add_row();
								// Mark as set up only after handler is attached
								grid._add_row_state.handler_setup = true;
							}
							grid._add_row_state.setup_in_progress = false;
							grid._add_row_setup_timeout = null;
						}, 100);
			}
		}
			}
		}
		
		grid._add_row_state.should_show = true;
	} else {
		// Hide Add Row button if no row has Expense Type = "Business"
		// Only update if state changed
		if (state_changed || grid._add_row_state.should_show !== false) {
		frm.set_df_property('reimbursement', 'cannot_add_rows', 1);
		grid.cannot_add_rows = true;
		if (grid.df) {
			grid.df.cannot_add_rows = true;
		}
		
		// Multiple methods to hide the button - use exact class from Frappe source
		if (grid.wrapper) {
			// Primary selector: .grid-add-row (exact class from Frappe grid.js line 97)
			var $add_btn = $(grid.wrapper).find('.grid-add-row');
			
			// If not found, try finding by text
			if ($add_btn.length === 0) {
				$(grid.wrapper).find('button').each(function() {
					var btn_text = $(this).text().trim();
					if (btn_text === 'Add Row' || btn_text.indexOf('Add Row') !== -1) {
						$add_btn = $add_btn.add($(this));
					}
				});
			}
			
			if ($add_btn.length > 0) {
					// Remove all click handlers first
					$add_btn.off('click');
					
				// Hide using multiple methods
				$add_btn.hide();
				$add_btn.css('display', 'none !important');
				$add_btn.css('visibility', 'hidden');
				$add_btn.addClass('hidden');
				$add_btn.attr('style', 'display: none !important;');
				
				// Prevent clicks and stop propagation
					$add_btn.on('click', function(e) {
					e.preventDefault();
					e.stopImmediatePropagation();
					e.stopPropagation();
					return false;
				});
				
				// Also disable the button
				$add_btn.prop('disabled', true);
				$add_btn.attr('disabled', 'disabled');
			}
		}
			
			// Reset handler setup flags so it can be set up again when shown
			grid._add_row_state.handler_setup = false;
			grid._add_row_state.setup_in_progress = false;
		}
		grid._add_row_state.should_show = false;
	}
}

function toggle_payment_mode_required(frm, cdt, cdn) {
	// Get the child doc to check payment_type value
	var child_doc = frappe.get_doc(cdt, cdn);
	if (!child_doc) {
		return;
	}

	var payment_type = child_doc.payment_type;
	var is_outside_payroll = (payment_type === 'Outside Payroll');
	var is_inside_payroll = (payment_type === 'Inside Payroll');

	// Get the grid field
	var grid_field = frm.get_field('reimbursement');
	if (!grid_field || !grid_field.grid) {
		// Retry after a short delay
		setTimeout(function() {
			toggle_payment_mode_required(frm, cdt, cdn);
		}, 200);
		return;
	}

	var grid = grid_field.grid;

	// Find the grid row for this child doc
	var grid_row = null;
	if (grid.rows && grid.rows.length > 0) {
		for (var i = 0; i < grid.rows.length; i++) {
			if (grid.rows[i].doc && grid.rows[i].doc.name === child_doc.name) {
				grid_row = grid.rows[i];
				break;
			}
		}
	}

	// If grid row not found, try to get it using get_row method
	if (!grid_row && grid.get_row) {
		try {
			grid_row = grid.get_row(child_doc.name);
		} catch(e) {
			// Ignore errors
		}
	}

	if (grid_row) {
		if (is_inside_payroll) {
			// For Inside Payroll: clear payment_mode value and make it read-only
			child_doc.payment_mode = ''; // Clear the value

			// Make the payment_mode field read-only (visible but not editable)
			if (grid_row.set_field_property) {
				grid_row.set_field_property('payment_mode', 'read_only', 1);
				grid_row.set_field_property('payment_mode', 'reqd', 0);
			}

			// For editable grid columns
			if (grid_row.columns_list) {
				grid_row.columns_list.forEach(function(column) {
					if (column.df && column.df.fieldname === 'payment_mode') {
						column.df.read_only = 1;
						column.df.reqd = 0;
						if (column.field) {
							column.field.set_value(''); // Clear value
							column.field.refresh();
						}
					}
				});
			}

			// For grid form view
			if (grid_row.grid_form && grid_row.grid_form.fields_dict && grid_row.grid_form.fields_dict.payment_mode) {
				var payment_mode_field = grid_row.grid_form.fields_dict.payment_mode;
				payment_mode_field.df.read_only = 1;
				payment_mode_field.df.reqd = 0;
				payment_mode_field.set_value(''); // Clear value
				payment_mode_field.refresh();
			}
		} else {
			// For Outside Payroll: make payment_mode editable and required
			if (grid_row.set_field_property) {
				grid_row.set_field_property('payment_mode', 'read_only', 0);
				grid_row.set_field_property('payment_mode', 'reqd', 1);
			}

			// For editable grid columns
			if (grid_row.columns_list) {
				grid_row.columns_list.forEach(function(column) {
					if (column.df && column.df.fieldname === 'payment_mode') {
						column.df.read_only = 0;
						column.df.reqd = 1;
						if (column.field) {
							column.field.refresh();
						}
					}
				});
			}

			// For grid form view
			if (grid_row.grid_form && grid_row.grid_form.fields_dict && grid_row.grid_form.fields_dict.payment_mode) {
				var payment_mode_field = grid_row.grid_form.fields_dict.payment_mode;
				payment_mode_field.df.read_only = 0;
				payment_mode_field.df.reqd = 1;
				payment_mode_field.refresh();
			}
		}
	} else {
		// Fallback: use setTimeout to wait for grid row to be available
		setTimeout(function() {
			toggle_payment_mode_required(frm, cdt, cdn);
		}, 200);
	}
}
"""
	
	try:
		# Check if client script already exists
		script_name = "Expense Claim - Reimbursement Add Row Control"
		if frappe.db.exists("Client Script", script_name):
			client_script = frappe.get_doc("Client Script", script_name)
			client_script.script = script
			client_script.enabled = 1
			client_script.save(ignore_permissions=True)
			frappe.db.commit()
			print(f"✅ Updated client script: {script_name}")
		else:
			# Create new client script
			client_script = frappe.get_doc({
				"doctype": "Client Script",
				"name": script_name,
				"dt": "Expense Claim",
				"view": "Form",
				"enabled": 1,
				"script": script
			})
			client_script.insert(ignore_permissions=True)
			frappe.db.commit()
			print(f"✅ Created client script: {script_name}")
	except Exception as e:
		frappe.log_error(f"Error creating client script for Reimbursement Add Row: {str(e)}", "Client Script Error")
		print(f"⚠️  Could not create client script: {str(e)}")


def customize_expense_claim_main():
	"""Customize Expense Claim main doctype - hide non-required fields"""
	print("\n🔧 Customizing Expense Claim main doctype...")
	
	# Fields to hide (non-required fields)
	fields_to_hide = [
		"naming_series",  # Keep but hide (system field)
		"employee_name",  # Keep but hide (auto-fetched)
		"department",
		# "approval_status",  # Removed - now visible
		"total_sanctioned_amount",
		"total_taxes_and_charges",
		"total_advance_amount",
		"grand_total",
		"total_amount_reimbursed",
		"is_paid",
		"posting_date",  # Keep but hide
		"mode_of_payment",
		# "payable_account",  # Removed - now visible
		"clearance_date",
		"remark",
		"project",
		"cost_center",
		# "status",  # Removed - now visible and positioned after employee field
		"task",
		"amended_from",  # Keep but hide (system field)
		"delivery_trip",
		"vehicle_log",
		"taxes_and_charges_sb",
		"taxes",
		"advance_payments_sb",
		"advances",
		"transactions_section",
		"column_break_17",
		# "accounting_details_tab",  # Removed - now visible
		# "accounting_details",  # Removed - now visible
		"column_break_24",
		# "accounting_dimensions_section",  # Removed - now visible
		"dimension_col_break",
		# "more_info_tab",  # Removed - now visible (contains status field)
		"more_details",
		"column_break_xdzn",
		"dashboard_tab",
		"column_break_5",
		"expense_details",  # Section break for expenses table
		"expenses",  # Expense Claim Detail child table
	]
	
	for fieldname in fields_to_hide:
		hide_field_and_make_non_mandatory("Expense Claim", fieldname)
	
	# Keep employee and company visible and mandatory
	update_property_setter("Expense Claim", "employee", "reqd", "1", "Check")
	update_property_setter("Expense Claim", "company", "reqd", "1", "Check")

	# Ensure Expense Approver is visible and non-mandatory
	update_property_setter("Expense Claim", "expense_approver", "hidden", "0", "Check")
	update_property_setter("Expense Claim", "expense_approver", "reqd", "0", "Check")

	# Ensure Status field is visible and non-mandatory, positioned after employee (at top)
	# First, make sure it's not hidden
	update_property_setter("Expense Claim", "status", "hidden", "0", "Check")
	update_property_setter("Expense Claim", "status", "reqd", "0", "Check")
	# Position it right after employee field (at the top of the form)
	update_property_setter("Expense Claim", "status", "insert_after", "employee", "Data")
	# Make it show in list view
	update_property_setter("Expense Claim", "status", "in_list_view", "1", "Check")
	# Make it show in standard filter
	update_property_setter("Expense Claim", "status", "in_standard_filter", "1", "Check")
	# Ensure it's not in a hidden tab by explicitly setting it to be in the main form
	# The insert_after should move it out of the more_info_tab

	# Delete Reporting Manager field
	delete_reporting_manager_field()

	# Move Expense Approver to after status field
	update_property_setter("Expense Claim", "expense_approver", "insert_after", "status", "Data")
	
	print("✅ Expense Claim main doctype customization complete!")


def check_status_field_visibility():
	"""Check if status field property setters are applied correctly"""
	print("\n🔍 Checking status field visibility...")

	status_hidden = frappe.db.exists('Property Setter', {
		'doc_type': 'Expense Claim',
		'field_name': 'status',
		'property': 'hidden'
	})
	status_reqd = frappe.db.exists('Property Setter', {
		'doc_type': 'Expense Claim',
		'field_name': 'status',
		'property': 'reqd'
	})

	if status_hidden:
		hidden_ps = frappe.get_doc('Property Setter', status_hidden)
		print(f'✅ Status hidden property setter exists: {hidden_ps.value}')
	else:
		print('❌ Status hidden property setter not found')

	if status_reqd:
		reqd_ps = frappe.get_doc('Property Setter', status_reqd)
		print(f'✅ Status reqd property setter exists: {reqd_ps.value}')
	else:
		print('❌ Status reqd property setter not found')


def verify_status_field_configuration():
	"""Verify that status field is properly configured in Expense Claim"""
	print("\n🔍 Verifying status field configuration...")

	# Get the Expense Claim doctype
	doctype = frappe.get_doc('DocType', 'Expense Claim')

	# Find the status field
	status_field = None
	for field in doctype.fields:
		if field.fieldname == 'status':
			status_field = field
			break

	if status_field:
		print(f'✅ Status field found in Expense Claim doctype')
		print(f'   Fieldname: {status_field.fieldname}')
		print(f'   Label: {status_field.label}')
		print(f'   Fieldtype: {status_field.fieldtype}')
		print(f'   Hidden: {status_field.hidden}')
		print(f'   Required: {status_field.reqd}')

		# Check property setters
		hidden_ps = frappe.db.get_value('Property Setter',
			{'doc_type': 'Expense Claim', 'field_name': 'status', 'property': 'hidden'},
			'value')
		reqd_ps = frappe.db.get_value('Property Setter',
			{'doc_type': 'Expense Claim', 'field_name': 'status', 'property': 'reqd'},
			'value')

		print(f'   Hidden Property Setter: {hidden_ps}')
		print(f'   Required Property Setter: {reqd_ps}')

		# Final determination
		is_hidden = hidden_ps == '1' if hidden_ps is not None else status_field.hidden
		is_required = reqd_ps == '1' if reqd_ps is not None else status_field.reqd

		if not is_hidden:
			print('✅ STATUS: Status field is VISIBLE')
		else:
			print('❌ STATUS: Status field is HIDDEN')

		if not is_required:
			print('✅ STATUS: Status field is NON-MANDATORY')
		else:
			print('⚠️ STATUS: Status field is MANDATORY')

	else:
		print('❌ Status field not found in Expense Claim doctype')


def check_property_setters():
	"""Check the actual property setter records"""
	print("\n🔍 Checking property setter records...")

	hidden_ps = frappe.db.sql("""
		SELECT name, value FROM `tabProperty Setter`
		WHERE doc_type = 'Expense Claim' AND field_name = 'status' AND property = 'hidden'
	""", as_dict=True)

	reqd_ps = frappe.db.sql("""
		SELECT name, value FROM `tabProperty Setter`
		WHERE doc_type = 'Expense Claim' AND field_name = 'status' AND property = 'reqd'
	""", as_dict=True)

	print(f'Hidden Property Setters for status: {hidden_ps}')
	print(f'Reqd Property Setters for status: {reqd_ps}')


def check_approval_status_property_setters():
	"""Check the property setter records for approval_status"""
	print("\n🔍 Checking approval_status property setter records...")

	hidden_ps = frappe.db.sql("""
		SELECT name, value FROM `tabProperty Setter`
		WHERE doc_type = 'Expense Claim' AND field_name = 'approval_status' AND property = 'hidden'
	""", as_dict=True)

	reqd_ps = frappe.db.sql("""
		SELECT name, value FROM `tabProperty Setter`
		WHERE doc_type = 'Expense Claim' AND field_name = 'approval_status' AND property = 'reqd'
	""", as_dict=True)

	print(f'Hidden Property Setters for approval_status: {hidden_ps}')
	print(f'Reqd Property Setters for approval_status: {reqd_ps}')


def fix_status_field_visibility():
	"""Fix the status field visibility by updating the property setter"""
	print("\n🔧 Fixing status field visibility...")

	try:
		# Update the hidden property setter
		ps = frappe.get_doc('Property Setter', 'Expense Claim-status-hidden')
		ps.value = '0'
		ps.save(ignore_permissions=True)
		frappe.db.commit()
		print('✅ Updated status field to be visible (hidden = 0)')
	except Exception as e:
		print(f'❌ Error updating property setter: {str(e)}')


def verify_approval_status_field_configuration():
	"""Verify that approval_status field is properly configured in Expense Claim"""
	print("\n🔍 Verifying approval_status field configuration...")

	# Get the Expense Claim doctype
	doctype = frappe.get_doc('DocType', 'Expense Claim')

	# Find the approval_status field
	approval_status_field = None
	for field in doctype.fields:
		if field.fieldname == 'approval_status':
			approval_status_field = field
			break

	if approval_status_field:
		print(f'✅ Approval Status field found in Expense Claim doctype')
		print(f'   Fieldname: {approval_status_field.fieldname}')
		print(f'   Label: {approval_status_field.label}')
		print(f'   Fieldtype: {approval_status_field.fieldtype}')
		print(f'   Hidden: {approval_status_field.hidden}')
		print(f'   Required: {approval_status_field.reqd}')

		# Check property setters
		hidden_ps = frappe.db.get_value('Property Setter',
			{'doc_type': 'Expense Claim', 'field_name': 'approval_status', 'property': 'hidden'},
			'value')
		reqd_ps = frappe.db.get_value('Property Setter',
			{'doc_type': 'Expense Claim', 'field_name': 'approval_status', 'property': 'reqd'},
			'value')

		print(f'   Hidden Property Setter: {hidden_ps}')
		print(f'   Required Property Setter: {reqd_ps}')

		# Final determination
		is_hidden = hidden_ps == '1' if hidden_ps is not None else approval_status_field.hidden
		is_required = reqd_ps == '1' if reqd_ps is not None else approval_status_field.reqd

		if not is_hidden:
			print('✅ STATUS: Approval Status field is VISIBLE')
		else:
			print('❌ STATUS: Approval Status field is HIDDEN')

		if not is_required:
			print('✅ STATUS: Approval Status field is NON-MANDATORY')
		else:
			print('⚠️ STATUS: Approval Status field is MANDATORY')

	else:
		print('❌ Approval Status field not found in Expense Claim doctype')


def update_expense_claim_status_options():
	"""Update status field options to match workflow requirements"""
	print("\n🔧 Updating Expense Claim status field options...")
	
	try:
		# Update the status field options to match workflow states
		update_property_setter(
			"Expense Claim",
			"status",
			"options",
			"Draft\nPending RM Approval\nApproved by RM\nRejected\nSubmitted to Payroll\nPaid",
			"Text"
		)
		print("✅ Updated status field options to match workflow states")
	except Exception as e:
		frappe.log_error(f"Error updating status options: {str(e)}", "Status Options Error")
		print(f"⚠️  Could not update status options: {str(e)}")


def update_expense_claim_approval_status_options():
	"""Update approval_status field options to match workflow requirements"""
	print("\n🔧 Updating Expense Claim approval_status field options...")
	
	try:
		update_property_setter(
			"Expense Claim",
			"approval_status",
			"options",
			"Draft\nPending RM Approval\nApproved by RM\nRejected\nSubmitted to Payroll\nPaid",
			"Text"
		)
		print("✅ Updated approval_status field options to match workflow states")
	except Exception as e:
		frappe.log_error(f"Error updating approval_status options: {str(e)}", "Approval Status Options Error")
		print(f"⚠️  Could not update approval_status options: {str(e)}")


def move_status_field_to_visible_area():
	"""Move status field from hidden tab to visible area (after employee field)"""
	print("\n🔧 Moving status field to visible area...")
	
	try:
		# Get the DocType
		ec_dt = frappe.get_doc("DocType", "Expense Claim")
		
		# Find employee and status field indices
		employee_idx = None
		status_idx = None
		for idx, field in enumerate(ec_dt.fields):
			if field.fieldname == "employee":
				employee_idx = idx
			if field.fieldname == "status":
				status_idx = idx
		
		if status_idx is not None and employee_idx is not None:
			# Check if status is already in a good position (within first 10 fields after employee)
			if status_idx <= employee_idx + 10:
				# Check if it's in a hidden tab
				in_hidden_tab = False
				for idx in range(employee_idx + 1, status_idx):
					prev_field = ec_dt.fields[idx]
					if prev_field.fieldtype == "Tab Break":
						tab_hidden = frappe.db.get_value("Property Setter",
							{"doc_type": "Expense Claim", "field_name": prev_field.fieldname, "property": "hidden"},
							"value"
						)
						if tab_hidden == "1":
							in_hidden_tab = True
							break
				
				if not in_hidden_tab:
					print("✅ Status field is already in visible area")
					return
			
			# Get the status field
			status_field = ec_dt.fields[status_idx]
			
			# Configure status field for list view
			status_field.in_list_view = 1
			status_field.in_standard_filter = 1
			status_field.hidden = 0
			
			# Remove it from current position
			ec_dt.fields.pop(status_idx)
			
			# Insert it right after employee field
			insert_position = employee_idx + 1
			ec_dt.fields.insert(insert_position, status_field)
			
			# Save the DocType
			ec_dt.save(ignore_permissions=True)
			frappe.db.commit()
			
			print(f"✅ Moved status field from index {status_idx} to index {insert_position}")
			print("✅ Status field is now visible in the main form area")
		else:
			print("⚠️  Could not find employee or status field to move")
	except Exception as e:
		frappe.log_error(f"Error moving status field: {str(e)}", "Status Field Move Error")
		print(f"⚠️  Could not move status field: {str(e)}")


def create_expense_claim_workflow_actions():
	"""Create Workflow Action Master records for Expense Claim workflow"""
	print("\n🔧 Creating Workflow Action master records...")
	
	workflow_actions = [
		"Submit for Approval",
		"Approve",
		"Reject",
		"Submit to Payroll",
		"Mark as Paid"
	]
	
	created_count = 0
	existing_count = 0
	
	for action_name in workflow_actions:
		if not frappe.db.exists("Workflow Action Master", action_name):
			try:
				action_doc = frappe.get_doc({
					"doctype": "Workflow Action Master",
					"workflow_action_name": action_name
				})
				action_doc.insert(ignore_permissions=True)
				frappe.db.commit()
				created_count += 1
				print(f"✅ Created Workflow Action: {action_name}")
			except Exception as e:
				frappe.log_error(f"Error creating Workflow Action {action_name}: {str(e)}", "Workflow Action Creation Error")
				print(f"⚠️  Could not create Workflow Action {action_name}: {str(e)}")
		else:
			existing_count += 1
			print(f"ℹ️  Workflow Action {action_name} already exists")
	
	print(f"✅ Workflow Actions: {created_count} created, {existing_count} already existed")


def create_expense_claim_workflow_states():
	"""Create Workflow State master records for Expense Claim workflow"""
	print("\n🔧 Creating Workflow State master records...")
	
	workflow_states = [
		"Draft",
		"Pending RM Approval",
		"Approved by RM",
		"Rejected",
		"Submitted to Payroll",
		"Paid"
	]
	
	created_count = 0
	existing_count = 0
	
	for state_name in workflow_states:
		if not frappe.db.exists("Workflow State", state_name):
			try:
				state_doc = frappe.get_doc({
					"doctype": "Workflow State",
					"workflow_state_name": state_name,
					"icon": "",
					"style": ""
				})
				state_doc.insert(ignore_permissions=True)
				frappe.db.commit()
				created_count += 1
				print(f"✅ Created Workflow State: {state_name}")
			except Exception as e:
				frappe.log_error(f"Error creating Workflow State {state_name}: {str(e)}", "Workflow State Creation Error")
				print(f"⚠️  Could not create Workflow State {state_name}: {str(e)}")
		else:
			existing_count += 1
			print(f"ℹ️  Workflow State {state_name} already exists")
	
	print(f"✅ Workflow States: {created_count} created, {existing_count} already existed")


def verify_expense_claim_workflow_states_exist():
	"""Verify all required workflow states exist before creating workflow"""
	required_states = [
		"Draft",
		"Pending RM Approval",
		"Approved by RM",
		"Rejected",
		"Submitted to Payroll",
		"Paid"
	]
	
	missing_states = []
	for state_name in required_states:
		if not frappe.db.exists("Workflow State", state_name):
			missing_states.append(state_name)
	
	if missing_states:
		raise Exception(
			f"The following Workflow States are missing and required for workflow: {', '.join(missing_states)}"
		)
	
	print("✅ All required Workflow States exist")


def setup_expense_claim_workflow():
	"""Create workflow for Expense Claim reimbursement process"""
	
	workflow_name = "Expense Claim Reimbursement Workflow"
	doctype = "Expense Claim"
	
	# Delete existing workflow if any
	if frappe.db.exists("Workflow", workflow_name):
		frappe.delete_doc("Workflow", workflow_name, force=1, ignore_permissions=True)
		frappe.db.commit()
	
	# Define workflow states
	states = [
		{
			"state": "Draft",
			"doc_status": "0",  # Saved (not submitted)
			"update_field": "approval_status",
			"update_value": "Draft",
			"is_optional_state": 0,
			"next_action_email_template": "",
			"allow_edit": "All",  # Employee can edit
			"send_email": 0
		},
		{
			"state": "Pending RM Approval",
			"doc_status": "0",  # Saved (not submitted until approved)
			"update_field": "approval_status",
			"update_value": "Pending RM Approval",
			"is_optional_state": 0,
			"next_action_email_template": "",
			"allow_edit": "Expense Approver",  # Only Reporting Manager can edit
			"send_email": 1
		},
		{
			"state": "Approved by RM",
			"doc_status": "0",  # Saved (not submitted until HR processes)
			"update_field": "approval_status",
			"update_value": "Approved by RM",
			"is_optional_state": 0,
			"next_action_email_template": "",
			"allow_edit": "HR Manager",  # Only HR can edit
			"send_email": 1
		},
		{
			"state": "Rejected",
			"doc_status": "0",  # Saved (closed but not cancelled - can't cancel before submit)
			"update_field": "approval_status",
			"update_value": "Rejected",
			"is_optional_state": 0,
			"next_action_email_template": "",
			"allow_edit": "All",  # Can view but not edit (handled by validation)
			"send_email": 1
		},
		{
			"state": "Submitted to Payroll",
			"doc_status": "1",  # Submitted (for Inside Payroll)
			"update_field": "approval_status",
			"update_value": "Submitted to Payroll",
			"is_optional_state": 0,
			"next_action_email_template": "",
			"allow_edit": "HR Manager",
			"send_email": 0
		},
		{
			"state": "Paid",
			"doc_status": "1",  # Submitted (completed)
			"update_field": "approval_status",
			"update_value": "Paid",
			"is_optional_state": 0,
			"next_action_email_template": "",
			"allow_edit": "HR Manager",
			"send_email": 0
		}
	]
	
	# Define workflow transitions
	transitions = [
		# Draft → Pending RM Approval (Employee submits)
		{
			"state": "Draft",
			"action": "Submit for Approval",
			"next_state": "Pending RM Approval",
			"allowed": "All",  # Employee can submit
			"allow_self_approval": 1,
			"condition": "",
			"send_email_to_creator": 0
		},
		
		# Pending RM Approval → Approved by RM
		{
			"state": "Pending RM Approval",
			"action": "Approve",
			"next_state": "Approved by RM",
			"allowed": "Expense Approver",  # Reporting Manager
			"allow_self_approval": 0,
			"condition": "",
			"send_email_to_creator": 1
		},
		
		# Pending RM Approval → Rejected
		{
			"state": "Pending RM Approval",
			"action": "Reject",
			"next_state": "Rejected",
			"allowed": "Expense Approver",  # Reporting Manager
			"allow_self_approval": 0,
			"condition": "",
			"send_email_to_creator": 1
		},
		
		# Approved by RM → Submitted to Payroll (Inside Payroll)
		# Note: Payment type logic will be handled in client script to show/hide actions
		{
			"state": "Approved by RM",
			"action": "Submit to Payroll",
			"next_state": "Submitted to Payroll",
			"allowed": "HR Manager",
			"allow_self_approval": 1,
			"condition": "",  # Condition handled in client script
			"send_email_to_creator": 0
		},
		
		# Approved by RM → Paid (Outside Payroll - HR marks as paid)
		# Note: Payment type logic will be handled in client script to show/hide actions
		{
			"state": "Approved by RM",
			"action": "Mark as Paid",
			"next_state": "Paid",
			"allowed": "HR Manager",
			"allow_self_approval": 1,
			"condition": "",  # Condition handled in client script
			"send_email_to_creator": 0
		},
		
		# Submitted to Payroll → Paid (after payroll processing)
		{
			"state": "Submitted to Payroll",
			"action": "Mark as Paid",
			"next_state": "Paid",
			"allowed": "HR Manager",
			"allow_self_approval": 1,
			"condition": "",
			"send_email_to_creator": 0
		}
	]
	
	# Create workflow document
	workflow_doc = frappe.get_doc({
		"doctype": "Workflow",
		"workflow_name": workflow_name,
		"document_type": doctype,
		"is_active": 1,
		"override_status": 0,  # Do not override status field
		"workflow_state_field": "approval_status",  # Use approval_status field
		"send_email_alert": 1  # Send email alerts
	})
	
	# Add states
	for state_data in states:
		workflow_doc.append("states", state_data)
	
	# Add transitions
	for transition_data in transitions:
		workflow_doc.append("transitions", transition_data)
	
	# Insert workflow
	workflow_doc.insert(ignore_permissions=True)
	frappe.db.commit()
	
	print(f"✅ Created Workflow: {workflow_name}")
	print(f"   - Document Type: {doctype}")
	print(f"   - States: {len(states)}")
	print(f"   - Transitions: {len(transitions)}")
	
	return workflow_doc.name


def add_status_field_visibility_script():
	"""Add client script to make status field visible in the main form area"""
	print("\n🔧 Adding client script to show status field in visible area...")
	
	try:
		script_name = "Expense Claim - Show Status Field"
		if frappe.db.exists("Client Script", script_name):
			script = frappe.get_doc("Client Script", script_name)
		else:
			script = frappe.new_doc("Client Script")
			script.update({
				"name": script_name,
				"dt": "Expense Claim",
				"view": "Form",
				"enabled": 1,
				"script": ""
			})
		
		# Script to show status field in visible area
		visibility_script = """
frappe.ui.form.on('Expense Claim', {
	refresh: function(frm) {
		// Ensure status field is visible and positioned correctly
		setTimeout(function() {
			var status_field = frm.get_field('status');
			if (status_field && status_field.$wrapper) {
				// Make sure the status field and its parent containers are visible
				status_field.$wrapper.show();
				status_field.$wrapper.closest('.form-group').show();
				status_field.$wrapper.closest('.form-section').show();
				status_field.$wrapper.closest('.form-column').show();
				
				// If status field is in a hidden tab, move it to visible area
				var status_parent = status_field.$wrapper.closest('.tab-pane');
				if (status_parent && status_parent.hasClass('hidden')) {
					// Find employee field
					var employee_field = frm.get_field('employee');
					if (employee_field && employee_field.$wrapper) {
						// Get the form group containing employee
						var employee_form_group = employee_field.$wrapper.closest('.form-group');
						if (employee_form_group.length) {
							// Clone status field and insert after employee
							var status_form_group = status_field.$wrapper.closest('.form-group');
							if (status_form_group.length) {
								var cloned_status = status_form_group.clone();
								cloned_status.insertAfter(employee_form_group);
								cloned_status.show();
								// Hide original if it's in hidden tab
								status_form_group.hide();
							}
						}
					}
				}
				
				// Force refresh the status field to show current value
				if (frm.doc.status) {
					status_field.set_value(frm.doc.status);
				}
			}
		}, 300);
	}
});
"""
		
		script.script = visibility_script
		script.enabled = 1
		script.save(ignore_permissions=True)
		frappe.db.commit()
		
		print("✅ Added client script to show status field in visible area")
		
	except Exception as e:
		frappe.log_error(f"Error adding status visibility script: {str(e)}", "Status Visibility Script Error")
		print(f"⚠️  Could not add status visibility script: {str(e)}")


def add_expense_claim_validations():
	"""Add validation rules for Expense Claim"""
	print("\n🔧 Adding validation rules for Expense Claim...")
	
	try:
		# Check if client script already exists
		script_name = "Expense Claim - Validation Rules"
		if frappe.db.exists("Client Script", script_name):
			script = frappe.get_doc("Client Script", script_name)
		else:
			script = frappe.new_doc("Client Script")
			script.update({
				"name": script_name,
				"dt": "Expense Claim",
				"script": ""
			})
		
		# Validation script
		validation_script = """
// Validate that only active employees can create expense claims
frappe.ui.form.on('Expense Claim', {
	validate: function(frm) {
		// Check if employee is active
		if (frm.doc.employee) {
			frappe.db.get_value('Employee', frm.doc.employee, 'status', (r) => {
				if (r && r.status !== 'Active') {
					frappe.msgprint(__('Only active employees can create expense claims.'));
					frappe.validated = false;
				}
			});
		}
	},
	
	// Prevent editing after submission (except for certain roles)
	refresh: function(frm) {
		// If approval_status is not Draft, prevent editing for employees
		if (frm.doc.approval_status && frm.doc.approval_status !== 'Draft' && frm.doc.docstatus === 0) {
			// Allow editing only for Reporting Manager or HR Manager
			const user_roles = frappe.user_roles;
			const can_edit = user_roles.includes('Expense Approver') || 
							user_roles.includes('HR Manager') || 
							user_roles.includes('HR User');
			
			if (!can_edit) {
				frm.set_read_only();
			}
		}
		
		// If rejected, make it read-only for everyone
		if (frm.doc.approval_status === 'Rejected') {
			frm.set_read_only();
		}
		
		// Handle payment type logic for workflow actions
		// Show/hide workflow actions based on payment type in reimbursement child table
		if (frm.doc.approval_status === 'Approved by RM' && frm.doc.reimbursement && frm.doc.reimbursement.length > 0) {
			// Check if any row has Inside Payroll
			const has_inside_payroll = frm.doc.reimbursement.some(function(row) {
				return row.payment_type === 'Inside Payroll';
			});
			
			// Check if any row has Outside Payroll
			const has_outside_payroll = frm.doc.reimbursement.some(function(row) {
				return row.payment_type === 'Outside Payroll';
			});
			
			// Show/hide workflow actions based on payment type
			setTimeout(function() {
				// Hide "Submit to Payroll" if no Inside Payroll rows
				if (!has_inside_payroll) {
					frm.page.remove_inner_button('Submit to Payroll');
				}
				
				// Hide "Mark as Paid" if no Outside Payroll rows (when in Approved by RM state)
				if (!has_outside_payroll && frm.doc.approval_status === 'Approved by RM') {
					frm.page.remove_inner_button('Mark as Paid');
				}
			}, 500);
		}
	}
});
"""
		
		script.script = validation_script
		script.save(ignore_permissions=True)
		frappe.db.commit()
		
		print("✅ Added validation rules for Expense Claim")
		
	except Exception as e:
		frappe.log_error(f"Error adding validation rules: {str(e)}", "Expense Claim Validation Error")
		print(f"⚠️  Could not add validation rules: {str(e)}")


def add_expense_claim_server_side_validations():
	"""Add server-side validation rules"""
	print("\n🔧 Adding server-side validation rules...")
	
	try:
		# Check if server script already exists
		script_name = "Expense Claim - Server Validation"
		if frappe.db.exists("Server Script", script_name):
			script = frappe.get_doc("Server Script", script_name)
		else:
			script = frappe.new_doc("Server Script")
			script.update({
				"name": script_name,
				"script_type": "DocType Event",
				"reference_doctype": "Expense Claim",
				"doctype_event": "Before Save",
				"script": ""
			})
		
		# Server-side validation script
		validation_script = """
# Validate that only active employees can create expense claims
def validate(doc, method):
	from frappe import _
	
	# Check if employee is active
	if doc.employee:
		employee_status = frappe.db.get_value("Employee", doc.employee, "status")
		if employee_status != "Active":
			frappe.throw(_("Only active employees can create expense claims."))
	
	# Prevent editing after submission (except for certain roles)
	if doc.approval_status and doc.approval_status != "Draft" and doc.docstatus == 0:
		user_roles = frappe.get_roles()
		can_edit = "Expense Approver" in user_roles or "HR Manager" in user_roles or "HR User" in user_roles
		
		if not can_edit and not doc.flags.ignore_permissions:
			frappe.throw(_("You cannot edit this expense claim after submission. Only Reporting Manager or HR can edit."))
	
	# If rejected, prevent any further edits
	if doc.approval_status == "Rejected" and doc.docstatus == 0:
		user_roles = frappe.get_roles()
		can_edit = "HR Manager" in user_roles or "HR User" in user_roles
		
		if not can_edit and not doc.flags.ignore_permissions:
			frappe.throw(_("Rejected expense claims cannot be edited."))
"""
		
		script.script = validation_script
		script.doctype_event = "Before Save"
		script.disabled = 0
		script.save(ignore_permissions=True)
		frappe.db.commit()
		
		print("✅ Added server-side validation rules for Expense Claim")
		
	except Exception as e:
		frappe.log_error(f"Error adding server-side validation: {str(e)}", "Expense Claim Server Validation Error")
		print(f"⚠️  Could not add server-side validation: {str(e)}")


def extend_bootinfo(bootinfo):
	"""Add server_script_enabled to boot data"""
	# Add server_script_enabled in boot
	if "server_script_enabled" in frappe.conf:
		enabled = frappe.conf.server_script_enabled
	else:
		enabled = True  # Default to True if not set
	bootinfo["server_script_enabled"] = enabled


# Override Expense Claim class to respect workflow status
class ExpenseClaimOverride(OriginalExpenseClaim):
	"""Override Expense Claim to respect workflow status"""
	
	def set_status(self, update=False):
		"""Override set_status to respect workflow when active"""
		# Check if workflow is active for Expense Claim
		workflow_name = get_workflow_name("Expense Claim")
		if workflow_name:
			workflow = frappe.get_doc("Workflow", workflow_name)
			if workflow.is_active and workflow.override_status and workflow.workflow_state_field == "status":
				# Workflow is managing status, don't override it
				# Get valid workflow states (use state field, not update_value)
				valid_states = [state.state for state in workflow.states]
				
				# If current status is a valid workflow state (and not just "Draft" matching docstatus),
				# it means workflow set it, so don't override
				if self.status and self.status in valid_states:
					# Special workflow states that should never be overridden
					workflow_managed_states = ["Pending RM Approval", "Approved by RM", "Rejected", "Submitted to Payroll", "Paid"]
					if self.status in workflow_managed_states:
						# This is definitely a workflow-managed state, don't override
						return
					
					# For "Draft", only override if it matches docstatus (normal case)
					# If status is "Draft" but docstatus suggests something else, workflow might have set it
					docstatus_based_status = {"0": "Draft", "1": "Submitted", "2": "Cancelled"}[cstr(self.docstatus or 0)]
					if self.status != docstatus_based_status:
						# Status doesn't match docstatus, workflow must have set it
						return
				
				# Only set initial status if document is new or status is empty/invalid
				# This should only happen for new documents
				if not self.status or (self.status not in valid_states and self.status in ["Draft", "Submitted", "Cancelled"]):
					# Set initial status based on docstatus only
					docstatus_based_status = {"0": "Draft", "1": "Submitted", "2": "Cancelled"}[cstr(self.docstatus or 0)]
					status = docstatus_based_status
					# Make sure it's a valid workflow state
					if status not in valid_states:
						status = "Draft"  # Default to Draft if not in workflow states
					if update:
						self.db_set("status", status)
					else:
						self.status = status
				return
		
		# If no workflow or workflow not overriding, use original logic
		# Call parent's set_status method
		super().set_status(update)
	
	def validate(self):
		"""Override validate to skip set_status if workflow is managing status"""
		# Check if workflow is active
		workflow_name = get_workflow_name("Expense Claim")
		if workflow_name:
			workflow = frappe.get_doc("Workflow", workflow_name)
			if workflow.is_active and workflow.override_status and workflow.workflow_state_field == "status":
				# Skip calling set_status in validate - workflow will manage it
				# Call other validations from parent
				validate_active_employee = frappe.get_attr("hrms.hr.utils.validate_active_employee")
				set_employee_name = frappe.get_attr("hrms.hr.utils.set_employee_name")
				
				validate_active_employee(self)
				set_employee_name(self)
				self.validate_sanctioned_amount()
				self.calculate_total_amount()
				self.validate_advances()
				self.set_expense_account(validate=True)
				self.set_default_accounting_dimension()
				self.calculate_taxes()
				# Skip self.set_status() - workflow manages it
				self.validate_company_and_department()
				if self.task and not self.project:
					self.project = frappe.db.get_value("Task", self.task, "project")
				
				return
		
		# If no workflow, use original validate
		super().validate()
	
	def on_submit(self):
		"""Override on_submit to handle workflow status"""
		# Check if workflow is active
		workflow_name = get_workflow_name("Expense Claim")
		if workflow_name:
			workflow = frappe.get_doc("Workflow", workflow_name)
			if workflow.is_active and workflow.override_status and workflow.workflow_state_field == "status":
				# Set approval_status based on workflow status
				if self.status in ["Approved by RM", "Submitted to Payroll", "Paid"]:
					self.approval_status = "Approved"
				elif self.status == "Rejected":
					self.approval_status = "Rejected"
				
				# Only proceed if approval_status is set correctly
				if self.approval_status == "Draft":
					frappe.throw(_("""Approval Status must be 'Approved' or 'Rejected'"""))
		
		# Call parent's on_submit
		super().on_submit()


def execute():
	"""Main execution function"""
	try:
		print("=" * 60)
		print("Customizing Expense Claim DocType")
		print("=" * 60)
		
		# Make Expense Claim Detail fields non-mandatory
		make_expense_claim_detail_fields_non_mandatory()
		
		# Add Reimbursement child table
		add_reimbursement_child_table()
		
		# Set defaults for Reimbursement child table
		set_reimbursement_child_defaults()
		
		# Create client script for Reimbursement Add Row button control
		create_reimbursement_add_row_script()
		
		# Customize main doctype only (Expense Claim Detail table customizations removed)
		customize_expense_claim_main()
		
		# Update status field options to match workflow requirements
		update_expense_claim_status_options()
		# Update approval_status field options to match workflow requirements
		update_expense_claim_approval_status_options()
		
		# Step 1: Create Workflow State master records FIRST (required for workflow validation)
		create_expense_claim_workflow_states()
		
		# Step 2: Verify all states exist (fail fast if any are missing)
		verify_expense_claim_workflow_states_exist()
		
		# Step 3: Create Workflow Action Master records (required for transitions)
		create_expense_claim_workflow_actions()
		
		# Step 4: Clear cache to ensure updated field options are loaded
		frappe.clear_cache()
		
		# Step 5: Create workflow (now all prerequisites are met)
		setup_expense_claim_workflow()
		
		# Step 6: Clear cache after workflow creation
		frappe.clear_cache()
		
		# Add status field visibility script
		add_status_field_visibility_script()
		
		# Add validation rules
		add_expense_claim_validations()
		add_expense_claim_server_side_validations()
		
		print("\n" + "=" * 60)
		print("✅ Expense Claim customization completed successfully!")
		print("=" * 60)
		
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Expense Claim Customization Error")
		raise


if __name__ == "__main__":
	execute()


