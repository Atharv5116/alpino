"""Employee Onboarding field-property tweaks."""

import frappe


def update_employee_onboarding_fields():
	update_property_setter(
		"Employee Onboarding",
		"job_applicant",
		"label",
		"Unique ID",
		"Data"
	)

	update_property_setter(
		"Employee Onboarding",
		"job_offer",
		"reqd",
		0,
		"Check"
	)
	update_property_setter(
		"Employee Onboarding",
		"job_offer",
		"hidden",
		1,
		"Check"
	)
	
	update_property_setter(
		"Employee Onboarding",
		"employee_onboarding_template",
		"hidden",
		1,
		"Check"
	)
	
	update_property_setter(
		"Employee Onboarding",
		"boarding_status",
		"read_only",
		0,
		"Check"
	)
	
	status_options = (
		"Draft\n"
		"Email Sent\n"
		"Employee Created"
	)
	update_property_setter(
		"Employee Onboarding",
		"boarding_status",
		"options",
		status_options,
		"Text"
	)
	
	update_property_setter(
		"Employee Onboarding",
		"boarding_status",
		"default",
		"Draft",
		"Data"
	)
	
	# Clear any Job Applicant field filters so all applicants show.
	try:
		field = frappe.get_doc("DocField", {"parent": "Employee Onboarding", "fieldname": "job_applicant"})
		if field:
			if hasattr(field, 'filters'):
				field.filters = ""
				field.save(ignore_permissions=True)
				frappe.db.commit()
	except:
		pass
	
	print("✅ Employee Onboarding fields updated successfully")


def update_property_setter(doctype, fieldname, property_name, value, property_type="Data"):
	"""Create or update a property setter."""
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

