"""
Configure Employee naming to allow manual entry (like Item Code)
"""

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def setup_employee_manual_naming():
	"""Change Employee naming from auto-series to manual entry (prompt)"""
	try:
		# Change autoname from series to prompt
		# This allows manual entry of Employee ID like Item Code
		make_property_setter(
			doctype="Employee",
			fieldname=None,  # DocType level property
			property="autoname",
			value="prompt",
			property_type="Data",
			for_doctype=True
		)
		
		frappe.db.commit()
		print("✅ Employee naming changed to manual entry (prompt)")
		print("   Users can now enter Employee ID manually when creating new employees")
		
	except Exception as e:
		print(f"⚠️  Could not update Employee naming: {str(e)}")
		frappe.log_error(f"Error updating Employee naming: {str(e)}\nTraceback: {frappe.get_traceback()}", "Employee Naming Config")


def revert_employee_naming_to_series():
	"""Revert Employee naming back to auto-series (if needed)"""
	try:
		# Find and delete the property setter
		property_setter = frappe.db.get_value(
			"Property Setter",
			{
				"doc_type": "Employee",
				"property": "autoname",
				"doctype_or_field": "DocType"
			},
			"name"
		)
		
		if property_setter:
			frappe.delete_doc("Property Setter", property_setter, force=1, ignore_permissions=True)
			frappe.db.commit()
			print("✅ Reverted Employee naming to default (series)")
		else:
			print("⚠️  No custom naming property setter found")
			
	except Exception as e:
		print(f"⚠️  Could not revert Employee naming: {str(e)}")
		frappe.log_error(f"Error reverting Employee naming: {str(e)}\nTraceback: {frappe.get_traceback()}", "Employee Naming Config")
