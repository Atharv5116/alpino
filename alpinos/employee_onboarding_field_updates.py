"""
Update Employee Onboarding fields:
- Change Job Applicant label to "Unique ID"
- Hide Job Offer field and make it non-mandatory
- Hide Employee Onboarding Template field
- Make Status field editable by HR
- Update Status field options
"""

import frappe


def update_employee_onboarding_fields():
	"""Update Employee Onboarding field properties"""
	
	# 1. Change Job Applicant label to "Unique ID"
	update_property_setter(
		"Employee Onboarding",
		"job_applicant",
		"label",
		"Unique ID",
		"Data"
	)
	
	# 2. Remove reqd from Job Offer and hide it
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
	
	# 3. Hide Employee Onboarding Template field
	update_property_setter(
		"Employee Onboarding",
		"employee_onboarding_template",
		"hidden",
		1,
		"Check"
	)
	
	# 4. Make Status field editable (remove read_only)
	update_property_setter(
		"Employee Onboarding",
		"boarding_status",
		"read_only",
		0,
		"Check"
	)
	
	# 5. Update Status field options
	status_options = (
		"Pre-Onboarding Initiated\n"
		"Job Confirmed\n"
		"Documents Pending\n"
		"Joined\n"
		"Active Employee"
	)
	update_property_setter(
		"Employee Onboarding",
		"boarding_status",
		"options",
		status_options,
		"Text"
	)
	
	# 6. Update default status to "Pre-Onboarding Initiated"
	update_property_setter(
		"Employee Onboarding",
		"boarding_status",
		"default",
		"Pre-Onboarding Initiated",
		"Data"
	)
	
	# 7. Remove any filters from Job Applicant field to show all job applicants
	# Clear any existing filters by setting filter to empty
	try:
		# Get the field definition
		field = frappe.get_doc("DocField", {"parent": "Employee Onboarding", "fieldname": "job_applicant"})
		if field:
			# Remove any filters
			if hasattr(field, 'filters'):
				field.filters = ""
				field.save(ignore_permissions=True)
				frappe.db.commit()
	except:
		pass
	
	print("✅ Employee Onboarding fields updated successfully")


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

