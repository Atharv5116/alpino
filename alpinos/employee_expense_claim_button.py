"""
Create Client Script for Employee doctype
Adds "Create Reimbursement" button that opens Expense Claim with employee pre-filled
Button only visible for active employees
"""

import frappe


def create_employee_expense_claim_button():
	"""Create client script for Employee to add Create Reimbursement button"""
	
	employee_script = """
frappe.ui.form.on('Employee', {
	refresh: function(frm) {
		// Add "Create Reimbursement" button only for active employees
		if (frm.doc.name && !frm.is_new() && frm.doc.status === 'Active') {
			frm.add_custom_button(__('Create Reimbursement'), function() {
				// Open new Expense Claim form with employee pre-filled
				frappe.model.with_doctype('Expense Claim', function() {
					var expense_claim_doc = frappe.model.get_new_doc('Expense Claim');
					expense_claim_doc.employee = frm.doc.name;
					
					// Set route to open the new form
					frappe.set_route('Form', 'Expense Claim', expense_claim_doc.name);
				});
			}, __('Actions'));
		}
	}
});
"""
	
	# Create or update Employee client script
	create_or_update_client_script(
		"Employee - Create Reimbursement Button",
		"Employee",
		employee_script
	)
	
	print("✅ Created client script for Employee - Create Reimbursement button")


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


def execute():
	"""Main execution function"""
	try:
		print("=" * 60)
		print("Creating Employee - Create Reimbursement Button")
		print("=" * 60)
		
		create_employee_expense_claim_button()
		
		print("\n" + "=" * 60)
		print("✅ Employee Expense Claim button setup completed successfully!")
		print("=" * 60)
		
	except Exception as e:
		frappe.log_error(f"Error creating Employee Expense Claim button: {str(e)}", "Employee Expense Claim Button Error")
		print(f"\n❌ Error: {str(e)}")
		raise


if __name__ == "__main__":
	execute()

